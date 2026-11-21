"""Desktop reference for the UART experiment, with the board's byte packing order."""
import numpy as np

from src import communication_runtime as runtime


def reference_run(compiled, source, source_count):
    from src.communications import CONFIG

    program = compiled['program']
    data = source.copy()
    for block in program['blocks'][source_count:]:
        runtime.enter(block)
        kind = block['kind']
        params = block['params']
        if kind == 'repeat_encode':
            data = np.repeat(data, params['factor'])
        elif kind == 'uart_loopback':
            sent = data.copy()
            packed = np.packbits(sent, bitorder='big')
            data = np.unpackbits(packed, count=len(sent), bitorder='big')
            baudrate = params['baudrate']
        elif kind == 'repeat_decode':
            factor = params['factor']
            data = (data.reshape(-1, factor).sum(axis=1) > factor // 2).astype(np.uint8)
        data = runtime.record(block, data)
        if kind == 'uart_loopback':
            received = data.copy()

    errors = int(np.count_nonzero(source != data))
    coded_errors = int(np.count_nonzero(sent != received))
    peek = received[:CONFIG['plot_points']].tolist()
    return {
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
        'constellation': None, 'text': None,
    }
