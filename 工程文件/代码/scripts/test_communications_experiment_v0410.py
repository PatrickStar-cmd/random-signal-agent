"""Core acceptance for measured design tools and classroom/scenario execution."""
from pathlib import Path
import copy
import sys
import threading
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import communications as c, communication_experiment_v0410 as lab
from src import communication_experiments as exp, communication_runtime as runtime


def program(snr=8):
    return c.preset(['random_bits', 'mod_qpsk', 'awgn', 'demod_qpsk', 'sink'],
                    {0: {'count': 256}, 2: {'esn0_db': snr}})


def submission(student='同学甲'):
    initial = program(30)
    task = {'title': '实测课堂作业', 'objective': '调整 SNR 并验收', 'initial_program': initial,
            'editable': ['blocks.block-2.esn0_db'], 'seeds': [42],
            'stages': [{'name': '可靠传输', 'weight': 1, 'hint': '观察误码',
                        'goals': [{'metric': 'ber', 'operator': '==', 'value': 0}]}]}
    raw = {'submission_schema': 1, 'student': student, 'task': task, 'program': initial,
           'stages': [None], 'attempts': [], 'hint_events': []}
    return exp.classroom_stage(raw, initial, 0)['submission']


class InspectionTests(unittest.TestCase):
    def test_actual_codec_input_and_iteration_traces(self):
        kinds = [('conv_encode', 'conv_soft_decode'), ('ldpc_encode', 'ldpc_decode'),
                 ('polar_encode', 'polar_decode'), ('turbo_encode', 'turbo_decode')]
        for encoder, decoder in kinds:
            with self.subTest(decoder=decoder):
                p = c.preset(['random_bits', encoder, 'mod_bpsk', 'awgn', 'soft_bpsk', decoder, 'sink'], {0: {'count': 64}})
                result, _ = lab._run(p, 42)
                trace = next(item for item in lab.inspect_run(p, result)['traces'] if item['kind'] == decoder)
                observations = result['experience']['observations']
                actual = next(item for item in observations if item['id'] == 'block-4')
                self.assertEqual(trace['input']['count'], actual['count'])
                self.assertEqual(trace['input']['i'], actual['i'][:64])
                self.assertTrue(trace['trace']['history'])

    def test_real_trace_identity_and_profile(self):
        p = program()
        trace = {'block_id': 'block-3', 'kind': 'viterbi', 'input': {'count': 200, 'i': [7, -4]},
                 'output': {'count': 100, 'i': [0, 1]}, 'trace': {'history': [{'step': 1, 'scores': [0, 4]}]}}
        result = {'metrics': {'ber': .2}, 'advanced': {'algorithm_traces': [trace]}, 'experience': {'observations': [
            {'id': 'block-3', 'kind': 'demod_qpsk', 'label': '译码', 'elapsed_ms': 5, 'rms': 2, 'peak': 3,
             'domain': 'LLR', 'llr_uncertain_fraction': .6, 'count': 100},
            {'id': 'block-2', 'kind': 'awgn', 'elapsed_ms': 1, 'rms': 1, 'peak': 2, 'domain': '复符号', 'count': 100}]}}
        value = lab.inspect_run(p, result)
        self.assertEqual(value['traces'], [trace]); self.assertIsNot(value['traces'][0], trace)
        self.assertEqual(value['profile'][0]['id'], 'block-3')
        self.assertAlmostEqual(value['profile'][0]['share'], 5 / 6)
        diagnostic = value['diagnostics'][0]
        self.assertEqual(diagnostic['evidence']['actual'], .6)
        self.assertEqual(diagnostic['comparison']['change']['after'], 11)
        self.assertEqual(p['blocks'][2]['params']['esn0_db'], 8)
        self.assertEqual(lab.inspect_run(p, {'metrics': {}})['traces'], [])

    def test_observed_profile_from_actual_engine(self):
        result, _ = lab._run(program(), 42)
        inspection = lab.inspect_run(program(), result)
        self.assertGreaterEqual(inspection['observation_count'], 4)
        self.assertTrue(all(row['elapsed_ms'] >= 0 for row in inspection['profile']))


