"""Measured run inspection, constrained design, classroom review and frame scenarios."""
import copy
import hashlib
import itertools
import json
import math
import time
import numpy as np

from src import communication_experiments as experiments
from src import communication_runtime as runtime


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise runtime.Cancelled('实验已取消。')


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def _change(program, block_id, parameter, value):
    if block_id == 'global':
        program[parameter] = value
    else:
        next(block for block in program['blocks'] if block['id'] == block_id)['params'][parameter] = value


def _axis(program, axis):
    from src import communications as c
    from src.communication_sweep import parameter
    if not isinstance(axis, dict) or not isinstance(axis.get('values'), list) or not 1 <= len(axis['values']) <= 21:
        raise ValueError('每个参数轴填写 1–21 个离散候选值。')
    target = {'global': axis.get('parameter')} if axis.get('block_id') == 'global' else {
        'block_id': axis.get('block_id'), 'parameter': axis.get('parameter')}
    block, key, spec = parameter(program, target)
    values = []
    for value in axis['values']:
        if spec['type'] == 'select':
            if value not in spec['choices']:
                raise ValueError(f'{spec["label"]}候选值请选择目录中的选项。')
        else:
            value = c.numeric(value, spec['label'], spec['min'], spec['max'], spec['type'] == 'integer')
        if value in values:
            raise ValueError('参数候选值应唯一。')
        values.append(value)
    return {'block_id': block['id'] if block else 'global', 'parameter': key, 'values': values}


def _rule(rule):
    if not isinstance(rule, dict) or not isinstance(rule.get('metric'), str) or not rule['metric']:
        raise ValueError('指标规则需要 metric。')
    if rule.get('operator') not in ('<=', '>=', '==') or not _number(rule.get('value')):
        raise ValueError('指标规则需要 <=、>= 或 == 与有限阈值。')
    return {key: rule[key] for key in ('metric', 'operator', 'value')}


def _check(metrics, rule):
    value = metrics.get(rule['metric'])
    passed = _number(value) and {'<=': lambda: value <= rule['value'],
                                '>=': lambda: value >= rule['value'],
                                '==': lambda: value == rule['value']}[rule['operator']]()
    return {**rule, 'actual': value, 'passed': bool(passed)}


def _run(program, seed, cancel=None, states=None, frame=0, observer_callback=None):
    from src import communications as c
    _cancel(cancel)
    candidate = copy.deepcopy(program); candidate['seed'] = seed
    built = c.build(candidate)
    observer = runtime.Observer(built, cancel=cancel, states=states, retain=True)
    observer.frame = frame
    if observer_callback:
        observer_callback(observer)
    started = time.perf_counter()
    with runtime.execution(observer):
        result = c.run(built['program'], built['token'])
    elapsed = time.perf_counter() - started
    result['experience'] = {'observations': observer.observations, 'frame': frame, 'contract': 1}
    metrics = {key: value for key, value in result['metrics'].items() if _number(value)}
    metrics['runtime_seconds'] = elapsed
    if metrics.get('net_bit_rate', 0) > 0 and 'bit_count' in metrics:
        metrics['frame_duration_seconds'] = metrics['bit_count'] / metrics['net_bit_rate']
    return result, metrics


