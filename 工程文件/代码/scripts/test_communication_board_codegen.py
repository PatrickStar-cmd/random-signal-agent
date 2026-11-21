"""Run generated programs with a desktop USB stream and a controllable UART peer."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import communications as c
from src import communication_graph_v0411 as graph
from src.communication_board_codegen import BoardCodeError, generate


class Pin:
    IN = PULL_UP = 1

    def __init__(self, number, *unused):
        self.number = number


class UartPeer:
    """Expose the actual bytes written by generated code, with optional wire faults."""
    def __init__(self, mode):
        self.mode = mode
        self.wire = []

    def open(self, peripheral, *, baudrate, bits, parity, stop, tx, rx, timeout):
        self.config = (peripheral, baudrate, bits, parity, stop, tx.number, rx.number, timeout)
        return self

    def any(self):
        return 0

    def write(self, data):
        self.wire.extend(data)

    def read(self, count):
        if self.mode == 'unplugged':
            return None
        byte = self.wire[-1]
        return bytes([byte ^ 0xff if self.mode == 'inverted' else byte])


def command(artifact):
    target = 'RUN ' + artifact['artifact_id']
    return 'RUN other stale\n' + target + ' not-valid\n' + target + ' TestNonce7\n'


def parse(output):
    return [json.loads(line.removeprefix('RS050 ')) for line in output.splitlines()]


def python_records(artifact, peer):
    namespace = {'__name__': 'board_test'}
    exec(compile(artifact['files']['main.py'], 'main.py', 'exec'), namespace)
    console = io.StringIO()
    with patch.dict(sys.modules, machine=SimpleNamespace(Pin=Pin, UART=peer.open)), \
         patch('sys.stdin', io.StringIO(command(artifact))), contextlib.redirect_stdout(console):
        namespace['serve']()
    return parse(console.getvalue())


CPP_UART = """
#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstring>
constexpr int uart0 = 0, GPIO_FUNC_UART = 0, UART_PARITY_NONE = 0;
inline unsigned char wire_byte;
inline void uart_init(int, unsigned) {}
inline void gpio_set_function(int, int) {}
inline void gpio_pull_up(int) {}
inline void uart_set_format(int, int, int, int) {}
inline bool uart_is_readable(int) { return false; }
inline void uart_write_blocking(int, const uint8_t *bytes, unsigned) { wire_byte = bytes[0]; }
inline bool uart_is_readable_within_us(int, unsigned) {
    return std::strcmp(std::getenv("UART_MODE"), "unplugged") != 0;
}
inline char uart_getc(int) {
    return std::strcmp(std::getenv("UART_MODE"), "inverted") == 0 ? ~wire_byte : wire_byte;
}
"""


class BoardCodegenTests(unittest.TestCase):
    def consistent(self, artifact, records):
        self.assertEqual([r['id'] for r in records[:-1]], [s['id'] for s in artifact['steps']])
        self.assertEqual({r['id']: r['values'] for r in records[:-1]}, artifact['expected']['nodes'])
        self.assertTrue(all(r['nonce'] == 'TestNonce7' for r in records))
        self.assertEqual(records[-1], {'type': 'done', 'nonce': 'TestNonce7',
                         'artifact_id': artifact['artifact_id'], 'board': artifact['board'],
                         'language': artifact['language'], 'experiment': artifact['experiment'],
                         'status': 'ok', 'metrics': artifact['expected']['metrics']})

    def check_fault(self, artifact, records, mode):
        done = records[-1]
        if mode == 'unplugged':
            uart = next(i for i, b in enumerate(artifact['steps']) if b['kind'] == 'uart_loopback')
            self.assertEqual(len(records) - 1, uart)
            self.assertEqual(done['status'], 'timeout')
            self.assertEqual(done['metrics'], {'compared_bits': 0, 'bit_errors': 0, 'ber': None,
                                               'expected_frames': 1, 'received_frames': 0, 'lost_frames': 1})
        else:
            self.assertEqual(done['status'], 'ok')
            self.assertEqual(done['metrics']['ber'], 1)
            self.assertEqual(done['metrics']['bit_errors'], done['metrics']['compared_bits'])

    def test_target_identity_sources_and_line_spans(self):
        ids = set()
        program = c.PRESETS['board_bpsk']['program']
        for board in ('pico', 'pico_w'):
            for language in ('cpp', 'micropython'):
                artifact = generate(program, language, board)
                self.assertEqual(artifact, generate(program, language, board))
                ids.add(artifact['artifact_id'])
                lines = artifact['files'][artifact['entry_file']].splitlines()
                for step in artifact['steps']:
                    span = artifact['source_map'][step['id']]
                    self.assertIn(step['id'], lines[span['start'] - 1])
                    self.assertIn('trace(', '\n'.join(lines[span['start'] - 1:span['end']]))
                self.assertEqual(artifact['expected']['nodes']['block-2'][:6], [-1, -1, -1, 1, 1, 1])
        self.assertEqual(len(ids), 4)

    def test_target_and_limit_diagnostics(self):
        for language, board in [('python', 'pico'), ('cpp', 'pico2')]:
            with self.assertRaises(BoardCodeError):
                generate(c.PRESETS['board_bpsk']['program'], language, board)
        with self.assertRaises(BoardCodeError) as error:
            generate({'document_schema': 2, 'graph': graph.demo()}, 'cpp', 'pico')
        self.assertEqual(error.exception.block_ids, ['merge'])
        awgn = c.preset(['bit_pattern', 'mod_bpsk', 'awgn', 'demod_bpsk', 'sink'])
        with self.assertRaises(BoardCodeError) as error:
            generate(awgn, 'cpp', 'pico')
        self.assertEqual(error.exception.block_ids, ['block-2'])
        long_input = c.preset(['bit_pattern', 'mod_bpsk', 'ideal', 'demod_bpsk', 'sink'],
                              {0: {'pattern': '1' * 2049}})
        with self.assertRaises(BoardCodeError) as error:
            generate(long_input, 'cpp', 'pico')
        self.assertIn('block-0', error.exception.block_ids)
        for source, index, params in [('board_uart', 2, {'timeout_ms': -1}),
                                      ('board_bpsk', 5, {'factor': 5})]:
            program = c.preset([b['kind'] for b in c.PRESETS[source]['program']['blocks']], {index: params})
            with self.assertRaises(BoardCodeError) as error:
                generate(program, 'cpp', 'pico')
            self.assertEqual(error.exception.block_ids, ['block-' + str(index)])

    def test_micropython_source_and_uart_bytes_with_partial_byte(self):
        for board in ('pico', 'pico_w'):
            for name in ('board_bpsk', 'board_uart'):
                artifact = generate(c.PRESETS[name]['program'], 'micropython', board)
                peer = UartPeer('echo')
                self.consistent(artifact, python_records(artifact, peer))
                if name == 'board_uart':
                    # 1011 repeated 3 times is 11100011 1111 followed by 4 padding bits.
                    self.assertEqual(peer.wire, [0xe3, 0xf0])
                    self.assertEqual(peer.config[:7], (0, 9600, 8, None, 1, 0, 1))
                    for mode in ('inverted', 'unplugged'):
                        self.check_fault(artifact, python_records(artifact, UartPeer(mode)), mode)
        multisegment = c.preset(['bit_pattern', 'bit_pattern', 'repeat_encode', 'repeat_encode',
                                 'mod_bpsk', 'ideal', 'demod_bpsk', 'repeat_decode', 'repeat_decode', 'sink'],
                                {0: {'pattern': '1'}, 1: {'pattern': '001'},
                                 2: {'factor': 5}, 3: {'factor': 7}, 7: {'factor': 7}, 8: {'factor': 5}})
        artifact = generate(multisegment, 'micropython', 'pico')
        self.consistent(artifact, python_records(artifact, UartPeer('echo')))

    @unittest.skipUnless(shutil.which('g++'), 'Host C++ compiler unavailable')
    def test_generated_cpp_matches_reference_and_handles_unplugged_uart(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'pico').mkdir()
            (folder / 'pico/stdlib.h').write_text('inline void stdio_init_all() {}\n')
            (folder / 'hardware').mkdir()
            (folder / 'hardware/uart.h').write_text(CPP_UART)
            for name in ('board_bpsk', 'board_uart'):
                artifact = generate(c.PRESETS[name]['program'], 'cpp', 'pico_w')
                (folder / 'main.cpp').write_text(artifact['files']['main.cpp'], encoding='utf-8')
                target = folder / ('test.exe' if os.name == 'nt' else 'test')
                subprocess.run(['g++', '-std=c++17', '-I.', 'main.cpp', '-o', target.name],
                               cwd=folder, check=True, timeout=45)
                modes = ['echo'] if name == 'board_bpsk' else ['echo', 'inverted', 'unplugged']
                for mode in modes:
                    completed = subprocess.run([str(target)], input=command(artifact), capture_output=True,
                                               text=True, check=True, timeout=5, env={**os.environ, 'UART_MODE': mode})
                    records = parse(completed.stdout)
                    if mode == 'echo':
                        self.consistent(artifact, records)
                    else:
                        self.check_fault(artifact, records, mode)


if __name__ == '__main__':
    unittest.main()