class OptimizationTests(unittest.TestCase):
    def settings(self):
        return {'axes': [{'block_id': 'block-2', 'parameter': 'esn0_db', 'values': [0, 25]},
                         {'block_id': 'global', 'parameter': 'symbol_rate', 'values': [500, 1000]}],
                'seeds': [42, 142], 'frames': 1,
                'constraints': [{'metric': 'ber', 'operator': '<=', 'value': .01}],
                'objectives': [{'metric': 'ber', 'direction': 'min'}, {'metric': 'net_bit_rate', 'direction': 'max'}]}

    def test_real_grid_feasibility_pareto_and_replay(self):
        progress = []
        result = lab.optimize(program(), self.settings(), progress.append)
        self.assertEqual(result['completed'], 8)
        self.assertEqual(len(result['candidates']), 4)
        self.assertEqual(result['pareto_indices'], [3])
        row = result['candidates'][3]
        self.assertEqual(row['values'], [25, 1000])
        self.assertEqual(row['metrics']['bit_count'], 512)
        self.assertTrue(row['feasible'])
        _, replay = lab._run(row['program'], row['trials'][0]['seed'])
        self.assertEqual(replay['bit_errors'], row['trials'][0]['metrics']['bit_errors'])
        self.assertEqual(progress[-1]['completed'], 8)

    def test_tradeoff_front_and_equal_points(self):
        values = [{'metrics': {'ber': b, 'rate': r}, 'feasible': f} for b, r, f in
                  [(.1, 10, True), (.2, 20, True), (.2, 10, True), (.0, 100, False), (.1, 10, True)]]
        self.assertEqual(lab.pareto_indices(values, [{'metric': 'ber', 'direction': 'min'}, {'metric': 'rate', 'direction': 'max'}]), [0, 1, 4])

    def test_invalid_metric_axis_and_cancellation(self):
        settings = self.settings(); settings['objectives'][0]['metric'] = 'invented_metric'
        with self.assertRaisesRegex(ValueError, '测量指标'):
            lab.optimize(program(), settings)
        settings = self.settings(); settings['axes'][1] = copy.deepcopy(settings['axes'][0])
        with self.assertRaisesRegex(ValueError, '不同参数'):
            lab.optimize(program(), settings)
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(runtime.Cancelled):
            lab.optimize(program(), self.settings(), cancel=cancel)


class ClassroomTests(unittest.TestCase):
    def test_same_task_import_and_independent_snapshot_recheck(self):
        first, second = submission(), submission('同学乙')
        second['stages'][0]['program']['blocks'][2]['params']['esn0_db'] = 0
        second['program']['blocks'][2]['params']['esn0_db'] = 30
        imported = lab.classroom_import([first, second])
        self.assertEqual(imported['count'], 2)
        self.assertEqual(imported['rows'][1]['imported_score'], 100)
        checked = lab.recheck([first, second])
        self.assertEqual(checked['rows'][0]['recheck']['score'], 100)
        self.assertEqual(checked['rows'][1]['recheck']['score'], 0)
        self.assertEqual(checked['rows'][1]['submission']['program']['blocks'][2]['params']['esn0_db'], 30)
        self.assertEqual(checked['completed'], 2)

    def test_task_identity_and_cancel(self):
        first, second = submission(), submission('同学乙')
        second['task']['stages'][0]['goals'][0]['value'] = .1
        with self.assertRaisesRegex(ValueError, '同一题目'):
            lab.classroom_import([first, second])
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(runtime.Cancelled):
            lab.recheck([first], cancel=cancel)


class ScenarioTests(unittest.TestCase):
    def test_step_linear_values_and_recovery_counts(self):
        settings = {'frames': 6, 'events': [
            {'frame': 2, 'block_id': 'block-2', 'parameter': 'esn0_db', 'value': 0, 'transition': 'step'},
            {'frame': 4, 'block_id': 'block-2', 'parameter': 'esn0_db', 'value': 30, 'transition': 'linear'}],
            'recovery': {'metric': 'ber', 'operator': '<=', 'value': 0, 'consecutive': 2}}
        result = lab.scenario(program(30), settings)
        self.assertEqual([row['parameters'][0]['value'] for row in result['rows']], [30, 0, 15, 30, 30, 30])
        self.assertEqual([row['seed'] for row in result['rows']], list(range(42, 48)))
        self.assertEqual(result['recoveries'][1]['recovery_frames'], 0)
        self.assertEqual(result['recoveries'][1]['confirmation_frame'], 5)
        self.assertEqual(result['last_result']['experience']['frame'], 5)

    def test_shared_state_actual_frequency_oscillator(self):
        p = c.preset(['random_bits', 'mod_qpsk', 'frequency_offset', 'awgn', 'demod_qpsk', 'sink'],
                     {0: {'count': 128}, 2: {'hz': 1}, 3: {'esn0_db': 30}})
        contexts = []
        result = lab.scenario(p, {'frames': 3, 'events': [{'frame': 2, 'block_id': 'block-2', 'parameter': 'hz', 'value': 2}],
                                 'recovery': {'metric': 'ber', 'operator': '<=', 'value': 1, 'consecutive': 1}}, observer_callback=contexts.append)
        self.assertGreater(result['state_count'], 0)
        self.assertIs(contexts[0].states, contexts[2].states)
        phase = contexts[-1].states['block-2:frequency_offset']['phase']
        expected = (2 * np.pi * 64 * (1 + 2 + 2) / p['symbol_rate']) % (2 * np.pi)
        self.assertAlmostEqual(phase, expected)

    def test_cancel_and_channel_parameters(self):
        settings = {'frames': 2, 'events': [{'frame': 1, 'block_id': 'block-0', 'parameter': 'count', 'value': 512}]}
        with self.assertRaisesRegex(ValueError, '信道积木'):
            lab.scenario(program(), settings)
        settings['events'] = [{'frame': 1, 'block_id': 'block-2', 'parameter': 'esn0_db', 'value': 4}]
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(runtime.Cancelled):
            lab.scenario(program(), settings, cancel=cancel)