def inspect_run(program, result):
    """Return only evidence recorded in this result, including actual codec traces."""
    from src import communications as c
    program = c.build(program)['program']
    if not isinstance(result, dict):
        raise ValueError('先运行当前工程，再查看测量诊断。')
    blocks = {block['id']: block for block in program['blocks']}
    observations = result.get('experience', {}).get('observations', [])
    profile = [{key: obs.get(key) for key in ('id', 'kind', 'label', 'domain', 'count', 'elapsed_ms',
                                               'rms', 'peak', 'llr_mean_abs', 'llr_uncertain_fraction')}
               for obs in observations if obs.get('id') in blocks and _number(obs.get('elapsed_ms'))]
    profile.sort(key=lambda obs: obs['elapsed_ms'], reverse=True)
    total = sum(obs['elapsed_ms'] for obs in profile)
    for obs in profile:
        obs['share'] = obs['elapsed_ms'] / total if total else 0
    traces = []
    for trace in result.get('advanced', {}).get('algorithm_traces', result.get('algorithm_traces', [])):
        if trace.get('block_id') in blocks:
            traces.append(copy.deepcopy(trace))
    diagnostics = []
    def add(obs, code, title, evidence, hint):
        diagnostic = {'block_id': obs['id'], 'kind': obs['kind'], 'code': code,
                      'title': title, 'evidence': evidence, 'hint': hint}
        channel = next((block for block in reversed(program['blocks'][:program['blocks'].index(blocks[obs['id']]) + 1])
                        if block['kind'] in ('awgn', 'complex_awgn', 'sample_awgn', 'bandlimited_awgn', 'frequency_offset', 'attenuation')), None)
        if channel:
            key = {'awgn': 'esn0_db', 'complex_awgn': 'snr_db', 'sample_awgn': 'snr_db',
                   'bandlimited_awgn': 'snr_db', 'frequency_offset': 'hz', 'attenuation': 'db'}[channel['kind']]
            if key in channel['params']:
                value = min(c.BLOCKS[channel['kind']]['params'][key]['max'], channel['params'][key] + 3) if 'snr' in key or key == 'esn0_db' else 0
                if value != channel['params'][key]:
                    candidate = copy.deepcopy(program); _change(candidate, channel['id'], key, value)
                    c.build(candidate)
                    diagnostic['comparison'] = {'label': f'{c.BLOCKS[channel["kind"]]["label"]} · {key}={value}',
                                                'program': candidate, 'change': {'block_id': channel['id'], 'parameter': key,
                                                                               'before': channel['params'][key], 'after': value}}
        diagnostics.append(diagnostic)
    for obs in observations:
        if obs.get('id') not in blocks:
            continue
        rms, peak = obs.get('rms'), obs.get('peak')
        if obs.get('count', 0) and _number(rms) and rms < 1e-9:
            add(obs, 'silent', '输出幅度接近零', {'metric': 'rms', 'actual': rms, 'operator': '<', 'threshold': 1e-9}, '比较该积木前后的功率与衰减设置。')
        if _number(rms) and rms > 0 and _number(peak) and obs.get('domain') not in ('比特', 'LLR'):
            papr = 20 * math.log10(max(peak / rms, 1e-15))
            if papr > 10:
                add(obs, 'crest', '峰均比超过 10 dB', {'metric': 'papr_db', 'actual': papr, 'operator': '>', 'threshold': 10}, '检查功放前的幅度分布，比较削峰与回退设置。')
        uncertain = obs.get('llr_uncertain_fraction')
        if _number(uncertain) and uncertain > .35:
            add(obs, 'soft_reliability', '低可靠度软比特占比较高', {'metric': 'llr_uncertain_fraction', 'actual': uncertain, 'operator': '>', 'threshold': .35}, '查看软解调输入星座，并对照信噪比、频偏和均衡参数。')
        if obs['kind'] in ('rx_carrier', 'rx_frequency', 'rx_frame', 'rx_timing', 'rx_burst_sync'):
            key = {'rx_carrier': 'carrier', 'rx_frequency': 'frequency', 'rx_frame': 'frame', 'rx_timing': 'timing', 'rx_burst_sync': 'burst'}[obs['kind']]
            measured = result.get('advanced', {}).get('recovery', {}).get(key, {})
            evidence = {name: value for name, value in measured.items() if _number(value) or type(value) is bool}
            evidence.update(rms=rms, count=obs.get('count'))
            if obs['kind'] == 'rx_frame' and _number(measured.get('peak')):
                threshold = blocks[obs['id']]['params']['threshold']
                evidence.update(metric='correlation_peak', actual=measured['peak'], operator='>=', threshold=threshold,
                                passed=measured['peak'] >= threshold)
            add(obs, 'synchronization', '同步输出与恢复测量', evidence, '对照本次恢复轨迹与同步前后观察点。')
    return {'diagnostics': diagnostics, 'profile': profile, 'profile_total_ms': total, 'traces': traces,
            'recovery': copy.deepcopy(result.get('advanced', {}).get('recovery', {})),
            'observation_count': len(observations), 'metrics': copy.deepcopy(result.get('metrics', {}))}


