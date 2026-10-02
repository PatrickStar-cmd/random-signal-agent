"""v0.2 acceptance: durability, idempotence, boundaries and full-data round trips."""
from pathlib import Path
import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['RS_AGENT_LLM_ENABLED'] = '0'
import numpy as np
from fastapi.testclient import TestClient
import server
from src.dialogue_agent import RandomSignalDialogueAgent, ConversationState
from src.signal_processing import SignalConfig, generate_random_signal, decimate_for_export
from src.tasks import TaskEngine, TaskConflict, TaskBusy
from src.workbench import ExperimentStore, snapshot, restore, export_archive, import_archive


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = server.create_app(data_dir=self.root/'data', upload_dir=self.root/'uploads')
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def post(self, route, payload):
        result = self.client.post(route, json={'session_id':'a', **payload})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def experiment(self, **params):
        return self.post('/api/experiment/run', {'template':'sine','config':{'duration':1,'sample_rate':200,'seed':42},**params})

    def test_save_restart_open_export_import_preserves_every_sample(self):
        result = self.experiment()
        self.assertEqual(len(result['state']['preprocess_comparison']['methods']),6)
        saved = self.post('/api/experiments/save', {'name':'<script>experiment</script>'})
        original = self.app.state.agent.get_session('a')
        raw = self.client.get('/api/experiments/export',params={'session_id':'a'}).content
        restored = import_archive(raw,'b')
        np.testing.assert_array_equal(restored.bundle.observed,original.bundle.observed)
        for method in original.preprocess_results:
            np.testing.assert_array_equal(restored.preprocess_results[method].signal, original.preprocess_results[method].signal)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            csv = np.loadtxt(io.BytesIO(archive.read('samples.csv')),delimiter=',',skiprows=1)
            self.assertEqual(csv.shape[0],200)
            np.testing.assert_array_equal(csv[:,1],original.bundle.observed)
            self.assertIn(b'score_terms',archive.read('report.html'))
        html = self.client.get('/api/experiments/export',params={'session_id':'a','format':'html','name':'<script>alert(1)</script>'}).text
        self.assertNotIn('<script>',html)
        self.assertIn('&lt;script&gt;',html)
        self.client.__exit__(None,None,None)
        self.app = server.create_app(data_dir=self.root/'data',upload_dir=self.root/'uploads')
        self.client = TestClient(self.app)
        self.client.__enter__()
        state = self.client.get('/api/state',params={'session_id':'a'}).json()['state']
        self.assertTrue(state['has_processed'])
        self.post('/api/experiments/open',{'id':saved['id']})
        np.testing.assert_array_equal(self.app.state.agent.get_session('a').bundle.observed,original.bundle.observed)
        imported = self.client.post('/api/experiments/import',data={'session_id':'b'},files={'file':('experiment.zip',raw)})
        self.assertEqual(imported.status_code,200,imported.text)
        self.assertTrue(imported.json()['state']['has_processed'])

    def test_templates_deterministic_and_goal_changes_are_explained(self):
        for template in ('sine','impulse','ar'):
            self.experiment(template=template)
            first = self.app.state.agent.get_session('a').bundle.observed.copy()
            self.experiment(template=template)
            np.testing.assert_array_equal(first,self.app.state.agent.get_session('a').bundle.observed)
        for goal in ('denoise','waveform','transient'):
            data = self.experiment(template='current',goal=goal)['state']['preprocess_comparison']
            self.assertEqual(data['goal'],goal)
            for row in data['methods']:
                self.assertAlmostEqual(row['score'],sum(row['score_terms'].values()),places=3)
                self.assertGreaterEqual(row['duration_ms'],0)

    def test_upload_no_reference_has_no_fabricated_snr(self):
        upload = self.client.post('/api/upload',data={'session_id':'a'},files={'file':('signal.csv',b'1\n2\n3\n4\n2\n1\n0\n-1\n-2\n-3\n')})
        self.assertEqual(upload.status_code,200,upload.text)
        data = self.experiment(template='current')['state']['preprocess_comparison']
        self.assertEqual(data['reference_mode'],'no_reference')
        for method in data['methods']:
            self.assertIsNone(method['processed_snr_db'])
            self.assertIsNone(method['snr_improvement_db'])

    def test_stream_retry_replays_without_executing_chat_twice(self):
        agent = self.app.state.agent
        with patch.object(agent,'chat',wraps=agent.chat) as chat:
            payload={'session_id':'a','request_id':'repeat','message':'你好'}
            stream=self.client.post('/api/chat/stream',json=payload)
            response=self.client.post('/api/chat',json=payload)
            self.assertEqual(response.status_code,200,response.text)
            self.assertIn('"event": "done"',stream.text)
            self.assertEqual(chat.call_count,1)
            conflict=self.client.post('/api/chat',json={**payload,'message':'new'})
            self.assertEqual(conflict.status_code,409)

    def test_async_progress_and_session_isolation(self):
        data={'session_id':'a','request_id':'async','template':'sine','config':{'duration':1},'respond_async':True}
        accepted=self.client.post('/api/experiment/run',json=data)
        self.assertEqual(accepted.status_code,202)
        key=accepted.json()['task_id']
        self.assertEqual(self.client.get(f'/api/tasks/{key}',params={'session_id':'b'}).status_code,404)
        stream=self.client.get(f'/api/tasks/{key}/events',params={'session_id':'a'}).text
        self.assertIn('"tool": "median"',stream)
        self.assertIn('"status": "success"',stream)
        saved=self.post('/api/experiments/save',{'name':'Original'})
        copied=self.post('/api/experiments/duplicate',{'id':saved['id'],'name':'Copy'})
        self.assertNotEqual(copied['id'],saved['id'])
        other=self.client.post('/api/experiments/open',json={'session_id':'b','id':saved['id']})
        self.assertEqual(other.status_code,400)
        self.assertFalse(self.client.get('/api/state',params={'session_id':'b'}).json()['state']['has_signal'])

    def test_size_numeric_and_archive_boundaries(self):
        with patch.object(server,'MAX_BODY',128):
            response=self.client.post('/api/chat',content=b'x'*129)
            self.assertEqual(response.status_code,413)
            response=self.client.post('/api/chat',content=iter([b'x'*65,b'x'*65]))
            self.assertEqual(response.status_code,413)
        for config in ({'duration':1e9},{'sample_rate':float('nan')},{'seed':1.2},{'base_frequency':200}):
            response=self.client.post('/api/experiment/run',content=json.dumps({'session_id':'a','config':config}))
            self.assertEqual(response.status_code,400,response.text)
        bad=self.client.post('/api/experiments/import',data={'session_id':'a'},files={'file':('bad.zip',b'garbage')})
        self.assertEqual(bad.status_code,400)

    def test_manifest_checksum_and_schema_reject_corruption(self):
        state=ConversationState('a',bundle=generate_random_signal(SignalConfig(duration=1)))
        document,raw=snapshot(state)
        with self.assertRaisesRegex(ValueError,'checksum'):
            restore(document,raw+b'bad')
        manifest=json.loads(document);manifest['schema_version']=999
        with self.assertRaisesRegex(ValueError,'schema'):
            restore(json.dumps(manifest),raw)

    def test_downsampling_keeps_narrow_peaks_and_shared_indices(self):
        x=np.arange(10000);a=np.zeros(10000);b=a.copy();a[91]=100;b[601]=-100
        t,pa,pb=decimate_for_export(x,a,b,max_points=520)
        self.assertLessEqual(len(t),520)
        self.assertEqual(t,sorted(t));self.assertEqual(t[0],0);self.assertEqual(t[-1],9999)
        self.assertEqual(pa[t.index(91)],100);self.assertEqual(pb[t.index(601)],-100)

    def test_batched_median_matches_scalar_reference(self):
        from src.preprocessing import _median_filter
        for n in (1, 11, 3000):
            samples=np.random.default_rng(42).normal(size=n)
            for window in (1, 7, 511):
                padded=np.pad(samples,(window//2,window//2),mode='edge')
                expected=np.array([np.median(padded[i:i+window]) for i in range(n)])
                np.testing.assert_array_equal(_median_filter(samples,window),expected)


class TaskTests(unittest.TestCase):
    def test_failed_operation_restores_previous_state(self):
        with tempfile.TemporaryDirectory() as temp:
            agent=RandomSignalDialogueAgent();engine=TaskEngine(agent,ExperimentStore(Path(temp)))
            def fail():
                agent.get_session('a').messages.append({'role':'user','content':'partial'})
                raise ValueError('expected failure')
            try:
                key=engine.submit('a','fail',{},fail)
                self.assertIn('error',engine.wait(key,'a'))
                self.assertEqual(agent.get_session('a').messages,[])
            finally:engine.close()

    def test_serialized_sessions_capacity_and_restart_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            agent=RandomSignalDialogueAgent();store=ExperimentStore(Path(temp));engine=TaskEngine(agent,store,workers=2,capacity=2)
            started=threading.Event();finish=threading.Event();calls=[]
            def operation():
                calls.append('run');started.set();finish.wait(3)
                return {'count':len(calls)}
            try:
                first=engine.submit('a','first',{'x':1},operation)
                self.assertTrue(started.wait(3))
                self.assertEqual(engine.submit('a','first',{'x':1},operation),first)
                second=engine.submit('a','second',{'x':2},operation)
                self.assertEqual(len(calls),1)
                with self.assertRaises(TaskBusy): engine.submit('b','third',{},operation)
                with self.assertRaises(TaskConflict): engine.submit('a','first',{'x':2},operation)
                finish.set();engine.wait(first,'a');engine.wait(second,'a')
                self.assertEqual(len(calls),2)
            finally: finish.set();engine.close()
            restarted=TaskEngine(RandomSignalDialogueAgent(),ExperimentStore(Path(temp)))
            try:
                self.assertEqual(restarted.submit('a','first',{'x':1},operation),first)
                self.assertEqual(restarted.wait(first,'a'),{'count':1})
                self.assertEqual(len(calls),2)
            finally: restarted.close()


if __name__=='__main__':
    log=ROOT/'logs/workbench/latest.log';log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    print(log.read_text(encoding='utf-8'));sys.exit(not result.wasSuccessful())
