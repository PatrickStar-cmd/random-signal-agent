"""Offline integration checks. Run with Python 3.12 from any directory."""
from pathlib import Path
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['RS_AGENT_LLM_ENABLED'] = '0'

import numpy as np
import server
import run_demo
from src import dialogue_agent
from src.signal_processing import SignalConfig, generate_random_signal


class ReproductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.patches = [
            patch.object(server, 'UPLOAD_DIR', cls.root / 'uploads'),
            patch.object(server, 'OUTPUT_DIR', cls.root / 'outputs'),
            patch.object(dialogue_agent, 'AUDIO_OUTPUT_DIR', cls.root / 'outputs' / 'audio'),
        ]
        for item in cls.patches:
            item.start()
        cls.httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.AgentRequestHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()
        for item in reversed(cls.patches):
            item.stop()
        cls.temp.cleanup()

    def request(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(self.base + path, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.read()

    def test_health_and_page(self):
        health = json.loads(self.request('/api/health'))
        self.assertEqual(health['status'], 'ok')
        self.assertFalse(health['llm']['configured'])
        self.assertIn(b'<html', self.request('/').lower())
        self.assertGreater(len(self.request('/background.jpg')), 100)

    def test_seed_and_demo(self):
        a = generate_random_signal(SignalConfig(seed=42))
        b = generate_random_signal(SignalConfig(seed=42))
        np.testing.assert_array_equal(a.observed, b.observed)
        with patch.object(run_demo, 'OUTPUT_DIR', self.root), contextlib.redirect_stdout(io.StringIO()):
            run_demo.main()
        result = json.loads((self.root / 'analysis_result.json').read_text(encoding='utf-8'))
        self.assertAlmostEqual(result['summary']['frequency_features']['dominant_frequency_hz'], 8.0, places=1)
        for name in ['signal_samples.csv', 'demo.html', 'design_report.md']:
            self.assertGreater((self.root / name).stat().st_size, 0)

    def test_agent_pipeline_and_stream(self):
        payload = {'session_id': 'verify', 'message': '采集一段 2 秒、采样率 200Hz、主频 8Hz 的正弦信号加高斯噪声，随机种子 42', 'agent_mode': True}
        result = json.loads(self.request('/api/chat', payload))
        self.assertTrue(result['state']['has_processed'])
        self.assertTrue(result['state']['has_summary'])
        self.assertTrue(result['tool_calls'])
        self.assertIn('advanced_analysis', result['state']['summary'])
        payload['message'] = '分析时域和频域特征'
        stream = self.request('/api/chat/stream', payload).decode()
        self.assertIn('data: [DONE]', stream)
        events = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith('data: {')]
        self.assertTrue(events)
        self.assertFalse(any(e.get('event') == 'error' for e in events))

    def test_upload_and_path_boundaries(self):
        for columns in (1, 2):
            csv = '\n'.join(str(np.sin(i / 4)) if columns == 1 else f'{i / 200},{np.sin(i / 4)}' for i in range(100))
            body = ('--verify\r\nContent-Disposition: form-data; name="session_id"\r\n\r\n../../escape\r\n'
                    '--verify\r\nContent-Disposition: form-data; name="file"; filename="../sample.csv"\r\n'
                    'Content-Type: text/csv\r\n\r\n' + csv + '\r\n--verify--\r\n').encode()
            req = urllib.request.Request(self.base + '/api/upload', data=body, headers={'Content-Type': 'multipart/form-data; boundary=verify'})
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.load(response)
            self.assertEqual(result['state']['signal']['sample_count'], 100)
        self.assertEqual(len(list((self.root / 'uploads').glob('*.csv'))), 2)
        for path in ['/../server.py', '/..\\server.py', '/outputs/../server.py']:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request(path)
            self.assertEqual(caught.exception.code, 404)

    def test_microphone_payload_and_audio(self):
        samples = (0.2 * np.sin(2 * np.pi * 440 * np.arange(8000) / 8000)).tolist()
        with patch('src.dialogue_agent.shutil.which', return_value=None):
            result = json.loads(self.request('/api/microphone', {'session_id': 'mic', 'sample_rate': 8000, 'samples': samples}))
        self.assertEqual(result['state']['signal']['sample_count'], 8000)
        audio = result['state']['audio_result']
        self.assertEqual(audio['download_format'], 'wav')
        self.assertTrue(self.request(audio['denoised_url']).startswith(b'RIFF'))


if __name__ == '__main__':
    log_dir = ROOT / 'logs' / 'verification'
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / 'latest.log').open('w', encoding='utf-8') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReproductionTests))
    print((log_dir / 'latest.log').read_text(encoding='utf-8'))
    sys.exit(0 if result.wasSuccessful() else 1)
