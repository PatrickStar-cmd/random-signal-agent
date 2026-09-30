"""Offline boundary regressions; overwrite logs/regression/latest.log."""

from pathlib import Path
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['RS_AGENT_LLM_ENABLED'] = '0'

import numpy as np
import server
from src.acquisition import load_signal_file
from src.signal_processing import SignalConfig, generate_random_signal


class SimulationRegressionTests(unittest.TestCase):
    def test_invalid_simulation_parameters_are_rejected(self):
        cases = ({'sample_rate': 0}, {'sample_rate': -1}, {'sample_rate': float('inf')},
                 {'duration': 0}, {'duration': .001}, {'duration': float('nan')},
                 {'noise_std': -1}, {'ar_coefficient': 1.1}, {'ar_coefficient': -1.1},
                 {'impulse_probability': -0.1}, {'impulse_probability': 1.1},
                 {'amplitude': float('nan')}, {'base_frequency': float('inf')})
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                generate_random_signal(SignalConfig(**kwargs))

    def test_valid_seeded_simulation_remains_repeatable(self):
        first = generate_random_signal(SignalConfig(seed=42))
        second = generate_random_signal(SignalConfig(seed=42))
        self.assertEqual(first.observed.size, 1600)
        self.assertTrue(np.all(np.isfinite(first.observed)))
        np.testing.assert_array_equal(first.observed, second.observed)
        np.testing.assert_allclose(first.observed, first.clean + first.noise)


class FileRegressionTests(unittest.TestCase):
    def load_text(self, text, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'signal.csv'
            path.write_text(text, encoding='utf-8-sig')
            return load_signal_file(path, **kwargs)

    def test_mixed_columns_are_rejected_in_both_orders(self):
        for text in ('time,value\n0,1\n2\n', 'value\n1\n2,3\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'columns'):
                self.load_text(text)

    def test_nonfinite_file_values_are_rejected(self):
        for text in ('1\nnan\n', '1\ninf\n', '0,1\n.01,-inf\n', 'nan,1\n.01,2\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'finite'):
                self.load_text(text)

    def test_headers_and_extra_columns_remain_supported(self):
        one = self.load_text('value\n1\n2\n3\n')
        np.testing.assert_array_equal(one.observed, [1, 2, 3])
        two = self.load_text('time,value,extra\n0,1,9\n.01,2,8\n.02,3,7\n')
        np.testing.assert_array_equal(two.observed, [1, 2, 3])
        self.assertAlmostEqual(two.config.sample_rate, 100)
        self.assertFalse(two.has_clean_reference)

    def test_invalid_file_time_axes_are_rejected(self):
        for text in ('0,1\n0,2\n', '.01,1\n0,2\n', '0,1\n.01,2\n.025,3\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'Time values'):
                self.load_text(text)

    def test_invalid_file_sample_rates_are_rejected(self):
        for rate in (0, -1, float('nan'), float('inf')):
            with self.subTest(rate=rate), self.assertRaisesRegex(ValueError, 'sample_rate'):
                self.load_text('1\n2\n', sample_rate=rate)

    def test_rounded_uniform_time_axis_is_accepted(self):
        bundle = self.load_text('0,1\n.00033333,2\n.00066667,3\n')
        self.assertAlmostEqual(bundle.config.sample_rate, 3000, delta=.1)
        one = self.load_text('1\n2\n3\n', sample_rate=100)
        np.testing.assert_allclose(one.time, [0, .01, .02])


class HTTPRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.agent = Mock()
        self.agent.chat.return_value = {'ok': True}
        self.patches = [patch.object(server, 'AGENT', self.agent)]
        for item in self.patches:
            item.start()
        self.httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.AgentRequestHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.httpd.server_port}'

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        req = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        return urllib.request.urlopen(req, timeout=5)

    def assert_bad_request(self, path, data, headers=None):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request(path, data, headers)
        self.assertEqual(caught.exception.code, 400)
        with caught.exception as response:
            self.assertIn('error', json.load(response))

    def test_invalid_json_returns_400_on_all_json_routes(self):
        routes = ('/api/chat', '/api/chat/stream', '/api/microphone', '/api/realtime/stop')
        for route in routes:
            for body in (b'{', b'[]', b'null', b'42', b'"text"', b'\xff'):
                with self.subTest(route=route, body=body):
                    self.assert_bad_request(route, body, {'Content-Type': 'application/json'})
        self.agent.chat.assert_not_called()
        with self.request('/api/chat', b'{"message":"hello"}') as response:
            self.assertEqual(json.load(response), {'ok': True})

    def test_negative_content_length_returns_400(self):
        self.assert_bad_request('/api/chat', b'', {'Content-Length': '-1'})

    def test_invalid_microphone_sample_rate_returns_400(self):
        for rate in ('bad', 'nan', 'inf', 0, -1, None, []):
            with self.subTest(rate=rate):
                body = json.dumps({'sample_rate': rate, 'samples': [0, 1]}).encode()
                self.assert_bad_request('/api/microphone', body)
        self.agent.use_microphone_samples.assert_not_called()

    def test_invalid_upload_sample_rate_returns_400(self):
        for rate in ('bad', 'nan', 'inf', '0', '-1'):
            body = ('--rate\r\nContent-Disposition: form-data; name="sample_rate"\r\n\r\n'
                    + rate + '\r\n--rate--\r\n').encode()
            with self.subTest(rate=rate):
                self.assert_bad_request('/api/upload', body,
                    {'Content-Type': 'multipart/form-data; boundary=rate'})
        self.agent.use_uploaded_file.assert_not_called()


if __name__ == '__main__':
    log_dir = ROOT / 'logs' / 'regression'
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / 'latest.log').open('w', encoding='utf-8') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    print((log_dir / 'latest.log').read_text(encoding='utf-8'))
    sys.exit(0 if result.wasSuccessful() else 1)
