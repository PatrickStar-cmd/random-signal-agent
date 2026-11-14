"""One fork, two to four receivers and one typed two-input merge.

The graph owns the shared blocks and common tail. Linear programs are projections
used by the established compiler and numerical engine, never independent copies.
"""
import copy
import hashlib
import json
import re
import numpy as np
from src import communication_segments as segments
from src import communication_sensing_v0411 as sensing

GLOBALS = ('seed', 'sample_rate', 'sample_count', 'symbol_rate')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def lanes(graph):
    return [('shared', graph['prefix']), *[(b['id'], b['blocks']) for b in graph['branches']], ('tail', graph['tail'])]


def nodes(graph):
    result = {lane + '/' + b['id']: {'lane': lane, **b} for lane, blocks in lanes(graph) for b in blocks}
    result['merge'] = {'id': 'merge', 'kind': 'branch_merge', 'lane': 'merge', 'params': graph['merge']}
    result.update({a['id']: {**a, 'lane': 'analysis'} for a in graph['analyses']})
    return result


def connections(graph):
    edges = []
    def add(a, b, port='in', output='out'):
        edges.append({'from': a, 'to': b, 'output': output, 'input': port})
    for lane, blocks in lanes(graph):
        keys = [lane + '/' + b['id'] for b in blocks]
        for a, b in zip(keys, keys[1:]):
            add(a, b)
    fork = 'shared/' + graph['prefix'][-1]['id']
    for branch in graph['branches']:
        add(fork, branch['id'] + '/' + branch['blocks'][0]['id'])
    for index, branch_id in enumerate(graph['merge']['inputs']):
        branch = next(b for b in graph['branches'] if b['id'] == branch_id)
        add(branch_id + '/' + branch['blocks'][-1]['id'], 'merge', 'ab'[index])
    add('merge', 'tail/' + graph['tail'][0]['id'])
    for analysis in graph['analyses']:
        add(analysis['source'], analysis['id'], output='power')
    return edges


def from_programs(programs, names=None, domain='llr'):
    from src import communications as c, communication_studio as studio
    builds, shared = studio.shared_prefix(programs)
    branches, tails = [], []
    for i, built in enumerate(builds):
        blocks = built['program']['blocks']
        demod = next((j for j, b in enumerate(blocks) if b['kind'].startswith(('soft_', 'demod_'))), None)
        if demod is None or domain == 'llr' and not blocks[demod]['kind'].startswith('soft_'):
            raise ValueError('LLR 汇合请选择软解调链路；复符号汇合请选择数字解调链路。')
        boundary = demod + (domain == 'llr')
        if boundary <= len(shared):
            raise ValueError('复符号汇合需要至少一个接收处理积木。')
        branches.append({'id': 'rx' + str(i + 1), 'name': (names or [])[i] if names and i < len(names) else f'接收分支 {i+1}',
                         'blocks': copy.deepcopy(blocks[len(shared):boundary])})
        tails.append(blocks[boundary:])
    if any([(b['kind'], b['params']) for b in tail] != [(b['kind'], b['params']) for b in tails[0]] for tail in tails[1:]):
        raise ValueError('各接收分支采用相同的公共解调 / 译码尾段。')
    graph = {'schema': 1, 'globals': {k: builds[0]['program'][k] for k in GLOBALS},
             'prefix': copy.deepcopy(builds[0]['program']['blocks'][:len(shared)]), 'branches': branches,
             'merge': {'domain': domain, 'mode': 'select', 'select': 0, 'weights': [.5, .5], 'inputs': ['rx1', 'rx2']},
             'tail': copy.deepcopy(tails[0]), 'analyses': [], 'layout': {}}
    graph['edges'] = connections(graph)
    return graph


def demo(kind='equalizer'):
    from src import communications as c
    if kind == 'sensing':
        p = copy.deepcopy(c.PRESETS['ofdm_isac_multi']['program'])
        graph = from_programs([p, copy.deepcopy(p)], ['训练均衡 A', '训练均衡 B'], 'symbols')
        source = 'rx1/' + graph['branches'][0]['blocks'][-1]['id']
        graph['analyses'] = [{'id': 'cfar1', 'kind': 'analysis_cfar2d', 'source': source, 'params': dict(sensing.DEFAULTS)}]
        graph['edges'] = connections(graph)
        return graph
    p = c.preset(['random_bits', 'conv_encode', 'mod_qpsk', 'tx_frame', 'complex_multipath', 'awgn',
                  'rx_frame', 'rx_equalizer', 'soft_qpsk', 'conv_soft_decode', 'sink'],
                 {0: {'count': 2048}, 3: {'length': 1024}, 4: {'taps': '1,0.65+0.15j'},
                  5: {'esn0_db': 18}, 8: {'noise_variance': 10**(-1.8)}})
    second = copy.deepcopy(p)
    second['blocks'][7]['params']['dfe'] = True
    return from_programs([p, second], ['线性 NLMS', '判决反馈 DFE'])


