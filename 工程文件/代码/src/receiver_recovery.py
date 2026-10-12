"""Real baseband timing recovery and trained symbol-spaced equalization.

These routines receive only received samples, public frame parameters and a
public transmitted preamble. Payload truth and channel settings are not inputs
to timing/adaptive algorithms. Fixed DFE explicitly uses configured CSI.
"""
from __future__ import annotations

import math
import numpy as np

TIMING_NAMES = ['手动抽样', '非线性时钟提取', '课件早迟门 PI', 'Gardner PI']
EQUALIZER_NAMES = ['关闭', '有限阶 ZF', '正则 MMSE', '已知响应 DFE', '自适应线性', '自适应 DFE']
ADAPTIVE_NAMES = ['LMS', 'NLMS', 'RLS']
TX_DEFAULT_FIELDS = {'training_symbols'}
RX_DEFAULT_FIELDS = {'timing_mode', 'loop_bandwidth', 'gate_spacing', 'feedback_taps', 'adaptive_algorithm',
                     'step_size', 'forgetting_factor', 'adapt_after_training'}


def preamble(count, levels):
    """Public frame format: repeatable symbols independent of payload/seed."""
    return np.random.default_rng(20261012).choice(levels, size=count)


def slice_level(value, levels):
    return float(levels[np.argmin(abs(levels - value))])


def clock_phase(wave, delay, sps, count, rectangular_direct=False):
    """Nonlinear clock harmonic over an acquisition window, modulo one T."""
    # Omit frame-edge transients so a constant payload cannot masquerade as
    # a usable symbol clock merely because the finite frame turns on/off.
    start = max(0, int(delay + 8 * sps))
    stop = min(len(wave), int(delay + (min(count-8, 136)) * sps))
    segment = wave[start:stop].copy()
    if len(segment) < 16 * sps: return 0., 0.
    if np.std(segment) < .01*max(float(np.sqrt(np.mean(segment**2))),1e-12): return 0., 0.
    if rectangular_direct:
        nonlinear = np.abs(np.diff(segment, prepend=segment[0]))
    else:
        segment -= np.mean(segment)
        nonlinear = segment ** 2
    energy = float(np.sum(nonlinear))
    if energy < 1e-16: return 0., 0.
    carrier = np.exp(-2j * np.pi * (np.arange(start, stop) - delay) / sps)
    harmonic = np.dot(nonlinear, carrier)
    confidence = float(abs(harmonic) / energy)
    phase = -float(np.angle(harmonic)) / (2 * np.pi)
    if rectangular_direct: phase += .5
    phase = (phase + .5) % 1 - .5
    return phase, confidence


def synchronize(wave, delay, sps, count, params, rectangular_direct=False):
    """NDA phase acquisition plus optional second-order timing loop.

    A coarse frame boundary and nominal symbol rate are supplied, not the
    channel's timing offset. One output per known frame symbol is retained.
    PI corrections and clock frequency are in units of symbol periods.
    """
    mode = params.get('timing_mode', 0)
    phase = params['sample_offset']; frequency = 0.
    coarse, confidence = clock_phase(wave, delay, sps, count, rectangular_direct)
    informative = confidence >= .005
    if mode and informative: phase = coarse
    initial = phase
    active = wave[max(0, int(delay-sps)):min(len(wave), int(delay+count*sps))]
    rms = float(np.sqrt(np.mean(active ** 2))) if len(active) else 0.
    rms = max(rms, 1e-8)
    theta = params.get('loop_bandwidth', .01) / (math.sqrt(.5) + 1 / (4 * math.sqrt(.5)))
    denominator = 1 + 2 * math.sqrt(.5) * theta + theta ** 2
    kp = 4 * math.sqrt(.5) * theta / denominator
    ki = 4 * theta ** 2 / denominator
    spacing = params.get('gate_spacing', .25) * sps
    phases = np.empty(count); errors = np.zeros(count); positions = np.empty(count)
    previous = None; previous_time = None
    grid = np.arange(len(wave))
    for k in range(count):
        time = delay + (k + phase) * sps
        on = float(np.interp(time, grid, wave, left=0, right=0))
        phases[k] = phase; positions[k] = time
        if mode == 2:
            early, late = np.interp([time-spacing, time+spacing], grid, wave, left=0, right=0)
            # Course rectified early/late detector: move toward larger amplitude.
            error = (abs(late) - abs(early)) / rms
        elif mode == 3 and previous is not None:
            middle = float(np.interp((previous_time+time)/2, grid, wave, left=0, right=0))
            error = middle * (previous - on) / (rms ** 2)
        else: error = 0.
        error = float(np.clip(error, -2, 2)); errors[k] = error
        if mode in (2, 3):
            frequency = float(np.clip(frequency + ki * error, -.002, .002))
            phase += frequency + kp * error
            if abs(phase) > 64: raise ValueError('定时环路漂移超过 64 码元，请检查脉冲、时钟误差和环路带宽。')
        previous = on; previous_time = time
    tail = phases[-min(128, count):]
    detrended = tail - np.linspace(tail[0], tail[-1], len(tail))
    return positions, {'method':TIMING_NAMES[mode], 'initial_phase':initial, 'final_phase':float(phases[-1]),
                       'clock_confidence':confidence, 'clock_informative':informative,
                       'frequency_ppm':frequency*1e6, 'phase_jitter':float(np.std(detrended)),
                       'phases':phases.tolist(), 'errors':errors.tolist(), 'sample_positions':positions.tolist()}


