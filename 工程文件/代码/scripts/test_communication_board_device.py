import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import communication_board_device as device


class BufferedPort(io.BytesIO):
    @property
    def in_waiting(self):
        return min(17, len(self.getbuffer()) - self.tell())


class BoardDeviceTests(unittest.TestCase):
    def setUp(self):
        self.program = {
            'artifact_id': 'a' * 64, 'language': 'cpp', 'board': 'pico', 'experiment': 'uart',
            'files': {'main.cpp': 'main', 'CMakeLists.txt': 'cmake'},
            'steps': [{'kind': k} for k in ('bit_pattern', 'uart_loopback', 'sink')],
            'expected': {'nodes': {k: [1, 0, 1] for k in ('a', 'b', 'z')}},
        }
        self.counts = {'expected_frames': 1, 'received_frames': 1, 'lost_frames': 0,
                       'compared_bits': 3, 'bit_errors': 0, 'ber': 0}

    def capture(self, pairs, status='ok', metrics=None):
        done = {k: self.program[k] for k in ('board', 'artifact_id', 'language', 'experiment')}
        frames = [{'type': 'node', 'id': 'stale', 'nonce': 'earlier'}]
        frames += [{'type': 'node', 'id': k, 'values': v, 'nonce': 'now'} for k, v in pairs]
        frames.append({**done, 'nonce': 'now', 'type': 'done', 'status': status,
                       'metrics': metrics or self.counts})
        return BufferedPort(b'Pico ready\r\n' + b''.join(
            b'RS050 ' + json.dumps(f).encode() + b'\r\n' for f in frames))

    def test_real_stream_records_and_checks_error_metrics(self):
        trace = self.program['expected']['nodes'].items()
        result = device._receive(self.capture(trace), self.program, 'now')
        self.assertTrue(result['matches_reference'])
        damaged = [(k, [0, 0, 1] if k in ('b', 'z') else v) for k, v in trace]
        metrics = {**self.counts, 'bit_errors': 1, 'ber': 1 / 3}
        result = device._receive(self.capture(damaged, metrics=metrics), self.program, 'now')
        self.assertFalse(result['matches_reference'])
        with self.assertRaisesRegex(ValueError, '计数'):
            device._receive(self.capture(damaged), self.program, 'now')

    def test_uart_timeout_requires_received_prefix_and_zero_denominator(self):
        metrics = {**self.counts, 'received_frames': 0, 'lost_frames': 1, 'compared_bits': 0, 'ber': None}
        result = device._receive(self.capture([('a', [1, 0, 1])], 'timeout', metrics), self.program, 'now')
        self.assertIsNone(result['metrics']['ber'])
        with self.assertRaisesRegex(ValueError, '不完整'):
            device._receive(self.capture([], 'timeout', metrics), self.program, 'now')

    def test_reject_unknown_device_and_cross_project_firmware(self):
        with TemporaryDirectory() as temp, patch.object(device, 'CACHE', Path(temp)), \
                patch.object(device, '_toolchain', return_value={'cmake': 'cmake', 'ninja': 'ninja',
                    'sdk': 'sdk', 'compiler': '/tools/arm-none-eabi-gcc', 'picotool_config': None}):
            commands = []

            def build_fixture(args, timeout, env):
                commands.append(args)
                if '--build' in args:
                    root = Path(args[args.index('--build') + 1])
                    root.mkdir()
                    (root / 'randomsign_board.uf2').write_bytes(b'UF2 fixture')

            with patch.object(device, '_command', side_effect=build_fixture):
                result = device.build_firmware(self.program)
            self.assertIn('-DPICO_BOARD=pico', commands[0])
            self.assertEqual(device.firmware_path(result['build_id']).read_bytes(), b'UF2 fixture')
            with self.assertRaisesRegex(ValueError, '不匹配'):
                device.deploy({**self.program, 'artifact_id': 'b' * 64}, 'bootsel:test', result['build_id'])
            with patch.object(device, '_connected', return_value=[]), self.assertRaisesRegex(ValueError, '刷新'):
                device.deploy(self.program, 'bootsel:test', result['build_id'])
            with self.assertRaises(ValueError):
                device.firmware_path('../other')
            device.firmware_path(result['build_id']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, '不匹配'):
                device.firmware_path(result['build_id'])

    def test_micropython_uses_selected_serial_and_installed_board_identity(self):
        connected = [{'id': 'serial:COM4:1234', 'path': 'COM4', 'kind': 'serial'}]
        program = {**self.program, 'board': 'pico_w', 'language': 'micropython', 'files': {'main.py': '# pico'}}
        with patch.object(device, '_connected', return_value=connected), \
                patch.object(device.importlib.util, 'find_spec', return_value=True), patch.object(device, '_command') as run:
            result = device.deploy(program, connected[0]['id'])
        args, _ = run.call_args.args
        self.assertIn('COM4', args)
        self.assertIn('Raspberry Pi Pico W with RP2040', args[args.index('exec') + 1])
        self.assertIn('reset', args)
        self.assertEqual(result['device_id'], connected[0]['id'])


if __name__ == '__main__':
    unittest.main()