def normalize(raw):
    from src import communications as c
    if not isinstance(raw, dict) or raw.get('schema') != 1:
        raise ValueError('可视工程版本应为 graph.schema=1。')
    g = copy.deepcopy(raw)
    if not isinstance(g.get('branches'), list) or not 2 <= len(g['branches']) <= 4:
        raise ValueError('可视工程使用 2–4 条接收分支。')
    ids = [b.get('id') for b in g['branches']]
    if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not re.fullmatch(r'rx[\w-]{1,40}', i) for i in ids):
        raise ValueError('接收分支 ID 使用 rx 开头的唯一名称。')
    for lane, blocks in lanes(g):
        if not isinstance(blocks, list) or not blocks:
            raise ValueError('共享前段、接收分支和公共尾段均需包含积木。')
        normalized = c.normalize({'schema': 1, **g['globals'], 'blocks': blocks}, draft=True)
        blocks[:] = normalized['blocks']
        g['globals'] = {k: normalized[k] for k in GLOBALS}
    for branch in g['branches']:
        if not isinstance(branch.get('name'), str) or not 1 <= len(branch['name']) <= 80:
            raise ValueError('分支名称使用 1–80 个字符。')
    q = g['merge']
    if q.get('domain') not in ('symbols', 'llr') or q.get('mode') not in ('select', 'weighted'):
        raise ValueError('汇合选择复符号 / LLR、选择一路 / 加权相加。')
    if not isinstance(q.get('inputs'), list) or len(q['inputs']) != 2 or len(set(q['inputs'])) != 2 or any(v not in ids for v in q['inputs']):
        raise ValueError('汇合节点需要两条不同接收分支。')
    q['select'] = c.numeric(q.get('select', 0), '选择输入', 0, 1, True)
    weights = q.get('weights', [.5, .5])
    if not isinstance(weights, list) or len(weights) != 2 or not any(weights):
        raise ValueError('填写两个汇合权重，至少一个具有非零值。')
    q['weights'] = [c.numeric(w, '汇合权重', -10, 10) for w in weights]
    if not isinstance(g.get('analyses', []), list) or len(g.get('analyses', [])) > 4:
        raise ValueError('每个可视工程最多保存 4 个分析节点。')
    g.setdefault('analyses', [])
    ordinary = {lane + '/' + b['id']: b for lane, blocks in lanes(g) for b in blocks}
    seen = set(ordinary) | {'merge'}
    for a in g['analyses']:
        if not isinstance(a.get('id'), str) or not re.fullmatch(r'cfar[\w-]{1,40}', a['id']) or a['id'] in seen or a.get('kind') != 'analysis_cfar2d':
            raise ValueError('分析节点使用唯一的 CFAR ID。')
        if a.get('source') not in ordinary or ordinary[a['source']]['kind'] != 'rx_isac_ofdm':
            raise ValueError('CFAR 分析端口连接 OFDM 通信与测距测速输出。')
        seen.add(a['id']); a['params'] = sensing.settings(a.get('params'))
    if not isinstance(g.get('edges'), list) or len(g['edges']) > 160:
        raise ValueError('连接表格式无效。')
    for edge in g['edges']:
        if set(edge) != {'from', 'to', 'output', 'input'} or edge['from'] not in seen or edge['to'] not in seen or edge['output'] not in ('out', 'power') or edge['input'] not in ('in', 'a', 'b'):
            raise ValueError('连接须指向工程内的有效端口。')
    g.setdefault('layout', {})
    if not isinstance(g['layout'], dict):
        raise ValueError('布局使用节点坐标表。')
    for key, pos in g['layout'].items():
        if key not in seen or not isinstance(pos, dict) or set(pos) != {'x', 'y'}:
            raise ValueError('布局坐标须属于有效节点。')
        for axis in ('x', 'y'):
            pos[axis] = c.numeric(pos[axis], '节点坐标', 0, 10000)
    return g


