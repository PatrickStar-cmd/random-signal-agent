"""Sampled finite-frame baseband transmission and chapter-four line codes.

Line levels are not bits and never pass through an RF constellation mapper.
FFT channels use periodic frames with explicit zero guards. Equalization uses
the configured linear impulse response, not the clean transmitted data.
"""
from __future__ import annotations

import hashlib
import json
import math
import numpy as np
from src import receiver_recovery as recovery
from src import communication_codecs as codec
from src import communication_runtime as runtime

LINE_CODES = {
    'nrz_unipolar': '单极性 NRZ', 'nrz_polar': '双极性 NRZ',
    'rz_unipolar': '单极性 RZ', 'rz_polar': '双极性 RZ',
    'diff': '差分 NRZI', 'ami': 'AMI', 'manchester': 'Manchester 双相',
    'miller': 'Miller', 'cmi': 'CMI', 'hdb3': 'HDB3 / HDBn',
}
WAVE_CHANNELS = {'sample_awgn', 'lowpass_channel', 'bandlimited_awgn', 'bandpass_channel', 'ac_coupling', 'isi_channel', 'timing_offset', 'clock_drift'}
PULSE_NAMES = ['矩形 NRZ', '三角脉冲', '高斯脉冲', '理想 sinc（截断）', '升余弦 RC', '根升余弦 RRC']


def line_scheme(kind):
    return kind[5:-7]


def expansion(scheme, params):
    return 2 if scheme in ('rz_unipolar', 'rz_polar', 'manchester', 'miller', 'cmi') or (scheme in ('ami', 'hdb3') and params['rz']) else 1


def alphabet(scheme):
    return np.array([0., 1.]) if scheme in ('nrz_unipolar', 'rz_unipolar') else np.array([-1., 0., 1.]) if scheme in ('ami', 'hdb3', 'rz_polar') else np.array([-1., 1.])


def line_encode(bits, scheme, params):
    bits = np.asarray(bits, dtype=int); first = 1 if params.get('initial_positive', True) else -1
    if scheme in ('nrz_unipolar', 'rz_unipolar'): levels = bits.astype(float)
    elif scheme in ('nrz_polar', 'rz_polar'): levels = 2. * bits - 1
    elif scheme == 'manchester': return np.column_stack((2 * bits - 1, 1 - 2 * bits)).ravel().astype(float)
    elif scheme in ('miller', 'cmi'):
        output = []; state = first; previous = 1
        for bit in bits:
            if scheme == 'miller':
                if not bit and not previous: state = -state
                output.append(state)
                if bit: state = -state
                output.append(state); previous = bit
            elif bit:
                output.extend([state, state]); state = -state
            else: output.extend([-1, 1])
        return np.array(output, dtype=float)
    elif scheme == 'diff':
        state = first; output = []
        for bit in bits:
            if bit: state = -state
            output.append(state)
        return np.array(output, dtype=float)
    else:
        levels = np.zeros(len(bits)); last = -first; parity = params.get('initial_parity', 0); zeros = 0
        for i, bit in enumerate(bits):
            if bit:
                last = -last; levels[i] = last; parity ^= 1; zeros = 0
            else:
                zeros += 1
                if scheme == 'hdb3' and zeros == params['order'] + 1:
                    if not parity:
                        last = -last; levels[i - params['order']] = last
                    levels[i] = last; parity = 0; zeros = 0
    if scheme.startswith('rz_') or (scheme in ('ami', 'hdb3') and params['rz']):
        return np.column_stack((levels, np.zeros(len(bits)))).ravel()
    return levels


