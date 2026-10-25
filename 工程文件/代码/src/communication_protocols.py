"""Packet-level reference PHY experiments with measured decoding and feedback."""
import base64
import copy
import math
import numpy as np
from src import communication_codecs as codec, communication_dsp as dsp
from src.communication_runtime import Cancelled


def packetize(bits, packet_bytes):
    """Sequence/length header, byte payload, CRC-16/CCITT-FALSE."""
    data = np.asarray(bits, dtype=np.uint8)
    if len(data) % 8:
        data = np.pad(data, (0, -len(data) % 8))
    packets = []
    for sequence, start in enumerate(range(0, len(data), packet_bytes * 8)):
        payload = data[start:start + packet_bytes * 8]
        header = codec.words_to_bits([sequence, len(payload) // 8], 16)
        content = np.r_[header, payload]
        packets.append({'sequence': sequence, 'payload': payload, 'wire': np.r_[content, codec.crc(content, 16)]})
    return packets


def unpack_packet(wire):
    wire = np.asarray(wire, dtype=np.uint8)
    if len(wire) < 48 or not np.array_equal(wire[-16:], codec.crc(wire[:-16], 16)):
        return None
    sequence, size = codec.bits_to_words(wire[:32], 16)
    if int(size) * 8 + 48 != len(wire):
        return None
    return int(sequence), wire[32:-16].copy()


def reassemble(packets):
    """Accept valid packets, suppress duplicate sequence numbers, sort by sequence."""
    accepted = {}
    for wire in packets:
        decoded = unpack_packet(wire)
        if decoded is not None:
            accepted.setdefault(decoded[0], decoded[1])
    return np.concatenate([accepted[i] for i in sorted(accepted)]) if accepted else np.array([], dtype=np.uint8)


def source_bits(program):
    from src import communications as c
    if any(b['kind']=='iq_source' for b in program['blocks']): raise ValueError('闭环协议请选择数字业务信源。')
    bits, _, _ = c.source_data(program)
    if not np.issubdtype(bits.dtype, np.integer) or np.any((bits != 0) & (bits != 1)):
        raise ValueError('闭环协议请选择数字业务信源。')
    return bits.astype(np.uint8)


def cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled('包级实验已取消。')


def transmit(bits, scheme, snr_db, rng, rate=1):
    from src import communications as c
    mother = c.conv_encode(bits)
    coded = mother if rate == 1 else codec.encode('puncture', mother, {'rate': rate})
    symbols, _ = c.modulate(coded, scheme)
    variance = 10. ** (-snr_db / 10)
    iq_noise = rng.normal(size=(len(symbols), 2))
    noise = np.sqrt(variance / 2) * (iq_noise[:, 0] + 1j * iq_noise[:, 1])
    received = symbols + noise
    llr = dsp.soft_demod(received, scheme, variance)[:len(coded)]
    if rate != 1:
        llr = codec.depuncture(llr, len(mother), rate)
    return llr, {'symbols': len(symbols), 'tx_energy': float(np.sum(abs(symbols) ** 2)),
                 'evm_percent': float(100 * np.linalg.norm(noise) / np.linalg.norm(symbols))}


def common(program, settings):
    from src import communications as c
    if not isinstance(settings, dict):
        raise ValueError('实验设置需要 JSON 对象。')
    size = c.numeric(settings.get('packet_bytes', 16), '每包字节', 1, 256, True)
    rate = c.numeric(settings.get('symbol_rate', program['symbol_rate']), '符号率', 1, 100000)
    packets = packetize(source_bits(program), size)
    return size, rate, packets


def protocol(program, settings, progress=None, cancel=None):
    """Stop-and-wait ARQ and Chase HARQ share exactly the same convolutional PHY."""
    if settings.get('phy', 'reference') == 'program': return program_protocol(program, settings, progress, cancel)
    if settings.get('phy', 'reference') != 'reference': raise ValueError('物理层请选择 reference 或 program。')
    from src import communications as c
    size, rate, packets = common(program, settings)
    mode = settings.get('mode', 'arq')
    if mode not in ('arq', 'harq'):
        raise ValueError('协议模式请选择 arq 或 harq。')
    count = c.numeric(settings.get('packets', 8), '最大包数', 1, 32, True)
    retries = c.numeric(settings.get('max_retries', 4), '最大重传次数', 0, 8, True)
    snr = c.numeric(settings.get('snr_db', 0), 'Es/N₀', -15, 40)
    delay = c.numeric(settings.get('feedback_delay', 20), '反馈往返延迟 / ms', 0, 10000) / 1000
    timeout = c.numeric(settings.get('timeout', 50), '反馈超时 / ms', .1, 20000) / 1000
    if timeout < delay:
        raise ValueError('反馈超时须大于等于反馈往返延迟。')
    loss = c.numeric(settings.get('feedback_loss', .05), '反馈丢失概率', 0, 1)
    scheme = settings.get('scheme', 'qpsk')
    if scheme not in ('bpsk', 'qpsk'):
        raise ValueError('ARQ/HARQ 调制请选择 bpsk 或 qpsk。')
    packets = packets[:count]
    events = []; rows = []; accepted = {}; clock = 0.; attempts = confirmations = 0
    config = {**settings, 'mode': mode, 'packet_bytes': size, 'packets': len(packets), 'symbol_rate': rate,
              'scheme': scheme, 'snr_db': snr, 'seed': program['seed'], 'source': '当前工程数字信源',
              'seed_policy': '按工程种子、包序号、发送次数派生物理层与反馈独立随机流；ARQ/HARQ 同包同次发送使用相同噪声。',
              'noise_reference': '标称单位符号能量 Es/N₀；信息比特 Eb/N₀ 计入包头、CRC、卷积尾位与重传能量。',
              'actual_chain': '序号/长度/CRC16 分包 → (7,5)₈ 卷积码 1/2 → ' + scheme.upper() +
              ' → AWGN → Max-log LLR → ' + ('Chase 软信息合并' if mode == 'harq' else '每次独立软译码') + ' → Viterbi → CRC16 → ACK/NACK'}
    for packet in packets:
        combined = None; ack = False; first_delivery = None; start_time = clock; last_errors = 0; packet_energy = 0.
        for attempt in range(retries + 1):
            cancelled(cancel); attempts += 1
            phy_seed, feedback_seed = np.random.SeedSequence([program['seed'], packet['sequence'], attempt, 4701]).spawn(2)
            llr, details = transmit(packet['wire'], scheme, snr, np.random.default_rng(phy_seed))
            packet_energy += details['tx_energy']
            combined = llr if combined is None or mode == 'arq' else combined + llr
            decoded = codec.soft_viterbi(combined)
            last_errors = int(np.count_nonzero(decoded[32:-16] != packet['payload']))
            received = unpack_packet(decoded)
            valid = received is not None and received[0] == packet['sequence'] and len(received[1]) == len(packet['payload'])
            begin = clock; clock += details['symbols'] / rate
            duplicate = valid and packet['sequence'] in accepted
            if valid and not duplicate:
                accepted[packet['sequence']] = received[1]; first_delivery = clock - start_time
            erased = np.random.default_rng(feedback_seed).random() < loss
            feedback = 'ACK' if valid else 'NACK'
            events.append({'packet': packet['sequence'], 'attempt': attempt + 1, 'start_seconds': begin,
                           'receive_seconds': clock, 'feedback': feedback, 'feedback_lost': bool(erased), 'duplicate': duplicate,
                           'crc_pass': valid, 'bit_errors': last_errors, 'combined_transmissions': attempt + 1 if mode == 'harq' else 1,
                           'llr_mean_abs': float(np.mean(abs(combined))),
                           'payload_ebn0_db': snr + 10 * math.log10(details['tx_energy'] / len(packet['payload'])),
                           'accumulated_payload_ebn0_db': snr + 10 * math.log10(packet_energy / len(packet['payload'])), **details})
            clock += timeout if erased else delay
            events[-1]['end_seconds'] = clock; events[-1]['event'] = 'timeout' if erased else feedback
            if valid and not erased:
                ack = True; confirmations += 1; break
        delivered = packet['sequence'] in accepted
        rows.append({'packet': packet['sequence'], 'bytes': len(packet['payload']) // 8, 'attempts': attempt + 1,
                     'retransmissions': attempt, 'delivered': delivered, 'confirmed': ack,
                     'delivery_latency_seconds': first_delivery, 'elapsed_seconds': clock - start_time,
                     'bit_errors': int(np.count_nonzero(accepted[packet['sequence']] != packet['payload'])) if delivered else last_errors})
        if progress:
            progress({'completed': len(rows), 'total': len(packets), 'frames': rows, 'events': events})
    original = np.concatenate([p['payload'] for p in packets])
    restored = np.concatenate([accepted[i] for i in sorted(accepted)]) if accepted else np.array([], dtype=np.uint8)
    metrics = {'packets': len(rows), 'delivered_packets': len(accepted), 'confirmed_packets': confirmations,
               'transmissions': attempts, 'retransmissions': attempts - len(rows), 'packet_loss_rate': 1 - len(accepted) / len(rows),
               'elapsed_seconds': clock, 'goodput_bps': len(restored) / max(clock, 1e-12),
               'mean_delivery_latency_seconds': float(np.mean([r['delivery_latency_seconds'] for r in rows if r['delivered']])) if accepted else None,
               'delivered_bit_errors': sum(r['bit_errors'] for r in rows if r['delivered']),
               'complete_payload': len(accepted) == len(packets) and np.array_equal(original, restored)}
    metrics.update(bit_count=len(original), bit_errors=sum(r['bit_errors'] for r in rows))
    metrics['ber'] = metrics['bit_errors']/metrics['bit_count']
    return {'config': config, 'source_program': copy.deepcopy(program), 'metrics': metrics, 'frames': rows, 'events': events, 'complete': True,
            'source_base64': base64.b64encode(np.packbits(original)).decode(), 'received_base64': base64.b64encode(np.packbits(restored)).decode()}


PROFILES = [
    {'name': 'BPSK 1/2', 'scheme': 'bpsk', 'rate': 1, 'code_rate': .5, 'threshold_db': -15.},
    {'name': 'QPSK 1/2', 'scheme': 'qpsk', 'rate': 1, 'code_rate': .5, 'threshold_db': 3.},
    {'name': 'QPSK 3/4', 'scheme': 'qpsk', 'rate': 3, 'code_rate': .75, 'threshold_db': 8.},
    {'name': '16QAM 3/4', 'scheme': 'qam16', 'rate': 3, 'code_rate': .75, 'threshold_db': 14.},
    {'name': '64QAM 3/4', 'scheme': 'qam64', 'rate': 3, 'code_rate': .75, 'threshold_db': 20.},
]


def amc(program, settings, progress=None, cancel=None):
    if settings.get('phy', 'reference') == 'program': return program_amc(program, settings, progress, cancel)
    if settings.get('phy', 'reference') != 'reference': raise ValueError('物理层请选择 reference 或 program。')
    from src import communications as c
    size, rate, packets = common(program, settings)
    count = c.numeric(settings.get('frames', 20), '帧数', 2, 100, True)
    lo = c.numeric(settings.get('snr_start', 0), '起始 Es/N₀', -15, 40)
    hi = c.numeric(settings.get('snr_stop', 24), '终止 Es/N₀', -15, 40)
    delay = c.numeric(settings.get('feedback_delay', 2), '额外反馈延迟帧数', 0, 20, True)
    hysteresis = c.numeric(settings.get('hysteresis', 1), '切换滞回 / dB', 0, 10)
    profile = 0; rows = []; estimates = []; total_bits = total_errors = delivered = failed = switches = 0; elapsed = 0.
    for frame in range(count):
        cancelled(cancel)
        feedback_index = frame - delay - 1
        feedback = estimates[feedback_index] if feedback_index >= 0 else None
        previous = profile
        if feedback is not None:
            while profile + 1 < len(PROFILES) and feedback >= PROFILES[profile + 1]['threshold_db'] + hysteresis:
                profile += 1
            while profile > 0 and feedback < PROFILES[profile]['threshold_db'] - hysteresis:
                profile -= 1
        switches += int(previous != profile)
        current = PROFILES[profile]; snr = lo + (hi - lo) * frame / (count - 1)
        # 64 known pilots provide a fresh receiver noise estimate every frame.
        pilot_seed, payload_seed = np.random.SeedSequence([program['seed'], frame, 4702]).spawn(2)
        pilot_rng = np.random.default_rng(pilot_seed)
        variance = 10 ** (-snr / 10); noise = np.sqrt(variance / 2) * (pilot_rng.normal(size=64) + 1j * pilot_rng.normal(size=64))
        estimate = float(-10 * np.log10(np.mean(abs(noise) ** 2))); estimates.append(estimate)
        packet = packets[frame % len(packets)]
        llr, detail = transmit(packet['wire'], current['scheme'], snr, np.random.default_rng(payload_seed), current['rate'])
        decoded = codec.soft_viterbi(llr); received = unpack_packet(decoded)
        crc_pass = received is not None and received[0] == packet['sequence']
        errors = int(np.count_nonzero(decoded[32:-16] != packet['payload'])); bits = len(packet['payload'])
        duration = (detail['symbols'] + 64) / rate; elapsed += duration; total_bits += bits; total_errors += errors
        delivered += bits if crc_pass else 0; failed += int(not crc_pass)
        rows.append({'frame': frame + 1, 'snr_db': snr, 'estimated_snr_db': estimate, 'feedback_snr_db': feedback,
                     'profile': current['name'], 'profile_index': profile, 'scheme': current['scheme'], 'code_rate': current['code_rate'],
                     'bit_errors': errors, 'bit_count': bits, 'ber': errors / bits, 'crc_pass': crc_pass,
                     'goodput_bps': bits / duration if crc_pass else 0., 'duration_seconds': duration,
                     'payload_ebn0_db': snr + 10 * math.log10((detail['tx_energy'] + 64) / bits), **detail})
        if progress:
            progress({'completed': len(rows), 'total': count, 'frames': rows})
    return {'config': {**settings, 'seed': program['seed'], 'symbol_rate': rate, 'packet_bytes': size, 'profiles': PROFILES,
                       'actual_chain': '当前数字信源分包/CRC16 → 自适应卷积码率/调制 → AWGN → 64 导频估计 Es/N₀ → 延迟反馈/滞回 → 软 Viterbi/CRC16',
                       'feedback_timing': '下一帧可用的测量反馈 + 额外延迟帧数', 'snr_reference': '单位平均符号能量 Es/N₀',
                       'energy_reference': 'payload_ebn0_db 使用实际数据符号能量与 64 个导频能量 / 有效信息比特数',
                       'payload_policy': '依次发送当前数字信源的分包，帧数超过包数时从头循环',
                       'seed_policy': '按工程种子与帧序号派生导频、数据独立噪声流；同帧导频估计与反馈配置独立。'},
            'source_program': copy.deepcopy(program), 'frames': rows, 'complete': True,
            'metrics': {'frames': count, 'bit_count': total_bits, 'bit_errors': total_errors, 'ber': total_errors / total_bits,
                        'fer': failed / count, 'goodput_bps': delivered / elapsed, 'elapsed_seconds': elapsed, 'profile_switches': switches}}


def packet_program(program, wire, seed):
    """Inject a real wire packet while retaining every configured PHY block."""
    from src import communications as c
    p = copy.deepcopy(program); source_count = 0
    while source_count < len(p['blocks']) and p['blocks'][source_count]['kind'] in c.SOURCES: source_count += 1
    if not source_count: raise ValueError('闭环物理层需要数字信源。')
    # Independent sources retain their user boundaries for multiuser transmitters.
    modulation = next((b['kind'][4:] for b in p['blocks'] if b['kind'].startswith('mod_')), 'bpsk')
    width = c.constellation(modulation)[0].shape[1] if modulation in ('bpsk','qpsk','psk8','qam16','qam64','qam256') else 1
    if source_count > 1:
        wire = np.pad(wire, (0, -len(wire) % width))
        units = np.array_split(np.arange(len(wire)//width), source_count)
        if any(not len(group) for group in units): raise ValueError('包长需要覆盖每个独立信源。')
        lengths = [len(group)*width for group in units]
    else: lengths = [len(wire)]
    start = 0
    for block, size in zip(p['blocks'][:source_count], lengths):
        block.update(kind='bit_pattern', params={'pattern': ''.join(str(int(v)) for v in wire[start:start+size])}); start += size
    p['seed'] = int(seed) % 4294967295
    return c.build(p)


class PacketReceiver:
    """Receiver evidence and Chase combining through the runtime decision hook."""
    def __init__(self, compiled, cancel, states, previous=None):
        from src import communication_runtime as runtime
        self.observer = runtime.Observer(compiled, points=16, cancel=cancel, states=states)
        self.observer.on_decision = self.decision
        self.previous = previous; self.llr = None; self.combined = None; self.snr_db = None; self.method = None; self.variance = None

    def decision(self, block, symbols, scheme, data, noise_variance):
        from src import communication_dsp as dsp
        if scheme not in ('bpsk','qpsk','psk8','qam16','qam64','qam256'):
            if self.previous is not None: raise ValueError('Chase 合并使用 BPSK、QPSK、PSK8 或 QAM 接收机。')
            return data
        _, points = dsp.constellation(scheme)
        residual = float(np.mean(np.min(abs(np.asarray(symbols)[:, None]-points[None, :])**2, axis=1)))
        variance = max(1e-12, float(noise_variance) if noise_variance is not None else residual)
        automatic = noise_variance is not None and any(b['kind']=='rx_noise_estimate' for b in self.observer.compiled['program']['blocks'])
        measured = noise_variance if automatic else residual
        self.variance = float(max(1e-12, measured))
        self.snr_db = float(-10*np.log10(max(1e-12, measured)))
        self.method = '接收噪声估计积木' if automatic else '最近星座残差的接收噪声估计'
        self.llr = np.asarray(data, float).copy() if block['kind'].startswith('soft_') else dsp.soft_demod(symbols, scheme, variance)[:len(data)]
        if self.previous is not None and len(self.previous) != len(self.llr): raise ValueError('重传码字的 LLR 长度需要保持一致。')
        self.combined = self.llr.copy() if self.previous is None else self.previous+self.llr
        if self.previous is None: return data
        return self.combined if block['kind'].startswith('soft_') else (self.combined < 0).astype(np.uint8)


def run_packet(program, packet, seed, cancel, states, previous=None):
    from src import communications as c, communication_runtime as runtime
    compiled = packet_program(program, packet['wire'], seed)
    receiver = PacketReceiver(compiled, cancel, states, previous)
    with runtime.execution(receiver.observer): result = c.run(compiled['program'], compiled['token'])
    decoded = np.asarray(result['sink']['values'], dtype=np.uint8)
    source_length = sum(len(b['params']['pattern']) for b in compiled['program']['blocks'] if b['kind']=='bit_pattern')
    if len(decoded) != source_length: raise ValueError('闭环接收端需要恢复完整的发送比特帧。')
    decoded = decoded[:len(packet['wire'])]
    analysis = result.get('analysis')
    if analysis:
        duration = float(analysis['duration_seconds']); energy = result['metrics'].get('tx_energy', analysis['tx']['power']*analysis['tx']['count'])
        sample_count = result['metrics'].get('tx_sample_count', analysis['tx']['count'])
    else:
        wave = result['baseband']; sample_count = wave['transmitter']['count']; duration = sample_count/wave['sample_rate']; energy = wave['transmit_power']*sample_count
    channel_duration = result['channel']['count']/(analysis['channel']['sample_rate'] if analysis else wave['sample_rate'])
    advanced = result.get('advanced', {})
    synchronized = advanced.get('recovery', {}).get('frame', {}).get('detected', True) and all(stage.get('detected', True) and stage.get('sync', {}).get('detected', True) for stage in advanced.get('wireless', {}).values())
    return decoded, receiver, {'duration_seconds': max(duration, channel_duration), 'tx_duration_seconds': duration,
                               'channel_tail_seconds': max(0., channel_duration-duration), 'tx_energy': float(energy), 'symbols': int(sample_count),
                               'evm_percent': result['metrics'].get('evm_percent'), 'estimated_snr_db': receiver.snr_db,
                               'estimated_noise_variance': receiver.variance,
                               'synchronization_pass': bool(synchronized),
                               'noise_estimator': receiver.method, 'phy_token': compiled['token'], 'phy_metrics': result['metrics'],
                               'executed_kinds': [b['kind'] for b in compiled['program']['blocks']],
                               'code_rate': result['metrics'].get('effective_rate', 1.), 'wire_padding_bits': source_length-len(packet['wire']), 'program': compiled['program']}


def program_protocol(program, settings, progress=None, cancel=None):
    from src import communications as c
    p = c.build(program)['program']; size, _, packets = common(p, settings)
    mode = settings.get('mode', 'arq')
    if mode not in ('arq', 'harq'): raise ValueError('协议模式请选择 arq 或 harq。')
    retries = c.numeric(settings.get('max_retries', 4), '最大重传次数', 0, 8, True)
    packets = packets[:c.numeric(settings.get('packets', 8), '最大包数', 1, 32, True)]
    delay = c.numeric(settings.get('feedback_delay', 20), '反馈往返延迟 / ms', 0, 10000)/1000
    timeout = c.numeric(settings.get('timeout', 50), '反馈超时 / ms', .1, 20000)/1000
    if timeout < delay: raise ValueError('反馈超时须大于等于反馈往返延迟。')
    loss = c.numeric(settings.get('feedback_loss', .05), '反馈丢失概率', 0, 1)
    if mode == 'harq' and not any(b['kind'] in {'mod_'+s for s in ('bpsk','qpsk','psk8','qam16','qam64','qam256')} for b in p['blocks']): raise ValueError('Chase 合并请选择 PSK / QAM 数字物理层。')
    events = []; rows = []; accepted = {}; clock = 0.; states = {}; confirmed = 0; last_program = None
    for packet in packets:
        combined = None; combined_count = 0; ack = False; first_delivery = None; start = clock; energy = 0.
        for attempt in range(retries+1):
            cancelled(cancel)
            seeds = np.random.SeedSequence([p['seed'], packet['sequence'], attempt, 4801]).spawn(2)
            seed = int(seeds[0].generate_state(1)[0])
            decoded, receiver, detail = run_packet(p, packet, seed, cancel, states, combined if mode == 'harq' else None)
            if detail['synchronization_pass']:
                if mode == 'harq' and receiver.combined is None: raise ValueError('该工程的接收机需要提供 PSK / QAM 解调软信息。')
                combined = receiver.combined; combined_count += 1
            last_program = detail.pop('program'); energy += detail['tx_energy']
            errors = int(np.count_nonzero(decoded[32:-16] != packet['payload'])); received = unpack_packet(decoded)
            valid = detail['synchronization_pass'] and received is not None and received[0] == packet['sequence'] and len(received[1]) == len(packet['payload'])
            duplicate = valid and packet['sequence'] in accepted
            begin = clock; clock += detail['duration_seconds']
            if valid and not duplicate: accepted[packet['sequence']] = received[1]; first_delivery = clock-start
            erased = bool(np.random.default_rng(seeds[1]).random() < loss); feedback = 'ACK' if valid else 'NACK'
            event = {'packet': packet['sequence'], 'attempt': attempt+1, 'start_seconds': begin, 'receive_seconds': clock,
                     'feedback': feedback, 'feedback_lost': erased, 'duplicate': duplicate, 'crc_pass': valid, 'bit_errors': errors,
                     'combined_transmissions': combined_count if mode == 'harq' else int(detail['synchronization_pass']),
                     'llr_mean_abs': float(np.mean(abs(combined))) if combined is not None else None, 'accumulated_tx_energy': energy, **detail}
            clock += timeout if erased else delay; event.update(end_seconds=clock, event='timeout' if erased else feedback); events.append(event)
            if valid and not erased: ack = True; confirmed += 1; break
        delivered = packet['sequence'] in accepted
        rows.append({'packet': packet['sequence'], 'bytes': len(packet['payload'])//8, 'attempts': attempt+1, 'retransmissions': attempt,
                     'delivered': delivered, 'confirmed': ack, 'delivery_latency_seconds': first_delivery, 'elapsed_seconds': clock-start,
                     'bit_errors': int(np.count_nonzero(accepted[packet['sequence']] != packet['payload'])) if delivered else errors})
        if progress: progress({'completed': len(rows), 'total': len(packets), 'frames': rows, 'events': events})
    original = np.concatenate([v['payload'] for v in packets]); restored = np.concatenate([accepted[i] for i in sorted(accepted)]) if accepted else np.array([], dtype=np.uint8)
    errors = sum(r['bit_errors'] for r in rows)
    return {'config': {**settings, 'phy': 'program', 'mode': mode, 'packet_bytes': size, 'packets': len(packets), 'seed': p['seed'],
                       'symbol_rate': p['symbol_rate'], 'actual_chain': ' → '.join(c.BLOCKS[b['kind']]['label'] for b in p['blocks']),
                       'noise_reference': '实际工程的信道与接收机参数', 'seed_policy': '按工程种子、包序号、发送次数配对信道与反馈随机流'},
            'source_program': p, 'actual_program': last_program, 'frames': rows, 'events': events, 'complete': True,
            'source_base64': base64.b64encode(np.packbits(original)).decode(), 'received_base64': base64.b64encode(np.packbits(restored)).decode(),
            'metrics': {'packets': len(rows), 'delivered_packets': len(accepted), 'confirmed_packets': confirmed,
                        'transmissions': len(events), 'retransmissions': len(events)-len(rows), 'packet_loss_rate': 1-len(accepted)/len(rows),
                        'elapsed_seconds': clock, 'goodput_bps': len(restored)/clock, 'bit_count': len(original), 'bit_errors': errors, 'ber': errors/len(original),
                        'mean_delivery_latency_seconds': float(np.mean([r['delivery_latency_seconds'] for r in rows if r['delivered']])) if accepted else None,
                        'delivered_bit_errors': sum(r['bit_errors'] for r in rows if r['delivered']),
                        'complete_payload': len(accepted) == len(packets) and np.array_equal(original, restored)}}


def adaptive_program(program, profile, coding, noise_id, snr):
    """Change an explicit MCS and selected noise input; retain the user PHY."""
    from src import communications as c
    p = copy.deepcopy(program); blocks = p['blocks']
    def make(kind, bid, params=None):
        return {'id': bid, 'kind': kind, 'params': {k: (params or {}).get(k, v['default']) for k,v in c.BLOCKS[kind]['params'].items()}}
    tx = next((b for b in blocks if b['kind'].startswith('mod_')), None)
    rx = next((b for b in blocks if b['kind'].startswith(('demod_','soft_'))), None)
    if tx is None or rx is None or tx['kind'][4:] not in ('bpsk','qpsk','psk8','qam16','qam64','qam256'): raise ValueError('AMC 需要配对的 PSK / QAM 调制解调器。')
    tx.update(make('mod_'+profile['scheme'], tx['id']))
    if coding == 'convolutional':
        encoders = [b for b in blocks if b['kind']=='conv_encode']
        if len(encoders)>1: raise ValueError('自适应卷积码模式使用一个卷积编码器。')
        blocks[:] = [b for b in blocks if b['kind'] not in ('puncture','depuncture')]
        if encoders:
            encoder = encoders[0]
            decoder = next(b for b in blocks if b['kind'] in ('conv_decode','conv_soft_decode'))
            outer = blocks[blocks.index(encoder)+1:blocks.index(tx)]
            if any(b['kind'] in c.ENCODERS and b['kind']!='interleave' for b in outer): raise ValueError('自适应卷积码后可接交织器，再进入调制器。')
        else:
            encoder = make('conv_encode', 'amc-conv-'+tx['id']); blocks.insert(blocks.index(tx), encoder)
            decoder = make('conv_soft_decode', 'amc-conv-'+rx['id']); blocks.insert(blocks.index(rx)+1, decoder)
        decoder.update(make('conv_soft_decode', decoder['id']))
        if profile['rate'] != 1:
            blocks.insert(blocks.index(encoder)+1, make('puncture', 'amc-puncture-'+encoder['id'], {'rate':profile['rate']}))
            blocks.insert(blocks.index(decoder), make('depuncture', 'amc-depuncture-'+decoder['id'], {'rate':profile['rate']}))
        rx.update(make('soft_'+profile['scheme'], rx['id'], {'noise_variance':max(.000001,min(100,10**(-snr/10)))}))
    else:
        rx.update(make(('soft_' if rx['kind'].startswith('soft_') else 'demod_')+profile['scheme'], rx['id'], rx['params']))
    noise = next(b for b in blocks if b['id']==noise_id)
    if noise['kind']=='ofdma_channel':
        values = [float(v.strip()) for v in noise['params']['snrs'].split(',')]
        noise['params']['snrs'] = ','.join(str(snr+value-values[0]) for value in values)
    else:
        parameter = 'esn0_db' if 'esn0_db' in noise['params'] else 'snr_db'
        noise['params'][parameter] = snr
    if any(b['kind']=='rx_noise_estimate' for b in blocks) and rx['kind'].startswith('soft_'): rx['params']['automatic_variance'] = True
    # Source bit counts are assigned to complete constellation words by packet_program.
    return c.normalize(p)


def program_amc(program, settings, progress=None, cancel=None):
    from src import communications as c
    p = c.build(program)['program']; size, _, packets = common(p, settings)
    count = c.numeric(settings.get('frames', 20), '帧数', 2, 100, True)
    coding = settings.get('coding', 'preserve')
    if coding not in ('preserve','convolutional'): raise ValueError('AMC 编码请选择 preserve 或 convolutional。')
    if coding=='convolutional' and any(b['kind']=='tx_ofdma' for b in p['blocks']): raise ValueError('OFDMA 多用户 AMC 使用保留工程编码模式，各用户按独立星座字传输。')
    candidates = [b for b in p['blocks'] if b['kind'] in c.CHANNELS and ('snr_db' in b['params'] or 'esn0_db' in b['params'] or b['kind']=='ofdma_channel')]
    noise_id = settings.get('noise_block_id')
    if noise_id is None and len(candidates)==1: noise_id = candidates[0]['id']
    noise = next((b for b in candidates if b['id']==noise_id), None)
    if noise is None: raise ValueError('请选择工程中具有 SNR / Es/N₀ 参数的噪声信道积木。')
    parameter = 'snrs' if noise['kind']=='ofdma_channel' else 'esn0_db' if 'esn0_db' in noise['params'] else 'snr_db'
    spec = c.BLOCKS[noise['kind']]['params'][parameter]
    if parameter=='snrs':
        values = [float(v.strip()) for v in noise['params']['snrs'].split(',')]
        spec = {'min':-100-min(v-values[0] for v in values), 'max':100-max(v-values[0] for v in values), 'label':'用户 0 SNR；各用户保持原有 SNR 差'}
    lo = c.numeric(settings.get('snr_start', 0), '起始信道 SNR', spec['min'], spec['max'])
    hi = c.numeric(settings.get('snr_stop', 24), '终止信道 SNR', spec['min'], spec['max'])
    delay = c.numeric(settings.get('feedback_delay', 2), '额外反馈延迟帧数', 0, 20, True)
    hysteresis = c.numeric(settings.get('hysteresis', 1), '切换滞回 / dB', 0, 10)
    profiles = copy.deepcopy(PROFILES if coding=='convolutional' else [PROFILES[i] for i in (0,1,3,4)])
    if coding=='preserve':
        for profile in profiles: profile.update(name=profile['scheme'].upper()+' · 工程编码', code_rate=None)
    profile_index = 0; rows = []; estimates = []; total_bits = total_errors = delivered = failed = switches = 0; elapsed = 0.; states = {}; actual = None
    for frame in range(count):
        cancelled(cancel)
        index = frame-delay-1; feedback = estimates[index] if index>=0 else None; previous = profile_index
        if feedback is not None:
            while profile_index+1<len(profiles) and feedback>=profiles[profile_index+1]['threshold_db']+hysteresis: profile_index += 1
            while profile_index>0 and feedback<profiles[profile_index]['threshold_db']-hysteresis: profile_index -= 1
        switches += int(previous!=profile_index); current = profiles[profile_index]; snr = lo+(hi-lo)*frame/(count-1)
        candidate = adaptive_program(p, current, coding, noise_id, snr)
        seed = int(np.random.SeedSequence([p['seed'], frame, 4802]).generate_state(1)[0]); packet = packets[frame%len(packets)]
        decoded, receiver, detail = run_packet(candidate, packet, seed, cancel, states)
        if receiver.snr_db is None: raise ValueError('AMC 反馈需要 PSK / QAM 接收软信息。')
        estimates.append(receiver.snr_db if detail['synchronization_pass'] else None); actual = detail.pop('program'); received = unpack_packet(decoded)
        valid = detail['synchronization_pass'] and received is not None and received[0]==packet['sequence'] and len(received[1])==len(packet['payload'])
        bits = len(packet['payload']); errors = int(np.count_nonzero(decoded[32:-16]!=packet['payload'])); duration = detail['duration_seconds']
        total_bits += bits; total_errors += errors; delivered += bits if valid else 0; failed += int(not valid); elapsed += duration
        rows.append({'frame':frame+1,'snr_db':snr,'feedback_snr_db':feedback,'profile':current['name'],'profile_index':profile_index,
                     'scheme':current['scheme'],'bit_errors':errors,'bit_count':bits,'ber':errors/bits,'crc_pass':valid,
                     'goodput_bps':bits/duration if valid else 0., **detail})
        if progress: progress({'completed':len(rows),'total':count,'frames':rows})
    return {'config':{**settings,'phy':'program','coding':coding,'seed':p['seed'],'packet_bytes':size,'profiles':profiles,
                      'noise_block_id':noise_id,'noise_parameter':parameter,'symbol_rate':p['symbol_rate'],
                      'actual_chain':' → '.join(c.BLOCKS[b['kind']]['label'] for b in actual['blocks']),
                      'feedback_timing':'实际接收测量在下一帧可用，再增加配置的反馈延迟帧数',
                      'snr_reference':c.BLOCKS[noise['kind']]['label']+' · '+spec['label'],
                      'seed_policy':'按工程种子与帧序号配对实际链路随机流'},
            'source_program':p,'actual_program':actual,'frames':rows,'complete':True,
            'metrics':{'frames':count,'bit_count':total_bits,'bit_errors':total_errors,'ber':total_errors/total_bits,'fer':failed/count,
                       'goodput_bps':delivered/elapsed,'elapsed_seconds':elapsed,'profile_switches':switches}}