def ordered(graph):
    """Read each lane's order from its edges, then validate the sole fork/merge."""
    g = normalize(graph)
    for lane, blocks in lanes(g):
        lookup = {lane + '/' + b['id']: b for b in blocks}
        inner = [e for e in g['edges'] if e['from'] in lookup and e['to'] in lookup and e['output'] == 'out']
        incoming = {e['to'] for e in inner}
        heads = set(lookup) - incoming
        if len(heads) != 1 or len(inner) != len(blocks) - 1:
            raise ValueError(f'{lane} 的积木需要连接成完整、单向的链路。')
        path, key = [], heads.pop()
        while key not in path:
            path.append(key)
            following = [e['to'] for e in inner if e['from'] == key]
            if not following: break
            if len(following) != 1: raise ValueError('分流位于共享信道之后。')
            key = following[0]
        if len(path) != len(blocks): raise ValueError('请将链路中的所有积木连接到汇合或信宿。')
        blocks[:] = [lookup[k] for k in path]
    expected = sorted(json.dumps(e, sort_keys=True) for e in connections(g))
    actual = sorted(json.dumps(e, sort_keys=True) for e in g['edges'])
    if expected != actual:
        raise ValueError('请连接共享前段、各接收分支、汇合 A/B 输入、公共尾段及分析端口。')
    return g


def projection(g, branch_id):
    branch = next(b for b in g['branches'] if b['id'] == branch_id)
    return {'schema': 1, **g['globals'], 'blocks': copy.deepcopy(g['prefix'] + branch['blocks'] + g['tail'])}


def identity(g):
    value = {k: v for k, v in g.items() if k != 'layout'}
    value['edges'] = sorted(g['edges'], key=lambda e: (e['from'], e['output'], e['to'], e['input']))
    return digest(value)


def build(raw):
    from src import communications as c, communication_studio as studio
    g = ordered(raw)
    builds = [c.build(projection(g, b['id'])) for b in g['branches']]
    _, shared = studio.shared_prefix([b['program'] for b in builds])
    if len(shared) != len(g['prefix']):
        raise ValueError('分流点放在共享信道之后、接收处理之前。')
    ports = {}
    signatures = []
    for branch, compiled in zip(g['branches'], builds):
        if compiled.get('transport') != 'advanced' or compiled['source_kind'] == 'analog':
            raise ValueError('可视分段实验使用单帧数字复基带链路，可从 NLMS / DFE 示例开始。')
        if any(b['kind'] in ('huffman_encode',) for b in g['prefix']):
            raise ValueError('分段数字实验请选择固定码长的信源编码。')
        program = compiled['program']
        stop = len(g['prefix']) + len(branch['blocks']) - 1
        point = program['blocks'][stop]
        row = compiled['plan'][stop]
        domain = g['merge']['domain']
        if domain == 'llr' and (row['output'] != 'LLR' or not point['kind'].startswith('soft_')):
            raise ValueError('LLR 汇合连接软解调器的输出。')
        if domain == 'symbols' and (row['output'] not in ('复符号', '复基带符号') or not g['tail'][0]['kind'].startswith(('demod_', 'soft_'))):
            raise ValueError('复符号汇合连接恢复后的符号和公共解调器。')
        f = compiled['features']
        scheme = f['modulator']['kind'][4:]
        signatures.append((domain, scheme, g['globals']['symbol_rate'], row['count']))
        for p in studio.describe(program)['ports']:
            lane = 'shared' if p['id'] in shared else branch['id'] if any(b['id'] == p['id'] for b in branch['blocks']) else 'tail'
            ports[lane + '/' + p['id']] = p
    if len(set(signatures)) != 1:
        raise ValueError('汇合端口的符号制式、点数和速率需要一致。')
    token = identity(g)
    return {'graph': g, 'token': token, 'ports': ports, 'builds': builds,
            'input_version': digest({'globals': g['globals'], 'blocks': g['prefix']}),
            'contract': {'frame': 0, 'symbol_origin': 0, 'bit_origin': 0,
                         'codeword': 'shared_encoder_frame', 'llr_sign': 'log_P0_over_P1',
                         'alignment': 'receiver_payload_order', 'branches': len(builds)}}


