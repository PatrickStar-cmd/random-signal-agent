"""Document-scoped execution, measured experiment tools and reproducible tasks."""
import copy
import hashlib
import itertools
import math
import time
import numpy as np
from src import communications as c, communication_graph_v0411 as graph
from src import communication_runtime as runtime, communication_experiments as experiments

TOOL_KINDS = ('probe', 'reference', 'metrics', 'assertion')
OPERATORS = {'<=': lambda a, b: a <= b, '>=': lambda a, b: a >= b,
             '<': lambda a, b: a < b, '>': lambda a, b: a > b,
             '==': lambda a, b: a == b}


def _document(raw):
    if not isinstance(raw, dict): raise ValueError('工程需要 JSON 对象。')
    if raw.get('schema') == 1 and 'blocks' in raw:
        raw = {'document_schema': 2, 'name': '通信实验', 'program': raw}
    if raw.get('document_schema') != 2: raise ValueError('请选择有效的完整工程。')
    return copy.deepcopy(raw)


def _sources(document):
    if document.get('graph'):
        return {**{key: b for key, b in graph.nodes(document['graph']).items() if b['lane'] != 'analysis'}}
    return {'linear/' + b['id']: b for b in document['program']['blocks']}


def validate_tools(document):
    tools = copy.deepcopy(document.get('tools', []))
    if not isinstance(tools, list) or len(tools) > 24: raise ValueError('每个工程最多包含 24 个实验工具。')
    sources = _sources(document); ids = set()
    for tool in tools:
        if not isinstance(tool, dict) or tool.get('kind') not in TOOL_KINDS:
            raise ValueError('请选择观察、参考对照、指标汇总或验收条件工具。')
        key = tool.get('id')
        if not isinstance(key, str) or not key or len(key) > 80 or key in ids:
            raise ValueError('实验工具使用互异的标识。')
        ids.add(key)
        if tool['kind'] in ('probe', 'reference'):
            if tool.get('source') not in sources: raise ValueError('工具观察点须属于当前工程。')
            tool['count'] = c.numeric(tool.get('count', 256), '观察数量', 1, 2048, True)
            if tool['kind'] == 'probe':
                tool['start'] = c.numeric(tool.get('start', 0), '起始位置', 0, 1000000, True)
            else:
                if tool.get('reference') not in sources: raise ValueError('参考点须属于当前工程。')
                if tool.get('metric', 'mse') not in ('mse', 'ber', 'ser', 'evm'):
                    raise ValueError('参考对照指标请选择 mse、ber、ser 或 evm。')
                tool.setdefault('metric', 'mse')
                for key in ('reference_start', 'source_start'):
                    tool[key] = c.numeric(tool.get(key, 0), '对齐起始位置', 0, 1000000, True)
        elif tool['kind'] == 'assertion':
            _rule(tool)
        elif not isinstance(tool.get('metrics', []), list) or len(tool.get('metrics', [])) > 32:
            raise ValueError('指标汇总最多选择 32 个指标。')
    return tools


def _rule(rule):
    if not isinstance(rule, dict) or not isinstance(rule.get('metric'), str) or not rule['metric']:
        raise ValueError('验收条件需要指定指标。')
    if rule.get('operator') not in OPERATORS: raise ValueError('选择有效的比较运算符。')
    value = rule.get('value', rule.get('threshold'))
    if type(value) not in (int, float, bool) or not math.isfinite(value): raise ValueError('填写有限的验收阈值。')
    return value