def line_decode(levels, scheme, params):
    levels = np.asarray(levels); allowed = alphabet(scheme)
    hard = allowed[np.argmin(abs(levels[:, None] - allowed), axis=1)]
    violations = 0
    if scheme.startswith('rz_') or (scheme in ('ami', 'hdb3') and params['rz']):
        violations += int(np.count_nonzero(abs(levels[1::2]) > .5)); hard = hard[::2]
    if scheme in ('nrz_unipolar', 'rz_unipolar'): bits = hard > .5
    elif scheme in ('nrz_polar', 'rz_polar'): bits = hard > 0
    elif scheme == 'diff': bits = hard != np.r_[1 if params['initial_positive'] else -1, hard[:-1]]
    elif scheme in ('manchester', 'miller', 'cmi'):
        pairs = hard.reshape(-1, 2)
        if scheme == 'manchester':
            bits = pairs[:, 0] > pairs[:, 1]; violations += int(np.count_nonzero(pairs[:, 0] == pairs[:, 1]))
        elif scheme == 'miller': bits = pairs[:, 0] != pairs[:, 1]
        else:
            bits = pairs[:, 0] == pairs[:, 1]; violations += int(np.count_nonzero((pairs[:, 0] > 0) & (pairs[:, 1] < 0)))
    else:
        bits = hard != 0; last = -(1 if params.get('initial_positive', True) else -1)
        for i, value in enumerate(hard):
            if not value: continue
            if value == last:
                if scheme == 'hdb3' and i >= params['order'] and np.all(hard[i - params['order'] + 1:i] == 0):
                    bits[i - params['order']:i + 1] = False
                else: violations += 1
            last = value
    return bits.astype(np.uint8), violations


