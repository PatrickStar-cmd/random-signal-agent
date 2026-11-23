"""Exercise public HTTP entry points, source bundles and desktop UART semantics."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from server import create_app
from src import communications as comm
from src import communication_workbench_v0412 as workbench
from src import communication_studio


class BoardApiTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app = create_app(data_dir=Path(temp.name))
        self.client = self.enterContext(TestClient(self.app))

    def test_catalog_and_reference(self):
        preset = self.client.get('/api/communications/catalog').json()['presets']['board_uart']
        program = preset['program']
        program['blocks'][0]['params']['pattern'] = '1011'
        report = workbench.run_document({'document_schema': 2, 'program': program})
        result = report['result']
        self.assertEqual(result['uart']['packed_bytes'], [0b11100011, 0b11110000])
        self.assertEqual(result['uart']['valid_bits'], 12)
        self.assertEqual(result['sink']['values'], [1, 0, 1, 1])
        self.assertEqual(len(report['observations']), 5)
        self.assertEqual(result['metrics']['ber'], 0)
        partial = {**program, 'blocks': program['blocks'][:3]}
        restored = communication_studio.complete_receiver(partial)
        self.assertEqual([b['kind'] for b in restored['blocks']], [b['kind'] for b in program['blocks']])
        self.assertEqual(comm.run(restored, comm.build(restored)['token'])['sink']['values'], [1, 0, 1, 1])

    def test_export_all_targets(self):
        for preset in ('board_bpsk', 'board_uart', 'board_text_uart', 'board_pn', 'board_hamming_fault', 'board_qpsk'):
            for language in ('cpp', 'micropython'):
                for board in ('pico', 'pico_w'):
                    with self.subTest(preset=preset, language=language, board=board):
                        payload = {'language': language, 'board': board, 'document': comm.PRESETS[preset]['program']}
                        result = self.client.post('/api/communications/board-generate', json=payload)
                        self.assertEqual(result.status_code, 200, result.text[:300])
                        generated = result.json()
                        archive = self.client.post('/api/communications/board-export', json=payload)
                        self.assertEqual(archive.status_code, 200)
                        with ZipFile(io.BytesIO(archive.content)) as files:
                            self.assertEqual(json.loads(files.read('experiment.json'))['source_map'], generated['source_map'])
                            self.assertEqual(files.read(generated['entry_file']).decode(), generated['files'][generated['entry_file']])

    def test_pair_endpoint_export_and_local_actions(self):
        payload = {'document': comm.PRESETS['board_link_hamming']['program'],
                   'targets': {'tx': {'board': 'esp32s3', 'language': 'cpp'},
                               'rx': {'board': 'pico_w', 'language': 'micropython'}}}
        base = '/api/communications/board-'
        project = self.client.post(base+'generate', json=payload).json()
        for role, ep in project['endpoints'].items():
            response = self.client.post(base+'export', json={**payload, 'role': role})
            with ZipFile(io.BytesIO(response.content)) as archive:
                self.assertEqual(archive.read(ep['entry_file']).decode(), ep['files'][ep['entry_file']])
        self.assertEqual(self.client.post(base+'run', json=payload).status_code, 403)
        with TestClient(self.app, base_url='http://localhost', client=('127.0.0.1', 12345)) as local:
            self.assertEqual(local.post(base+'build', json=payload).status_code, 400)
            with patch('src.communication_board_device.build_firmware', return_value={'size':10}) as build:
                self.assertEqual(local.post(base+'build', json={**payload,'role':'tx'}).status_code, 200)
                self.assertEqual(build.call_args.args[0]['artifact_id'], project['endpoints']['tx']['artifact_id'])
            with patch('src.communication_board_pair.measure', return_value={'status':'ok'}) as run:
                ids = {'tx':'serial:A','rx':'serial:B'}
                self.assertEqual(local.post(base+'run', json={**payload,'device_ids':ids}).json()['status'],'ok')
                self.assertEqual(run.call_args.args[1],ids)
            with patch('src.communication_board_device._connected', return_value=[{'id':'same','path':'COM1','kind':'serial'}]):
                response = local.post(base+'run', json={**payload,'device_ids':{'tx':'same','rx':'same'}})
                self.assertEqual(response.status_code,400)

    def test_device_actions_require_local_access(self):
        for action in ('devices', 'build', 'deploy', 'run'):
            response = self.client.post('/api/communications/board-' + action, json={})
            self.assertEqual(response.status_code, 403, action)
        with TestClient(self.app, base_url='http://localhost', client=('127.0.0.1', 65432)) as local:
            with patch('src.communication_board_device.devices', return_value={'devices': [], 'tools': {}}):
                self.assertEqual(local.post('/api/communications/board-devices', json={}).json()['devices'], [])
                response = local.post('/api/communications/board-devices', headers={'Origin': 'https://external.example'}, json={})
                self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get('/api/board/firmware/invalid').status_code, 403)
