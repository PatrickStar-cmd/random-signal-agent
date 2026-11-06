"""Multi-target OFDM echoes and power-domain two-dimensional CA-CFAR."""
import json
import math
import numpy as np
from src import communication_isac_v0410 as isac, communication_runtime as runtime

TX = set()
CHANNEL = {'isac_echo_multi'}
RX = set()
KINDS = CHANNEL
DEFAULTS = {'training_range': 2, 'training_doppler': 4, 'guard_range': 1,
            'guard_doppler': 1, 'pfa': .001, 'direct_bins': 1, 'cluster_radius': 1}


def register(block, number, field, blocks):
    block('isac_echo_multi', '🛰️ 多目标延迟与多普勒', 'channel',
          '按目标表叠加距离、径向速度、幅度与初相，直达路径保持独立。',
          targets=field('目标表 JSON（距离 m、速度 m/s、幅度、相位 °）',
                        '[{"range_m":780,"velocity_mps":37.5,"amplitude":0.25,"phase_deg":0},'
                        '{"range_m":1560,"velocity_mps":-56.25,"amplitude":0.2,"phase_deg":30}]', max_length=3000),
          carrier_ghz=number('射频载频 / GHz', 3, .1, 100),
          direct=number('直达路径幅度', 1, 0, 2))


def targets(q):
    from src import communications as c
    values = json.loads(q['targets'])
    if not isinstance(values, list) or len(values) > 8:
        raise ValueError('目标表使用 0–8 个目标对象；空列表用于纯噪声实验。')
    result = []
    for row in values:
        if not isinstance(row, dict) or set(row) - {'range_m', 'velocity_mps', 'amplitude', 'phase_deg'}:
            raise ValueError('目标字段使用 range_m、velocity_mps、amplitude、phase_deg。')
        result.append({
            'range_m': c.numeric(row.get('range_m'), '目标距离', 0, 100000),
            'velocity_mps': c.numeric(row.get('velocity_mps', 0), '径向速度', -1000, 1000),
            'amplitude': c.numeric(row.get('amplitude', .25), '回波幅度', 0, 2),
            'phase_deg': c.numeric(row.get('phase_deg', 0), '初相', -360, 360),
        })
    return result


def build_stage(kind, q, domain, count, features):
    values = targets(q)
    for row in values or [{'range_m': 1, 'velocity_mps': 0, 'amplitude': 0}]:
        isac.build_stage('isac_echo', {**row, 'carrier_ghz': q['carrier_ghz'], 'direct': q['direct']}, domain, count, features)
    features.pop('isac_echo', None)
    features[kind] = {'params': q, 'count': count}
    return domain, count


def run_stage(kind, data, q, state, rng, fs):
    values = targets(q)
    memory = runtime.state('multi_echo', lambda: {'phases': [math.radians(v['phase_deg']) for v in values]})
    output = q['direct'] * data.copy()
    details = []
    for i, row in enumerate(values):
        delay = 2 * row['range_m'] / isac.C * fs
        whole = int(math.floor(delay))
        taps = np.sinc(np.arange(-4, 5) - (delay - whole)) * np.kaiser(9, 6)
        taps /= taps.sum()
        extended = np.convolve(data, taps)
        positions = np.arange(len(data)) + 4 - whole
        delayed = np.zeros(len(data), complex)
        valid = (positions >= 0) & (positions < len(extended))
        delayed[valid] = extended[positions[valid]]
        fd = 2 * row['velocity_mps'] * q['carrier_ghz'] * 1e9 / isac.C
        phase = memory['phases'][i] + 2 * np.pi * fd * np.arange(len(data)) / fs
        memory['phases'][i] = float((memory['phases'][i] + 2 * np.pi * fd * len(data) / fs) % (2 * np.pi))
        output += row['amplitude'] * delayed * np.exp(1j * phase)
        details.append({**row, 'delay_samples': delay, 'doppler_hz': fd})
    return output, {'targets': details, 'direct': q['direct']}, fs


def presets(preset):
    p = preset(['random_bits', 'mod_qpsk', 'tx_isac_ofdm', 'isac_echo_multi',
                'complex_awgn', 'rx_isac_ofdm', 'demod_qpsk', 'sink'],
               {0: {'count': 16384}, 2: {'cp': 32}, 4: {'snr_db': 30}})
    p['symbol_rate'] = 15000
    return {'ofdm_isac_multi': {'label': '通感 · 多目标距离与速度', 'program': p}}


