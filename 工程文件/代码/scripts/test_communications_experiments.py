"""Core v0.4.8 classroom, reproducible queue and measured target-search tests."""
from pathlib import Path
import copy
import json
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import communications as c, communication_experiments as exp


def program(snr=8):
    return c.preset(['random_bits', 'mod_qpsk', 'awgn', 'demod_qpsk', 'sink'],
                    {0: {'count': 1024}, 2: {'esn0_db': snr}})


def task(snr=0):
    return {'assignment_schema': 1, 'title': '修复海洋链路', 'kind': 'repair',
            'objective': '调整信道信噪比，恢复数字传输。', 'initial_program': program(snr),
            'editable': ['blocks.block-2.esn0_db'], 'seeds': [42, 142],
            'stages': [{'name': '基本传输', 'hint': '观察误码计数。', 'weight': 1,
                        'goals': [{'metric': 'ber', 'operator': '<=', 'value': .3}]},
                       {'name': '完整恢复', 'hint': '提高信噪比。', 'weight': 3,
                        'goals': [{'metric': 'bit_errors', 'operator': '==', 'value': 0}]}]}


class ClassroomTests(unittest.TestCase):
    def test_task_roundtrip_and_actual_repair(self):
        original = task()
        normalized = exp.validate_assignment(original)
        self.assertEqual(normalized, exp.validate_assignment(json.loads(json.dumps(normalized))))
        result = exp.classroom(normalized, program(30))
        self.assertTrue(result['passed'])
        self.assertEqual(result['score'], 100)
        self.assertEqual(result['changes'], ['blocks.block-2.esn0_db'])
        self.assertEqual(len(result['trials']), 2)
        self.assertEqual(original['initial_program']['blocks'][2]['params']['esn0_db'], 0)
        self.assertTrue(all(t['metrics']['bit_errors'] == 0 for t in result['trials']))

    def test_stages_unlock_in_order_and_weighted_score(self):
        value = task()
        value['stages'].append({'name': '收尾', 'hint': '完成前两阶段。', 'weight': 2,
                                'goals': [{'metric': 'bit_count', 'operator': '>=', 'value': 1}]})
        result = exp.classroom(value, program(0))
        self.assertTrue(result['stages'][0]['passed'])
        self.assertFalse(result['stages'][1]['passed'])
        self.assertFalse(result['stages'][2]['unlocked'])
        self.assertFalse(result['stages'][2]['passed'])
        self.assertAlmostEqual(result['score'], 100 / 6)

    def test_fixed_parameters_and_structure_are_checked(self):
        changed = program(30); changed['symbol_rate'] *= 2
        with self.assertRaisesRegex(ValueError, '固定参数'):
            exp.classroom(task(), changed)
        changed = program(30); changed['blocks'][0]['kind'] = 'pn_bits'
        with self.assertRaises(ValueError):
            exp.classroom(task(), changed)
        value = task(); value['editable'].append('blocks.missing.esn0_db')
        with self.assertRaisesRegex(ValueError, '有效参数路径'):
            exp.validate_assignment(value)

    def test_invalid_goals_and_cancellation(self):
        value = task(); value['stages'][0]['goals'][0]['value'] = float('nan')
        with self.assertRaises(ValueError):
            exp.validate_assignment(value)
        event = threading.Event(); event.set()
        with self.assertRaises(exp.runtime.Cancelled):
            exp.classroom(task(), program(), cancel=event)


class QueueTests(unittest.TestCase):
    def test_multi_project_queue_matches_direct_run_counters(self):
        programs = [program(0), program(12)]
        progress = []
        result = exp.batch(programs, {'seeds': [42, 142], 'frames': 2, 'names': ['低信噪比', '高信噪比']},
                           lambda value: progress.append(value['completed']))
        self.assertTrue(result['complete']); self.assertEqual(len(result['rows']), 8)
        self.assertEqual(progress, list(range(1, 9)))
        self.assertEqual([r['seed'] for r in result['rows'][:4]], [42, 43, 142, 143])
        for index, source in enumerate(programs):
            errors = 0
            for seed in (42, 43, 142, 143):
                trial = copy.deepcopy(source); trial['seed'] = seed
                built = c.build(trial); errors += c.run(built['program'], built['token'])['metrics']['bit_errors']
            summary = result['summaries'][index]
            self.assertEqual(summary['bit_errors'], errors)
            self.assertEqual(summary['bit_count'], 4096)
            self.assertEqual(summary['ber'], errors / 4096)
            self.assertEqual(summary['frame_duration_seconds'], 1024 / 2000)
        self.assertGreater(result['summaries'][0]['ber'], result['summaries'][1]['ber'])
        json.dumps(result, allow_nan=False)

    def test_cancellation_returns_completed_measurements(self):
        event = threading.Event()
        result = exp.batch([program()], {'seeds': [42, 142]}, lambda value: event.set(), event)
        self.assertFalse(result['complete'])
        self.assertEqual(result['completed'], 1)
        self.assertEqual(len(result['rows']), 1)

    def test_queue_bounds_and_unique_seed_trials(self):
        for settings in ({'seeds': [42, 42]}, {'seeds': [42, 43], 'frames': 2},
                         {'seeds': list(range(0, 3200, 100)), 'frames': 32}, {'mode': 'unknown'}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                exp.batch([program()], settings)

    def test_protocol_queue_uses_packet_goodput_and_latency(self):
        result = exp.batch([program(30)], {'seeds': [42], 'mode': 'protocol',
                                          'protocol': {'snr_db': 30, 'feedback_loss': 0, 'packets': 2}})
        self.assertTrue(result['complete'])
        self.assertGreater(result['summaries'][0]['goodput_bps'], 0)
        self.assertGreater(result['summaries'][0]['mean_delivery_latency_seconds'], 0)


class TargetSearchTests(unittest.TestCase):
    def settings(self):
        return {'block_id': 'block-2', 'parameter': 'esn0_db', 'start': -2, 'stop': 16,
                'step': 6, 'target_ber': .01, 'seeds': [42, 142], 'frames': 1}

    def test_selects_lowest_measured_passing_grid_point(self):
        original = program(); result = exp.target_search(original, self.settings())
        self.assertTrue(result['complete']); self.assertEqual(result['completed'], 8)
        passing = [p for p in result['points'] if p['ber'] <= .01]
        self.assertTrue(passing)
        self.assertEqual(result['selected']['snr_db'], min(p['snr_db'] for p in passing))
        self.assertEqual(result['selected']['program']['blocks'][2]['params']['esn0_db'], result['selected']['snr_db'])
        self.assertEqual(original['blocks'][2]['params']['esn0_db'], 8)
        for point in result['points']:
            self.assertEqual(point['bit_count'], 2048)
            self.assertEqual(point['ber'], point['bit_errors'] / point['bit_count'])

    def test_search_bounds_cancellation_and_no_qualifying_point(self):
        settings = self.settings(); settings.update(stop=-2, target_ber=0)
        result = exp.target_search(program(), settings)
        self.assertIsNone(result['selected']); self.assertTrue(result['complete'])
        event = threading.Event()
        result = exp.target_search(program(), self.settings(), lambda value: event.set(), event)
        self.assertFalse(result['complete']); self.assertEqual(result['completed'], 1)
        settings = self.settings(); settings['step'] = .01
        with self.assertRaises(ValueError):
            exp.target_search(program(), settings)


if __name__ == '__main__':
    unittest.main()
