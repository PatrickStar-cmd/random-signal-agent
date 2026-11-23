"""Translate a checked linear Scratch program to a standalone RP2040 project."""
import hashlib
import json
from pathlib import Path

from src import communications, communication_runtime, communication_studio
from src.communication_workbench_v0412 import build_document, diagnose


TEMPLATES = Path(__file__).with_name('board_templates')
ESP32 = 'esp32s3'
BOARDS = ('pico', 'pico_w', ESP32)
LANGUAGES = ('cpp', 'micropython')
KINDS = {'bit_pattern', 'text', 'pn_bits', 'repeat_encode', 'hamming_encode', 'mod_bpsk',
         'mod_qpsk', 'ideal', 'demod_bpsk', 'demod_qpsk', 'uart_loopback', 'uart_link', 'bit_flip',
         'repeat_decode', 'hamming_decode', 'sink'}
MAX_SAMPLES = 2048


class BoardCodeError(ValueError):
    def __init__(self, message, block_ids=()):
        super().__init__(message)
        self.block_ids = list(block_ids)


def _cpp_block(block, count, fmt):
    kind, params = block['kind'], block['params']
    trace = f'trace(nonce, "{block["id"]}", data);'
    if kind in ('bit_pattern', 'text', 'pn_bits'):
        source = ['data.clear();']
        if kind == 'bit_pattern':
            source.append(f'for (char bit : std::string("{params["pattern"]}")) data.push_back(bit - \'0\');')
        elif kind == 'text':
            payload = ', '.join(f'0x{b:02x}' for b in params['text'].encode('utf-8'))
            source.extend([f'const uint8_t utf8[] = {{{payload}}};',
                           'for (uint8_t byte : utf8) {',
                           '    for (int shift = 7; shift >= 0; --shift) data.push_back((byte >> shift) & 1);', '}'])
        else:
            tap = 4 if params['degree'] == 9 else 1
            source.extend([f'unsigned state = {params["initial"]};',
                           f'for (unsigned n = 0; n < {params["count"]}; ++n) {{',
                           '    data.push_back(state & 1u);',
                           f'    unsigned feedback = (state ^ (state >> {tap})) & 1u;',
                           f'    state = (state >> 1) | (feedback << {params["degree"] - 1});', '}'])
        return source + ['reference.insert(reference.end(), data.begin(), data.end());', trace, 'data = reference;']
    if kind == 'repeat_encode':
        return ['Samples encoded;', f'encoded.reserve(data.size() * {params["factor"]});',
                f'for (int8_t bit : data) encoded.insert(encoded.end(), {params["factor"]}, bit);',
                'data.swap(encoded);', trace]
    if kind == 'mod_bpsk':
        return ['for (int8_t &bit : data) bit = 1 - 2 * bit;', trace]
    if kind == 'hamming_encode':
        return ['data.resize(((data.size() + 3) / 4) * 4, 0);', 'Samples encoded;',
                'for (size_t i = 0; i < data.size(); i += 4) {',
                '    int a = data[i], b = data[i+1], c = data[i+2], d = data[i+3];',
                '    for (int bit : {a^b^d, a^c^d, a, b^c^d, b, c, d}) encoded.push_back(bit);',
                '}', 'data.swap(encoded);', trace]
    if kind == 'mod_qpsk':
        return ['// First bit selects I, second bit selects Q. Es = 1.',
                'constexpr float axis = 0.7071067811865475f;',
                'for (size_t i = 0; i < data.size(); i += 2) {',
                '    int qbit = i + 1 < data.size() ? data[i+1] : 0;',
                '    iq.push_back({axis * (1 - 2 * data[i]), axis * (1 - 2 * qbit)});',
                '}', trace.replace(', data);', ', iq);')]
    if kind == 'ideal':
        return ['// An ideal channel preserves every transmitted symbol.',
                trace.replace(', data);', ', iq);') if fmt == 'iq' else trace]
    if kind == 'uart_loopback':
        return [f'if (!uart_loopback(data, {params["baudrate"]}, {params["timeout_ms"]})) {{',
                '    finish(nonce, false, reference, data);', '    return;', '}', trace]
    if kind == 'demod_bpsk':
        return ['for (int8_t &symbol : data) symbol = (symbol < 0);', trace]
    if kind == 'demod_qpsk':
        return ['data.clear();', 'for (const IQ &s : iq) {',
                '    data.push_back(s.i < 0);', '    data.push_back(s.q < 0);', '}',
                f'data.resize({count}); // Remove constellation padding.', trace]
    if kind == 'bit_flip':
        return [f'data[7 * ({params["codeword"]} - 1) + ({params["position"]} - 1)] ^= 1;', trace]
    if kind == 'hamming_decode':
        return ['Samples decoded, syndromes;', 'for (size_t i = 0; i < data.size(); i += 7) {',
                '    unsigned s = 0;',
                '    for (unsigned p = 1; p <= 7; ++p) if (data[i+p-1]) s ^= p;',
                '    syndromes.push_back(s);', '    if (s) data[i+s-1] ^= 1;',
                '    for (unsigned p : {3, 5, 6, 7}) decoded.push_back(data[i+p-1]);',
                '}', f'decoded.resize({count}); // Remove data padding.', 'data.swap(decoded);',
                trace.replace(', data);', ', data, syndromes);')]
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