def pareto_indices(candidates, objectives):
    """Indices of feasible candidates with no strictly better measured competitor."""
    feasible = [index for index, item in enumerate(candidates) if item['feasible'] and
                all(_number(item['metrics'].get(objective['metric'])) for objective in objectives)]
    def dominates(a, b):
        left = [a['metrics'][obj['metric']] * (1 if obj['direction'] == 'min' else -1) for obj in objectives]
        right = [b['metrics'][obj['metric']] * (1 if obj['direction'] == 'min' else -1) for obj in objectives]
        return all(x <= y for x, y in zip(left, right)) and any(x < y for x, y in zip(left, right))
    return [i for i in feasible if not any(dominates(candidates[j], candidates[i]) for j in feasible if i != j)]


def optimize(program, settings, progress=None, cancel=None):
    from src import communications as c
    program = c.build(program)['program']
    if not isinstance(settings, dict) or not isinstance(settings.get('axes'), list) or len(settings['axes']) != 2:
        raise ValueError('受约束选参需要两个离散参数轴。')
    axes = [_axis(program, axis) for axis in settings['axes']]
    if (axes[0]['block_id'], axes[0]['parameter']) == (axes[1]['block_id'], axes[1]['parameter']):
        raise ValueError('两个参数轴请选择不同参数。')
    constraints = settings.get('constraints', [])
    if not isinstance(constraints, list) or len(constraints) > 8:
        raise ValueError('选参约束最多 8 项。')
    constraints = [_rule(rule) for rule in constraints]
    objectives = settings.get('objectives', [{'metric': 'ber', 'direction': 'min'}, {'metric': 'net_bit_rate', 'direction': 'max'}])
    if not isinstance(objectives, list) or len(objectives) != 2 or any(not isinstance(obj, dict) or not obj.get('metric') or obj.get('direction') not in ('min', 'max') for obj in objectives):
        raise ValueError('填写两个目标指标与 min / max 方向。')
    if objectives[0]['metric'] == objectives[1]['metric']:
        raise ValueError('两个目标请选择不同指标。')
    seeds, frames = experiments.seeds_and_frames(settings, program['seed'])
    values = list(itertools.product(*(axis['values'] for axis in axes)))
    total = len(values) * len(seeds) * frames
    if total > 256:
        raise ValueError('选参实验最多运行 256 帧，请减少候选值、种子或帧数。')
    programs = []
    for pair in values:
        candidate = copy.deepcopy(program)
        for axis, value in zip(axes, pair):
            _change(candidate, axis['block_id'], axis['parameter'], value)
        programs.append(c.build(candidate)['program'])
    candidates = []; completed = 0
    for index, candidate in enumerate(programs):
        trials = []
        for seed in seeds:
            for frame in range(frames):
                actual_seed = (seed + frame) % 4294967295
                _, metrics = _run(candidate, actual_seed, cancel)
                trials.append({'seed': actual_seed, 'base_seed': seed, 'frame': frame + 1, 'metrics': metrics})
                completed += 1
                if progress:
                    progress({'completed': completed, 'total': total, 'candidate': index + 1, 'candidates': len(values)})
        common = set.intersection(*(set(row['metrics']) for row in trials))
        metrics = {key: float(np.mean([row['metrics'][key] for row in trials])) for key in common}
        for count, errors, rate in (('bit_count', 'bit_errors', 'ber'), ('symbol_count', 'symbol_errors', 'ser')):
            if count in common and errors in common:
                metrics[count] = sum(row['metrics'][count] for row in trials)
                metrics[errors] = sum(row['metrics'][errors] for row in trials)
                metrics[rate] = metrics[errors] / metrics[count] if metrics[count] else 0
        required = {rule['metric'] for rule in constraints} | {obj['metric'] for obj in objectives}
        missing = required - metrics.keys()
        if missing:
            raise ValueError('当前链路缺少所选测量指标：' + '、'.join(sorted(missing)))
        checks = [_check(metrics, rule) for rule in constraints]
        candidates.append({'index': index, 'values': list(values[index]), 'program': candidate, 'metrics': metrics,
                           'trials': trials, 'checks': checks, 'feasible': all(check['passed'] for check in checks)})
    front = pareto_indices(candidates, objectives)
    for item in candidates:
        item['pareto'] = item['index'] in front
    return {'axes': axes, 'objectives': objectives, 'constraints': constraints, 'seeds': seeds, 'frames': frames,
            'candidates': candidates, 'pareto_indices': front, 'completed': completed, 'total': total, 'complete': True}