def _merge_snapshots(g, entries):
    from src import communication_dsp as dsp, communication_algorithms as algorithms
    q = g['merge']; candidates = [entries[key]['snapshot'] for key in q['inputs']]
    selected = q['select'] if q['mode'] == 'select' else 0 if q['weights'] == [1, 0] else 1 if q['weights'] == [0, 1] else None
    base = copy.deepcopy(candidates[selected if selected is not None else 0])
    arrays, variances = [], []
    for snap in candidates:
        v = snap['variables']; a = v['data']
        variance = v['wireless_state'].get('soft_variance', v['noise_estimate'])
        if q['domain'] == 'symbols':
            a = a[v['prefix']:]
            if g['tail'][0]['params'].get('compensate', False): a = a / v['gain']
            a = np.pad(a[:len(v['mapped'])], (0, max(0, len(v['mapped']) - len(a))))
            variance = v['wireless_state'].get('soft_variance', v['noise_estimate'] if g['tail'][0]['params'].get('automatic_variance') else g['tail'][0]['params'].get('noise_variance'))
        arrays.append(a); variances.append(variance)
    if arrays[0].shape != arrays[1].shape or candidates[0]['variables']['fs'] != candidates[1]['variables']['fs']:
        raise ValueError('汇合输入的实际长度和速率需要一致。')
    output = arrays[selected].copy() if selected is not None else sum(w * a for w, a in zip(q['weights'], arrays))
    v = base['variables']
    noise_method = 'selected_receiver_variance'
    effective_variance = variances[selected] if selected is not None else None
    if selected is None:
        v['data'] = output
        if q['domain'] == 'llr':
            v['demapped'] = (output < 0).astype(np.uint8)
            _, v['decided_indices'] = dsp.map_bits(v['demapped'], v['scheme'])
            v['decision_symbols'] = sum(w * snap['variables']['decision_symbols'] for w, snap in zip(q['weights'], candidates))
        else:
            v['prefix'] = 0; v['gain'] = 1 + 0j
            effective_variance, _ = algorithms.noise_estimate(output, dsp.constellation(v['scheme'])[1])
            v['noise_estimate'] = effective_variance
            v['wireless_state']['soft_variance'] = effective_variance
            noise_method = 'measured_merged_decision_residual'
    details = {**q, 'count': len(output), 'sha256': hashlib.sha256(output.tobytes()).hexdigest(),
               'noise_method': noise_method, 'noise_variance': np.asarray(effective_variance).tolist() if effective_variance is not None else None,
               'input_relation': 'shared_channel_correlated', 'llr_sign': 'log_P0_over_P1'}
    return base, details, output