def pulse(params):
    sps, span, alpha, kind = params['sps'], params['span'], params['rolloff'], params['pulse']
    if kind == 0: return np.ones(sps)
    t = np.arange(-span * sps // 2, span * sps // 2 + 1) / sps
    if kind == 1: result = np.maximum(1 - abs(t), 0)
    elif kind == 2: result = np.exp(-.5 * (t / .35) ** 2)
    elif kind == 3 or alpha == 0: result = np.sinc(t)
    elif kind == 4:
        denominator = 1 - (2 * alpha * t) ** 2
        result = np.divide(np.sinc(t) * np.cos(np.pi * alpha * t), denominator, out=np.zeros_like(t), where=abs(denominator) > 1e-10)
        special = np.isclose(abs(t), 1 / (2 * alpha))
        result[special] = np.pi / 4 * np.sinc(1 / (2 * alpha))
    else:
        denominator = np.pi * t * (1 - (4 * alpha * t) ** 2)
        numerator = np.sin(np.pi * t * (1 - alpha)) + 4 * alpha * t * np.cos(np.pi * t * (1 + alpha))
        result = np.divide(numerator, denominator, out=np.zeros_like(t), where=abs(denominator) > 1e-10)
        result[t == 0] = 1 + alpha * (4 / np.pi - 1)
        special = np.isclose(abs(t), 1 / (4 * alpha))
        result[special] = alpha / np.sqrt(2) * ((1 + 2 / np.pi) * np.sin(np.pi / (4 * alpha)) + (1 - 2 / np.pi) * np.cos(np.pi / (4 * alpha)))
    return result / np.max(abs(result))


def parse_taps(params):
    try: taps = np.array([float(v.strip()) for v in params['taps'].split(',')])
    except ValueError as exc: raise ValueError('ISI 抽头须为逗号分隔的实数。') from exc
    if not 1 <= len(taps) <= 17 or not np.all(np.isfinite(taps)) or np.max(abs(taps)) > 8 or not np.any(taps) or params['origin'] >= len(taps):
        raise ValueError('ISI 需要 1–17 个有限非全零抽头，幅值不超过 8，参考抽头位置须在数组内。')
    return taps


def linear_channel(data, kind, params, sample_rate, sps):
    if kind == 'isi_channel':
        taps = parse_taps(params); impulse = np.zeros((len(taps) - 1) * params['spacing'] + 1)
        impulse[::params['spacing']] = taps; shift = params['origin'] * params['spacing']
        return np.convolve(np.pad(data, (0, shift)), impulse)[shift:shift + len(data)]
    if kind == 'timing_offset':
        positions = np.arange(len(data)) - params['offset'] * sps
        return np.interp(positions, np.arange(len(data)), data, left=0, right=0)
    if kind == 'clock_drift':
        positions = np.arange(len(data)) / (1 + params['ppm'] * 1e-6)
        return np.interp(positions, np.arange(len(data)), data, left=0, right=0)
    frequency = np.fft.fftfreq(len(data), 1 / sample_rate)
    if kind == 'bandpass_channel': response = abs(abs(frequency) - params['center_hz']) <= params['bandwidth_hz'] / 2
    elif kind == 'ac_coupling': response = 1j * frequency / (params['cutoff_hz'] + 1j * frequency)
    else: response = abs(frequency) <= params['cutoff_hz']
    return np.fft.ifft(np.fft.fft(data) * response).real


def zf_coefficients(response, half):
    indices = range(-half, half + 1)
    matrix = np.array([[response.get(i - j, 0) for j in indices] for i in indices])
    if np.linalg.cond(matrix) > 1e8: raise ValueError('迫零均衡方程病态或无解；请改变信道抽头/均衡阶数，或使用 MMSE。')
    target = np.zeros(2 * half + 1); target[half] = 1
    return np.linalg.solve(matrix, target)


def gray_decode(word):
    result = word.copy(); shift = 1
    while shift < 16:
        result ^= result >> shift; shift *= 2
    return result


def pam_map(bits, order, gray):
    width = int(math.log2(order)); padded = np.pad(bits, (0, -len(bits) % width)).reshape(-1, width)
    words = padded.dot(2 ** np.arange(width - 1, -1, -1))
    indices = gray_decode(words) if gray else words
    return (2 * indices - order + 1) / math.sqrt((order ** 2 - 1) / 3)


def pam_decode(values, order, gray):
    indices = np.clip(np.rint((values * math.sqrt((order ** 2 - 1) / 3) + order - 1) / 2), 0, order - 1).astype(int)
    words = indices ^ (indices >> 1) if gray else indices
    return ((words[:, None] >> np.arange(int(math.log2(order)) - 1, -1, -1)) & 1).astype(np.uint8).ravel()


def frame_layout(count, transmit, blocks):
    count += transmit.get('training_symbols', 0)
    shaping = pulse(transmit)
    guard = max(2 * len(shaping), 8 * transmit['sps']) + sum((len(parse_taps(b['params'])) - 1) * b['params']['spacing'] for b in blocks if b['kind'] == 'isi_channel')
    drift = sum(abs(b['params']['ppm']) for b in blocks if b['kind']=='clock_drift') * 1e-6
    if drift > .001: raise ValueError('累积采样时钟误差绝对值不能超过 1000 ppm。')
    if drift: guard += math.ceil((count*transmit['sps']+2*guard)*drift/(1-drift))+transmit['sps']
    return shaping, guard, (count - 1) * transmit['sps'] + len(shaping) + 2 * guard


def build(program):
    from src import communications as c
    items = program['blocks']; sources = []
    for item in items:
        if item['kind'] not in c.SOURCES: break
        sources.append(item)
    if not sources: raise ValueError('基带链路需要开头的信源。')
    analog = sources[0]['kind'] in ('sine', 'square', 'gaussian')
    if any((b['kind'] in ('sine', 'square', 'gaussian')) != analog for b in sources): raise ValueError('两类信源不能混合。')
    source_counts = [program['sample_count'] if analog else b['params']['count'] if b['kind'] in ('random_bits','pn_bits') else len(b['params']['pattern']) if b['kind'] == 'bit_pattern' else len(b['params']['text'].encode()) * 8 for b in sources]
    for b in sources:
        if b['kind']=='pn_bits': codec.pn(1,b['params']['degree'],b['params']['initial'])
    count = program['sample_count'] if analog else sum(source_counts)
    if not analog and count > c.CONFIG['max_source_bits']: raise ValueError('合并数字信源超过上限。')
    domain = '模拟样本' if analog else '比特'; direction = 'tx'; stack = []; modulator = None; channels = 0; attenuation = 0; line = None
    plan = [{'id': b['id'], 'label': c.BLOCKS[b['kind']]['label'], 'output': domain, 'count': size} for b, size in zip(sources, source_counts)]
    for index, b in enumerate(items[len(sources):], len(sources)):
        kind, params = b['kind'], b['params']; before = count
        def fail(message): raise ValueError(f'第 {index+1} 块「{c.BLOCKS[kind]["label"]}」：{message}')
        if kind in c.ENCODERS:
            if direction != 'tx': fail('发转换器须放在波形形成器前。')
            if kind.startswith('line_'):
                if domain != '比特': fail('线路编码器需要比特，模拟信源请先 PCM 编码。')
                line = kind; count *= expansion(line_scheme(kind), params); domain = '线路电平'
            elif kind in codec.SOURCE_CODECS:
                if domain != '模拟样本': fail('信源编码需要模拟样本。')
                count=codec.encoded_count(kind,count,params); domain='比特'
            elif kind == 'pcm_encode':
                if domain != '模拟样本': fail('PCM 需要模拟样本。')
                count *= params['bits']; domain = '比特'
            else:
                if domain != '比特': fail('信道编码/交织需要比特，须位于线路编码之前。')
                if kind == 'ldpc_encode': fail('LDPC 请连接 PSK/QAM 软解调链路。')
                if kind in ('crc_append','scramble'):
                    count=codec.encoded_count(kind,count,params)
                    if kind=='scramble': codec.pn(1,params['degree'],params['initial'])
                elif kind == 'repeat_encode': count *= params['factor']
                elif kind == 'hamming_encode': count = math.ceil(count / 4) * 7
                elif kind == 'conv_encode': count = (count + 2) * 2
                else: count = math.ceil(count / params['columns']) * params['columns']
            stack.append((kind, params, before))
        elif kind in ('mod_baseband', 'mod_pam'):
            if direction != 'tx' or domain != ('线路电平' if kind == 'mod_baseband' else '比特'): fail('基带形成器需要线路电平，PAM 需要比特；一条链路仅用一个形成器。')
            modulator = b; symbol_count = count if kind == 'mod_baseband' else math.ceil(count / math.log2(params['order']))
            shaping, guard, count = frame_layout(symbol_count, params, items); domain = '基带波形'; direction = 'channel'
        elif kind in c.CHANNELS:
            if direction != 'channel': fail('信道须位于波形形成器和抽样判决之间。')
            if kind not in WAVE_CHANNELS | {'ideal','attenuation','dropout','awgn','analog_awgn','phase_shift'}: fail('该信道需要数字复基带链路。')
            if kind in ('awgn', 'analog_awgn', 'phase_shift'): fail('实基带链路请选择基带白噪声/带限 AWGN；相位旋转属于复包络链路。')
            channels += 1
            if kind == 'attenuation': attenuation += params['db']
            if attenuation > 100: fail('总衰减不能超过 100 dB。')
            fs = program['symbol_rate'] * modulator['params']['sps']
            if 'cutoff_hz' in params and params['cutoff_hz'] >= fs / 2: fail('截止频率须小于波形采样率的一半。')
            if kind == 'bandpass_channel' and (params['center_hz'] <= params['bandwidth_hz'] / 2 or params['center_hz'] + params['bandwidth_hz'] / 2 >= fs / 2): fail('带通上下边界须严格位于 0 和 Nyquist 之间。')
        elif kind in ('demod_baseband', 'demod_pam'):
            if direction != 'channel' or not channels or kind != 'de' + modulator['kind']: fail('需要配对的形成器、信道和基带/PAM 接收器。')
            if params['cutoff_hz'] >= program['symbol_rate'] * modulator['params']['sps'] / 2: fail('接收低通截止须低于波形采样率的一半。')
            if count + len(shaping) - 1 > c.CONFIG['max_bits']: fail('接收滤波中间数组超过上限，请减少数据/每码元采样点。')
            if params['equalizer'] in (4,5):
                dimensions = 2*params['half_taps']+1+(params.get('feedback_taps',4) if params['equalizer']==5 else 0)
                if modulator['params'].get('training_symbols',0)<max(32,4*dimensions): fail('自适应均衡需要发送公共训练前导，长度至少为 max(32, 4×均衡总抽头数)。')
            domain = '线路电平' if line else '比特'; count = next(v['input_count'] for v in plan if v.get('kind') == modulator['kind']); direction = 'rx'
        elif kind in c.PAIRS:
            if direction != 'rx' or not stack: fail('没有可以配对的发送转换器。')
            expected, expected_params, original = stack.pop()
            if c.PAIRS[kind] != expected or params != expected_params: fail('须按相反顺序译码并保持线路初态/参数等一致。')
            if kind.startswith('line_'):
                if domain != '线路电平': fail('线路译码需要基带抽样电平。')
                domain = '比特'
            elif domain != '比特': fail('先完成线路译码。')
            if kind == 'pcm_decode' or c.PAIRS[kind] in codec.SOURCE_CODECS: domain = '模拟样本'
            count = original
        elif kind == 'sink':
            if index != len(items) - 1 or direction != 'rx' or stack or domain != ('模拟样本' if analog else '比特'): fail('信宿前需要完整的配对接收链路。')
        else: fail('基带波形链路不能连接此积木。')
        if count > c.CONFIG['max_bits']: fail('中间波形/比特数量超过上限，请减少数据或采样点。')
        plan.append({'id': b['id'], 'kind': kind, 'label': c.BLOCKS[kind]['label'], 'input_count': before, 'count': count, 'output': domain})
    if not items or items[-1]['kind'] != 'sink' or modulator is None: raise ValueError('需要完整基带/PAM 链路及信宿。')
    token = hashlib.sha256(json.dumps(program, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()
    auto = any(b['kind'] in ('demod_baseband','demod_pam') and b['params'].get('timing_mode',0) for b in items)
    return {'program': program, 'token': token, 'plan': plan, 'source_kind': 'analog' if analog else 'digital', 'transport': 'baseband',
            'model': '实基带波形 · 多点/码元 · '+('自动符号同步 / 已知帧粗定位' if auto else '已知帧边界')+' · 有限帧滤波', 'summary': f'{len(sources)} 个信源 · {len(items)} 个积木 · {count} 个接收'+('样本' if analog else '比特')}


def run(compiled, source, texts, source_count, rng):
    from src import communications as c
    p = compiled['program']; data = source.copy(); reference = source.copy() if compiled['source_kind'] == 'digital' else None
    stack = []; clipped = corrections = violations = 0; gain = 1.; warnings = []; line_params = None; recovery_info = {}; codec_info=[]
    for block in p['blocks'][source_count:]:
        runtime.enter(block)
        kind, params = block['kind'], block['params']
        if kind in c.ENCODERS:
            stack.append((kind, params, len(data)))
            if kind.startswith('line_'):
                coded = data.copy(); line_params = params; scheme = line_scheme(kind); data = line_encode(data, scheme, params)
            elif kind in set(codec.PAIRS.values())-{'conv_encode'}:
                data=codec.encode(kind,data,params)
                if kind in codec.SOURCE_CODECS: reference=data.copy()
            elif kind == 'pcm_encode':
                clipped = int(np.count_nonzero(abs(data) > params['full_scale']))
                quantized = np.rint((np.clip(data, -params['full_scale'], params['full_scale']) + params['full_scale']) / (2 * params['full_scale']) * (2 ** params['bits'] - 1)).astype(int)
                data = ((quantized[:, None] >> np.arange(params['bits'] - 1, -1, -1)) & 1).astype(np.uint8).ravel(); reference = data.copy()
            elif kind == 'repeat_encode': data = np.repeat(data, params['factor'])
            elif kind == 'hamming_encode': data = c.hamming_encode(data)
            elif kind == 'conv_encode': data = c.conv_encode(data)
            else: data = np.pad(data, (0, -len(data) % params['columns'])).reshape(-1, params['columns']).T.ravel()
        elif kind in ('mod_baseband', 'mod_pam'):
            tx = params; pam = kind == 'mod_pam'
            if pam: coded = data.copy(); scheme = str(params['order']) + '-PAM'; symbols = pam_map(data, params['order'], params['gray'])
            else: symbols = data.copy()
            allowed = (2*np.arange(tx['order'])-tx['order']+1)/math.sqrt((tx['order']**2-1)/3) if pam else alphabet(scheme)
            training = recovery.preamble(tx.get('training_symbols',0),allowed)
            frame_symbols = np.r_[training,symbols]
            shaping, guard, length = frame_layout(len(symbols), tx, p['blocks']); fs = p['symbol_rate'] * tx['sps']
            impulses = np.zeros((len(frame_symbols) - 1) * tx['sps'] + 1 + 2 * guard); impulses[guard:guard + len(frame_symbols) * tx['sps']:tx['sps']] = frame_symbols
            sent = tx['amplitude'] * np.convolve(impulses, shaping); data = sent.copy()
            response = np.zeros_like(data); response[guard:guard + len(shaping)] = shaping
            power = float(np.mean(sent ** 2)); data_power = float(np.mean(sent[guard:len(sent)-guard] ** 2))
        elif kind in c.CHANNELS:
            if kind in ('sample_awgn', 'bandlimited_awgn'):
                noise = rng.normal(size=len(data)) * math.sqrt(data_power * 10 ** (-params['snr_db'] / 10))
                if kind == 'bandlimited_awgn':
                    data = linear_channel(data, kind, params, fs, tx['sps']); response = linear_channel(response, kind, params, fs, tx['sps'])
                    noise = linear_channel(noise, kind, params, fs, tx['sps'])
                data += noise
            elif kind in WAVE_CHANNELS:
                data = linear_channel(data, kind, params, fs, tx['sps']); response = linear_channel(response, kind, params, fs, tx['sps'])
            elif kind == 'attenuation':
                factor = 10 ** (-params['db'] / 20); data *= factor; response *= factor; gain *= factor
            elif kind == 'dropout': data *= rng.random(len(data)) >= params['probability']
        elif kind in ('demod_baseband', 'demod_pam'):
            received = data.copy(); rx = params
            if params['compensate']: data /= gain; response /= gain
            if params['filter'] == 1:
                receive_filter = shaping[::-1] / np.dot(shaping, shaping)
                filtered = np.convolve(data, receive_filter); response = np.convolve(response, receive_filter); delay = guard + len(shaping) - 1
            else:
                filtered = linear_channel(data, 'lowpass_channel', params, fs, tx['sps']) if params['filter'] == 2 else data.copy()
                if params['filter'] == 2: response = linear_channel(response, 'lowpass_channel', params, fs, tx['sps'])
                delay = guard + len(shaping) // 2
            sampling = delay + params['sample_offset'] * tx['sps']
            half = params['half_taps']; count = len(frame_symbols)
            positions = sampling + np.arange(-half, count + half) * tx['sps']
            if params.get('timing_mode',0):
                recovered_positions, timing = recovery.synchronize(filtered,delay,tx['sps'],count,params,tx['pulse']==0 and params['filter']==0)
                phases = np.array(timing['phases']); extended = np.r_[np.full(half,phases[0]),phases,phases[-1]+np.arange(1,half+1)*timing['frequency_ppm']*1e-6]
                positions = delay+(np.arange(-half,count+half)+extended)*tx['sps']
                sampling = recovered_positions[0]
                recovery_info['timing'] = timing
                if not timing['clock_informative']: warnings.append('接收波形的码元时钟分量不足，自动同步从手动初相开始；长连码/零信号/窄滚降或严重失真可能无法锁定。')
            samples = np.interp(positions, np.arange(len(filtered)), filtered, left=0, right=0) / tx['amplitude']
            extra = params.get('feedback_taps',4) if params['equalizer']==3 else 0
            h = {i: float(np.interp(sampling + i * tx['sps'], np.arange(len(response)), response, left=0, right=0)) for i in range(-2 * half, 2 * half + extra + 1)}
            coefficients = np.zeros(2 * half + 1); coefficients[half] = 1
            if params['equalizer'] == 1: coefficients = zf_coefficients(h, half)
            elif params['equalizer'] == 2:
                # Finite linear MMSE: minimize ||H c - delta||² + lambda ||c||².
                matrix = np.array([[h.get(i-j, 0) for j in range(-half, half+1)] for i in range(-2*half, 2*half+1)])
                target = np.zeros(4*half+1); target[2*half] = 1
                coefficients = np.linalg.solve(matrix.T @ matrix + params['regularization'] * np.eye(2*half+1), matrix.T @ target)
            if params['equalizer']>=3:
                full_decided, equalization = recovery.equalize(samples,count,allowed,training,params,h if params['equalizer']==3 else None)
                coefficients = np.array(equalization['forward_coefficients']); recovery_info['equalizer'] = equalization
                warnings.append('DFE 数据段反馈使用接收判决，判错可能传播。' if params['equalizer'] in (3,5) else '自适应线性均衡使用发送公共前导训练；训练后可按判决继续更新。')
            else: full_decided = np.convolve(samples, coefficients)[2 * half:2 * half + count]
            decided = full_decided[len(training):]
            before_equalization = samples[half+len(training):half+count].copy()
            if params['equalizer'] in (1,2,3):
                warnings.append('均衡器使用配置中的已知线性响应；未用干净信源或接收数据估计信道。有限抽头仍有残余 ISI，迫零可能放大噪声。')
            if params.get('timing_mode',0) or len(training) or params['equalizer']>=3:
                manual_positions = delay+(np.arange(len(training),count)+params['sample_offset'])*tx['sps']
                manual = np.interp(manual_positions,np.arange(len(filtered)),filtered,left=0,right=0)/tx['amplitude']
                recovery_info.update(training_symbols=len(training),payload_symbols=len(symbols),frame_symbols=count,payload_efficiency=len(symbols)/count,
                                     public_preamble=training.tolist(),before_sync_rmse=float(np.sqrt(np.mean((manual-symbols)**2))))
            if pam: data = pam_decode(decided, tx['order'], tx['gray'])[:len(coded)]; demapped = data.copy()
            else: data = decided.copy()
        elif kind in c.PAIRS:
            _, expected, size = stack.pop()
            if c.PAIRS[kind] in codec.SOURCE_CODECS: decoded_bits=data.copy()
            if kind.startswith('line_'): data, violations = line_decode(data, line_scheme(kind), params); demapped = data.copy()
            elif kind in codec.PAIRS:
                data,details=codec.decode(kind,data,params); codec_info.append({'kind':kind,**details})
            elif kind == 'repeat_decode': data = (data.reshape(-1, params['factor']).sum(axis=1) > params['factor']//2).astype(np.uint8)
            elif kind == 'hamming_decode': data, n = c.hamming_decode(data); corrections += n
            elif kind == 'conv_decode': data = c.viterbi_decode(data)
            elif kind == 'deinterleave': data = data.reshape(params['columns'], -1).T.ravel()
            else:
                decoded_bits = data.copy(); quantized = data.reshape(-1, params['bits']).dot(2 ** np.arange(params['bits'] - 1, -1, -1))
                data = quantized / (2 ** params['bits'] - 1) * 2 * params['full_scale'] - params['full_scale']
            data = data[:size]
        data=runtime.record(block,data,locals().get('fs',p['sample_rate']))
    analog = compiled['source_kind'] == 'analog'
    if not analog: decoded_bits = data.astype(np.uint8)
    errors = int(np.count_nonzero(reference != decoded_bits)); coded_errors = int(np.count_nonzero(coded != demapped))
    energy = float(np.mean(symbols ** 2)); error = float(np.mean((decided-symbols)**2))
    allowed = (2*np.arange(tx['order'])-tx['order']+1)/math.sqrt((tx['order']**2-1)/3) if pam else alphabet(scheme)
    nearest = allowed[np.argmin(abs(decided[:,None]-allowed),axis=1)]
    metrics = {'bit_count':len(reference),'bit_errors':errors,'ber':errors/len(reference), 'coded_bit_count':len(coded),'coded_bit_errors':coded_errors,'coded_ber':coded_errors/len(coded),
               'symbol_count':len(symbols),'symbol_errors':int(np.count_nonzero(nearest!=symbols)),'effective_rate':len(reference)/len(coded),
               'evm_percent':100*math.sqrt(error/energy) if energy else 0., 'rmse':float(np.sqrt(np.mean((data-source)**2))) if analog else None,
               'clipped_samples':clipped,'hamming_syndromes':corrections,'line_violations':violations,'level_rmse':math.sqrt(error),
               'before_equalizer_rmse':float(np.sqrt(np.mean((before_equalization-symbols)**2))), 'line_expansion':len(symbols)/len(coded)}
    shown = min(len(sent), c.CONFIG['plot_points']); grid = np.fft.fftshift(np.fft.fftfreq(len(sent),1/fs)); density=abs(np.fft.fftshift(np.fft.fft(sent)))**2/(fs*len(sent))
    eyes=[]
    for i in range(min(len(symbols)-1,64)):
        positions=delay+(len(training)+i-1)*tx['sps']+np.arange(2*tx['sps']+1)
        eyes.append(np.interp(positions,np.arange(len(filtered)),filtered,left=0,right=0).tolist())
    waveform_start=max(0,guard-len(shaping)//2); waveform_end=min(len(sent),waveform_start+shown)
    waveform={'count':len(sent),'plot_count':waveform_end-waveform_start,'i':sent[waveform_start:waveform_end].tolist(),'q':[0.]*(waveform_end-waveform_start)}
    result={'token':compiled['token'],'seed':p['seed'],'summary':compiled['summary'],'model':compiled['model'],'transport':'baseband','plan':compiled['plan'], 'metrics':metrics,
            'sink':{'kind':compiled['source_kind'],'values':data.tolist(),'reference':source.tolist(),'count':len(data),'plot_count':min(len(data),c.CONFIG['plot_points']),'sample_rate':p['sample_rate'] if analog else None},
            'channel':{'count':len(received),'plot_count':waveform_end-waveform_start,'symbol_rate':fs,'i':received[waveform_start:waveform_end].tolist(),'q':[0.]*(waveform_end-waveform_start)},'constellation':None,'text':None,
            'baseband':{'scheme':LINE_CODES.get(scheme,scheme),'sample_rate':fs,'symbol_rate':p['symbol_rate'],'sps':tx['sps'],'pulse':PULSE_NAMES[tx['pulse']], 'guard_samples':guard,'warnings':warnings,'transmit_power':power,'data_power':data_power,
                        'transmitter':waveform,'spectrum':{'frequency_hz':grid.tolist(),'density_db':(10*np.log10(np.maximum(density,1e-20))).tolist()},
                        'line_levels':symbols.tolist(),'decision_levels':decided.tolist(),'before_equalizer':before_equalization.tolist(),'equalizer_coefficients':coefficients.tolist(),
                        'sampled_impulse':{str(i):v for i,v in h.items()},'eye':{'samples_per_symbol':tx['sps'],'traces':eyes,'point_count':2*tx['sps']+1}}}
    if recovery_info: result['baseband']['recovery'] = recovery_info
    if codec_info:
        result['baseband']['codecs']=codec_info
        checks=[v['crc_pass'] for v in codec_info if 'crc_pass' in v]
        metrics.update(crc_pass=all(checks) if checks else None,crc_detected_frame_errors=int(not all(checks)) if checks else None)
    if not analog and len(texts)==source_count: result['text']={'sent':b''.join(texts).decode(),'received':np.packbits(decoded_bits).tobytes().decode('utf-8',errors='replace')}
    return result