def _python_block(block, count, fmt):
    kind, params = block['kind'], block['params']
    trace = f'trace(nonce, "{block["id"]}", data)'
    if kind in ('bit_pattern', 'text', 'pn_bits'):
        if kind == 'bit_pattern':
            source = [f'data = [int(bit) for bit in "{params["pattern"]}"]']
        elif kind == 'text':
            payload = ', '.join(f'0x{b:02x}' for b in params['text'].encode('utf-8'))
            source = [f'utf8 = bytes([{payload}])',
                      'data = [(byte >> shift) & 1 for byte in utf8 for shift in range(7, -1, -1)]']
        else:
            tap = 4 if params['degree'] == 9 else 1
            source = ['data = []', f'state = {params["initial"]}', f'for n in range({params["count"]}):',
                      '    data.append(state & 1)', f'    feedback = (state ^ (state >> {tap})) & 1',
                      f'    state = (state >> 1) | (feedback << {params["degree"] - 1})']
        return source + ['reference.extend(data)', trace, 'data = reference']
    if kind == 'repeat_encode':
        return [f'data = [bit for bit in data for _ in range({params["factor"]})]', trace]
    if kind == 'mod_bpsk':
        return ['data = [1 - 2 * bit for bit in data]', trace]
    if kind == 'hamming_encode':
        return ['padded = data + [0] * (-len(data) % 4)', 'data = []',
                'for i in range(0, len(padded), 4):',
                '    a, b, c, d = padded[i:i+4]',
                '    data.extend((a^b^d, a^c^d, a, b^c^d, b, c, d))', trace]
    if kind == 'mod_qpsk':
        return ['from array import array', 'iq = array("f")', 'axis = 0.7071067811865475',
                'for i in range(0, len(data), 2):',
                '    qbit = data[i+1] if i+1 < len(data) else 0',
                '    iq.append(axis * (1 - 2 * data[i]))', '    iq.append(axis * (1 - 2 * qbit))',
                trace.replace('trace(', 'trace_iq(').replace(', data)', ', iq)')]
    if kind == 'ideal':
        return ['# An ideal channel preserves every transmitted symbol.',
                trace.replace('trace(', 'trace_iq(').replace(', data)', ', iq)') if fmt == 'iq' else trace]
    if kind == 'uart_loopback':
        return [f'data = uart_loopback(data, {params["baudrate"]}, {params["timeout_ms"]})',
                'if data is None:', '    finish(nonce, False, reference, [])', '    return', trace]
    if kind == 'demod_bpsk':
        return ['data = [int(symbol < 0) for symbol in data]', trace]
    if kind == 'demod_qpsk':
        return ['data = [int(axis < 0) for axis in iq]', f'del data[{count}:]  # Remove constellation padding.', trace]
    if kind == 'bit_flip':
        return ['data = data[:]', f'data[7 * ({params["codeword"]} - 1) + ({params["position"]} - 1)] ^= 1', trace]
    if kind == 'hamming_decode':
        return ['decoded = []', 'syndromes = []', 'for i in range(0, len(data), 7):',
                '    word = data[i:i+7]', '    s = 0', '    for p in range(1, 8):',
                '        if word[p-1]: s ^= p', '    syndromes.append(s)', '    if s: word[s-1] ^= 1',
                '    decoded.extend((word[2], word[4], word[5], word[6]))',
                f'data = decoded[:{count}]  # Remove data padding.',
                f'send({{"type": "node", "nonce": nonce, "id": "{block["id"]}", "values": data, "syndromes": syndromes}})']
    if kind == 'repeat_decode':
        factor = params['factor']
        return [f'data = [int(sum(data[i:i + {factor}]) > {factor // 2})',
                f'        for i in range(0, len(data), {factor})]', trace]
    if kind == 'sink':
        return [trace, 'finish(nonce, True, reference, data)']
    raise BoardCodeError('请选择已适配的板端积木。', [block['id']])


