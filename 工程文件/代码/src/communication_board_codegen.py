"""Translate a checked linear Scratch program to a standalone RP2040 project."""
import hashlib
import json
from pathlib import Path

from src import communications, communication_runtime, communication_studio
from src.communication_workbench_v0412 import build_document, diagnose


TEMPLATES = Path(__file__).with_name('board_templates')
BOARDS = ('pico', 'pico_w')
LANGUAGES = ('cpp', 'micropython')
KINDS = {'bit_pattern', 'repeat_encode', 'mod_bpsk', 'ideal', 'demod_bpsk',
         'uart_loopback', 'repeat_decode', 'sink'}
MAX_SAMPLES = 2048


class BoardCodeError(ValueError):
    def __init__(self, message, block_ids=()):
        super().__init__(message)
        self.block_ids = list(block_ids)


def _cpp_block(block):
    kind, params = block['kind'], block['params']
    trace = f'trace(nonce, "{block["id"]}", data);'
    if kind == 'bit_pattern':
        return ['data.clear();',
                f'for (char bit : std::string("{params["pattern"]}")) data.push_back(bit - \'0\');',
                'reference.insert(reference.end(), data.begin(), data.end());',
                trace, 'data = reference;']
    if kind == 'repeat_encode':
        return ['Samples encoded;', f'encoded.reserve(data.size() * {params["factor"]});',
                f'for (int8_t bit : data) encoded.insert(encoded.end(), {params["factor"]}, bit);',
                'data.swap(encoded);', trace]
    if kind == 'mod_bpsk':
        return ['for (int8_t &bit : data) bit = 1 - 2 * bit;', trace]
    if kind == 'ideal':
        return ['// An ideal channel preserves every transmitted symbol.', trace]
    if kind == 'uart_loopback':
        return [f'if (!uart_loopback(data, {params["baudrate"]}, {params["timeout_ms"]})) {{',
                '    finish(nonce, false, reference, data);', '    return;', '}', trace]
    if kind == 'demod_bpsk':
        return ['for (int8_t &symbol : data) symbol = (symbol < 0);', trace]
    if kind == 'repeat_decode':
        factor = params['factor']
        return [f'for (size_t start = 0; start < data.size(); start += {factor}) {{',
                '    unsigned ones = 0;',
                f'    for (size_t i = 0; i < {factor}; ++i) ones += data[start + i];',
                f'    data[start / {factor}] = ones > {factor // 2};', '}',
                f'data.resize(data.size() / {factor});', trace]
    if kind == 'sink':
        return [trace, 'finish(nonce, true, reference, data);']
    raise BoardCodeError('请选择已适配的板端积木。', [block['id']])


def _python_block(block):
    kind, params = block['kind'], block['params']
    trace = f'trace(nonce, "{block["id"]}", data)'
    if kind == 'bit_pattern':
        return [f'data = [int(bit) for bit in "{params["pattern"]}"]',
                'reference.extend(data)', trace, 'data = reference']
    if kind == 'repeat_encode':
        return [f'data = [bit for bit in data for _ in range({params["factor"]})]', trace]
    if kind == 'mod_bpsk':
        return ['data = [1 - 2 * bit for bit in data]', trace]
    if kind == 'ideal':
        return ['# An ideal channel preserves every transmitted symbol.', trace]
    if kind == 'uart_loopback':
        return [f'data = uart_loopback(data, {params["baudrate"]}, {params["timeout_ms"]})',
                'if data is None:', '    finish(nonce, False, reference, [])', '    return', trace]
    if kind == 'demod_bpsk':
        return ['data = [int(symbol < 0) for symbol in data]', trace]
    if kind == 'repeat_decode':
        factor = params['factor']
        return [f'data = [int(sum(data[i:i + {factor}]) > {factor // 2})',
                f'        for i in range(0, len(data), {factor})]', trace]
    if kind == 'sink':
        return [trace, 'finish(nonce, True, reference, data)']
    raise BoardCodeError('请选择已适配的板端积木。', [block['id']])