def parameter_paths(document):
    result = []
    g = document.get('graph')
    globals_ = g['globals'] if g else document['program']
    lane_labels = {'linear': '链路', 'shared': '共享前段', 'tail': '公共尾段'}
    if g: lane_labels.update({b['id']: b['name'] for b in g['branches']})
    global_labels = {'sample_rate': '全局 采样率 / Hz', 'sample_count': '全局 样本数', 'symbol_rate': '全局 符号率 / Baud'}
    for name in graph.GLOBALS:
        if name != 'seed': result.append({'path': 'globals/' + name, 'label': global_labels[name], 'value': globals_[name], 'type': 'number'})
    for key, b in _sources(document).items():
        if key == 'merge': continue
        label = lane_labels[key.split('/')[0]] + ' ' + c.BLOCKS[b['kind']]['label']
        for name, spec in c.BLOCKS[b['kind']]['params'].items():
            if spec['type'] in ('number', 'integer', 'boolean') or (spec['type'] == 'select' and
                    all(type(value) in (int, float) and math.isfinite(value) for value in spec['choices'])):
                result.append({'path': key + '/' + name, 'label': label + ' ' + spec['label'],
                               'value': b['params'].get(name, spec['default']), 'type': spec['type'], 'spec': spec})
    if g:
        result.extend({'path': 'merge/weights/' + str(i), 'label': '汇合权重 ' + str(i + 1), 'value': value, 'type': 'number'}
                      for i, value in enumerate(g['merge']['weights']))
        result.append({'path': 'merge/select', 'label': '汇合选择输入', 'value': g['merge']['select'], 'type': 'integer'})
        analysis_labels = {'training_range': '距离训练单元', 'training_doppler': '多普勒训练单元',
                           'guard_range': '距离保护单元', 'guard_doppler': '多普勒保护单元',
                           'pfa': '目标虚警概率', 'direct_bins': '直达路径排除单元', 'cluster_radius': '聚类半径'}
        for index, a in enumerate(g['analyses']):
            result.extend({'path': 'analysis/' + a['id'] + '/' + name, 'label': 'CFAR 分析 ' + str(index + 1) + ' ' + analysis_labels[name], 'value': value, 'type': 'number'}
                          for name, value in a['params'].items())
    return result


def set_parameter(document, path, value):
    """Modify one explicitly listed, fully qualified parameter in place."""
    if path not in {row['path'] for row in parameter_paths(document)}: raise ValueError('请选择参数列表内的完整路径。')
    parts = path.split('/'); g = document.get('graph')
    if parts[0] == 'globals': (g['globals'] if g else document['program'])[parts[1]] = value
    elif parts[0] == 'merge':
        if parts[1] == 'weights': g['merge']['weights'][int(parts[2])] = value
        else: g['merge'][parts[1]] = value
    elif parts[0] == 'analysis': next(a for a in g['analyses'] if a['id'] == parts[1])['params'][parts[2]] = value
    else: _sources(document)['/'.join(parts[:2])]['params'][parts[2]] = value


def build_document(raw):
    document = _document(raw)
    if document.get('graph'):
        built = graph.build(document['graph']); document['graph'] = built['graph']
        branch = document.get('graphActiveBranch', built['graph']['branches'][0]['id'])
        document['program'] = graph.projection(built['graph'], branch)
        graph_nodes = graph.nodes(built['graph'])
        lane_labels = {'shared': '共享前段', 'tail': '公共尾段', **{b['id']: b['name'] for b in built['graph']['branches']}}
        sources = {key: {'node_id': key, **row, 'kind': graph_nodes[key]['kind'],
                        'label': lane_labels[graph_nodes[key]['lane']] + ' ' + c.BLOCKS[graph_nodes[key]['kind']]['label']}
                   for key, row in built['ports'].items()}
        sources['merge'] = {'node_id': 'merge', 'label': '双输入汇合', 'output': 'LLR' if built['graph']['merge']['domain'] == 'llr' else '复符号'}
        kind = 'graph'
    else:
        built = c.build(document.get('program')); document['program'] = built['program']
        sources = {'linear/' + row['id']: {'node_id': 'linear/' + row['id'], **row} for row in built['plan']}
        kind = 'linear'
    document['tools'] = validate_tools(document)
    token = graph.digest({'signal': built['token'], 'tools': document['tools']})
    nodes = [{**row, 'id': key, 'label': row.get('label', key)} for key, row in sources.items()]
    return {'document': document, 'token': token, 'signal_token': built['token'], 'kind': kind,
            'built': built, 'sources': list(sources.values()), 'nodes': nodes, 'parameters': parameter_paths(document)}


