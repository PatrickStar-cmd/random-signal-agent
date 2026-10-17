"""Finite-frame complex-envelope models of the course's six analog modulations.

The real passband signal is Re{u(t) exp(j*2*pi*fc*t)}. FFT filters use
periodic frame boundaries; these are educational ideal filters, not RF circuits.
"""
from __future__ import annotations

import math
import numpy as np
from src import communication_runtime as runtime

SCHEMES = {'am', 'dsb', 'ssb', 'vsb', 'fm', 'pm'}
LABELS = {'am': 'AM', 'dsb': 'DSB-SC', 'ssb': 'SSB', 'vsb': 'VSB', 'fm': 'FM', 'pm': 'PM'}


def sideband_response(count, sample_rate, upper, vestige_hz=0):
    frequencies = np.fft.fftfreq(count, 1 / sample_rate)
    signed = frequencies if upper else -frequencies
    response = .5 + .5 * np.clip(signed / vestige_hz, -1, 1) if vestige_hz else np.where(signed > 0, 1., np.where(signed < 0, 0., .5))
    # DC and the self-conjugate Nyquist bin must both obey H(f)+H(-f)=1.
    response[0] = .5
    if count % 2 == 0: response[count // 2] = .5
    return response


def analytic_signal(message):
    multiplier = np.zeros(len(message))
    multiplier[0] = 1
    multiplier[1:(len(message) + 1) // 2] = 2
    if len(message) % 2 == 0: multiplier[len(message) // 2] = 1
    return np.fft.ifft(np.fft.fft(message) * multiplier)


def modulate(message, scheme, params, sample_rate):
    amplitude = params['amplitude']
    warnings = []
    if scheme == 'am':
        envelope = amplitude * (1 + params['sensitivity'] * message)
        if np.any(envelope < 0): warnings.append('AM 已过调制：包络发生翻转，包络检波会失真；可减小幅值/调幅灵敏度或改用相干解调。')
        return envelope.astype(complex), warnings
    if scheme == 'dsb': return (amplitude * message).astype(complex), warnings
    if scheme == 'ssb' and params['method'] == 0:
        analytic = analytic_signal(message)
        return amplitude / 2 * (analytic if params['upper'] else analytic.conjugate()), warnings
    if scheme in ('ssb', 'vsb'):
        response = sideband_response(len(message), sample_rate, params['upper'], params.get('vestige_hz', 0))
        return amplitude * np.fft.ifft(np.fft.fft(message) * response), warnings
    # A known zero-phase pilot precedes angle-modulated data. It supplies the
    # initial phase reference without using the clean message in the receiver.
    phase = params['sensitivity'] * message if scheme == 'pm' else 2 * np.pi * params['sensitivity'] / sample_rate * np.cumsum(message)
    phase = np.r_[0., phase]
    if np.any(np.abs(np.diff(phase)) >= np.pi):
        raise ValueError('角调制相邻相位变化须小于 π；请提高模拟采样率或减小信源幅值/调制灵敏度。')
    return amplitude * np.exp(1j * phase), warnings


def validate(scheme, transmit, receive, sample_rate):
    if scheme == 'vsb' and transmit['vestige_hz'] >= sample_rate / 2:
        raise ValueError('VSB 残留边带宽度须小于模拟采样率的一半。')
    if receive['cutoff_hz'] >= sample_rate / 2:
        raise ValueError('解调低通截止频率须小于模拟采样率的一半；0 表示不滤波。')


def demodulate(received, scheme, transmit, receive, sample_rate):
    amplitude = transmit['amplitude']
    if scheme == 'am':
        detected = np.abs(received) if receive['method'] == 0 else received.real
        message = (detected / amplitude - 1) / transmit['sensitivity']
    elif scheme in ('dsb', 'ssb', 'vsb'):
        message = received.real * (1 if scheme == 'dsb' else 2) / amplitude
    else:
        phase = np.unwrap(np.angle(received))
        message = ((phase[1:] - phase[0]) / transmit['sensitivity'] if scheme == 'pm'
                   else np.diff(phase) * sample_rate / (2 * np.pi * transmit['sensitivity']))
    if receive['cutoff_hz']:
        mask = np.abs(np.fft.fftfreq(len(message), 1 / sample_rate)) <= receive['cutoff_hz']
        message = np.fft.ifft(np.fft.fft(message) * mask).real
    return message


def run(compiled, source, noise_rng, config):
    program = compiled['program']; sample_rate = program['sample_rate']
    modulator = next(b for b in program['blocks'] if b['kind'].startswith('mod_'))
    scheme = modulator['kind'][4:]; transmit = modulator['params']
    sent, warnings = modulate(source, scheme, transmit, sample_rate)
    data = sent.copy(); gain = 1 + 0j; transmitted_power = float(np.mean(abs(sent) ** 2))
    for block in program['blocks']:
        kind, params = block['kind'], block['params']
        if kind not in ('sine','square','gaussian'): runtime.enter(block)
        if kind == 'analog_awgn':
            scale = math.sqrt(transmitted_power * 10 ** (-params['snr_db'] / 10) / 2)
            data += scale * (noise_rng.normal(size=len(data)) + 1j * noise_rng.normal(size=len(data)))
        elif kind in ('attenuation', 'phase_shift'):
            factor = 10 ** (-params['db'] / 20) if kind == 'attenuation' else np.exp(1j * np.deg2rad(params['degrees']))
            data *= factor; gain *= factor
        elif kind == 'dropout': data *= noise_rng.random(len(data)) >= params['probability']
        elif kind.startswith('demod_'):
            received = data.copy(); decision = received / gain if params['compensate'] else received.copy()
            recovered = demodulate(decision, scheme, transmit, params, sample_rate)
        if kind.startswith('mod_') or kind in ('ideal','analog_awgn','attenuation','phase_shift','dropout'):
            data=runtime.record(block,data,sample_rate)
        elif kind.startswith('demod_') or kind=='sink':
            recovered=runtime.record(block,recovered,sample_rate)
    if scheme in ('fm', 'pm') and np.any(np.abs(decision) < 1e-10 * transmit['amplitude']):
        warnings.append('角调制接收样本接近零幅值，相位不可可靠判定；可能出现相位跳变或周跳。')
    error = recovered - source
    error_power = float(np.mean(error ** 2)); source_power = float(np.mean(source ** 2))
    channel_error = float(np.mean(abs(decision - sent) ** 2))
    metrics = {'rmse': math.sqrt(error_power), 'max_abs_error': float(np.max(abs(error))),
               'output_snr_db': 10 * math.log10(source_power / error_power) if source_power > 0 and error_power > 1e-24 else None,
               'channel_error_percent': 100 * math.sqrt(channel_error / transmitted_power) if transmitted_power > 0 else None,
               'sample_count': len(source), 'channel_sample_count': len(sent), 'transmit_power': transmitted_power,
               'overmodulated_samples': int(np.count_nonzero(1 + transmit['sensitivity'] * source < 0)) if scheme == 'am' else 0}
    spectrum = abs(np.fft.fftshift(np.fft.fft(sent))) ** 2 / (sample_rate * len(sent))
    shown = min(len(sent), config['plot_points'])
    return {'token': compiled['token'], 'seed': program['seed'], 'summary': compiled['summary'], 'model': compiled['model'],
            'transport': 'analog', 'metrics': metrics, 'plan': compiled['plan'], 'text': None, 'constellation': None,
            'sink': {'kind': 'analog', 'values': recovered.tolist(), 'reference': source.tolist(), 'sample_rate': sample_rate,
                     'count': len(source), 'plot_count': min(len(source), config['plot_points'])},
            'channel': {'count': len(received), 'plot_count': shown, 'symbol_rate': sample_rate,
                        'i': received[:shown].real.tolist(), 'q': received[:shown].imag.tolist()},
            'analog': {'scheme': LABELS[scheme], 'family': '非线性角调制' if scheme in ('fm', 'pm') else '线性调制',
                       'sample_rate': sample_rate, 'pilot_samples': int(scheme in ('fm', 'pm')), 'warnings': warnings,
                       'transmitter': {'count': len(sent), 'plot_count': shown, 'i': sent[:shown].real.tolist(), 'q': sent[:shown].imag.tolist()},
                       'spectrum': {'frequency_hz': np.fft.fftshift(np.fft.fftfreq(len(sent), 1 / sample_rate)).tolist(),
                                    'density_db': (10 * np.log10(np.maximum(spectrum, 1e-20))).tolist()}}}
