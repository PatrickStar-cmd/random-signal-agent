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
    bits, _, _ = c.source_data(program)
    if not np.issubdtype(bits.dtype, np.integer) or np.any((bits != 0) & (bits != 1)):
        raise ValueError('包级实验需要数字信源，请先选用比特、文字、图片或文件信源。')
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
