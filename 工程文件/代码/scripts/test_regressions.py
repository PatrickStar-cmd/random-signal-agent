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


if __name__ == '__main__':
    log_dir = ROOT / 'logs' / 'regression'
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / 'latest.log').open('w', encoding='utf-8') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    print((log_dir / 'latest.log').read_text(encoding='utf-8'))
    sys.exit(0 if result.wasSuccessful() else 1)
