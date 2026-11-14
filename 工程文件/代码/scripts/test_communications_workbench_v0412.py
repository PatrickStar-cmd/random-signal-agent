"""Whole-document execution, measured tools, graph debugging and task recovery."""
import copy
import math
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import communications as c, communication_graph_v0411 as graph
from src import communication_workbench_v0412 as workbench


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.document = {'document_schema': 2, 'name': '分支实验', 'graph': graph.demo(), 'tools': []}

    def test_single_batch_and_restored_row_use_same_complete_graph(self):
        direct = workbench.run_document(self.document)
        task = workbench.run_task(self.document, {'seeds': [42], 'frames': 1})
        self.assertTrue(task['complete'])
        self.assertEqual(task['last_result']['metrics'], direct['metrics'])
        restored = workbench.restore_trial(task, 0)
        self.assertEqual(workbench.run_document(restored)['metrics'], direct['metrics'])
        self.assertEqual(task['rows'][0]['scopes'], ['shared', 'rx1', 'rx2', 'merge', 'tail'])

    def test_whole_graph_debug_pauses_at_actual_scoped_output(self):
        paused, release = threading.Event(), threading.Event()
        seen = []; active = []; contexts = []
        def gate(row):
            seen.append(row)
            self.assertIn(row['local_id'], active[-1].values)
            if row['id'] == 'rx2/block-7':
                paused.set()
                self.assertTrue(release.wait(5))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(workbench.run_document, self.document, gate=gate,
                                 on_context=active.append, contexts=contexts)
            self.assertTrue(paused.wait(5))
            self.assertFalse(future.done())
            self.assertNotIn('merge', [o['id'] for o in seen])
            release.set(); debugged = future.result(timeout=10)
        ordinary = workbench.run_document(self.document)
        self.assertEqual(debugged['result']['sink'], ordinary['result']['sink'])
        self.assertEqual(debugged['metrics'], ordinary['metrics'])
        self.assertEqual([o['id'] for o in seen][-3:], ['merge', 'tail/block-9', 'tail/block-10'])
        self.assertEqual([o['id'] for o in debugged['observations']], [o['id'] for o in seen])
        self.assertTrue(all(not o['reused'] for o in debugged['observations']))
        self.assertEqual(len(set(o['id'] for o in seen)), len(seen))
        self.assertEqual(seen[-3]['context_index'], 2)

    def test_background_graph_breakpoints_page_active_receiver_and_merge(self):
        from src.communication_jobs import Jobs
        built = workbench.build_document(self.document)
        with tempfile.TemporaryDirectory() as directory:
            jobs = Jobs(directory, threading.BoundedSemaphore(1))
            try:
                receipt = jobs.start('graph-scope', 'workbench-debug', {'document': self.document, 'token': built['token'],
                    'debug_mode': 'continue', 'breakpoints': [{'block_id': 'rx2/block-7'}, {'block_id': 'merge'}]})
                job = jobs.get('graph-scope', receipt['id'])
                for node, index in [('rx2/block-7', 1), ('merge', 2)]:
                    with job.condition:
                        self.assertTrue(job.condition.wait_for(lambda: job.status == 'paused' and
                            job.progress.get('observation', {}).get('id') == node, timeout=8))
                    values = jobs.window('graph-scope', job.id, node, 0, 13, branch=index)
                    self.assertEqual(values['plot_count'], 13)
                    self.assertEqual(job.progress['total'], len(built['nodes']))
                    self.assertEqual(job.progress['completed'], len(job.trace))
                    jobs.control('graph-scope', job.id, 'continue')
                with job.condition:
                    self.assertTrue(job.condition.wait_for(lambda: job.status in ('completed', 'failed'), timeout=8))
                self.assertEqual(job.status, 'completed', job.error)
                self.assertEqual(job.progress['completed'], len(built['nodes']))
                self.assertEqual(job.progress['total'], len(built['nodes']))
                self.assertEqual(job.result['metrics']['ber'], 0)
            finally: jobs.close()

    def test_scoped_scan_reuses_same_input_and_unchanged_receiver(self):
        task = workbench.run_task(self.document, {'mode': 'scan', 'seeds': [42], 'axes': [
            {'path': 'rx2/block-7/step_size', 'values': [.05, .1]}]})
        self.assertEqual(task['completed'], 2)
        first, second = task['rows']
        self.assertEqual(first['input_hash'], second['input_hash'])
        sections = {v['section']: v for v in second['execution']}
        self.assertEqual(sections['shared']['executed'], [])
        self.assertEqual(sections['rx1']['executed'], [])
        self.assertTrue(sections['rx2']['executed'])
        observations = {o['id']: o for o in task['last_result']['observations']}
        self.assertTrue(observations['rx1/block-7']['reused'])
        self.assertFalse(observations['rx2/block-7']['reused'])
        restored = workbench.restore_trial(task, 0)
        self.assertEqual(restored['graph']['branches'][1]['blocks'][1]['params']['step_size'], .05)

    def test_upstream_axis_changes_input(self):
        task = workbench.run_task(self.document, {'mode': 'scan', 'axes': [
            {'path': 'shared/block-5/esn0_db', 'values': [12, 18]}]})
        self.assertNotEqual(task['rows'][0]['input_hash'], task['rows'][1]['input_hash'])
        self.assertTrue(task['rows'][1]['execution'][0]['executed'])

    def test_analysis_parameter_scan_retains_full_graph(self):
        d = {**self.document, 'graph': graph.demo('sensing')}
        task = workbench.run_task(d, {'axes': [{'path': 'analysis/cfar1/pfa', 'values': [.001, .0001]}]})
        self.assertEqual(task['rows'][1]['execution'][1]['executed'], [])
        self.assertIn('cfar1.detections', task['rows'][1]['metrics'])
        self.assertEqual(workbench.restore_trial(task, 1)['graph']['analyses'][0]['params']['pfa'], .0001)

    def test_tools_are_derived_from_full_actual_arrays(self):
        self.document['tools'] = [
            {'id': 'probe', 'kind': 'probe', 'source': 'rx1/block-8', 'start': 50, 'count': 27},
            {'id': 'compare', 'kind': 'reference', 'reference': 'rx1/block-8', 'source': 'rx2/block-8',
             'metric': 'mse', 'reference_start': 7, 'source_start': 9, 'count': 81},
            {'id': 'metrics', 'kind': 'metrics', 'metrics': ['rx1.ber', 'rx2.ber', 'merged.ber']},
            {'id': 'check', 'kind': 'assertion', 'metric': 'merged.ber', 'operator': '<=', 'value': .01}]
        contexts = []; result = workbench.run_document(self.document, contexts=contexts)
        probe, compare, metrics, check = result['tools']
        np.testing.assert_array_equal(probe['i'], contexts[0].values['block-8'][50:77])
        expected = np.mean(abs(contexts[0].values['block-8'][7:88] - contexts[1].values['block-8'][9:90]) ** 2)
        self.assertAlmostEqual(compare['value'], float(expected))
        self.assertEqual(compare['count'], 81)
        self.assertEqual(metrics['metrics']['merged.ber'], result['result']['metrics']['ber'])
        self.assertEqual(check['samples'], result['result']['metrics']['bit_count'])
        self.assertTrue(check['passed'])

    def test_reference_domain_and_nonoverlap_validation(self):
        self.document['tools'] = [{'id': 'r', 'kind': 'reference', 'reference': 'shared/block-0',
                                   'source': 'rx1/block-8', 'metric': 'mse'}]
        with self.assertRaisesRegex(ValueError, '同类型'): workbench.run_document(self.document)
        self.document['tools'][0].update(reference='rx1/block-8', source_start=900000)
        with self.assertRaisesRegex(ValueError, '有效样本'): workbench.run_document(self.document)

    def test_linear_bit_reference_and_analog_execution(self):
        p = c.preset(['random_bits', 'mod_bpsk', 'awgn', 'demod_bpsk', 'sink'], {2: {'esn0_db': 30}})
        d = {'document_schema': 2, 'program': p, 'tools': [
            {'id': 'r', 'kind': 'reference', 'reference': 'linear/block-0', 'source': 'linear/block-3', 'metric': 'ber'},
            {'id': 'a', 'kind': 'assertion', 'metric': 'ber', 'operator': '==', 'value': 0}]}
        measured = workbench.run_document(d)
        self.assertEqual(measured['tools'][0]['value'], 0)
        self.assertTrue(measured['tools'][1]['passed'])
        analog = next(v['program'] for v in c.PRESETS.values() if any(b['kind'] == 'mod_am' for b in v['program']['blocks']))
        result = workbench.run_document(analog)
        self.assertEqual(result['scope'], 'linear')
        self.assertGreater(len(result['observations']), 0)

    def test_multidocument_queue_names_and_paired_seeds(self):
        second = copy.deepcopy(self.document); second['name'] = '第二工程'
        second['graph']['branches'][1]['blocks'][1]['params']['step_size'] = .08
        second['delivery'] = {'records': [{'taskResult': {'rows': ['old result']}}]}
        task = workbench.run_task(self.document, {'documents': [self.document, second], 'seeds': [7, 17]})
        self.assertEqual(task['completed'], 4)
        self.assertEqual([s['name'] for s in task['summaries']], ['分支实验', '第二工程'])
        self.assertEqual([r['seed'] for r in task['rows']], [7, 17, 7, 17])
        self.assertNotIn('delivery', task['documents'][1])

    def test_cancel_checkpoint_resume_and_task_identity(self):
        cancel = threading.Event()
        settings = {'seeds': [42, 52]}
        result = workbench.run_task(self.document, settings, progress=lambda v: cancel.set(), cancel=cancel)
        self.assertFalse(result['complete']); self.assertEqual(result['completed'], 1)
        finished = workbench.run_task(self.document, settings, resume=result)
        self.assertTrue(finished['complete']); self.assertEqual(finished['completed'], 2)
        with self.assertRaisesRegex(ValueError, '原任务'):
            workbench.run_task(self.document, {'seeds': [42]}, resume=result)

    def test_classroom_and_pareto_use_measured_graph_constraints(self):
        task = workbench.run_task(self.document, {'mode': 'pareto',
            'axes': [{'path': 'shared/block-5/esn0_db', 'values': [5, 18]}],
            'constraints': [{'metric': 'merged.ber', 'operator': '<=', 'value': .001}]})
        self.assertEqual(len(task['summaries']), 2)
        self.assertTrue(task['summaries'][1]['feasible']); self.assertTrue(task['summaries'][1]['pareto'])
        self.document['tools'] = [{'id': 'a', 'kind': 'assertion', 'metric': 'merged.ber', 'operator': '<', 'value': 0}]
        graded = workbench.run_task(self.document, {'mode': 'classroom'})
        self.assertFalse(graded['passed'])
        self.assertFalse(graded['summaries'][0]['feasible'])

    def test_diagnostics_locate_missing_edge_and_parameter(self):
        g = self.document['graph']; removed = g['edges'].pop(2)
        issue = workbench.diagnose(self.document)['issues'][0]
        self.assertEqual(issue['edge'], removed); self.assertEqual(issue['node'], removed['to'])
        g['edges'] = graph.connections(g)
        g['branches'][1]['blocks'][1]['params']['step_size'] = -1
        issue = workbench.diagnose(self.document)['issues'][0]
        self.assertEqual(issue['node'], 'rx2/block-7'); self.assertEqual(issue['field'], 'step_size')
        g['branches'][1]['blocks'][1]['params']['step_size'] = .1
        self.assertTrue(workbench.diagnose(self.document)['valid'])
        g['branches'][0]['blocks'].reverse()
        self.assertTrue(workbench.diagnose(self.document)['valid'])

    def test_build_identifies_nodes_parameters_and_tool_changes(self):
        before = workbench.build_document(self.document)
        self.document['graph']['layout']['merge'] = {'x': 300, 'y': 200}
        after = workbench.build_document(self.document)
        self.assertEqual(before['token'], after['token'])
        self.assertIn('merge', [n['id'] for n in after['nodes']])
        self.assertIn('rx1/block-7/step_size', [p['path'] for p in after['parameters']])
        labels = {p['path']: p['label'] for p in after['parameters']}
        self.assertIn('采样率', labels['globals/sample_rate'])
        self.assertIn(self.document['graph']['branches'][0]['name'], labels['rx1/block-7/step_size'])
        self.assertNotIn('block-7', labels['rx1/block-7/step_size'])
        self.document['tools'] = [{'id': 'a', 'kind': 'assertion', 'metric': 'ber', 'operator': '<=', 'value': .1}]
        self.assertNotEqual(before['token'], workbench.build_document(self.document)['token'])

    def test_task_limits_and_unknown_paths_fail_before_execution(self):
        with self.assertRaisesRegex(ValueError, '完整路径'):
            workbench.run_task(self.document, {'axes': [{'path': 'rx7/block-7/x', 'values': [1]}]})
        with self.assertRaisesRegex(ValueError, '256'):
            workbench.run_task(self.document, {'seeds': list(range(0, 3200, 100)), 'frames': 16})
        with self.assertRaisesRegex(ValueError, '观察点'):
            workbench.validate_tools({**self.document, 'tools': [{'id': 'p', 'kind': 'probe', 'source': 'missing'}]})

    def test_symbol_assertion_uses_actual_symbol_denominator(self):
        measured = workbench.run_document({'document_schema': 2,
            'program': c.preset(['random_bits', 'mod_qpsk', 'awgn', 'demod_qpsk', 'sink']),
            'tools': [{'id': 'ser', 'kind': 'assertion', 'metric': 'ser', 'operator': '<=', 'value': 1},
                      {'id': 'evm', 'kind': 'assertion', 'metric': 'evm_percent', 'operator': '<=', 'value': 100}]})
        self.assertEqual(measured['metrics']['ser'], measured['metrics']['symbol_errors'] / measured['metrics']['symbol_count'])
        for tool in measured['tools']:
            self.assertEqual(tool['samples'], measured['metrics']['symbol_count'])
            self.assertEqual(tool['sample_unit'], 'symbols')

    def test_parameter_directory_only_offers_numeric_scan_candidates(self):
        for preset in c.PRESETS.values():
            for row in workbench.build_document(preset['program'])['parameters']:
                self.assertIn(type(row['value']), (int, float, bool), row['path'])
                self.assertTrue(math.isfinite(row['value']), row['path'])
                if row['type'] == 'select':
                    self.assertTrue(all(type(v) in (int, float) and math.isfinite(v)
                                        for v in row['spec']['choices']), row['path'])
        params = c.BLOCKS['rx_equalizer']['params']
        strings = {**params['algorithm'], 'choices': ['LMS', 'NLMS'], 'default': 'NLMS'}
        with patch.dict(params, {'algorithm': strings}):
            self.assertNotIn('rx1/block-7/algorithm', [row['path'] for row in workbench.parameter_paths(self.document)])


if __name__ == '__main__': unittest.main()