def diagnose(raw):
    """Return actionable locations for shape, parameter and connection errors."""
    document = _document(raw); issues = []; g = document.get('graph')
    def add(node, field, message, action='edit_parameter', edge=None):
        issues.append({'node': node, 'field': field, 'edge': edge, 'message': message, 'action': action})
    source = _sources(document)
    globals_ = g['globals'] if g else document['program']
    for key, b in source.items():
        if key == 'merge': continue
        try: c.normalize({'schema': 1, **{k: globals_[k] for k in graph.GLOBALS},
                          'blocks': [{name: b[name] for name in ('id', 'kind', 'params')}]})
        except (ValueError, KeyError, TypeError) as exc:
            specs = c.BLOCKS.get(b.get('kind'), {}).get('params', {})
            field = next((name for name, spec in specs.items() if spec['label'] in str(exc)), None)
            add(key, field, str(exc))
    if g:
        try:
            try: ordered = graph.ordered(g)
            except (ValueError, KeyError, IndexError, TypeError): ordered = g
            expected = graph.connections(ordered)
            for edge in expected:
                if edge not in g.get('edges', []): add(edge['to'], None, '此处需要连接前一个积木。', 'connect', edge)
            for edge in g.get('edges', []):
                if edge not in expected: add(edge['to'], None, '按当前积木顺序调整此连接。', 'reorder_or_disconnect', edge)
        except (KeyError, IndexError, StopIteration, TypeError) as exc:
            add('merge', None, '请检查接收分支与汇合输入。', 'select_branch')
    if not issues:
        try: build_document(document)
        except (ValueError, KeyError, TypeError) as exc:
            message = str(exc)
            node = 'merge' if g and any(word in message for word in ('汇合', '速率', '点数')) else None
            for key, b in source.items():
                if b.get('kind') in c.BLOCKS and c.BLOCKS[b['kind']]['label'] in message: node = key; break
            add(node, None, message, 'inspect_contract')
    return {'valid': not issues, 'issues': issues}


def _metric_values(result, graph_result=None):
    def scalars(value):
        values = {key: value for key, value in value.get('metrics', {}).items()
                  if type(value) in (int, float, bool) and math.isfinite(value)}
        if values.get('symbol_count') and 'symbol_errors' in values:
            values['ser'] = values['symbol_errors'] / values['symbol_count']
        return values
    metrics = scalars(result)
    metrics.update({'merged.' + key: value for key, value in list(metrics.items())})
    if graph_result:
        for b in graph_result['branches']:
            metrics.update({b['id'] + '.' + key: value for key, value in scalars(b['result']).items()})
        for a in graph_result['analyses']:
            metrics[a['id'] + '.detections'] = len(a['detections'])
            for key in ('tested_cells', 'crossing_fraction', 'crossings'):
                if key in a: metrics[a['id'] + '.' + key] = a[key]
    return metrics


def _measured_check(rule, metrics):
    threshold = _rule(rule); name = rule['metric']
    if name not in metrics: raise ValueError('当前结果缺少指标：' + name)
    value = metrics[name]
    prefix = name.rsplit('.', 1)[0] + '.' if '.' in name else ''
    samples = metrics.get(prefix + 'tested_cells')
    unit = 'cells'
    if samples is None:
        metric = name.rsplit('.', 1)[-1]
        denominator = 'symbol_count' if metric in ('ser', 'evm_percent', 'symbol_errors') else 'coded_bit_count' if metric in ('coded_ber', 'coded_bit_errors') else 'bit_count'
        samples = metrics.get(prefix + denominator, metrics.get(denominator)); unit = 'symbols' if denominator == 'symbol_count' else 'bits'
        if not samples: samples = metrics.get('input_sample_count'); unit = 'samples'
    return {'metric': name, 'value': value, 'threshold': threshold, 'operator': rule['operator'],
            'passed': bool(OPERATORS[rule['operator']](value, threshold)), 'samples': samples, 'sample_unit': unit}