def _link_block(block, count, language, role):
    cpp = language == 'cpp'
    key = block['id']
    if block['kind'] == 'sink':
        return ([f'trace(nonce, "{key}", data);', 'endpoint_event(nonce, "done", "ok");'] if cpp else
                [f'trace(nonce, "{key}", data)', 'endpoint_event(nonce, "done", "ok")'])
    baud, timeout = (block['params'][k] for k in ('baudrate', 'timeout_ms'))
    if cpp:
        lines = [f'link_open({baud});']
        if role == 'tx':
            return lines + ['transmit_frame(data, frame_seq(nonce));', f'trace(nonce, "{key}", data);',
                            'endpoint_event(nonce, "done", "ok");']
        return lines + ['endpoint_event(nonce, "ready", "ready");',
                        f'const char *status = receive_frame(data, nonce, {count}, {timeout});',
                        'if (std::strcmp(status, "ok")) { endpoint_event(nonce, "done", status); return; }',
                        f'trace(nonce, "{key}", data);']
    lines = [f'port = open_link({baud}, {timeout})']
    if role == 'tx':
        return lines + ['transmit_frame(port, data, int(nonce[-4:], 16))', f'trace(nonce, "{key}", data)',
                        'endpoint_event(nonce, "done", "ok")']
    return lines + ['endpoint_event(nonce, "ready", "ready")',
                    f'status, data = receive_frame(port, nonce, {count})',
                    'if status != "ok":', '    endpoint_event(nonce, "done", status)', '    return',
                    f'trace(nonce, "{key}", data)']


