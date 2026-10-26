"""Editable classroom packages and measured multi-project experiment queues."""
import copy
import math
import time
import numpy as np
from src import communication_runtime as runtime
from src.communication_sweep import interval


MAX_RUNS = 256


def _text(value, label, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{label}需要 1–{limit} 个字符。')
    return value.strip()


def seeds_and_frames(settings, default_seed=42):
    from src import communications as c
    if not isinstance(settings, dict):
        raise ValueError('实验设置需要 JSON 对象。')
    seeds = settings.get('seeds', [default_seed])
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 32:
        raise ValueError('随机种子列表需要 1–32 项。')
    seeds = [c.numeric(seed, '随机种子', 0, 4294967294, True) for seed in seeds]
    if len(seeds) != len(set(seeds)):
        raise ValueError('随机种子列表应使用互异种子。')
    frames = c.numeric(settings.get('frames', 1), '每种子帧数', 1, 32, True)
    actual = [(seed + frame) % 4294967295 for seed in seeds for frame in range(frames)]
    if len(actual) != len(set(actual)):
        raise ValueError('种子加帧序号形成重复试验，请增大种子间隔。')
    return seeds, frames


def parameter_paths(program):
    from src import communications as c
    result = {key: program[key] for key in ('seed', 'sample_rate', 'sample_count', 'symbol_rate')}
    for block in program['blocks']:
        for key, value in block['params'].items():
            if key in c.BLOCKS[block['kind']]['params']:
                result[f'blocks.{block["id"]}.{key}'] = value
    return result


def validate_assignment(task):
    """A portable task embeds its original chain and explicit editable parameters."""
    from src import communications as c, communication_learning as learn
    if not isinstance(task, dict) or task.get('assignment_schema', 1) != 1:
        raise ValueError('教学实验包使用 assignment_schema: 1。')
    program = c.build(task.get('initial_program'))['program']
    title = _text(task.get('title'), '任务标题', 100)
    objective = _text(task.get('objective'), '任务目标')
    kind = task.get('kind', 'experiment')
    if kind not in ('experiment', 'repair'):
        raise ValueError('任务类型请选择 experiment 或 repair。')
    editable = task.get('editable', [])
    paths = parameter_paths(program)
    if not isinstance(editable, list) or any(not isinstance(path, str) or path not in paths for path in editable):
        raise ValueError('可调参数需要当前初始链路中的有效参数路径。')
    if len(editable) != len(set(editable)):
        raise ValueError('可调参数路径应唯一。')
    stages = task.get('stages')
    if not isinstance(stages, list) or not 1 <= len(stages) <= 8:
        raise ValueError('教学任务需要 1–8 个阶段。')
    normalized = []
    for stage in stages:
        if not isinstance(stage, dict):
            raise ValueError('每个阶段需要名称、目标和提示。')
        goals = stage.get('goals')
        learn.check(program, {'metrics': {}}, goals=goals)
        normalized.append({'name': _text(stage.get('name'), '阶段名称', 100),
                           'goals': copy.deepcopy(goals),
                           'hint': _text(stage.get('hint', '观察接收结果并调整开放参数。'), '阶段提示'),
                           'weight': c.numeric(stage.get('weight', 1), '阶段权重', .01, 100)})
    seeds, frames = seeds_and_frames({'seeds': task.get('seeds', [program['seed']]), 'frames': 1})
    return {'assignment_schema': 1, 'title': title, 'objective': objective, 'kind': kind,
            'initial_program': program, 'editable': editable, 'stages': normalized, 'seeds': seeds}


def _allowed_changes(task, candidate):
    from src import communications as c
    original = copy.deepcopy(task['initial_program'])
    current = c.build(candidate)['program']
    if [(b['id'], b['kind']) for b in original['blocks']] != [(b['id'], b['kind']) for b in current['blocks']]:
        raise ValueError('本任务保留初始积木及排列，按开放参数完成实验。')
    before, after = parameter_paths(original), parameter_paths(current)
    changes = [path for path in before if before[path] != after[path]]
    locked = [path for path in changes if path not in task['editable']]
    if locked:
        raise ValueError('请恢复固定参数：' + '、'.join(locked[:6]))
    # Compare the full normalized program after restoring permitted values so that
    # nested component definitions cannot bypass classroom parameter boundaries.
    for path in task['editable']:
        if path.startswith('blocks.'):
            _, block_id, parameter = path.split('.')
            next(b for b in original['blocks'] if b['id'] == block_id)['params'][parameter] = after[path]
        else:
            original[path] = after[path]
    if original != current:
        raise ValueError('请保留任务初始工程结构，并修改指定的开放参数。')
    return current, changes


def _run(program, seed, cancel):
    from src import communications as c
    if cancel is not None and cancel.is_set():
        raise runtime.Cancelled('实验已停止。')
    candidate = copy.deepcopy(program)
    candidate['seed'] = seed
    started = time.perf_counter()
    built = c.build(candidate)
    ctx = runtime.Observer(built, cancel=cancel)
    with runtime.execution(ctx):
        result = c.run(built['program'], built['token'])
    return result, time.perf_counter() - started


def classroom(task, program, settings=None, progress=None, cancel=None):
    """Run actual measurements across the teacher's seeds; unlock stages in order."""
    from src import communication_learning as learn
    task = validate_assignment(task)
    candidate, changes = _allowed_changes(task, program)
    seeds = task['seeds']
    trials = []
    for seed in seeds:
        measured, elapsed = _run(candidate, seed, cancel)
        trials.append({'seed': seed, 'metrics': measured['metrics'], 'runtime_seconds': elapsed,
                       'stages': [learn.check(candidate, measured, goals=s['goals']) for s in task['stages']]})
        if progress:
            progress({'completed': len(trials), 'total': len(seeds), 'trials': trials})
    stages = []; unlocked = True; earned = 0.
    for index, stage in enumerate(task['stages']):
        passed = all(trial['stages'][index]['passed'] for trial in trials)
        complete = unlocked and passed
        stages.append({**stage, 'index': index, 'unlocked': unlocked, 'passed': complete,
                       'checks': [{'seed': trial['seed'], **trial['stages'][index]} for trial in trials]})
        if complete:
            earned += stage['weight']
        unlocked = complete
    total_weight = sum(s['weight'] for s in task['stages'])
    return {'task': task, 'program': candidate, 'changes': changes, 'trials': trials, 'stages': stages,
            'passed': all(s['passed'] for s in stages), 'score': 100 * earned / total_weight,
            'completed': len(trials), 'total': len(seeds), 'complete': True,
            'evidence': '每个阶段目标均在任务指定的每个随机种子上重新运行并验收。'}


def _summary(rows, index, name):
    values = [r for r in rows if r['program_index'] == index]
    metrics = [r['metrics'] for r in values]
    bits = sum(m.get('bit_count', 0) for m in metrics)
    errors = sum(m.get('bit_errors', 0) for m in metrics)
    summary = {'program_index': index, 'name': name, 'runs': len(values), 'bit_count': bits,
               'bit_errors': errors, 'ber': errors / bits if bits else None,
               'ber_interval': interval(errors, bits) if bits else None,
               'runtime_seconds': sum(r['runtime_seconds'] for r in values)}
    for key in ('net_bit_rate', 'goodput_bps', 'mean_delivery_latency_seconds', 'frame_duration_seconds', 'evm_percent', 'rmse'):
        points = [m[key] for m in metrics if type(m.get(key)) in (int, float) and math.isfinite(m[key])]
        summary[key] = float(np.mean(points)) if points else None
        if points:
            summary[key + '_range'] = [float(min(points)), float(max(points))]
            summary[key + '_p95'] = float(np.percentile(points, 95))
    runtimes = [r['runtime_seconds'] for r in values]
    summary['runtime_p95_seconds'] = float(np.percentile(runtimes, 95)) if runtimes else None
    return summary


def batch(programs, settings, progress=None, cancel=None, resume=None):
    from src import communications as c
    if not isinstance(programs, list) or not 1 <= len(programs) <= 12:
        raise ValueError('批量实验需要 1–12 个工程。')
    prepared = [c.build(p)['program'] for p in programs]
    seeds, frames = seeds_and_frames(settings, prepared[0]['seed'])
    total = len(prepared) * len(seeds) * frames
    if total > MAX_RUNS:
        raise ValueError(f'批量实验最多执行 {MAX_RUNS} 次，请减少工程、种子或帧数。')
    names = settings.get('names', [f'工程 {i + 1}' for i in range(len(prepared))])
    if not isinstance(names, list) or len(names) != len(prepared):
        raise ValueError('工程名称数量应与工程数量一致。')
    names = [_text(name, '工程名称', 100) for name in names]
    mode = settings.get('mode', 'link')
    if mode not in ('link', 'protocol'):
        raise ValueError('批量模式请选择 link 或 protocol。')
    result = {'programs': prepared, 'settings': copy.deepcopy(settings), 'names': names, 'mode': mode,
              'rows': [], 'summaries': [], 'completed': 0, 'total': total, 'complete': False,
              'seed_policy': '各工程使用相同的种子和帧序号；每次运行独立初始化算法状态。',
              'latency_reference': '链路模式显示整帧发送时长；协议模式显示实际交付延迟。'}
    if resume:
        if resume.get('programs') != prepared or resume.get('settings') != settings:
            raise ValueError('续跑工程与检查点设置需要一致。')
        result['rows'] = copy.deepcopy(resume['rows'])
        result['completed'] = len(result['rows'])
        result['summaries'] = [_summary(result['rows'], i, name) for i, name in enumerate(names)]
    done = {(r['program_index'], r['base_seed'], r['frame']) for r in result['rows']}
    prior_elapsed = resume.get('elapsed_seconds', 0) if resume else 0
    started = time.perf_counter()
    for index, program in enumerate(prepared):
        for seed in seeds:
            for frame in range(frames):
                if (index, seed, frame + 1) in done:
                    continue
                if cancel is not None and cancel.is_set():
                    result['elapsed_seconds'] = prior_elapsed + time.perf_counter() - started
                    return result
                trial_seed = (seed + frame) % 4294967295
                try:
                    if mode == 'protocol':
                        from src.communication_protocols import protocol
                        trial = copy.deepcopy(program); trial['seed'] = trial_seed
                        before = time.perf_counter()
                        measured = protocol(trial, settings.get('protocol', {}), cancel=cancel)
                        elapsed = time.perf_counter() - before
                    else:
                        measured, elapsed = _run(program, trial_seed, cancel)
                except runtime.Cancelled:
                    result['elapsed_seconds'] = prior_elapsed + time.perf_counter() - started
                    return result
                metrics = copy.deepcopy(measured['metrics'])
                if mode == 'link' and metrics.get('bit_count') and metrics.get('net_bit_rate', 0) > 0:
                    metrics['frame_duration_seconds'] = metrics['bit_count'] / metrics['net_bit_rate']
                result['rows'].append({'program_index': index, 'name': names[index], 'seed': trial_seed,
                                       'base_seed': seed, 'frame': frame + 1, 'metrics': metrics, 'runtime_seconds': elapsed})
                result['completed'] += 1
                result['summaries'] = [_summary(result['rows'], i, name) for i, name in enumerate(names)]
                result['elapsed_seconds'] = prior_elapsed + time.perf_counter() - started
                if progress:
                    progress(result)
    result['complete'] = True
    result['analysis'] = batch_analysis(result)
    return result


def target_search(program, settings, progress=None, cancel=None, resume=None):
    """Measure all ordered SNR grid points with matched seeds and choose the first pass."""
    from src import communications as c
    from src.communication_sweep import parameter
    built = c.build(program); program = built['program']
    seeds, frames = seeds_and_frames(settings, program['seed'])
    block, key, spec = parameter(program, {'block_id': settings.get('block_id'), 'parameter': settings.get('parameter')})
    if key not in ('snr_db', 'esn0_db'):
        raise ValueError('最低信噪比搜索请选择信道的 SNR / EsN₀ 参数。')
    start = c.numeric(settings.get('start', 0), '起始信噪比', spec['min'], spec['max'])
    stop = c.numeric(settings.get('stop', 16), '结束信噪比', start, spec['max'])
    step = c.numeric(settings.get('step', 2), '搜索步长', .01, max(.01, spec['max'] - spec['min']))
    target = c.numeric(settings.get('target_ber', .01), '目标 BER', 0, 1)
    count = math.floor((stop - start) / step + 1e-9) + 1
    if count > 41 or count * len(seeds) * frames > MAX_RUNS:
        raise ValueError('搜索最多 41 个信噪比点、256 次实际运行。')
    results = {'program': program, 'settings': copy.deepcopy(settings), 'target_ber': target,
               'points': [], 'selected': None, 'completed': 0, 'total': count * len(seeds) * frames, 'complete': False,
               'criterion': '按错误比特总数 / 比特总数验收，选择扫描范围内满足目标的最低信噪比点。',
               'seed_policy': '各信噪比点使用相同种子序列。', 'resolution_db': step}
    if resume:
        if resume.get('program') != program or resume.get('settings') != settings:
            raise ValueError('搜索续跑设置需要与检查点一致。')
        results.update(copy.deepcopy(resume))
        results['complete'] = False
    for index in range(count):
        if index < len(results['points']):
            continue
        if cancel is not None and cancel.is_set():
            return results
        value = start + index * step
        candidate = copy.deepcopy(program)
        next(b for b in candidate['blocks'] if b['id'] == block['id'])['params'][key] = value
        # Keep the exact AWGN noise scale in a directly connected soft demapper.
        if block['kind'] == 'awgn' and sum(b['kind'] == 'awgn' for b in candidate['blocks']) == 1 and all(b['kind'] not in c.CHANNELS or b['kind'] in ('awgn', 'ideal') for b in candidate['blocks']):
            for b in candidate['blocks']:
                if b['kind'].startswith('soft_'):
                    b['params']['noise_variance'] = max(.000001, min(100, 10 ** (-value / 10)))
        partial = results.get('current_batch')
        def notify(value):
            results.update(current_batch=copy.deepcopy(value), current_snr_db=start + index * step,
                           completed=index * len(seeds) * frames + value['completed'])
            if progress:
                progress(results)
        measured = batch([candidate], {'seeds': seeds, 'frames': frames}, notify, cancel, partial)
        if not measured['complete']:
            notify(measured)
            return results
        summary = measured['summaries'][0]
        if not summary['bit_count']:
            raise ValueError('目标 BER 搜索需要可统计误码率的数字链路。')
        point = {'snr_db': value, 'program': candidate, **summary, 'passed': summary['ber'] <= target}
        results['points'].append(point)
        results['completed'] = (index + 1) * len(seeds) * frames
        results.pop('current_batch', None)
        if point['passed'] and results['selected'] is None:
            results['selected'] = copy.deepcopy(point)
        if progress:
            progress(results)
    results['complete'] = True
    return results


def batch_analysis(result):
    """Measured distributions and differences paired by base seed and frame."""
    distributions = []; paired = []
    rows = result['rows']
    for index, name in enumerate(result['names']):
        selected = [r for r in rows if r['program_index'] == index]
        values = {}
        for metric in ('ber', 'goodput_bps', 'net_bit_rate', 'mean_delivery_latency_seconds', 'frame_duration_seconds'):
            samples = [r['metrics'][metric] for r in selected if type(r['metrics'].get(metric)) in (int, float)]
            if samples:
                values[metric] = {'values': samples, 'quantiles': np.percentile(samples, [0, 25, 50, 75, 100]).tolist()}
        distributions.append({'program_index': index, 'name': name, 'metrics': values})
        if index:
            baseline = {(r['base_seed'], r['frame']): r for r in rows if r['program_index'] == 0}
            for r in selected:
                other = baseline.get((r['base_seed'], r['frame']))
                if other:
                    delta = {key: value - other['metrics'][key] for key, value in r['metrics'].items()
                             if type(value) in (int, float) and type(other['metrics'].get(key)) in (int, float)}
                    paired.append({'program_index': index, 'name': name, 'base_seed': r['base_seed'],
                                   'frame': r['frame'], 'delta': delta})
    return {'distributions': distributions, 'paired': paired, 'reference': result['names'][0]}


def validate_submission(raw):
    """Portable student work: independent stage snapshots and chronological attempts."""
    if not isinstance(raw, dict) or raw.get('submission_schema') != 1:
        raise ValueError('作业包使用 submission_schema: 1。')
    task = validate_assignment(raw.get('task'))
    stages = raw.get('stages', [None] * len(task['stages']))
    attempts = raw.get('attempts', [])
    hints = raw.get('hint_events', [])
    if not isinstance(stages, list) or len(stages) != len(task['stages']):
        raise ValueError('作业阶段数需要与任务一致。')
    if not isinstance(attempts, list) or len(attempts) > 100 or not isinstance(hints, list) or len(hints) > 200:
        raise ValueError('作业保留最多 100 次验收和 200 次提示记录。')
    for attempt in attempts + [s for s in stages if s]:
        if not isinstance(attempt, dict) or type(attempt.get('stage')) is not int or not 0 <= attempt['stage'] < len(stages):
            raise ValueError('验收记录需要有效阶段。')
        _allowed_changes(task, attempt.get('program'))
        if not isinstance(attempt.get('trials'), list) or type(attempt.get('passed')) is not bool:
            raise ValueError('验收记录需要测量与通过状态。')
    for index, stage in enumerate(stages):
        if stage and (stage['stage'] != index or not stage['passed']):
            raise ValueError('阶段成果需要对应阶段的通过记录。')
        if stage and any(s is None for s in stages[:index]):
            raise ValueError('阶段成果按任务顺序保存。')
    for event in hints:
        if not isinstance(event, dict) or type(event.get('stage')) is not int or not 0 <= event['stage'] < len(stages):
            raise ValueError('提示记录需要有效阶段。')
    active = next((i for i, value in enumerate(stages) if value is None), len(stages) - 1)
    from src import communications as c
    program = c.build(raw.get('program', task['initial_program']))['program']
    _allowed_changes(task, program)
    return {'submission_schema': 1, 'task': task, 'student': _text(raw.get('student', '我的实验'), '学生姓名', 100),
            'notes': str(raw.get('notes', ''))[:12000], 'attempts': copy.deepcopy(attempts),
            'stages': copy.deepcopy(stages), 'hint_events': copy.deepcopy(hints), 'active_stage': active, 'program': program}


def classroom_stage(submission, program, stage, progress=None, cancel=None):
    from datetime import datetime, timezone
    from src import communications as c, communication_learning as learn
    saved = validate_submission(submission); task = saved['task']
    stage = c.numeric(stage, '验收阶段', 0, len(task['stages']) - 1, True)
    if any(value is None for value in saved['stages'][:stage]):
        raise ValueError('完成前一阶段后继续验收。')
    if len(saved['attempts']) >= 100:
        raise ValueError('本作业已保存 100 次验收，请导出成果。')
    candidate, changes = _allowed_changes(task, program)
    trials = []
    for seed in task['seeds']:
        measured, elapsed = _run(candidate, seed, cancel)
        checked = learn.check(candidate, measured, goals=task['stages'][stage]['goals'])
        trials.append({'seed': seed, 'metrics': measured['metrics'], 'runtime_seconds': elapsed, **checked})
        if progress:
            progress({'completed': len(trials), 'total': len(task['seeds']), 'trials': trials})
    attempt = {'stage': stage, 'number': len(saved['attempts']) + 1,
               'time': datetime.now(timezone.utc).isoformat(), 'program': copy.deepcopy(candidate),
               'changes': changes, 'trials': trials, 'passed': all(t['passed'] for t in trials),
               'notes': saved['notes'], 'hints_used': sum(e['stage'] == stage for e in saved['hint_events'])}
    saved['attempts'].append(attempt); saved['program'] = candidate
    if attempt['passed']:
        saved['stages'][stage] = copy.deepcopy(attempt)
    saved['active_stage'] = next((i for i, value in enumerate(saved['stages']) if value is None), len(saved['stages']) - 1)
    score = sum(s['weight'] for i, s in enumerate(task['stages']) if saved['stages'][i]) / sum(s['weight'] for s in task['stages']) * 100
    return {'submission': saved, 'attempt': attempt, 'score': score, 'passed': all(saved['stages']),
            'completed': len(trials), 'total': len(trials), 'complete': True}