def _tool_results(tools, samples, metrics):
    output = []
    for tool in tools:
        value = {'id': tool['id'], 'kind': tool['kind']}
        if tool['kind'] == 'probe':
            data, obs = samples[tool['source']]; start = tool['start']; cut = data[start:start + tool['count']]
            if not len(cut): raise ValueError('观察区间应落在实际输出样本内。')
            shown = cut.astype(complex)
            value.update(source=tool['source'], domain=obs['domain'], start=start, count=len(cut),
                         total_count=len(data), sample_rate=obs['sample_rate'], i=shown.real.tolist(), q=shown.imag.tolist())
        elif tool['kind'] == 'reference':
            reference, a = samples[tool['reference']]; measured, b = samples[tool['source']]
            if a['domain'] != b['domain'] or a['sample_rate'] != b['sample_rate']:
                raise ValueError('参考对照请选择同类型、同采样率的观察点。')
            x = reference[tool['reference_start']:tool['reference_start'] + tool['count']]
            y = measured[tool['source_start']:tool['source_start'] + tool['count']]
            count = min(len(x), len(y))
            if count == 0: raise ValueError('参考对照需要重叠的有效样本区间。')
            x, y = x[:count], y[:count]; metric = tool['metric']
            if x.shape != y.shape: raise ValueError('参考对照选择具有相同流维度的数据。')
            if metric == 'ber':
                if a['domain'] != '比特': raise ValueError('BER 参考对照请选择比特输出。')
                measured_value = float(np.mean(x != y))
            elif metric == 'ser':
                if a['domain'] not in ('复符号', '复基带符号'): raise ValueError('SER 对照请选择判决后的符号输出。')
                points = np.unique(x)
                if len(points) > 256: raise ValueError('SER 参考点使用有限星座的已判决符号。')
                decisions = points[np.argmin(abs(y[:, None] - points[None, :]) ** 2, axis=1)]
                measured_value = float(np.mean(x != decisions))
            else:
                measured_value = float(np.mean(abs(x.astype(complex) - y.astype(complex)) ** 2))
                if metric == 'evm':
                    power = float(np.mean(abs(x.astype(complex)) ** 2))
                    if power == 0: raise ValueError('EVM 参考信号需要非零功率。')
                    measured_value = 100 * (measured_value / power) ** .5
            value.update(reference=tool['reference'], source=tool['source'], metric=metric, value=measured_value,
                         count=count, reference_start=tool['reference_start'], source_start=tool['source_start'],
                         sample_rate=a['sample_rate'], alignment='explicit_start_indices', unit='%' if metric == 'evm' else 'ratio' if metric in ('ber', 'ser') else 'power')
        elif tool['kind'] == 'metrics':
            names = tool.get('metrics') or [key for key in metrics if key.startswith('merged.')]
            missing = set(names) - metrics.keys()
            if missing: raise ValueError('当前结果缺少指标：' + '、'.join(sorted(missing)))
            value['metrics'] = {name: metrics[name] for name in names}
        else: value.update(_measured_check(tool, metrics))
        output.append(value)
    return output