def classroom_import(submissions):
    if not isinstance(submissions, list) or not 1 <= len(submissions) <= 64:
        raise ValueError('一次导入 1–64 份同题作业包。')
    normalized = [experiments.validate_submission(item) for item in submissions]
    identity = _hash(normalized[0]['task'])
    if any(_hash(item['task']) != identity for item in normalized):
        raise ValueError('教师汇总请选择同一题目、初始链路、开放参数与验收标准的作业包。')
    task = normalized[0]['task']; weight = sum(stage['weight'] for stage in task['stages'])
    rows = []
    for index, item in enumerate(normalized):
        completed = sum(stage is not None for stage in item['stages'])
        score = sum(task['stages'][i]['weight'] for i, stage in enumerate(item['stages']) if stage) / weight * 100
        rows.append({'index': index, 'student': item['student'], 'completed_stages': completed,
                     'total_stages': len(task['stages']), 'imported_score': score,
                     'attempts': len(item['attempts']), 'hints': len(item['hint_events']),
                     'comment': '', 'submission': item})
    return {'classroom_schema': 1, 'task_id': identity, 'task': task, 'rows': rows, 'count': len(rows)}


def recheck(submissions, settings=None, progress=None, cancel=None):
    """Re-measure each saved stage snapshot with the task's original seed set."""
    from src import communication_learning as learning
    package = classroom_import(submissions)
    task = package['task']; weights = sum(stage['weight'] for stage in task['stages'])
    total = sum(sum(snapshot is not None for snapshot in row['submission']['stages']) * len(task['seeds']) for row in package['rows'])
    completed = 0
    for row in package['rows']:
        stages = []
        for index, snapshot in enumerate(row['submission']['stages']):
            _cancel(cancel)
            trials = []
            if snapshot:
                for seed in task['seeds']:
                    result, metrics = _run(snapshot['program'], seed, cancel)
                    checked = learning.check(snapshot['program'], result, goals=task['stages'][index]['goals'])
                    trials.append({'seed': seed, 'metrics': metrics, **checked})
                    completed += 1
                    if progress:
                        progress({'completed': completed, 'total': total, 'student': row['student'], 'stage': index + 1})
            stages.append({'stage': index, 'name': task['stages'][index]['name'], 'submitted': bool(snapshot),
                           'passed': bool(trials) and all(trial['passed'] for trial in trials), 'trials': trials})
        row['recheck'] = {'stages': stages, 'score': sum(task['stages'][i]['weight'] for i, stage in enumerate(stages) if stage['passed']) / weights * 100,
                          'passed': all(stage['passed'] for stage in stages)}
    package.update(completed=completed, total=total, complete=True)
    return package