def settings(raw=None):
    from src import communications as c
    q = {**DEFAULTS, **(raw or {})}
    if set(q) != set(DEFAULTS):
        raise ValueError('CFAR 参数包含未知字段。')
    for key in ('training_range', 'training_doppler'):
        q[key] = c.numeric(q[key], '训练单元', 1, 32, True)
    for key in ('guard_range', 'guard_doppler', 'direct_bins', 'cluster_radius'):
        q[key] = c.numeric(q[key], '保护 / 排除 / 聚类单元', 0, 16, True)
    q['pfa'] = c.numeric(q['pfa'], '目标虚警概率', 1e-6, .2)
    return q


def detect(power, ranges, velocities, raw=None):
    q = settings(raw)
    a = np.asarray(power, float)
    if a.ndim != 2 or a.shape != (len(velocities), len(ranges)) or a.size > 262144 or not np.all(np.isfinite(a)) or np.any(a < 0):
        raise ValueError('CFAR 输入须为有限、非负的线性距离—速度功率网格及匹配坐标轴。')
    gy, gx = q['guard_doppler'], q['guard_range']
    ry, rx = gy + q['training_doppler'], gx + q['training_range']
    h, w = a.shape
    if h <= 2 * ry or w <= 2 * rx:
        raise ValueError('训练与保护窗需要完整落在距离—速度网格内，请缩小窗口。')
    keep = np.ones(a.shape, float)
    keep[:, :q['direct_bins']] = 0
    def sums(values, dy, dx, yy, xx):
        integral = np.pad(values, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        return (integral[yy + dy + 1, xx + dx + 1] - integral[yy - dy, xx + dx + 1]
                - integral[yy + dy + 1, xx - dx] + integral[yy - dy, xx - dx])
    yy, xx = np.meshgrid(np.arange(ry, h - ry), np.arange(rx, w - rx), indexing='ij')
    n = sums(keep, ry, rx, yy, xx) - sums(keep, gy, gx, yy, xx)
    total = sums(a * keep, ry, rx, yy, xx) - sums(a * keep, gy, gx, yy, xx)
    valid = (n > 0) & (xx >= q['direct_bins'])
    noise = total / np.maximum(n, 1)
    alpha = n * np.expm1(-math.log(q['pfa']) / np.maximum(n, 1))
    threshold = alpha * noise
    hits = valid & (a[yy, xx] > threshold)
    cells = [(int(y), int(x)) for y, x in zip(yy[hits], xx[hits])]
    # Keep one measured peak per connected cluster of threshold crossings.
    pending = set(cells)
    peaks = []
    radius = q['cluster_radius']
    while pending:
        root = pending.pop()
        group, queue = [root], [root]
        while queue:
            y, x = queue.pop()
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    item = (y + dy, x + dx)
                    if item in pending:
                        pending.remove(item); group.append(item); queue.append(item)
        y, x = max(group, key=lambda pair: a[pair])
        peaks.append({'row': y, 'column': x, 'range_m': float(ranges[x]),
                      'velocity_mps': float(velocities[y]), 'power': float(a[y, x]),
                      'threshold': float(threshold[y - ry, x - rx]),
                      'noise': float(noise[y - ry, x - rx]), 'cluster_cells': len(group)})
    def grid(values):
        out = [[None] * w for _ in range(h)]
        for y, x, value in zip(yy[valid], xx[valid], values[valid]):
            out[int(y)][int(x)] = float(value)
        return out
    tested = int(valid.sum())
    return {'kind': 'analysis_cfar2d', 'settings': q, 'detections': sorted(peaks, key=lambda p: -p['power']),
            'threshold': grid(threshold), 'noise': grid(noise), 'tested_cells': tested,
            'crossing_cells': len(cells), 'crossing_fraction': len(cells) / max(1, tested),
            'training_cells_min': int(n[valid].min()) if tested else 0,
            'valid_region': {'row': [ry, h - ry], 'column': [max(rx, q['direct_bins']), w - rx]},
            'power_domain': 'linear', 'threshold_model': 'independent_square_law_noise',
            'range_axis_m': list(ranges), 'velocity_axis_mps': list(velocities)}
