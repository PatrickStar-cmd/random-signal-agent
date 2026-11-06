"""Core graph, frozen execution, document and detector acceptance."""
import copy
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from src import communications as c, communication_graph_v0411 as graph
from src import communication_runtime as runtime, communication_segments as segments
from src import communication_sensing_v0411 as sensing, communication_studio as studio


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.g = graph.demo()

    def run_graph(self, cache=None, partial=False):
        built = graph.build(self.g)
        return graph.run(self.g, built['token'], cache, partial)

    def test_full_and_resumed_values_metrics_every_block(self):
        built = graph.build(self.g)
        contexts = []
        result = graph.run(self.g, built['token'], contexts=contexts)
        for i, compiled in enumerate(built['builds']):
            full, ctx = runtime.observe_run(compiled['program'], compiled['token'], retain=True, states={})
            self.assertEqual(full['metrics'], result['branches'][i]['result']['metrics'])
            self.assertEqual(full['sink'], result['branches'][i]['result']['sink'])
            for key, values in ctx.values.items():
                np.testing.assert_array_equal(values, contexts[i].values[key])
        self.assertEqual(result['merged_result']['sink'], result['branches'][0]['result']['sink'])

    def test_actual_source_and_channel_execute_once(self):
        original = runtime.enter
        visited = []
        with patch.object(runtime, 'enter', side_effect=lambda b: (visited.append(b['id']), original(b))[-1]), patch.object(c, 'source_data', wraps=c.source_data) as source:
            self.run_graph()
        self.assertEqual(source.call_count, 1)
        for b in self.g['prefix']:
            self.assertEqual(visited.count(b['id']), 1, b['kind'])

    def test_local_edit_reuses_prefix_and_unmodified_receiver(self):
        cache = {}
        first = self.run_graph(cache)
        self.g['branches'][1]['blocks'][1]['params']['step_size'] = .08
        second = self.run_graph(cache, True)
        self.assertTrue(second['shared_reused'])
        self.assertEqual(first['input_hash'], second['input_hash'])
        self.assertEqual(second['execution'][1]['executed'], [])
        self.assertGreater(len(second['execution'][2]['executed']), 0)
        full = self.run_graph()
        self.assertEqual(second['merged_result']['metrics'], full['merged_result']['metrics'])
        self.assertEqual(second['branches'][1]['result']['sink'], full['branches'][1]['result']['sink'])

    def test_upstream_edit_invalidates_snapshot(self):
        cache = {}; first = self.run_graph(cache)
        self.g['globals']['seed'] += 1
        second = self.run_graph(cache, True)
        self.assertFalse(second['shared_reused'])
        self.assertNotEqual(first['input_hash'], second['input_hash'])
        self.assertTrue(all(row['executed'] for row in second['execution']))

    def test_layout_preserves_token_topology_changes_it(self):
        first = graph.build(self.g)['token']
        self.g['layout'] = {'merge': {'x': 250, 'y': 700}}
        self.assertEqual(first, graph.build(self.g)['token'])
        self.g['merge']['select'] = 1
        self.assertNotEqual(first, graph.build(self.g)['token'])

    def test_two_to_four_receivers_one_authoritative_tail(self):
        for i in (3, 4):
            b = copy.deepcopy(self.g['branches'][0]); b.update(id='rx'+str(i), name='接收 '+str(i))
            self.g['branches'].append(b)
        self.g['merge']['inputs'] = ['rx3', 'rx4']
        self.g['edges'] = graph.connections(self.g)
        result = self.run_graph()
        self.assertEqual(len(result['branches']), 4)
        self.assertEqual(result['merged_result']['sink'], result['branches'][2]['result']['sink'])
        self.assertEqual(sum(bool(v['executed']) for v in result['execution'] if v['section']=='shared'), 1)

    def test_disconnected_draft_saves_and_build_names_problem(self):
        self.g['edges'].pop(0)
        raw = {'document_schema': 2, 'name': '断线草稿', 'graph': self.g, 'program': graph.projection(self.g, 'rx1')}
        self.assertEqual(studio.validate_document(raw)['graph']['edges'], self.g['edges'])
        with self.assertRaisesRegex(ValueError, '完整|连接'):
            graph.build(self.g)

    def test_merge_contract_checks_types_and_wiring(self):
        self.g['merge']['domain'] = 'symbols'
        with self.assertRaisesRegex(ValueError, '复符号'):
            graph.build(self.g)
        self.g = graph.demo(); self.g['edges'].append(copy.deepcopy(self.g['edges'][-1]))
        with self.assertRaises(ValueError): graph.build(self.g)

    def test_selected_and_unit_weight_preserve_receiver(self):
        for mode in ('select', 'weighted'):
            self.g['merge'].update(mode=mode, select=1, weights=[0, 1])
            result = self.run_graph()
            self.assertEqual(result['merged_result']['metrics'], result['branches'][1]['result']['metrics'])
            self.assertEqual(result['merged_result']['sink'], result['branches'][1]['result']['sink'])

    def test_weighted_llr_runs_real_decoder(self):
        self.g['merge'].update(mode='weighted', weights=[.6, .4])
        result = self.run_graph()
        self.assertEqual(result['merge']['llr_sign'], 'log_P0_over_P1')
        self.assertEqual(result['merged_result']['sink']['count'], 2048)
        self.assertEqual(result['merged_result']['metrics']['bit_errors'], 0)

    def test_merge_observation_and_signed_weights_match_decoder_input(self):
        self.g['merge'].update(mode='weighted', weights=[-1, 0])
        built=graph.build(self.g); contexts=[]
        value=graph.run(self.g,built['token'],contexts=contexts)
        actual=contexts[-1].values['merge-output']
        np.testing.assert_array_equal(actual,-contexts[0].values['block-8'])
        obs=next(v for v in value['merged_result']['experience']['observations'] if v['id']=='merge-output')
        np.testing.assert_allclose(obs['i'],actual[:len(obs['i'])])
        self.assertEqual(value['merged_result']['metrics']['coded_bit_errors'],int(np.count_nonzero(contexts[0].values['block-1']!=(actual<0))))

    def test_selected_mimo_symbols_preserve_effective_variance(self):
        p=copy.deepcopy(c.PRESETS['receiver_soft_ldpc']['program']);other=copy.deepcopy(p)
        other['blocks'][5]['params']['correlation']=.9
        self.g=graph.from_programs([p,other],domain='symbols')
        self.g['merge']['select']=1
        contexts=[];built=graph.build(self.g);value=graph.run(self.g,built['token'],contexts=contexts)
        np.testing.assert_array_equal(contexts[-1].values['block-6'],contexts[1].values['block-6'])
        self.assertEqual(value['merge']['noise_method'],'selected_receiver_variance')
        self.assertEqual(len(value['merge']['noise_variance']),len(contexts[1].values['block-5']))

    def test_frozen_filter_states_and_rng_remain_unchanged(self):
        cache = {}; self.run_graph(cache)
        state = copy.deepcopy(cache['frozen'])
        self.g['branches'][1]['blocks'][1]['params']['step_size'] = .15
        self.run_graph(cache, True)
        self.assertEqual(state['rng_state'], cache['frozen']['rng_state'])
        self.assertEqual(state['states'], cache['frozen']['states'])
        np.testing.assert_array_equal(state['variables']['data'], cache['frozen']['variables']['data'])

    def test_checkpoint_contains_training_lengths_codeword_and_state(self):
        b = graph.build(self.g)['builds'][0]
        _, ctx, _ = segments.execute(b, stop_after=len(self.g['prefix']) - 1)
        v = ctx.snapshot['variables']
        self.assertEqual(v['stack'][0][0], 'conv_encode')
        self.assertEqual(len(v['preamble']), 1024)
        self.assertEqual(len(v['reference']), 2048)
        self.assertEqual(len(v['encoded']), 4100)
        self.assertEqual(set(v), set(segments.VARIABLES))

    def test_schema_one_two_and_graph_roundtrip(self):
        p = c.PRESETS['digital']['program']
        self.assertEqual(studio.validate_document(p)['document_schema'], 2)
        raw = {'document_schema': 2, 'name': '接线', 'graph': self.g, 'graphActiveBranch': 'rx2', 'program': p}
        checked = studio.validate_document(json.loads(json.dumps(raw)))
        self.assertEqual(checked['program'], graph.projection(checked['graph'], 'rx2'))
        with tempfile.TemporaryDirectory() as folder:
            store = studio.ProjectStore(folder)
            saved = store.save('one', checked)
            self.assertEqual(store.load('one', saved['id'])['document'], checked)

    def test_stale_graph_result_is_cleared(self):
        result = self.run_graph()
        self.g['merge']['select'] = 1
        raw = {'document_schema': 2, 'name': '接线', 'graph': self.g, 'graphResult': result}
        self.assertIsNone(studio.validate_document(raw)['graphResult'])

    def test_python_export_reproduces_numerics(self):
        source = graph.python_export(self.g)
        scope = {}
        with patch('builtins.print'):
            exec(compile(source, 'graph-export.py', 'exec'), scope)
        self.assertEqual(scope['result']['merged_result']['metrics'], self.run_graph()['merged_result']['metrics'])

    def test_job_cache_is_session_owned_and_windows_are_stable(self):
        from src.communication_jobs import Jobs
        with tempfile.TemporaryDirectory() as folder:
            jobs = Jobs(folder, threading.BoundedSemaphore(2))
            try:
                payload = {'graph': self.g, 'token': graph.build(self.g)['token'], 'partial': True}
                ids = []
                for session in ('a', 'a', 'b'):
                    job = jobs.start(session, 'graph', payload)
                    deadline = time.monotonic() + 20
                    while job['status'] in ('queued', 'running') and time.monotonic() < deadline:
                        time.sleep(.02); job = jobs.status(session, job['id'])
                    self.assertEqual(job['status'], 'completed', job['error'])
                    ids.append(job)
                self.assertFalse(ids[0]['result']['shared_reused'])
                self.assertTrue(ids[1]['result']['shared_reused'])
                self.assertFalse(ids[2]['result']['shared_reused'])
                with self.assertRaises(KeyError): jobs.get('b', ids[0]['id'])
                value = jobs.window('a', ids[1]['id'], self.g['tail'][-1]['id'], 0, 12, branch=1)
                self.assertEqual(value['plot_count'], 12)
            finally:
                jobs.executor.shutdown(wait=True)

    def test_graph_api_build_job_export_and_project_reload(self):
        from fastapi.testclient import TestClient
        import server
        with tempfile.TemporaryDirectory() as folder, TestClient(server.create_app(
                data_dir=Path(folder)/'data', upload_dir=Path(folder)/'uploads',
                output_dir=Path(folder)/'outputs')) as client:
            def call(action, **payload):
                response=client.post('/api/communications/'+action,json={'session_id':'graph-test',**payload})
                self.assertEqual(response.status_code,200,response.text)
                return response.json()
            g=call('graph-create',demo='equalizer')['graph']
            built=call('graph-build',graph=g)
            self.assertIn('graph.run',call('graph-export',graph=g)['code'])
            receipt=call('job-start',kind='graph',payload={'graph':g,'token':built['token']})
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                value=call('job-status',id=receipt['id'])
                if value['status'] in ('completed','failed'): break
                time.sleep(.01)
            self.assertEqual(value['status'],'completed',value.get('error'))
            document={'document_schema':2,'name':'接线 API','graph':g,'graphResult':value['result']}
            saved=call('project-save',document=document)
            loaded=call('project-load',id=saved['id'])['document']
            self.assertEqual(loaded['graphResult']['input_hash'],value['result']['input_hash'])
            preview=call('report-preview',document=loaded)
            self.assertTrue(preview['summary'])