def _source(blocks, board, language, experiment):
    cpp = language == 'cpp'
    entry = 'main.cpp' if cpp else 'main.py'
    template = (TEMPLATES / (entry + '.in')).read_text(encoding='utf-8')
    helpers = ''
    if experiment == 'uart':
        helper = 'uart.cpp.in' if cpp else 'uart.py.in'
        helpers = (TEMPLATES / helper).read_text(encoding='utf-8').rstrip() + '\n\n'
    template = template.replace('@UART_HELPER@', helpers).replace('@BOARD@', board).replace('@EXPERIMENT@', experiment)
    prefix, suffix = template.split('@PROGRAM@\n')
    lines = prefix.splitlines()
    source_map = {}
    for block in blocks:
        start = len(lines) + 1
        if cpp:
            lines.append(f'    {{ // {block["kind"]} [{block["id"]}]')
            lines.extend('        ' + s for s in _cpp_block(block))
            lines.append('    }')
        else:
            lines.append(f'    # {block["kind"]} [{block["id"]}]')
            lines.extend('    ' + s for s in _python_block(block))
        source_map[block['id']] = {'file': entry, 'start': start, 'end': len(lines)}
    files = {entry: '\n'.join(lines) + '\n' + suffix}
    if cpp:
        cmake = (TEMPLATES / 'CMakeLists.txt.in').read_text(encoding='utf-8')
        files['CMakeLists.txt'] = cmake.replace('@BOARD@', board)
    return files, source_map, entry


def _checked(document):
    try:
        return build_document(document)
    except ValueError as exc:
        ids = []
        raw = document if isinstance(document, dict) else {}
        program = raw.get('program', raw)
        if not raw.get('graph') and isinstance(program, dict) and program.get('blocks'):
            try:
                # Structural errors from Build include the exact position, even for
                # repeated copies of the same block. Parameter errors use its ID.
                if str(exc).startswith('第 '):
                    error = communication_studio.describe(program)['error']
                    ids = [error['id']]
                else:
                    check = {'document_schema': 2, 'program': {**communications.CONFIG['defaults'], **program}}
                    ids = [issue['node'].removeprefix('linear/') for issue in diagnose(check)['issues']
                           if issue['node']]
            except (ValueError, TypeError, KeyError, AttributeError, IndexError):
                # A malformed input may have no canvas node to focus.
                pass
        raise BoardCodeError(str(exc), ids) from exc


def generate(document, language, board):
    """Return printable sources and line spans with a reference from the desktop engine."""
    if language not in LANGUAGES or board not in BOARDS:
        raise BoardCodeError('请选择 C++ 或 MicroPython，以及 Pico 或 Pico W。')
    built = _checked(document)
    if built['kind'] != 'linear':
        raise BoardCodeError('板端生成支持线性链路，请选择线性工程。', ['merge'])
    compiled = built['built']
    blocks = compiled['program']['blocks']
    unsupported = [b for b in blocks if b['kind'] not in KINDS]
    if unsupported:
        labels = dict.fromkeys(communications.BLOCKS[b['kind']]['label'] for b in unsupported)
        raise BoardCodeError('这些积木目前仅支持电脑仿真：' + '、'.join(labels),
                             [b['id'] for b in unsupported])
    large = [r['id'] for r in compiled['plan'] if r['count'] > MAX_SAMPLES]
    if large:
        raise BoardCodeError(f'板端每个积木最多输出 {MAX_SAMPLES} 个数据，请缩短信源或降低重复次数。', large)
    experiment = 'uart' if any(b['kind'] == 'uart_loopback' for b in blocks) else 'bpsk'
    files, source_map, entry = _source(blocks, board, language, experiment)
    # Hash the complete generated project before substituting its own identity.
    packed = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    artifact_id = hashlib.sha256(packed).hexdigest()
    files[entry] = files[entry].replace('@ARTIFACT@', artifact_id)
    result, observer = communication_runtime.observe_run(compiled['program'], compiled['token'], retain=True)
    nodes = {b['id']: observer.values[b['id']].real.astype(int).tolist() for b in blocks}
    measured = result['metrics']
    metrics = {'compared_bits': measured['bit_count'], 'bit_errors': measured['bit_errors'],
               'ber': measured['ber'], 'expected_frames': 1, 'received_frames': 1, 'lost_frames': 0}
    steps = [{'id': b['id'], 'kind': b['kind'], 'label': communications.BLOCKS[b['kind']]['label']}
             for b in blocks]
    return {'files': files, 'entry_file': entry, 'source_map': source_map, 'steps': steps,
            'expected': {'nodes': nodes, 'metrics': metrics}, 'experiment': experiment,
            'artifact_id': artifact_id, 'board': board, 'language': language,
            'host_tools': [tool['id'] for tool in built['document']['tools']]}