class ReportMaterialsTests(unittest.TestCase):
    def test_long_teacher_comments_render_as_complete_paginated_material(self):
        from src import communication_report as report
        from src.communication_report_materials import materials
        package = lab.classroom_import([submission()]); comment = '观察频偏并记录每一帧恢复情况。' * 200
        package['rows'][0]['comment'] = comment
        doc = {'document_schema': 2, 'name': '教师评阅报告', 'program': program(),
               'v0410': {'teacher': package}, 'report': {'materials': ['teacher-review', 'teacher-comments']}}
        item = next(item for item in materials(doc) if item['id'] == 'teacher-comments')
        self.assertEqual(''.join(row[1] for row in item['rows']), comment)
        self.assertTrue(report.render(doc).startswith(b'%PDF'))

    def test_design_materials_use_saved_measured_values(self):
        from src.communication_report_materials import materials, prepare
        p = program(); result, _ = lab._run(p, 42)
        settings = OptimizationTests().settings(); settings.update(seeds=[42])
        design = {'inspection': lab.inspect_run(p, result), 'optimization': lab.optimize(p, settings),
                  'teacher': lab.recheck([submission()]),
                  'scenarioResult': lab.scenario(p, {'frames': 2, 'events': [{'frame': 1, 'block_id': 'block-2', 'parameter': 'esn0_db', 'value': 30}]}),
                  'flowResult': {'branches': [{'name': '分支一', 'result': result}], 'merged_result': result, 'merge': {'domain': 'symbols', 'mode': 'weighted', 'weights': [.5, .5], 'count': 128}}}
        doc = {'v0410': design, 'result': result}
        available = {item['id']: item for item in materials(doc)}
        self.assertTrue({'run-profile', 'design-pareto', 'teacher-review', 'scenario-metrics', 'scenario-recovery', 'flow-merge'} <= available.keys())
        self.assertEqual(available['scenario-metrics']['series'][0]['x'], [1, 2])
        self.assertEqual(available['teacher-review']['rows'][0][3], 100)
        doc['report'] = {'materials': ['design-pareto', 'scenario-recovery']}
        self.assertEqual([item['id'] for item in prepare(doc)[1]], ['design-pareto', 'scenario-recovery'])

    def test_wireless_and_turbo_report_materials_are_actual(self):
        from src.communication_report_materials import materials
        expectations = {'mlse_bpsk': 'rx_mlse-trellis', 'music_mvdr': 'rx_music-music',
                        'tdl_a': 'tdl-delay-power', 'self_describing_frames': 'self-frame-events',
                        'ofdm_isac': 'rx_isac_ofdm-range-doppler', 'turbo_logmap': 'run-trace-block-5'}
        for preset, expected in expectations.items():
            with self.subTest(preset=preset):
                p = c.PRESETS[preset]['program']; result, _ = lab._run(p, 42)
                items = {item['id']: item for item in materials({'result': result})}
                self.assertIn(expected, items)
                if preset == 'ofdm_isac':
                    sensing = result['advanced']['wireless']['rx_isac_ofdm']['sensing']
                    self.assertEqual(items[expected]['heatmap']['x'], sensing['range_axis_m'])
                    self.assertEqual(items[expected]['heatmap']['y'], sensing['velocity_axis_mps'])
                    self.assertEqual(items[expected]['heatmap']['values'], sensing['power_db'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