class SensingTests(unittest.TestCase):
    def test_analytic_pfa_on_independent_square_law_noise(self):
        rng = np.random.default_rng(411)
        hits = tested = 0
        for _ in range(32):
            grid = rng.exponential(size=(128, 128))
            value = sensing.detect(grid, list(range(128)), list(range(128)))
            hits += value['crossing_cells']; tested += value['tested_cells']
        measured = hits / tested
        self.assertLess(abs(measured - .001), 5 * (.001 * .999 / tested)**.5)

    def test_two_targets_stationary_negative_speed_and_edge(self):
        a = np.ones((64, 32))
        a[32, 8] = 200; a[20, 18] = 160; a[0, 0] = 1000
        value = sensing.detect(a, list(range(32)), list(range(-32, 32)))
        self.assertEqual([(p['range_m'], p['velocity_mps']) for p in value['detections']], [(8., 0.), (18., -12.)])
        self.assertIsNone(value['threshold'][0][0])
        # 11 x 7 outer window minus 3 x 3 guard, minus 11 excluded direct cells.
        self.assertEqual(value['training_cells_min'], 57)

    def test_neighbor_cluster_and_direct_path_exclusion(self):
        a = np.ones((40, 20)); a[:, :2] = 1e6; a[20, 8] = 500; a[20, 9] = 300
        value = sensing.detect(a, list(range(20)), list(range(40)), {'direct_bins': 2, 'guard_range': 2})
        self.assertEqual(len(value['detections']), 1)
        self.assertEqual(value['detections'][0]['cluster_cells'], 2)
        self.assertEqual(value['detections'][0]['column'], 8)

    def test_linear_power_and_window_validation(self):
        for grid in (np.full((32, 32), -1), np.full((32, 32), np.nan), np.ones((2, 2))):
            with self.assertRaises(ValueError): sensing.detect(grid, list(range(grid.shape[1])), list(range(grid.shape[0])))

    def test_real_ofdm_two_targets_and_analysis_branch(self):
        g = graph.demo('sensing'); built = graph.build(g)
        result = graph.run(g, built['token'])
        peaks = result['analyses'][0]['detections'][:2]
        for p, expected in zip(peaks, [(780, 37.5), (1560, -56.25)]):
            self.assertLess(abs(p['range_m'] - expected[0]), 157)
            self.assertLess(abs(p['velocity_mps'] - expected[1]), 4)
        self.assertEqual(result['merged_result']['sink'], result['branches'][0]['result']['sink'])
        self.assertEqual(result['analyses'][0]['input_hash'], result['input_hash'])

    def test_real_stationary_single_target_and_excluded_edge(self):
        p=copy.deepcopy(c.PRESETS['ofdm_isac_multi']['program'])
        q=next(b['params'] for b in p['blocks'] if b['kind']=='isac_echo_multi')
        for distance in (1560,156):
            q['targets']=json.dumps([{'range_m':distance,'velocity_mps':0,'amplitude':.3}])
            b=c.build(p);v=c.run(p,b['token'])['advanced']['wireless']['rx_isac_ofdm']['sensing']
            detected=sensing.detect(v['power'],v['range_axis_m'],v['velocity_axis_mps'])
            if distance==1560:
                peak=detected['detections'][0]
                self.assertLess(abs(peak['range_m']-distance),157)
                self.assertEqual(peak['velocity_mps'],0)
            else:
                self.assertTrue(all(row[1] is None for row in detected['threshold']))
                self.assertTrue(all(peak['column']>=3 for peak in detected['detections']))

    def test_cfar_only_edit_reuses_actual_receivers(self):
        g = graph.demo('sensing'); cache = {}
        first = graph.run(g, graph.build(g)['token'], cache)
        g['analyses'][0]['params']['pfa'] = .0001
        value = graph.run(g, graph.build(g)['token'], cache, True)
        self.assertTrue(value['shared_reused'])
        self.assertEqual(value['execution'][1]['executed'], [])
        self.assertEqual(value['input_hash'], first['input_hash'])
        self.assertGreater(value['analyses'][0]['threshold'][50][10], first['analyses'][0]['threshold'][50][10])

    def test_multi_target_parameters_and_zero_target_noise(self):
        p = copy.deepcopy(c.PRESETS['ofdm_isac_multi']['program'])
        echo = next(b for b in p['blocks'] if b['kind']=='isac_echo_multi')
        echo['params'].update(targets='[]', direct=0)
        built = c.build(p); result = c.run(p, built['token'])
        spectrum = result['advanced']['wireless']['rx_isac_ofdm']['sensing']
        value = sensing.detect(spectrum['power'], spectrum['range_axis_m'], spectrum['velocity_axis_mps'])
        self.assertLess(value['crossing_fraction'], .02)
        echo['params']['targets'] = '[{"range_m":100000}]'
        with self.assertRaisesRegex(ValueError, 'CP'): c.build(p)

    def test_graph_pdf_includes_topology_and_detection(self):
        from src import communication_report as report
        g = graph.demo('sensing'); result = graph.run(g, graph.build(g)['token'])
        raw = {'document_schema': 2, 'name': '多目标接线实验', 'graph': g, 'graphResult': result}
        pdf = report.render(raw)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf), 10000)


if __name__ == '__main__':
    unittest.main()