def _timeline(program, settings):
    from src import communications as c
    from src.communication_sweep import parameter
    frames = c.numeric(settings.get('frames', 16), '场景帧数', 1, 128, True)
    events = settings.get('events', [])
    if not isinstance(events, list) or not 1 <= len(events) <= 64:
        raise ValueError('帧级时间表填写 1–64 个事件。')
    lanes = {}; normalized = []
    for event in events:
        if not isinstance(event, dict):
            raise ValueError('时间表事件需要帧号、积木、参数、值和变化方式。')
        frame = c.numeric(event.get('frame'), '事件帧号', 1, frames, True)
        block, key, spec = parameter(program, {'block_id': event.get('block_id'), 'parameter': event.get('parameter')})
        if c.BLOCKS[block['kind']]['category'] != 'channel' or spec['type'] not in ('number', 'integer'):
            raise ValueError('场景事件请选择信道积木的数值参数，例如 SNR、CFO 或干扰幅度。')
        value = c.numeric(event.get('value'), spec['label'], spec['min'], spec['max'], spec['type'] == 'integer')
        transition = event.get('transition', 'step')
        if transition not in ('step', 'linear'):
            raise ValueError('场景变化方式请选择 step 或 linear。')
        entry = {'frame': frame, 'block_id': block['id'], 'parameter': key, 'value': value, 'transition': transition}
        lane = lanes.setdefault((block['id'], key), [])
        if any(previous['frame'] == frame for previous in lane):
            raise ValueError('同一参数在同一帧保存一个事件。')
        lane.append(entry); normalized.append(entry)
    for lane in lanes.values():
        lane.sort(key=lambda event: event['frame'])
    schedule = []
    for frame in range(1, frames + 1):
        candidate = copy.deepcopy(program); parameters = []
        for (block_id, key), lane in lanes.items():
            initial = next(block for block in program['blocks'] if block['id'] == block_id)['params'][key]
            previous_frame, value = 0, initial
            for event in lane:
                if frame >= event['frame']:
                    previous_frame, value = event['frame'], event['value']
                else:
                    if event['transition'] == 'linear':
                        value += (event['value'] - value) * (frame - previous_frame) / (event['frame'] - previous_frame)
                    break
            _change(candidate, block_id, key, value)
            parameters.append({'block_id': block_id, 'parameter': key, 'value': value})
        schedule.append((c.build(candidate)['program'], parameters))
    return frames, sorted(normalized, key=lambda event: event['frame']), schedule


def scenario(program, settings, progress=None, cancel=None, observer_callback=None):
    from src import communications as c
    program = c.build(program)['program']
    if not isinstance(settings, dict):
        raise ValueError('帧场景设置需要 JSON 对象。')
    frames, events, schedule = _timeline(program, settings)
    recovery = _rule(settings.get('recovery', {'metric': 'ber', 'operator': '<=', 'value': .01}))
    consecutive = c.numeric(settings.get('recovery', {}).get('consecutive', 2), '恢复连续帧数', 1, frames, True)
    rows = []; states = {}; last = None
    for index, (candidate, parameters) in enumerate(schedule):
        seed = (program['seed'] + index) % 4294967295
        last, metrics = _run(candidate, seed, cancel, states, index, observer_callback)
        checked = _check(metrics, recovery)
        if recovery['metric'] not in metrics:
            raise ValueError(f'当前链路缺少恢复指标 {recovery["metric"]}。')
        rows.append({'frame': index + 1, 'seed': seed, 'metrics': metrics, 'parameters': parameters,
                     'events': [event for event in events if event['frame'] == index + 1],
                     'recovery_check': checked, 'state_count': len(states)})
        if progress:
            progress({'completed': index + 1, 'total': frames, 'frame': index + 1, 'metrics': metrics, 'state_count': len(states)})
    recoveries = []
    event_frames = sorted({event['frame'] for event in events})
    for index, start in enumerate(event_frames):
        stop = event_frames[index + 1] if index + 1 < len(event_frames) else frames + 1
        streak = 0; recovered = None
        for row in rows[start - 1:stop - 1]:
            streak = streak + 1 if row['recovery_check']['passed'] else 0
            if streak >= consecutive:
                recovered = row['frame'] - consecutive + 1
                break
        recoveries.append({'event_frame': start, 'window_end': stop - 1, 'recovered_frame': recovered,
                           'recovery_frames': recovered - start if recovered is not None else None,
                           'confirmation_frame': recovered + consecutive - 1 if recovered is not None else None})
    return {'program': program, 'settings': {'frames': frames, 'events': events, 'recovery': {**recovery, 'consecutive': consecutive}},
            'rows': rows, 'recoveries': recoveries, 'last_result': last, 'last_program': schedule[-1][0],
            'state_count': len(states), 'completed': frames, 'total': frames, 'complete': True}