def run_document(raw, cache=None, partial=False, progress=None, cancel=None, contexts=None, gate=None, on_context=None):
    built = build_document(raw); document = built['document']; contexts = contexts if contexts is not None else []
    start_index = len(contexts); g = document.get('graph'); graph_result = None; samples = {}; observations = []
    if g:
        graph_result = graph.run(g, built['signal_token'], cache, partial, progress, cancel, contexts, gate, on_context)
        result = graph_result['merged_result']; current = contexts[start_index:]
        for i, branch in enumerate(g['branches']):
            ctx = current[i]
            for block in branch['blocks']:
                key = branch['id'] + '/' + block['id']
                obs = next(o for o in ctx.observations if o['id'] == block['id'])
                samples[key] = (ctx.values[block['id']], obs)
        for block in g['prefix']:
            key = 'shared/' + block['id']; ctx = current[0]
            samples[key] = (ctx.values[block['id']], next(o for o in ctx.observations if o['id'] == block['id']))
        for block in g['tail']:
            key = 'tail/' + block['id']; ctx = current[-1]
            samples[key] = (ctx.values[block['id']], next(o for o in ctx.observations if o['id'] == block['id']))
        ctx = current[-1]; samples['merge'] = (ctx.values['merge-output'], next(o for o in ctx.observations if o['id'] == 'merge-output'))
    else:
        def scoped_gate(row):
            if gate: gate({**row, 'id': 'linear/' + row['id'], 'node_id': 'linear/' + row['id'],
                           'local_id': row['id'], 'scope': 'linear', 'context_index': 0})
        ctx = runtime.Observer(built['built'], retain=True, states={}, cancel=cancel, gate=scoped_gate if gate else None)
        ctx.scope = 'linear'
        if on_context: on_context(ctx)
        with runtime.execution(ctx): result = c.run(document['program'], built['signal_token'])
        result['experience'] = {'observations': ctx.observations, 'frame': 0, 'contract': 1}
        contexts.append(ctx)
        samples = {'linear/' + o['id']: (ctx.values[o['id']], o) for o in ctx.observations}
    ordered_keys = (['shared/' + b['id'] for b in g['prefix']] +
                    [branch['id'] + '/' + b['id'] for branch in g['branches'] for b in branch['blocks']] +
                    ['merge'] + ['tail/' + b['id'] for b in g['tail']]) if g else list(samples)
    execution_map = {row['section']: row for row in graph_result['execution']} if g else {}
    for key in ordered_keys:
        _, obs = samples[key]
        scope = key.split('/', 1)[0]
        index = (len(g['branches']) if scope in ('merge', 'tail') else
                 next((i for i, b in enumerate(g['branches']) if b['id'] == scope), 0)) if g else 0
        reused = obs['id'] in execution_map.get('merge-tail' if scope == 'tail' else scope, {}).get('reused', [])
        observations.append({**obs, 'id': key, 'node_id': key, 'local_id': obs['id'], 'reused': reused,
                             'scope': scope, 'context_index': index, 'branch': index})
    metrics = _metric_values(result, graph_result)
    source_arrays = [values for key, (values, obs) in samples.items()
                     if key.split('/', 1)[0] in ('shared', 'linear') and c.BLOCKS[obs['kind']]['category'] == 'source']
    metrics['input_sample_count'] = sum(len(values) for values in source_arrays)
    fingerprint = hashlib.sha256()
    for values in source_arrays:
        array = np.ascontiguousarray(values)
        fingerprint.update(array.dtype.str.encode()); fingerprint.update(str(array.shape).encode()); fingerprint.update(array.tobytes())
    input_hash = graph_result['input_hash'] if g else fingerprint.hexdigest()
    return {'document_token': built['token'], 'signal_token': built['signal_token'], 'scope': 'graph' if g else 'linear',
            'input_hash': input_hash, 'input_scope': 'shared_channel' if g else 'source',
            'graph_result': graph_result, 'result': result, 'metrics': metrics,
            'tools': _tool_results(document['tools'], samples, metrics), 'observations': observations,
            'execution': graph_result['execution'] if g else [{'section': 'linear', 'executed': [o['id'] for o in ctx.observations], 'reused': []}],
            'complete': True, 'seed': document['program']['seed']}