def fixed_dfe_coefficients(response, half, feedback_count, regularization):
    """Unit-gain finite feedforward, cancel postcursors by hard feedback."""
    indices = np.arange(-half, half + 1)
    lags = range(-2 * half, 2 * half + feedback_count + 1)
    residual = [i for i in lags if i != 0 and not 1 <= i <= feedback_count]
    matrix = np.array([[response.get(i-int(j), 0.) for j in indices] for i in residual])
    center = np.array([response.get(-int(j), 0.) for j in indices])
    inverse_center = np.linalg.solve(matrix.T @ matrix + regularization*np.eye(len(indices)), center)
    gain = float(np.dot(center, inverse_center))
    if gain < 1e-12: raise ValueError('DFE 主抽样响应为零，无法归一化；请调整抽样/信道或选择自适应训练。')
    forward = inverse_center / gain
    feedback = np.array([sum(forward[j+half]*response.get(i-j, 0.) for j in indices) for i in range(1,feedback_count+1)])
    return forward, feedback


def equalize(samples, count, levels, training, params, response=None):
    """samples includes N observations on either side of the complete frame.

    y[k] = f.T x[k] - b.T past_decisions. On training symbols the feedback
    register uses the public preamble; thereafter only receiver decisions.
    """
    mode = params['equalizer']; half = params['half_taps']; forward_count = 2*half+1
    feedback_count = params.get('feedback_taps', 4) if mode in (3,5) else 0
    forward = np.zeros(forward_count); forward[half] = 1
    feedback = np.zeros(feedback_count)
    adaptive = mode in (4,5); algorithm = params.get('adaptive_algorithm',1)
    if mode == 3: forward, feedback = fixed_dfe_coefficients(response,half,feedback_count,params['regularization'])
    weights = np.r_[forward,feedback]; history = np.zeros(feedback_count)
    inverse = np.eye(len(weights))/params['regularization'] if adaptive and algorithm==2 else None
    output = np.empty(count); errors = np.empty(count); updates = 0; trace=[]
    for k in range(count):
        inputs = np.r_[samples[k:k+forward_count][::-1], -history]
        value = float(np.dot(weights,inputs)); output[k] = value
        decision = slice_level(value,levels)
        desired = float(training[k]) if k<len(training) else decision
        error = desired-value; errors[k] = error
        update = adaptive and (k<len(training) or params.get('adapt_after_training',True))
        if update:
            if algorithm == 2:
                forgetting = params.get('forgetting_factor',.995)
                projected = inverse@inputs; denominator = forgetting + float(inputs@projected)
                if denominator<=1e-12: raise ValueError('RLS 相关矩阵失去正定性，请增大正则参数。')
                gain = projected/denominator
                weights += gain*error
                inverse = (inverse-np.outer(gain,inputs)@inverse)/forgetting
                inverse = (inverse+inverse.T)/2
            else:
                step = params.get('step_size',.2)
                if algorithm == 1: step /= 1e-8+float(inputs@inputs)
                weights += step*error*inputs
            updates += 1
            if not np.all(np.isfinite(weights)) or np.max(abs(weights))>1e6 or (inverse is not None and not np.all(np.isfinite(inverse))):
                raise ValueError('自适应均衡发散，请减小步长、增加训练长度或调整遗忘/正则参数。')
        if feedback_count:
            history[1:] = history[:-1]; history[0] = desired if k<len(training) else decision
        if k%max(1,math.ceil(count/256)) == 0:
            trace.append({'symbol':k,'mse':float(np.mean(errors[max(0,k-31):k+1]**2))})
    n=len(training);window=min(64,n)
    return output, {'method':EQUALIZER_NAMES[mode], 'algorithm':ADAPTIVE_NAMES[algorithm] if adaptive else '固定响应',
                    'forward_coefficients':weights[:forward_count].tolist(), 'feedback_coefficients':weights[forward_count:].tolist(),
                    'training_symbols':n,'updates':updates,'decision_directed':adaptive and params.get('adapt_after_training',True),
                    'training_initial_mse':float(np.mean(errors[:window]**2)) if n else None,
                    'training_final_mse':float(np.mean(errors[n-window:n]**2)) if n else None,
                    'error_trace':trace}
