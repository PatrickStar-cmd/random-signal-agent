"""Shared parameters, measured grids and transparent teaching experiments."""
import ast
import copy
import json
import math
import operator
import re
import time
import numpy as np


OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
             ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}


def expression(value, names):
    """Evaluate a small arithmetic AST; names is a resolver, never Python eval."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        result = value
    else:
        if not isinstance(value, str) or not 1 <= len(value) <= 256:
            raise ValueError('参数公式需要数值或 1–256 字符的算式。')
        try:
            tree = ast.parse(value.strip(), mode='eval')
        except SyntaxError as exc:
            raise ValueError('参数公式语法有误。') from exc
        if sum(1 for _ in ast.walk(tree)) > 64:
            raise ValueError('单个参数公式最多包含 64 个语法节点。')
        def visit(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                answer = node.value
            elif isinstance(node, ast.Name):
                answer = names(node.id)
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                answer = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            elif isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
                left, right = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Pow) and abs(right) > 16:
                    raise ValueError('公式幂指数的绝对值须小于等于 16。')
                try:
                    answer = OPERATORS[type(node.op)](left, right)
                except (ArithmeticError, ValueError) as exc:
                    raise ValueError('参数公式的算术运算失败。') from exc
            else:
                raise ValueError('公式支持数值、工程变量、括号以及 + − * / // % ** 运算。')
            if not isinstance(answer, (int, float)) or abs(answer) > 1e12 or not math.isfinite(answer):
                raise ValueError('公式结果须为绝对值小于等于 10¹² 的有限实数。')
            return answer
        result = visit(tree.body)
    if abs(result) > 1e12 or not math.isfinite(result):
        raise ValueError('参数须为绝对值小于等于 10¹² 的有限实数。')
    return result


def resolve_program(raw, variables=None, bindings=None):
    from src import communications as c
    variables = {} if variables is None else variables
    bindings = {} if bindings is None else bindings
    if not isinstance(variables, dict) or len(variables) > 64 or not isinstance(bindings, dict) or len(bindings) > 256:
        raise ValueError('工程最多包含 64 个变量和 256 个参数绑定。')
    if any(not isinstance(k, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', k) for k in variables):
        raise ValueError('变量名由英文字母开头，包含字母、数字、下划线，最长 32 字符。')
    resolved = {}; visiting = set()
    def lookup(name):
        if name in resolved:
            return resolved[name]
        if name not in variables:
            raise ValueError(f'请先定义变量 {name}。')
        if name in visiting:
            raise ValueError(f'变量 {name} 存在循环依赖。')
        visiting.add(name); resolved[name] = expression(variables[name], lookup); visiting.remove(name)
        return resolved[name]
    for name in variables:
        lookup(name)
    program = copy.deepcopy(raw)
    if not isinstance(program, dict) or not isinstance(program.get('blocks'), list):
        raise ValueError('请提供有效的通信工程。')
    blocks = {b['id']: b for b in program['blocks']}
    for path, formula in bindings.items():
        value = expression(formula, lookup)
        if path in ('seed', 'sample_rate', 'sample_count', 'symbol_rate'):
            program[path] = value
        else:
            parts = path.split('.') if isinstance(path, str) else []
            if len(parts) != 3 or parts[0] != 'blocks' or parts[1] not in blocks:
                raise ValueError(f'参数绑定路径无效：{path}。')
            block = blocks[parts[1]]
            spec = c.BLOCKS[block['kind']]['params'].get(parts[2])
            if spec is None or spec['type'] not in ('number', 'integer', 'select'):
                raise ValueError(f'绑定目标须为数值参数：{path}。')
            if spec['type'] in ('integer', 'select') and int(value) == value:
                value = int(value)
            block.setdefault('params', {})[parts[2]] = value
    return {'program': c.normalize(program, draft=True), 'variables': resolved, 'bindings': copy.deepcopy(bindings)}


def axis_spec(program, axis):
    from src import communications as c
    from src.communication_sweep import parameter
    if not isinstance(axis, dict) or set(axis) - {'block_id', 'parameter', 'values', 'mode'}:
        raise ValueError('扫描轴需要 block_id、parameter、values，可选 mode。')
    values = axis.get('values')
    if not isinstance(values, list) or not 1 <= len(values) <= 21:
        raise ValueError('每个扫描轴需要 1–21 个参数值。')
    if len(set(values)) != len(values):
        raise ValueError('扫描轴参数值须唯一。')
    settings = {'global': axis.get('parameter')} if axis.get('block_id') == 'global' else {'block_id': axis.get('block_id'), 'parameter': axis.get('parameter')}
    block, name, spec = parameter(program, settings)
    checked = []
    for value in values:
        if spec['type'] == 'select':
            if type(value) is not int or value not in spec['choices']:
                raise ValueError('扫描枚举值须属于参数可选项。')
            checked.append(value)
        else:
            checked.append(c.numeric(value, spec['label'], spec['min'], spec['max'], spec['type'] == 'integer'))
    return block, name, spec, {**settings, 'values': checked, 'mode': axis.get('mode', 'native')}


def sweep2d(program, token, settings, progress=None, cancel=None):
    from src import communications as c
    from src.communication_sweep import sweep
    built = c.build(program)
    if token != built['token']:
        raise ValueError('配置已改变，请重新 Build 后扫描。')
    if not isinstance(settings, dict):
        raise ValueError('二维扫描设置需要 JSON 对象。')
    xblock, xname, xspec, xs = axis_spec(built['program'], settings.get('x'))
    yblock, yname, yspec, ys = axis_spec(built['program'], settings.get('y'))
    if settings['x']['block_id'] == settings['y']['block_id'] and xname == yname:
        raise ValueError('二维扫描请选择两个不同参数。')
    if ys['mode'] != 'native':
        raise ValueError('纵轴采用参数原始单位，Eb/N₀ 可设置在横轴。')
    frames = c.numeric(settings.get('frames', 2), '每点帧数', 1, 100, True)
    if len(xs['values']) * len(ys['values']) * frames > c.CONFIG['max_sweep_runs']:
        raise ValueError('二维扫描总计最多 300 帧。')
    result = {'program': built['program'], 'token': token, 'settings': copy.deepcopy(settings),
              'x_values': xs['values'], 'y_values': ys['values'], 'x_label': xspec['label'], 'y_label': yspec['label'],
              'points': [], 'complete': False, 'total_points': len(xs['values']) * len(ys['values']),
              'seed_policy': '每个网格点使用相同种子序列 seed + 帧序号；恢复点保留该点参数与基准种子。'}
    started = time.monotonic()
    for row, y in enumerate(ys['values']):
        if cancel is not None and cancel.is_set():
            break
        if time.monotonic() - started > c.CONFIG['max_sweep_seconds']:
            result['stop_reason'] = 'time_limit'; break
        candidate = copy.deepcopy(built['program'])
        if yblock is None:
            candidate[yname] = y
        else:
            next(b for b in candidate['blocks'] if b['id'] == yblock['id'])['params'][yname] = y
        row_build = c.build(candidate)
        def current_row(value):
            active = []
            for column, point in enumerate(value['points']):
                cell = copy.deepcopy(candidate)
                if xblock is None:
                    cell[xname] = point['noise_db']
                else:
                    next(b for b in cell['blocks'] if b['id'] == xblock['id'])['params'][xname] = point['noise_db']
                # Match sweep's automatic LLR calibration in each restored point.
                if xblock is not None and xblock['kind'] == 'awgn' and xname == 'esn0_db':
                    pure = all(b['kind'] not in c.CHANNELS or b['kind'] in ('ideal', 'awgn') for b in cell['blocks']) and sum(b['kind'] == 'awgn' for b in cell['blocks']) == 1
                    if pure:
                        for b in cell['blocks']:
                            if b['kind'].startswith('soft_'):
                                b['params']['noise_variance'] = max(.000001, min(100, 10 ** (-point['noise_db'] / 10)))
                active.append({**point, 'x': point['db'], 'y': y, 'row': row, 'column': column, 'program': c.build(cell)['program']})
            current = {**result, 'points': result['points'] + active, 'completed_points': len(result['points']) + len(active),
                       'completed': len(result['points']) + len(active), 'total': result['total_points'], 'x_label': value['axis']}
            return current
        def update(value):
            if progress:
                progress(current_row(value))
        row_result = sweep(candidate, row_build['token'], {**xs, 'frames': frames, 'target_errors': settings.get('target_errors', 100)}, update, cancel)
        result = current_row(row_result); result['elapsed_seconds'] = time.monotonic() - started
        if not row_result['complete']:
            break
    result['complete'] = len(result['points']) == result['total_points'] and all(p['stop_reason'] in ('target_errors', 'frame_limit') for p in result['points'])
    result['completed_points'] = result['completed'] = len(result['points']); result['total'] = result['total_points']; result['elapsed_seconds'] = time.monotonic() - started
    if progress:
        progress(result)
    return result


CHALLENGES = [
    {'id': 'clean-link', 'name': '🎯 可靠比特传输', 'preset': 'soft_viterbi', 'objective': '调整接收链路，使当前帧 BER ≤ 0.01。',
     'steps': ['先预测噪声增加对 BER 的影响。', '运行一次，查看 BER 与星座图。', '调整信噪比、纠错或接收机，再比较两次结果。'], 'goals': [{'metric': 'ber', 'operator': '<=', 'value': .01}]},
    {'id': 'clean-constellation', 'name': '✨ 清晰星座', 'preset': 'agc_soft', 'objective': '调整接收机，使 EVM ≤ 15%。',
     'steps': ['观察旋转、扩散与增益误差。', '选择载波、均衡或噪声设置。', '记录 EVM 改善与对应参数。'], 'goals': [{'metric': 'evm_percent', 'operator': '<=', 'value': 15.}]},
    {'id': 'reliable-packets', 'name': '📦 完整业务传输', 'preset': 'text', 'objective': '完成包传输，交付丢包率为 0。',
     'steps': ['比较 ARQ 与 HARQ 的重传次数。', '调整信噪比、重传上限与反馈延迟。', '比较完整交付率和 goodput。'], 'goals': [{'metric': 'packet_loss_rate', 'operator': '<=', 'value': 0.}]},
    {'id': 'adaptive-link', 'name': '🚦 自适应速率', 'preset': 'digital', 'objective': '在变化信道中完成至少一次档位切换且 FER ≤ 0.1。',
     'steps': ['预测高信噪比区间的最佳调制阶数。', '运行 AMC，观察反馈延迟。', '调整滞回并比较切换次数与 FER。'], 'goals': [{'metric': 'profile_switches', 'operator': '>=', 'value': 1}, {'metric': 'fer', 'operator': '<=', 'value': .1}]},
    {'id': 'image-delivery', 'name': '🖼️ 恢复一张图片', 'preset': 'business_image', 'objective': '传输图片并恢复全部像素。',
     'steps': ['运行图片传输，比较发送与接收图像。', '降低信噪比，观察错误像素与 PSNR。', '调整纠错与信道参数，恢复所有像素。'], 'goals': [{'metric': 'sink.media.metrics.mse', 'operator': '<=', 'value': 0.}]},
    {'id': 'audio-quality', 'name': '🎙️ 还原一段声音', 'preset': 'business_audio', 'objective': '使音频重构 RMSE ≤ 0.05。',
     'steps': ['播放原始与重构音频。', '比较量化步长、码率与波形误差。', '调整量化及信道参数，达到重构目标。'], 'goals': [{'metric': 'sink.media.metrics.rmse', 'operator': '<=', 'value': .05}]},
    {'id': 'burst-repair', 'name': '🛡️ 修复突发错误', 'preset': 'business_rs_burst', 'objective': '用交织与 RS 译码恢复图片全部像素。',
     'steps': ['观察突发错误在码字间的分布。', '比较交织列数及 RS 纠错强度。', '查看纠正字节数并验证接收图片。'], 'goals': [{'metric': 'sink.media.metrics.mse', 'operator': '<=', 'value': 0.}]},
    {'id': 'file-integrity', 'name': '📁 文件完整交付', 'preset': 'business_packets', 'objective': '使分包传输后的文件校验值一致。',
     'steps': ['观察各包序号、长度和 CRC。', '改变包长与噪声，观察丢包。', '调节纠错和信道使文件逐字节一致。'], 'goals': [{'metric': 'sink.media.metrics.identical', 'operator': '==', 'value': True}]},
    {'id': 'spread-antijamming', 'name': '📡 扩频抗窄带干扰', 'preset': 'dsss_interference', 'objective': '在窄带干扰下使 BER ≤ 0.01。',
     'steps': ['观察窄带干扰与扩频信号的频谱。', '调整扩频倍率、捕获门限及干扰幅度。', '比较解扩前后信号并达到误码率目标。'], 'goals': [{'metric': 'ber', 'operator': '<=', 'value': .01}]},
]


def catalog():
    from src.communication_protocols import PROFILES
    return {'challenges': CHALLENGES, 'amc_profiles': PROFILES,
            'algorithms': [{'id': 'viterbi', 'name': 'Viterbi 网格与幸存路径'}, {'id': 'ldpc', 'name': 'LDPC 校验与迭代'}, {'id': 'constellation', 'name': '星座判决区与 LLR'}],
            'formula_example': {'variables': {'Rs': 1000, 'sps': 8, 'Fs': 'Rs*sps'}, 'bindings': {'symbol_rate': 'Rs', 'sample_rate': 'Fs'}}}


def check(program, result, challenge_id=None, goals=None):
    from src import communications as c
    c.build(program)
    challenge = next((v for v in CHALLENGES if v['id'] == challenge_id), None)
    if challenge_id is not None and challenge is None:
        raise ValueError('未知教学挑战。')
    selected = goals if goals is not None else challenge['goals'] if challenge else None
    if not isinstance(selected, list) or not 1 <= len(selected) <= 12:
        raise ValueError('请提供 1–12 个实验目标。')
    metrics = result.get('metrics', {}) if isinstance(result, dict) else {}
    comparisons = {'<=': operator.le, '>=': operator.ge, '==': operator.eq}
    rows = []
    for goal in selected:
        name, op, target = goal.get('metric'), goal.get('operator'), goal.get('value')
        if not isinstance(name, str) or op not in comparisons or type(target) not in (int, float, bool) or not math.isfinite(target) or type(target) is bool and op != '==':
            raise ValueError('目标格式为 metric、operator（<=、>=、==）、value。')
        actual = result
        if '.' in name:
            for part in name.split('.'):
                actual = actual.get(part) if isinstance(actual, dict) else None
        else:
            actual = metrics.get(name)
        passed = type(actual) in (int, float, bool) and math.isfinite(actual) and comparisons[op](actual, target)
        rows.append({'metric': name, 'operator': op, 'target': target, 'actual': actual, 'passed': passed,
                     'message': '目标达成' if passed else '请运行包含该指标的实验' if actual is None else '继续调整参数'})
    return {'challenge': challenge, 'checks': rows, 'passed': all(r['passed'] for r in rows), 'evidence': '当前工程的一次实际运行结果'}


def difference(before, after):
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError('请提供包含 program 和 result 的两次实验快照。')
    def flatten(value, prefix=''):
        if isinstance(value, dict):
            return {key: item for name, child in value.items() for key, item in flatten(child, f'{prefix}.{name}' if prefix else name).items()}
        if isinstance(value, list):
            return {key: item for i, child in enumerate(value) for key, item in flatten(child, f'{prefix}[{i}]').items()}
        return {prefix: value}
    def program_fields(value):
        p = value.get('program', {})
        return {**{k: v for k, v in p.items() if k != 'blocks'},
                'blocks': {b['id']: {'position': i, 'kind': b['kind'], 'params': b.get('params', {})} for i, b in enumerate(p.get('blocks', []))}}
    a, b = flatten(program_fields(before)), flatten(program_fields(after))
    changes = [{'path': k, 'before': a.get(k), 'after': b.get(k)} for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k)]
    ma = before['result'].get('metrics', {}) if isinstance(before.get('result'), dict) else {}
    mb = after['result'].get('metrics', {}) if isinstance(after.get('result'), dict) else {}
    metrics = []
    for name in sorted(ma.keys() | mb.keys()):
        x, y = ma.get(name), mb.get(name)
        if type(x) in (int, float) or type(y) in (int, float):
            metrics.append({'metric': name, 'before': x, 'after': y, 'delta': y - x if type(x) in (int, float) and type(y) in (int, float) else None})
    return {'changes': changes, 'metrics': metrics, 'changed_parameters': len(changes)}


def export_python(program, variables=None, bindings=None):
    from src import communications as c
    resolved = resolve_program(program, variables, bindings)
    built = c.build(resolved['program'])
    encoded = json.dumps(built['program'], ensure_ascii=False, allow_nan=False)
    metadata = json.dumps({'variables': variables or {}, 'bindings': bindings or {}, 'resolved_variables': resolved['variables']}, ensure_ascii=False)
    source = '''"""通信积木实验：将脚本放入部署包的 工程文件/代码 目录，使用项目 Python 执行。"""
import json
from pathlib import Path
from src import communications

''' + f'PROGRAM = json.loads({encoded!r})\nPARAMETERS = json.loads({metadata!r})\n' + '''

def write_plot(result, output):
    # Standalone SVG, drawn from the exact JSON result without extra packages.
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="960" height="600" viewBox="0 0 960 600">',
           '<rect width="960" height="600" rx="20" fill="#edf9fc"/>',
           '<style>text{font-family:Arial,sans-serif;fill:#153b52}.label{font-size:17px}.note{font-size:13px}</style>',
           '<text x="40" y="32" class="label">Communication experiment · seed ' + str(PROGRAM['seed']) + '</text>']
    sink = result.get('sink', {})
    values = sink.get('values', [])[:256]; reference = sink.get('reference', [])[:256]
    if values:
        low = min(values + reference); high = max(values + reference); span = max(high-low, 1e-9)
        svg.extend(['<rect x="40" y="65" width="880" height="205" fill="white" stroke="#377b94" stroke-width="2"/>',
                    '<text x="40" y="55" class="label">Sink samples (blue: received, orange: reference)</text>'])
        for series, color in [(reference, '#e7a33b'), (values, '#087b9a')]:
            coordinates = ' '.join(f'{45+870*i/max(1,len(series)-1):.2f},{265-195*(v-low)/span:.2f}' for i, v in enumerate(series))
            svg.append(f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="1.6"/>')
        svg.append('<text x="40" y="292" class="note">Sample index → 0 to ' + str(len(values)-1) + '; amplitude ' + f'{low:.3g} to {high:.3g}' + '</text>')
    constellation = result.get('constellation')
    points = constellation if constellation is not None else result.get('channel', {})
    ix, qx = points.get('i', []), points.get('q', [])
    if ix and qx:
        extent = max(1., max(abs(v) for v in ix+qx)) * 1.1
        svg.extend(['<rect x="40" y="325" width="880" height="230" fill="white" stroke="#377b94" stroke-width="2"/>',
                    '<text x="40" y="317" class="label">' + ('Received constellation' if constellation else 'Channel samples') + ' · I / Q</text>',
                    '<path d="M40 440H920 M480 325V555" stroke="#c8dce3"/>'])
        for i, q in zip(ix, qx):
            svg.append(f'<circle cx="{480+425*i/extent:.2f}" cy="{440-105*q/extent:.2f}" r="2.2" fill="#087b9a" opacity="0.65"/>')
    svg.append('</svg>')
    output.write_text(''.join(svg), encoding='utf-8')

def main():
    built = communications.build(PROGRAM)
    result = communications.run(built['program'], built['token'])
    output = Path('communication_experiment_result.json')
    output.write_text(json.dumps({'program': built['program'], 'parameters': PARAMETERS,
                                  'result': result}, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    write_plot(result, Path('communication_experiment_plot.svg'))
    print(json.dumps(result['metrics'], ensure_ascii=False, indent=2))
    print(f'实验结果已保存：{output.resolve()}')

if __name__ == '__main__':
    main()
'''
    return {'filename': 'communication_experiment.py', 'source': source, 'program': built['program']}


def explain(algorithm, seed=42, snr_db=2, scheme='qpsk'):
    from src import communications as c, communication_codecs as codec, communication_dsp as dsp
    seed = c.numeric(seed, '演示种子', 0, 4294967294, True)
    snr_db = c.numeric(snr_db, '演示 Es/N₀', -15, 40)
    rng = np.random.default_rng(seed)
    if algorithm == 'viterbi':
        bits = rng.integers(0, 2, 12, dtype=np.uint8); coded = c.conv_encode(bits)
        noise = 10 ** (-snr_db / 20) / math.sqrt(2) * rng.normal(size=len(coded))
        llr = 4 * (1 - 2 * coded.astype(float) + noise) / 10 ** (-snr_db / 10)
        scores = np.array([0., np.inf, np.inf, np.inf]); paths = []; steps = []
        for index, pair in enumerate(llr.reshape(-1, 2)):
            updated = np.full(4, np.inf); surviving = np.zeros(4, dtype=int); branches = []
            for previous in range(4):
                for bit in (0, 1):
                    dest, expected = c.transition(previous, bit); cost = scores[previous] + float(np.dot(expected, pair))
                    branches.append({'from': previous, 'to': dest, 'bit': bit, 'output': list(expected), 'cost': float(cost) if np.isfinite(cost) else None})
                    if cost < updated[dest]:
                        updated[dest] = cost; surviving[dest] = previous
            scores = updated - np.min(updated); paths.append(surviving)
            steps.append({'step': index + 1, 'llr': pair.tolist(), 'scores': [float(x) if np.isfinite(x) else None for x in scores],
                          'survivors': surviving.tolist(), 'branches': branches})
        state = 0; trace = [state]
        for path in reversed(paths):
            state = int(path[state]); trace.append(state)
        return {'algorithm': algorithm, 'seed': seed, 'snr_db': snr_db, 'input_bits': bits.tolist(), 'coded_bits': coded.tolist(),
                'decoded_bits': codec.soft_viterbi(llr).tolist(), 'traceback_states': list(reversed(trace)), 'steps': steps,
                'explanation': '每一步比较四个状态的累计软判决代价并保留最小路径；从零尾状态向前回溯。'}
    if algorithm == 'ldpc':
        bits = rng.integers(0, 2, 64, dtype=np.uint8); coded = codec.ldpc_encode(bits)
        sigma = 10 ** (-snr_db / 20) / math.sqrt(2)
        llr = 2 * (1 - 2 * coded.astype(float) + sigma * rng.normal(size=len(coded))) / sigma ** 2
        h = codec.ldpc_matrix(); rows, cols = np.nonzero(h); outgoing = llr[cols].copy(); incoming = np.zeros_like(outgoing); steps = []
        hard = (llr < 0).astype(np.uint8)
        steps.append({'iteration': 0, 'unsatisfied_checks': int(((hard @ h.T) % 2).sum()), 'bit_errors': int(np.count_nonzero(hard[:64] != bits)), 'llr': llr.tolist()})
        for iteration in range(1, 21):
            for row in range(64):
                edges = np.flatnonzero(rows == row); values = outgoing[edges]; signs = np.where(values < 0, -1., 1.); magnitudes = abs(values)
                minimum = np.argmin(magnitudes); minima = np.partition(magnitudes, 1)[:2]; other = np.full(len(edges), minima[0]); other[minimum] = minima[1]
                incoming[edges] = .8 * np.prod(signs) * signs * other
            posterior = llr.copy(); np.add.at(posterior, cols, incoming); hard = (posterior < 0).astype(np.uint8); syndrome = (hard @ h.T) % 2
            steps.append({'iteration': iteration, 'unsatisfied_checks': int(syndrome.sum()), 'bit_errors': int(np.count_nonzero(hard[:64] != bits)), 'llr': posterior.tolist()})
            if not np.any(syndrome):
                break
            outgoing = np.clip(posterior[cols] - incoming, -60, 60)
        return {'algorithm': algorithm, 'seed': seed, 'snr_db': snr_db, 'input_bits': bits.tolist(), 'decoded_bits': hard[:64].tolist(),
                'edges': [{'check': int(row), 'variable': int(col)} for row, col in zip(rows, cols)], 'steps': steps,
                'explanation': '归一化最小和消息在校验节点和变量节点之间传播，逐轮显示校验方程与信息位错误数。'}
    if algorithm == 'constellation':
        if scheme not in ('bpsk', 'qpsk', 'psk8', 'qam16', 'qam64', 'qam256'):
            raise ValueError('请选择可演示的星座调制。')
        labels, points = c.constellation(scheme); variance = 10 ** (-snr_db / 10)
        indices = rng.integers(0, len(points), size=32); received = points[indices] + np.sqrt(variance / 2) * (rng.normal(size=32) + 1j * rng.normal(size=32))
        llr = dsp.soft_demod(received, scheme, variance).reshape(32, -1); _, decisions = c.demodulate(received, scheme)
        grid_axis = np.linspace(-1.75, 1.75, 41); grid = (grid_axis[None, :] + 1j * grid_axis[:, None]).ravel()
        _, region = c.demodulate(grid, scheme)
        return {'algorithm': algorithm, 'seed': seed, 'snr_db': snr_db, 'scheme': scheme,
                'constellation': [{'i': float(p.real), 'q': float(p.imag), 'bits': labels[i].tolist()} for i, p in enumerate(points)],
                'samples': [{'i': float(p.real), 'q': float(p.imag), 'sent': int(indices[i]), 'decision': int(decisions[i]), 'llr': llr[i].tolist()} for i, p in enumerate(received)],
                'regions': {'axis': grid_axis.tolist(), 'indices': region.reshape(41, 41).tolist()},
                'explanation': '判决区取欧氏距离最小的星座点；每位 LLR 对比该位为 0 和 1 的最近点距离，正值偏向 0。'}
    raise ValueError('未知算法演示。')