def _source(blocks, plan, formats, board, language, experiment, role=None):
    cpp = language == 'cpp'
    esp = board == ESP32
    filename = 'main.cpp' if cpp else 'main.py'
    entry = 'main/main.cpp' if cpp and esp else filename
    extension = '.cpp.in' if cpp else '.py.in'
    template = (TEMPLATES / (filename + '.in')).read_text(encoding='utf-8')
    before, single_finish, after = template.split('@SINGLE_ONLY@\n')
    template = before + ('' if role else single_finish) + after
    files = {}
    if cpp and esp:
        files['main/esp_console.hpp'] = (TEMPLATES / 'esp_console.hpp.in').read_text(encoding='utf-8')
    kinds = {b['kind'] for b in blocks}
    helpers = ''
    if cpp and (role or esp and 'uart_loopback' in kinds):
        driver = 'esp_uart.hpp.in' if esp else 'pico_uart.hpp.in'
        files[Path(entry).with_name('board_uart.hpp').as_posix()] = (TEMPLATES / driver).read_text(encoding='utf-8')
        helpers += '#include "board_uart.hpp"\n'
    for kind, helper in [('uart_loopback', 'esp_loopback' if esp and cpp else 'uart'), ('uart_link', 'link'),
                         ('mod_qpsk', 'qpsk'), ('hamming_decode', 'hamming')]:
        if kind in kinds and (cpp or helper != 'hamming'):
            code = (TEMPLATES / (helper + extension)).read_text(encoding='utf-8').rstrip()
            if helper == 'link':
                common, sender, receiver = code.split('@DIRECTION@\n')
                code = common + (sender if role == 'tx' else receiver).rstrip()
            helpers += code + '\n\n'
    if cpp:
        valid_nonce = ('valid && std::strlen(nonce) >= 4 && std::strspn(nonce, "0123456789abcdefABCDEF") == std::strlen(nonce)'
                       if role else 'valid')
    else:
        valid_nonce = ('4 <= len(nonce) <= 32 and all(c in "0123456789abcdefABCDEF" for c in nonce)' if role else
                       '1 <= len(nonce) <= 32 and all(c in NONCE_CHARS for c in nonce)')
    substitutions = {'UART_HELPER': helpers, 'PLATFORM': 'ESP32-S3' if esp else 'Pico', 'BOARD': board,
                     'EXPERIMENT': experiment, 'ROLE': role or '', 'VALID_NONCE': valid_nonce,
                     'PLATFORM_INCLUDES': '#include "esp_console.hpp"' if esp else '#include "pico/stdlib.h"\n#include "hardware/uart.h"',
                     'MAIN': 'extern "C" void app_main()' if esp else 'int main()',
                     'CONSOLE_INIT': 'start_console()' if esp else 'stdio_init_all()',
                     'MAIN_RETURN': 'return' if esp else 'return 0', 'UART': '1' if esp else '0',
                     'TX': '17' if esp else '0', 'RX': '18' if esp else '1',
                     'WIRE_PINS': 'GPIO17 to GPIO18' if esp else 'GP0 to GP1'}
    for key, value in substitutions.items():
        template = template.replace('@'+key+'@', value)
    prefix, suffix = template.split('@PROGRAM@\n')
    if cpp and 'mod_qpsk' in kinds:
        prefix += '    std::vector<IQ> iq;\n'
    lines = prefix.splitlines()
    source_map = {}
    for block, row in zip(blocks, plan, strict=True):
        start = len(lines) + 1
        if role and block['kind'] in ('uart_link', 'sink'):
            body = _link_block(block, row['count'], language, role)
        else:
            emitter = _cpp_block if cpp else _python_block
            body = emitter(block, row['count'], formats[block['id']])
        if cpp:
            lines.append(f'    {{ // {block["kind"]} [{block["id"]}]')
            lines.extend('        ' + s for s in body)
            lines.append('    }')
        else:
            lines.append(f'    # {block["kind"]} [{block["id"]}]')
            lines.extend('    ' + s for s in body)
        source_map[block['id']] = {'file': entry, 'start': start, 'end': len(lines)}
    files[entry] = '\n'.join(lines) + '\n' + suffix
    if cpp and esp:
        files['CMakeLists.txt'] = ('cmake_minimum_required(VERSION 3.16)\nset(IDF_TARGET esp32s3)\n'
                                   'set(COMPONENTS main)\ninclude($ENV{IDF_PATH}/tools/cmake/project.cmake)\nproject(randomsign_board)\n')
        files['main/CMakeLists.txt'] = 'idf_component_register(SRCS "main.cpp" INCLUDE_DIRS "." REQUIRES esp_driver_uart esp_driver_gpio vfs)\n'
        files['sdkconfig.defaults'] = 'CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y\nCONFIG_ESP_CONSOLE_UART_DEFAULT=y\nCONFIG_ESP_MAIN_TASK_STACK_SIZE=8192\n'
    elif cpp:
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


