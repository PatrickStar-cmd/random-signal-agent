"""Desktop reference for the UART experiment, with the board's byte packing order."""
import numpy as np

from src import communication_runtime as runtime


def reference_run(compiled, source, texts, source_count):
    from src.communications import CONFIG, decode_hamming_frame, flip_hamming_bit, hamming_encode

    program = compiled['program']
    data = source.copy()
    hamming_lengths = []
    node_details = {}
    link = None
    corrections = 0
    for block in program['blocks'][source_count:]:
        runtime.enter(block)
        kind = block['kind']
        params = block['params']
        if kind == 'repeat_encode':
            data = np.repeat(data, params['factor'])
        elif kind == 'hamming_encode':
            hamming_lengths.append(len(data))
            data = hamming_encode(data)
        elif kind in ('uart_loopback', 'uart_link'):
            sent = data.copy()
            packed = np.packbits(sent, bitorder='big')
            baudrate = params['baudrate']
            if kind == 'uart_link':
                from src.communication_board_link import encode_frame, decode_frame
                wire = encode_frame(sent, 0)
                data = decode_frame(wire, 0)
                link = {'sequence': 0, 'valid_bits': len(data), 'crc16': int.from_bytes(wire[-2:], 'big'),
                        'wire_bytes': list(wire)}
            else:
                data = np.unpackbits(packed, count=len(sent), bitorder='big')
        elif kind == 'repeat_decode':
            factor = params['factor']
            data = (data.reshape(-1, factor).sum(axis=1) > factor // 2).astype(np.uint8)
        elif kind == 'bit_flip':
            data, node_details[block['id']] = flip_hamming_bit(data, params)
        elif kind == 'hamming_decode':
            data, n, node_details[block['id']] = decode_hamming_frame(data, hamming_lengths.pop())
            corrections += n
        data = runtime.record(block, data)
        if kind in ('uart_loopback', 'uart_link'):
            received = data.copy()

    errors = int(np.count_nonzero(source != data))
    coded_errors = int(np.count_nonzero(sent != received))
    peek = received[:CONFIG['plot_points']].tolist()
    text = None
    if len(texts) == source_count:
        text = {'sent': b''.join(texts).decode('utf-8'),
                'received': np.packbits(data, bitorder='big').tobytes().decode('utf-8', errors='replace')}
    result = {
        'token': compiled['token'], 'seed': program['seed'], 'model': compiled['model'],
        'transport': 'uart', 'summary': compiled['summary'], 'plan': compiled['plan'],
        'metrics': {'bit_count': len(source), 'bit_errors': errors, 'ber': errors / len(source),
                    'coded_bit_count': len(sent), 'coded_bit_errors': coded_errors,
                    'coded_ber': coded_errors / len(sent), 'effective_rate': len(source) / len(sent),
                    'expected_frames': 1, 'received_frames': 1, 'lost_frames': 0},
        'uart': {'baudrate': baudrate, 'packed_bytes': packed.tolist(), 'valid_bits': len(sent)},
        'sink': {'kind': 'digital', 'values': data.tolist(), 'reference': source.tolist(),
                 'sample_rate': None, 'count': len(data), 'plot_count': min(len(data), CONFIG['plot_points'])},
        'channel': {'count': len(received), 'plot_count': len(peek), 'i': peek, 'q': [0] * len(peek)},
        'constellation': None, 'text': text,
    }
    if link is not None:
        result['uart']['frame'] = link
    if node_details:
        result['node_details'] = node_details
        result['metrics']['hamming_syndromes'] = corrections
    return result