def run(raw, token, cache=None, partial=False, progress=None, cancel=None, contexts=None,
        gate=None, on_context=None):
    built = build(raw)
    if token != built['token']: raise ValueError('连接或参数已更新，请重新构建可视工程。')
    g = built['graph']; cache = cache if cache is not None else {}
    input_version = built['input_version']; reuse = partial and gate is None and cache.get('input_version') == input_version
    def scoped_gate(scope, index):
        if gate is None: return None
        def observe(row):
            key = 'merge' if row['id'] == 'merge-output' else scope + '/' + row['id']
            gate({**row, 'id': key, 'node_id': key, 'local_id': row['id'],
                  'scope': 'merge' if key == 'merge' else scope, 'context_index': index})
        return observe
    execution = []; entries = cache.get('branches', {}) if reuse else {}
    if reuse:
        frozen = cache['frozen']
        execution.append({'section': 'shared', 'executed': [], 'reused': [b['id'] for b in g['prefix']]})
    else:
        _, ctx, actual = segments.execute(built['builds'][0], stop_after=len(g['prefix']) - 1, cancel=cancel,
                                         gate=scoped_gate('shared', 0), on_context=on_context, scope='shared')
        frozen = ctx.snapshot
        execution.append({'section': 'shared', 'executed': actual, 'reused': []})
    source_hash = segments.input_hash(frozen)
    results = []
    current = {}
    for i, (branch, compiled) in enumerate(zip(g['branches'], built['builds'])):
        key = digest({'input': input_version, 'blocks': branch['blocks'], 'tail': g['tail']})
        saved = entries.get(branch['id'])
        if reuse and saved and saved['key'] == key:
            entry = saved
            actual = []
        else:
            stop = len(g['prefix']) + len(branch['blocks']) - 1
            _, ctx, actual = segments.execute(compiled, frozen, stop, cancel,
                                             gate=scoped_gate(branch['id'], i), on_context=on_context, scope=branch['id'])
            entry = {'key': key, 'snapshot': ctx.snapshot}
            result, final_ctx, tail_actual = segments.execute(compiled, ctx.snapshot, cancel=cancel, scope=branch['id'])
            entry['result'] = result
            entry['observer'] = final_ctx
            actual += tail_actual
        if contexts is not None: contexts.append(entry['observer'])
        result = copy.deepcopy(entry['result'])
        result['experience']['graph'] = {'token': token, 'branch': branch['id'], 'input_version': input_version, 'input_hash': source_hash}
        results.append({'id': branch['id'], 'name': branch['name'], 'result': result})
        current[branch['id']] = entry
        execution.append({'section': branch['id'], 'executed': actual,
                          'reused': [] if actual else [b['id'] for b in branch['blocks'] + g['tail']]})
        if progress: progress({'completed': i + 1, 'total': len(g['branches']) + 1, 'input_hash': source_hash})
    merged, merge, merge_values = _merge_snapshots(g, current)
    base_choice = g['merge']['select'] if g['merge']['mode'] == 'select' else int(g['merge']['weights'] == [0, 1])
    base_id = g['merge']['inputs'][base_choice]
    base_index = next(i for i, b in enumerate(g['branches']) if b['id'] == base_id)
    compiled = built['builds'][base_index]
    merged['index'] = len(g['prefix']) + len(g['branches'][base_index]['blocks']) - 1
    result, ctx, actual = segments.execute(compiled, merged, cancel=cancel,
        gate=scoped_gate('tail', len(g['branches'])), on_context=on_context, scope='tail',
        initial=({'id': 'merge-output', 'kind': 'branch_merge', 'label': '🔗 双输入汇合'},
                 merge_values, 'LLR' if g['merge']['domain'] == 'llr' else '复符号'))
    merge['observation_id'] = 'merge-output'
    result['experience']['graph'] = {'token': token, 'branch': 'merge', 'input_version': input_version, 'input_hash': source_hash}
    result['experience']['merge'] = merge
    if contexts is not None: contexts.append(ctx)
    execution.append({'section': 'merge-tail', 'executed': actual, 'reused': []})
    analyses = []
    for a in g['analyses']:
        lane, block_id = a['source'].split('/', 1)
        entry = current[lane]
        measured = entry['result']['advanced']['wireless']['rx_isac_ofdm']['sensing']
        detection = sensing.detect(measured['power'], measured['range_axis_m'], measured['velocity_axis_mps'], a['params'])
        analyses.append({'id': a['id'], 'source': a['source'], 'input_hash': source_hash, 'graph_token': token,
                         'power': measured['power'], **detection})
    seen = set()
    def memory_bytes(value):
        if id(value) in seen: return 0
        seen.add(id(value))
        if isinstance(value, np.ndarray): return value.nbytes
        if isinstance(value, dict): return sum(memory_bytes(v) for v in value.values())
        if isinstance(value, (list, tuple)): return sum(memory_bytes(v) for v in value)
        if hasattr(value, 'values') and hasattr(value, 'observations'): return memory_bytes(value.values)
        return 0
    from src import communications as c
    if memory_bytes([frozen, current]) > 2 * c.CONFIG['max_capture_bytes']:
        raise ValueError('冻结工程超过 128 MiB，请减少帧长或接收分支。')
    cache.clear(); cache.update(input_version=input_version, frozen=frozen, branches=current)
    if progress: progress({'completed': len(g['branches']) + 1, 'total': len(g['branches']) + 1, 'input_hash': source_hash})
    return {'graph_token': token, 'input_version': input_version, 'input_hash': source_hash,
            'shared_reused': bool(reuse), 'execution': execution, 'branches': results, 'merge': merge,
            'merged_result': result, 'analyses': analyses, 'complete': True,
            'contract': built['contract'], 'program': compiled['program']}


def python_export(raw):
    g = build(raw)['graph']
    payload = json.dumps(g, ensure_ascii=False, indent=2)
    return ('"""Run from the installed RandomSign runtime directory."""\nimport json\n'
            'from src import communication_graph_v0411 as graph\n\n'
            f'project = json.loads({payload!r})\n'
            'built = graph.build(project)\nresult = graph.run(project, built["token"])\n'
            'print(json.dumps(result, ensure_ascii=False, indent=2))\n')