def generate(document, language, board, targets=None):
    """Return printable sources and line spans with a reference from the desktop engine."""
    if language not in LANGUAGES or board not in BOARDS:
        raise BoardCodeError('请选择支持的开发板和编程语言。')
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
    kinds = {b['kind'] for b in blocks}
    experiment = 'uart' if 'uart_loopback' in kinds else 'qpsk' if 'mod_qpsk' in kinds else 'bpsk'
    symbol_format = 'iq' if experiment == 'qpsk' else 'bpsk'
    formats = {b['id']: symbol_format if b['kind'] in ('mod_bpsk', 'mod_qpsk', 'ideal') else 'bits'
               for b in blocks}
    result, observer = communication_runtime.observe_run(compiled['program'], compiled['token'], retain=True)
    nodes = {}
    for block_id, fmt in formats.items():
        values = observer.values[block_id]
        nodes[block_id] = ([[float(v.real), float(v.imag)] for v in values] if fmt == 'iq' else
                           values.real.astype(int).tolist())
    syndromes = {key: detail['syndromes'] for key, detail in result.get('node_details', {}).items()
                 if 'syndromes' in detail}
    measured = result['metrics']
    metrics = {'compared_bits': measured['bit_count'], 'bit_errors': measured['bit_errors'],
               'ber': measured['ber'], 'expected_frames': 1, 'received_frames': 1, 'lost_frames': 0}
    steps = [{'id': b['id'], 'kind': b['kind'], 'label': communications.BLOCKS[b['kind']]['label'],
              'format': formats[b['id']], **(b['params'] if b['kind'] == 'bit_flip' else {})}
             for b in blocks]
    common = {'steps': steps, 'expected': {'nodes': nodes, 'syndromes': syndromes, 'metrics': metrics},
              'host_tools': [tool['id'] for tool in built['document']['tools']]}
    if 'uart_link' not in kinds:
        return {**common, **_project(blocks, compiled['plan'], formats, board, language, experiment)}
    if not isinstance(targets, dict):
        raise BoardCodeError('请分别选择发送端和接收端的板型与语言。')
    split = next(i for i, b in enumerate(blocks) if b['kind'] == 'uart_link')
    endpoints, files, ranges = {}, {}, {}
    for role, section in [('tx', slice(None, split+1)), ('rx', slice(split, None))]:
        choice = targets.get(role)
        if not isinstance(choice, dict) or choice.get('board') not in BOARDS or choice.get('language') not in LANGUAGES:
            raise BoardCodeError('请选择两个端点的板型与语言。')
        ep = _project(blocks[section], compiled['plan'][section], formats, choice['board'], choice['language'], 'link', role)
        ep['role'] = role
        ep['steps'] = steps[section]
        ep['expected'] = {'nodes': {s['id']: nodes[s['id']] for s in ep['steps']},
                          'syndromes': {k: v for k, v in syndromes.items() if k in ep['source_map']}}
        endpoints[role] = ep
        files.update({role+'/'+name: contents for name, contents in ep['files'].items()})
        ranges.update({k: {**span, 'file': role+'/'+span['file']} for k, span in ep['source_map'].items()})
    key = hashlib.sha256(''.join(ep['artifact_id'] for ep in endpoints.values()).encode()).hexdigest()
    return {**common, 'experiment': 'link', 'endpoints': endpoints, 'files': files, 'source_map': ranges,
            'entry_file': 'tx/'+endpoints['tx']['entry_file'], 'artifact_id': key,
            'frame': result['uart']['frame'], 'bridge': blocks[split]['id']}


def _project(blocks, plan, formats, board, language, experiment, role=None):
    files, source_map, entry = _source(blocks, plan, formats, board, language, experiment, role)
    packed = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    artifact_id = hashlib.sha256(packed).hexdigest()
    files[entry] = files[entry].replace('@ARTIFACT@', artifact_id)
    return {'files': files, 'source_map': source_map, 'entry_file': entry, 'artifact_id': artifact_id,
            'board': board, 'language': language, 'experiment': experiment}