def run_task(raw, settings, progress=None, cancel=None, resume=None):
    """Run an explicit grid of whole documents with paired independent seeds."""
    if not isinstance(settings, dict): raise ValueError('实验设置需要 JSON 对象。')
    mode = settings.get('mode', 'batch')
    if mode not in ('scan', 'batch', 'pareto', 'classroom'): raise ValueError('选择扫描、批量、选参或课堂验收。')
    documents = settings.get('documents', [raw])
    if not isinstance(documents, list) or not 1 <= len(documents) <= 12: raise ValueError('实验队列使用 1–12 个工程。')
    documents = [build_document(d)['document'] for d in documents]
    # Trial receipts keep executable structure and editor annotations, while run
    # histories remain in the owning project instead of nesting in every trial.
    execution_keys = {'document_schema', 'name', 'description', 'program', 'graph', 'graphActiveBranch',
                      'tools', 'groups', 'subprojects', 'scratch', 'variables', 'annotations'}
    documents = [{k: v for k, v in d.items() if k in execution_keys} for d in documents]
    settings = copy.deepcopy(settings)
    if 'documents' in settings: settings['documents'] = documents
    seeds, frames = experiments.seeds_and_frames(settings, documents[0]['program']['seed'])
    axes = settings.get('axes', [])
    if not isinstance(axes, list) or len(axes) > 2: raise ValueError('每次实验最多配置两个参数轴。')
    seen = set()
    for axis in axes:
        if not isinstance(axis, dict) or axis.get('path') in seen: raise ValueError('参数轴使用互异的完整路径。')
        if not isinstance(axis.get('values'), list) or not 1 <= len(axis['values']) <= 32: raise ValueError('每个参数轴使用 1–32 个候选值。')
        if any(type(v) not in (int, float, bool) or not math.isfinite(v) for v in axis['values']): raise ValueError('参数候选值须为有限数值。')
        seen.add(axis['path'])
    combinations = list(itertools.product(*(a['values'] for a in axes))) if axes else [()]
    total = len(documents) * len(combinations) * len(seeds) * frames
    if total > 256: raise ValueError('一次实验最多运行 256 帧。')
    constraints = settings.get('constraints', [])
    if not isinstance(constraints, list) or len(constraints) > 24: raise ValueError('验收条件最多设置 24 项。')
    for rule in constraints: _rule(rule)
    objectives = settings.get('objectives', [{'metric': 'ber', 'direction': 'min'}, {'metric': 'evm_percent', 'direction': 'min'}])
    if not isinstance(objectives, list) or not 1 <= len(objectives) <= 4 or any(
            not isinstance(o, dict) or not isinstance(o.get('metric'), str) or o.get('direction') not in ('min', 'max') for o in objectives):
        raise ValueError('选参目标需要指标名称和 min / max 方向。')
    task_token = graph.digest({'documents': [build_document(d)['token'] for d in documents], 'settings': settings})
    value = {'task_token': task_token, 'mode': mode, 'documents': documents, 'settings': copy.deepcopy(settings),
             'rows': [], 'summaries': [], 'candidates': [], 'completed': 0, 'total': total, 'complete': False,
             'last_result': None, 'seed_policy': '各候选使用配对种子，每帧独立初始化。'}
    if resume:
        if resume.get('task_token') != task_token: raise ValueError('续跑工程与参数需要匹配原任务。')
        value['rows'] = copy.deepcopy(resume['rows']); value['last_result'] = copy.deepcopy(resume.get('last_result'))
    done = {(r['document_index'], r['candidate_index'], r['base_seed'], r['frame']) for r in value['rows']}
    candidates = []
    for di, document in enumerate(documents):
        for ci, parameters in enumerate(combinations):
            candidate = copy.deepcopy(document)
            for axis, parameter in zip(axes, parameters): set_parameter(candidate, axis['path'], parameter)
            build_document(candidate)
            candidates.append((di, ci, candidate, dict(zip((a['path'] for a in axes), parameters))))
    def summarize():
        value['completed'] = len(value['rows']); summaries = []
        for index, (di, ci, candidate, parameters) in enumerate(candidates):
            rows = [r for r in value['rows'] if r['document_index'] == di and r['candidate_index'] == ci]
            if not rows: continue
            common = set.intersection(*(set(row['metrics']) for row in rows))
            metrics = {key: float(np.mean([row['metrics'][key] for row in rows])) for key in common}
            prefixes = {''} | {key[:-len('bit_count')] for key in common if key.endswith('bit_count')}
            for prefix in prefixes:
                for count, errors, rate in (('bit_count', 'bit_errors', 'ber'), ('symbol_count', 'symbol_errors', 'ser')):
                    if prefix + count in common and prefix + errors in common:
                        n = sum(row['metrics'][prefix + count] for row in rows); err = sum(row['metrics'][prefix + errors] for row in rows)
                        metrics[prefix + count] = n; metrics[prefix + errors] = err; metrics[prefix + rate] = err / n if n else 0.
            for key in common:
                if key.endswith('.tested_cells'):
                    prefix = key[:-len('tested_cells')]
                    metrics[key] = sum(row['metrics'][key] for row in rows)
                    if prefix + 'crossings' in common:
                        metrics[prefix + 'crossings'] = sum(row['metrics'][prefix + 'crossings'] for row in rows)
                        metrics[prefix + 'crossing_fraction'] = metrics[prefix + 'crossings'] / metrics[key] if metrics[key] else 0.
            checks = [_measured_check(rule, metrics) for rule in constraints]
            tool_checks = [tool['passed'] for row in rows for tool in row['tools'] if tool['kind'] == 'assertion']
            summaries.append({'index': index, 'document_index': di, 'candidate_index': ci, 'name': candidate.get('name', '通信实验'),
                'parameters': parameters, 'runs': len(rows), 'metrics': metrics, 'checks': checks,
                'feasible': all(check['passed'] for check in checks) and all(tool_checks),
                'ber_interval': experiments.interval(metrics.get('bit_errors', 0), metrics.get('bit_count', 0)) if metrics.get('bit_count') else None})
        if mode == 'pareto' and summaries:
            from src.communication_experiment_v0410 import pareto_indices
            missing = {o['metric'] for o in objectives} - set.intersection(*(set(s['metrics']) for s in summaries))
            if missing: raise ValueError('选参结果缺少指标：' + '、'.join(sorted(missing)))
            front = pareto_indices(summaries, objectives)
            for i, item in enumerate(summaries): item['pareto'] = i in front
        value['summaries'] = summaries; value['candidates'] = summaries
        value['passed'] = bool(summaries) and all(s['feasible'] for s in summaries)
    summarize()
    # Each paired seed owns a frozen physical input, shared only by compatible candidates.
    caches = {}
    for di, ci, candidate, parameters in candidates:
        for seed in seeds:
            for frame in range(frames):
                if (di, ci, seed, frame + 1) in done: continue
                if cancel is not None and cancel.is_set(): return value
                trial = copy.deepcopy(candidate); actual_seed = (seed + frame) % 4294967295
                (trial['graph']['globals'] if trial.get('graph') else trial['program'])['seed'] = actual_seed
                before = time.perf_counter()
                try:
                    cache = caches.setdefault((di, seed, frame), {})
                    while len(caches) > 4: caches.pop(next(iter(caches)))
                    measured = run_document(trial, cache=cache, partial=True, cancel=cancel)
                except runtime.Cancelled: return value
                row = {'document_index': di, 'candidate_index': ci, 'seed': actual_seed, 'base_seed': seed, 'frame': frame + 1,
                       'parameters': parameters, 'document_token': measured['document_token'], 'metrics': measured['metrics'],
                       'scopes': ['shared', *[b['id'] for b in trial['graph']['branches']], 'merge', 'tail'] if trial.get('graph') else ['linear'],
                       'tools': [{k: v for k, v in tool.items() if k not in ('i', 'q')} for tool in measured['tools']],
                       'runtime_seconds': time.perf_counter() - before,
                       'input_hash': measured['input_hash'],
                       'execution': measured['execution']}
                value['rows'].append(row); value['last_result'] = measured; summarize()
                if progress: progress(value)
    value['complete'] = True
    return value


def restore_trial(task, row_index):
    row = task['rows'][c.numeric(row_index, '记录索引', 0, len(task['rows']) - 1, True)]
    document = copy.deepcopy(task['documents'][row['document_index']])
    for path, value in row['parameters'].items(): set_parameter(document, path, value)
    (document['graph']['globals'] if document.get('graph') else document['program'])['seed'] = row['seed']
    return build_document(document)['document']
