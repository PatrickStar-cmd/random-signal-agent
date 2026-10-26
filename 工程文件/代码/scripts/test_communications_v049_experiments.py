"""Durable experiments, real breakpoints and independent classroom milestones."""
from pathlib import Path
import copy
import json
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import communications as c, communication_experiments as exp, communication_learning as learn
from src import communication_runtime as runtime
from src.communication_jobs import Jobs


def program(snr=4):
    return c.preset(['random_bits', 'mod_qpsk', 'awgn', 'demod_qpsk', 'sink'], {0: {'count': 256}, 2: {'esn0_db': snr}})


def wait(jobs, identifier, states=('completed', 'cancelled', 'failed')):
    for _ in range(1000):
        value = jobs.status('v049', identifier)
        if value['status'] in states:
            if value['status'] == 'failed': raise AssertionError(value['error'])
            return value
        time.sleep(.005)
    raise AssertionError('job timeout')


class Experiments(unittest.TestCase):
    def restart(self, kind, payload, reached):
        with tempfile.TemporaryDirectory() as directory:
            jobs = Jobs(directory, threading.BoundedSemaphore(1)); original = jobs.persist
            def save(job, value):
                original(job, value)
                if not value.get('not_started') and reached(value): job.cancel.set()
            jobs.persist = save
            try:
                first = jobs.start('v049', kind, payload)
                value = wait(jobs, first['id'])
                self.assertFalse(value['result']['complete'])
            finally: jobs.close()
            jobs = Jobs(directory, threading.BoundedSemaphore(1))
            try:
                self.assertEqual(jobs.status('v049', first['id'])['kind'], kind)
                second = jobs.control('v049', first['id'], 'resume')
                return wait(jobs, second['id'])['result']
            finally: jobs.close()

    def test_batch_service_restart_skips_finished_measurements(self):
        programs = [program(0), program(8)]; settings = {'seeds': [42, 142], 'frames': 2}
        expected = exp.batch(programs, settings)
        calls = []; original = exp._run
        def measured(p, seed, cancel):
            calls.append((p['blocks'][2]['params']['esn0_db'], seed))
            return original(p, seed, cancel)
        with patch.object(exp, '_run', measured):
            actual = self.restart('batch', {'programs': programs, 'settings': settings}, lambda r: r['completed'] >= 3)
        self.assertEqual(len(calls), 8)
        self.assertEqual([r['metrics'] for r in actual['rows']], [r['metrics'] for r in expected['rows']])
        self.assertTrue(actual['complete'])

    def test_target_search_restart_restores_partial_snr_seed(self):
        p = program(); built = c.build(p)
        settings = {'block_id': 'block-2', 'parameter': 'esn0_db', 'start': 0, 'stop': 4, 'step': 2, 'seeds': [42, 142], 'frames': 2}
        expected = exp.target_search(p, settings)
        calls = []; original = exp._run
        def measured(p, seed, cancel):
            calls.append(seed); return original(p, seed, cancel)
        with patch.object(exp, '_run', measured):
            actual = self.restart('target-search', {'program': p, 'token': built['token'], 'settings': settings}, lambda r: r['completed'] >= 5)
        self.assertEqual(len(calls), 12)
        self.assertEqual([(r['ber'], r['bit_count']) for r in actual['points']], [(r['ber'], r['bit_count']) for r in expected['points']])
        self.assertEqual(actual['completed'], 12)

    def test_two_dimensional_restart_restores_incomplete_row(self):
        p = program(); built = c.build(p)
        settings = {'x': {'block_id': 'block-2', 'parameter': 'esn0_db', 'values': [0, 4]},
                    'y': {'block_id': 'global', 'parameter': 'seed', 'values': [42, 142]}, 'frames': 3, 'target_errors': 10000}
        expected = learn.sweep2d(p, built['token'], settings)
        actual = self.restart('sweep2d', {'program': p, 'token': built['token'], 'settings': settings},
                              lambda r: sum(p['frames'] for p in r['points']) >= 4)
        self.assertEqual([(r['row'], r['column'], r['frames'], r['bit_errors']) for r in actual['points']],
                         [(r['row'], r['column'], r['frames'], r['bit_errors']) for r in expected['points']])

    def test_debug_breakpoint_stops_at_actual_output(self):
        with tempfile.TemporaryDirectory() as directory:
            jobs = Jobs(directory, threading.BoundedSemaphore(1)); p = program(); b = c.build(p)
            try:
                value = jobs.start('v049', 'debug', {'program': p, 'token': b['token'], 'debug_mode': 'continue',
                    'breakpoints': [{'block_id': 'block-2', 'metric': 'rms', 'operator': '>=', 'value': 0}]})
                paused = wait(jobs, value['id'], ('paused', 'failed'))
                self.assertEqual([o['id'] for o in paused['observations']], ['block-0', 'block-1', 'block-2'])
                self.assertGreater(paused['progress']['breakpoint']['actual'], 0)
                jobs.control('v049', value['id'], 'continue')
                result = wait(jobs, value['id'])['result']
                self.assertEqual(result['metrics'], c.run(p, b['token'])['metrics'])
            finally: jobs.close()

    def test_llr_breakpoint_measures_full_output(self):
        # Validate domains using a real supported coded link.
        p = copy.deepcopy(c.PRESETS['agc_soft']['program']); built = c.build(p)
        soft = next(b for b in p['blocks'] if b['kind'].startswith('soft_'))
        rule = {'block_id': soft['id'], 'metric': 'llr_uncertain_fraction', 'operator': '>=', 'value': 0}
        runtime.validate_breakpoints([rule], built)
        result, observer = runtime.observe_run(p, built['token'])
        observation = next(o for o in observer.observations if o['id'] == soft['id'])
        self.assertTrue(runtime.breakpoint_match(rule, observation))
        self.assertGreaterEqual(observation['llr_uncertain_fraction'], 0)
        self.assertLessEqual(observation['llr_uncertain_fraction'], 1)

    def test_batch_replay_seed_and_paired_statistics(self):
        value = exp.batch([program(0), program(8)], {'seeds': [42, 142], 'frames': 2})
        row = value['rows'][3]; p = copy.deepcopy(value['programs'][row['program_index']]); p['seed'] = row['seed']
        replay = c.run(p, c.build(p)['token'])
        self.assertEqual(row['metrics']['bit_errors'], replay['metrics']['bit_errors'])
        self.assertEqual(len(value['analysis']['paired']), 4)
        self.assertEqual(len(value['analysis']['distributions'][0]['metrics']['ber']['values']), 4)

    def test_independent_stage_history_hints_and_portable_submission(self):
        p = program(0)
        task = {'title': '分阶段实验', 'objective': '分别观察低信噪比和可靠传输', 'initial_program': p,
                'editable': ['blocks.block-2.esn0_db'], 'seeds': [42, 142], 'stages': [
                    {'name': '观察错误', 'goals': [{'metric': 'ber', 'operator': '>=', 'value': .01}]},
                    {'name': '可靠传输', 'goals': [{'metric': 'bit_errors', 'operator': '==', 'value': 0}]}]}
        package = exp.validate_submission({'submission_schema': 1, 'task': task})
        with self.assertRaises(ValueError): exp.classroom_stage(package, program(30), 1)
        first = exp.classroom_stage(package, p, 0)['submission']
        first['hint_events'].append({'stage': 1, 'time': '2026-10-26T00:00:00Z'})
        failed = exp.classroom_stage(first, p, 1)['submission']
        final = exp.classroom_stage(failed, program(30), 1)
        self.assertEqual(final['score'], 100)
        self.assertEqual(len(final['submission']['attempts']), 3)
        self.assertEqual(final['submission']['stages'][0]['program']['blocks'][2]['params']['esn0_db'], 0)
        restored = exp.validate_submission(json.loads(json.dumps(final['submission'])))
        self.assertEqual(restored, final['submission'])
        self.assertEqual(len(restored['hint_events']), 1)


if __name__ == '__main__': unittest.main()
