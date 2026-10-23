"""v0.4.7 arithmetic, grid recovery, packet PHY and teaching acceptance."""
from pathlib import Path
import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['RS_AGENT_LLM_ENABLED'] = '0'
import numpy as np
from fastapi.testclient import TestClient
import server
from src import communications as c, communication_learning as learn, communication_protocols as link
from src import communication_codecs as codec
from src.communication_jobs import Jobs


def program(count=512):
    return c.preset(['random_bits', 'mod_qpsk', 'awgn', 'demod_qpsk', 'sink'], {0: {'count': count}, 2: {'esn0_db': 8}})


def grid_settings():
    return {'x': {'block_id': 'block-2', 'parameter': 'esn0_db', 'values': [0, 6]},
            'y': {'block_id': 'global', 'parameter': 'symbol_rate', 'values': [500, 1000]}, 'frames': 2, 'target_errors': 10000}


class LearningTests(unittest.TestCase):
    def test_variable_dependencies_and_shared_formula_values(self):
        raw = program()
        answer = learn.resolve_program(raw, {'Fs': 'Rs*sps', 'Rs': 1200, 'sps': 8, 'N': '2**9'},
                                       {'sample_rate': 'Fs', 'symbol_rate': 'Rs', 'blocks.block-0.count': 'N'})
        self.assertEqual(answer['program']['sample_rate'], 9600)
        self.assertEqual(answer['program']['symbol_rate'], 1200)
        self.assertEqual(answer['program']['blocks'][0]['params']['count'], 512)
        self.assertEqual(raw['sample_rate'], c.CONFIG['defaults']['sample_rate'])
        c.build(answer['program'])

    def test_formula_rejects_calls_cycles_and_invalid_values(self):
        for variables in ({'a': '__import__("os")'}, {'a': 'a+1'}, {'a': 'b', 'b': 'a'},
                          {'a': 'missing+1'}, {'a': '2**100000'}, {'a': '1/0'}, {'a': '(1).__class__'}, {'a': True}):
            with self.subTest(variables=variables), self.assertRaises(ValueError):
                learn.resolve_program(program(), variables)
        with self.assertRaises(ValueError):
            learn.resolve_program(program(), {}, {'blocks.block-0.unknown': 2})

    def test_grid_measures_true_metrics_and_restores_exact_point(self):
        p = program(); built = c.build(p); settings = grid_settings(); progress = []
        result = learn.sweep2d(p, built['token'], settings, lambda value: progress.append(value['completed_points']))
        self.assertTrue(result['complete']); self.assertEqual(len(result['points']), 4)
        self.assertEqual([(r['row'], r['column']) for r in result['points']], [(0, 0), (0, 1), (1, 0), (1, 1)])
        for point in result['points']:
            errors = 0
            for frame in range(2):
                candidate = copy.deepcopy(point['program']); candidate['seed'] += frame
                cb = c.build(candidate); errors += c.run(cb['program'], cb['token'])['metrics']['bit_errors']
            self.assertEqual(point['bit_errors'], errors)
            self.assertEqual(point['program']['symbol_rate'], point['y'])
        self.assertLess(result['points'][1]['ber'], result['points'][0]['ber'])
        self.assertEqual(progress[-1], 4)

    def test_grid_cancellation_and_bounds(self):
        p = program(); built = c.build(p); settings = grid_settings(); event = threading.Event()
        result = learn.sweep2d(p, built['token'], settings, lambda value: event.set(), event)
        self.assertFalse(result['complete'])
        with self.assertRaises(ValueError):
            learn.sweep2d(p, 'stale', settings)
        settings['frames'] = 100
        with self.assertRaises(ValueError):
            learn.sweep2d(p, built['token'], settings)

    def test_packet_crc_reorder_duplicate_and_partial_payload(self):
        bits = np.unpackbits(np.frombuffer(b'Ocean packet experiment!', dtype=np.uint8))
        packets = link.packetize(bits, 7)
        self.assertEqual([len(v['payload']) // 8 for v in packets], [7, 7, 7, 3])
        restored = link.reassemble([v['wire'] for v in reversed(packets)] + [packets[0]['wire']])
        np.testing.assert_array_equal(bits, restored)
        invalid = packets[0]['wire'].copy(); invalid[37] ^= 1
        self.assertIsNone(link.unpack_packet(invalid))

    def test_protocol_ideal_delivery_and_feedback_timeout_duplicate(self):
        p = c.build(program())['program']
        result = link.protocol(p, {'snr_db': 30, 'feedback_loss': 0, 'packet_bytes': 16})
        self.assertTrue(result['metrics']['complete_payload'])
        self.assertEqual(result['source_base64'], result['received_base64'])
        self.assertEqual(result['metrics']['retransmissions'], 0)
        lost = link.protocol(p, {'snr_db': 30, 'feedback_loss': 1, 'max_retries': 1, 'packet_bytes': 16})
        self.assertTrue(lost['metrics']['complete_payload'])
        self.assertEqual(lost['metrics']['confirmed_packets'], 0)
        self.assertTrue(any(v['duplicate'] for v in lost['events']))
        self.assertTrue(all(v['event'] == 'timeout' for v in lost['events']))
        self.assertLess(lost['metrics']['goodput_bps'], result['metrics']['goodput_bps'])

    def test_harq_combines_real_soft_information(self):
        p = c.build(program(2048))['program']
        settings = {'snr_db': -3, 'packet_bytes': 16, 'packets': 16, 'max_retries': 5, 'feedback_loss': 0}
        arq = link.protocol(p, {**settings, 'mode': 'arq'})
        harq = link.protocol(p, {**settings, 'mode': 'harq'})
        self.assertGreater(harq['metrics']['delivered_packets'], arq['metrics']['delivered_packets'])
        self.assertLess(harq['metrics']['transmissions'], arq['metrics']['transmissions'])
        self.assertTrue(any(v['combined_transmissions'] > 1 for v in harq['events']))
        self.assertEqual(harq, link.protocol(p, {**settings, 'mode': 'harq'}))
        reference = {(e['packet'], e['attempt']): e for e in arq['events']}
        for event in harq['events']:
            pair = reference.get((event['packet'], event['attempt']))
            if pair is not None:
                self.assertEqual(pair['evm_percent'], event['evm_percent'])
                self.assertEqual(pair['feedback_lost'], event['feedback_lost'])
            if event['attempt'] > 1:
                self.assertAlmostEqual(event['accumulated_payload_ebn0_db'] - event['payload_ebn0_db'], 10 * np.log10(event['attempt']))

    def test_amc_real_decoding_feedback_delay_and_mcs_switch(self):
        p = c.build(program())['program']
        result = link.amc(p, {'snr_start': 0, 'snr_stop': 28, 'frames': 20, 'feedback_delay': 1, 'hysteresis': .5})
        self.assertGreater(result['metrics']['profile_switches'], 2)
        self.assertEqual(result['frames'][0]['profile'], 'BPSK 1/2')
        self.assertEqual(result['frames'][-1]['profile'], '64QAM 3/4')
        self.assertIsNone(result['frames'][1]['feedback_snr_db'])
        self.assertEqual(result['frames'][2]['feedback_snr_db'], result['frames'][0]['estimated_snr_db'])
        self.assertGreater(result['metrics']['goodput_bps'], 0)
        self.assertEqual(result['metrics']['bit_errors'], sum(v['bit_errors'] for v in result['frames']))
        delayed = link.amc(p, {'snr_start': 0, 'snr_stop': 28, 'frames': 20, 'feedback_delay': 10, 'hysteresis': .5})
        self.assertEqual([v['estimated_snr_db'] for v in result['frames']], [v['estimated_snr_db'] for v in delayed['frames']])

    def test_challenge_and_difference_use_run_evidence(self):
        p = program(); p['blocks'][2]['params']['esn0_db'] = 12
        b = c.build(p); run = c.run(b['program'], b['token'])
        self.assertTrue(learn.check(p, run, 'clean-link')['passed'])
        self.assertFalse(learn.check(p, {'metrics': {'ber': .5}}, 'clean-link')['passed'])
        self.assertFalse(learn.check(p, {'metrics': {}}, 'reliable-packets')['passed'])
        other = copy.deepcopy(p); other['blocks'][2]['params']['esn0_db'] = 1
        second = c.build(other); result = c.run(second['program'], second['token'])
        diff = learn.difference({'program': p, 'result': run}, {'program': other, 'result': result})
        self.assertEqual(diff['changed_parameters'], 1)
        self.assertEqual(diff['changes'][0]['path'], 'blocks.block-2.params.esn0_db')
        self.assertGreater(next(v['delta'] for v in diff['metrics'] if v['metric'] == 'ber'), 0)
        parameters_only = learn.difference({'program': p, 'result': None}, {'program': other, 'result': None})
        self.assertEqual(parameters_only['changed_parameters'], 1)
        self.assertEqual(parameters_only['metrics'], [])

    def test_guided_media_goals_and_example_references(self):
        for challenge in learn.catalog()['challenges']:
            self.assertIn(challenge['preset'], c.PRESETS)
            c.build(c.PRESETS[challenge['preset']]['program'])
        p = c.PRESETS['business_packets']['program']; built = c.build(p)
        result = c.run(built['program'], built['token'])
        self.assertTrue(learn.check(p, result, 'file-integrity')['passed'])

    def test_python_export_runs_in_clean_directory(self):
        p = program(); exported = learn.export_python(p, {'N': 128}, {'blocks.block-0.count': 'N'})
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / exported['filename']; script.write_text(exported['source'], encoding='utf-8')
            process = subprocess.run([sys.executable, str(script)], cwd=directory, env={**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONIOENCODING': 'utf-8'}, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads((Path(directory) / 'communication_experiment_result.json').read_text(encoding='utf-8'))
            self.assertEqual(result['result']['metrics']['bit_count'], 128)
            self.assertEqual(result['parameters']['resolved_variables']['N'], 128)
            import xml.etree.ElementTree as ET
            plot = ET.parse(Path(directory) / 'communication_experiment_plot.svg')
            self.assertGreater(len(plot.findall('.//{http://www.w3.org/2000/svg}circle')), 0)
            self.assertEqual(len(plot.findall('.//{http://www.w3.org/2000/svg}polyline')), 2)
            for name in ('analog_am', 'line_manchester'):
                exported = learn.export_python(c.PRESETS[name]['program'])
                script.write_text(exported['source'], encoding='utf-8')
                process = subprocess.run([sys.executable, str(script)], cwd=directory, env={**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONIOENCODING': 'utf-8'}, capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertIn('Channel samples', (Path(directory) / 'communication_experiment_plot.svg').read_text(encoding='utf-8'))

    def test_algorithm_walkthroughs_match_decoding(self):
        value = learn.explain('viterbi', snr_db=20)
        self.assertEqual(value['input_bits'], value['decoded_bits'])
        self.assertEqual(len(value['traceback_states']), len(value['steps']) + 1)
        self.assertEqual(value['traceback_states'][0], 0)
        ldpc = learn.explain('ldpc', snr_db=3)
        self.assertEqual(ldpc['steps'][-1]['unsatisfied_checks'], 0)
        self.assertEqual(ldpc['input_bits'], ldpc['decoded_bits'])
        v = learn.explain('constellation', snr_db=20, scheme='qam16')
        self.assertEqual(len(v['constellation']), 16)
        self.assertEqual(len(v['regions']['indices']), 41)
        self.assertEqual(len(v['samples'][0]['llr']), 4)
        self.assertTrue(all(sample['sent'] == sample['decision'] for sample in v['samples']))

    def test_job_contract_for_all_three_experiments(self):
        p = program(128); built = c.build(p)
        with tempfile.TemporaryDirectory() as directory:
            jobs = Jobs(directory, threading.BoundedSemaphore(1))
            try:
                for kind, settings in [('sweep2d', grid_settings()), ('protocol', {'snr_db': 30}), ('amc', {'frames': 3})]:
                    job = jobs.start('lesson', kind, {'program': p, 'token': built['token'], 'settings': settings})
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        state = jobs.status('lesson', job['id'])
                        if state['status'] in ('completed', 'failed', 'cancelled'):
                            break
                        time.sleep(.01)
                    self.assertEqual(state['status'], 'completed', state)
                    self.assertTrue(state['result']['complete'])
            finally:
                jobs.close()

    def test_job_cancellation_releases_waiting_execution(self):
        p = program(128); built = c.build(p)
        with tempfile.TemporaryDirectory() as directory:
            jobs = Jobs(directory, threading.BoundedSemaphore(0))
            try:
                for kind, settings in [('sweep2d', grid_settings()), ('protocol', {}), ('amc', {'frames': 100})]:
                    job = jobs.start('lesson', kind, {'program': p, 'token': built['token'], 'settings': settings})
                    jobs.control('lesson', job['id'], 'cancel')
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline:
                        state = jobs.status('lesson', job['id'])
                        if state['status'] == 'cancelled':
                            break
                        time.sleep(.01)
                    self.assertEqual(state['status'], 'cancelled')
            finally:
                jobs.close()

    def test_http_catalog_learning_actions_and_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(server.create_app(data_dir=root / 'data', upload_dir=root / 'uploads', output_dir=root / 'outputs')) as client:
                self.assertIn('challenges', client.get('/api/communications/catalog').json()['learning'])
                payload = {'session_id': 'lesson', 'program': program(), 'variables': {'Rs': 1200}, 'bindings': {'symbol_rate': 'Rs'}}
                result = client.post('/api/communications/learning-resolve', json=payload)
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()['program']['symbol_rate'], 1200)
                result = client.post('/api/communications/learning-export', json=payload)
                self.assertEqual(result.status_code, 200, result.text)
                self.assertIn('communications.run', result.json()['source'])
                result = client.post('/api/communications/learning-explain', json={'session_id': 'lesson', 'algorithm': 'viterbi'})
                self.assertEqual(result.status_code, 200, result.text)
                self.assertIn('steps', result.json())
                lesson = {'variables': {'Rs': 1200}, 'bindings': {'symbol_rate': 'Rs'},
                          'scan': {'points': []}, 'protocolResult': {'frames': []}, 'amcResult': {'frames': []},
                          'diff': {'changes': []}, 'baseline': {'program': program()}, 'notes': '观察延迟反馈',
                          'explanation': {'algorithm': 'viterbi'}}
                document = {'document_schema': 2, 'name': '教学工程', 'program': program(), 'learning': lesson}
                saved = client.post('/api/communications/project-save', json={'session_id': 'lesson', 'document': document}).json()
                loaded = client.post('/api/communications/project-load', json={'session_id': 'lesson', 'id': saved['id']}).json()
                self.assertEqual(loaded['document']['learning'], lesson)


if __name__ == '__main__':
    unittest.main()
