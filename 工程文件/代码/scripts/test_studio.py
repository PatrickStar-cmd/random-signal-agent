"""v0.2.5 acceptance: real-data import, comparison, cancellation and safe cleanup."""
from pathlib import Path
import copy
import io
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['RS_AGENT_LLM_ENABLED']='0'
import numpy as np
from fastapi.testclient import TestClient
import server
from src.data_import import inspect_data
from src.dialogue_agent import RandomSignalDialogueAgent, ConversationState
from src.signal_processing import SignalConfig, generate_random_signal
from src.tasks import TaskEngine, TaskBusy, check_cancelled
from src.workbench import ExperimentStore, export_archive, import_archive
from src.limits import LIMITS


class ImportTests(unittest.TestCase):
    def test_select_columns_units_headers_and_preserve_original_rows(self):
        raw=b'time_ms,unused,signal\n0,label,1\n5,text,2\n10,note,3\n'
        preview,bundle=inspect_data(raw,{'signal_column':2,'time_column':0,'time_unit':'ms'})
        self.assertTrue(preview['valid']);self.assertEqual(preview['sample_rate'],200)
        self.assertEqual(preview['preview'][0]['line'],2)
        np.testing.assert_array_equal(bundle.observed,[1,2,3])
        np.testing.assert_array_equal(bundle.time,[0,.005,.01])
        self.assertFalse(bundle.has_clean_reference)
        again,_=inspect_data(raw,preview['mapping']);self.assertEqual(preview['token'],again['token'])

    def test_missing_nonfinite_and_time_errors_are_located_not_skipped(self):
        cases=[(b't,x\n0,1\n.005,\n.01,3',3),(b't,x\n0,1\n.005,nan\n.01,3',3),
               (b't,x\n0,1\n0,2\n.01,3',3),(b't,x\n0,1\n.005,2\n.012,3',3)]
        for raw,line in cases:
            preview,bundle=inspect_data(raw)
            self.assertFalse(preview['valid']);self.assertIsNone(bundle)
            self.assertTrue(any(issue['line']==line for issue in preview['issues']))
            self.assertEqual(preview['rows'],3)
        preview,_=inspect_data(b'0,bad\n1,2\n2,3')
        self.assertFalse(preview['valid']);self.assertEqual(preview['issues'][0]['line'],1)

    def test_manual_time_delimiters_and_bounds(self):
        for raw,delimiter in [(b'1;label\n2;text','semicolon'),(b'1\tlabel\n2\ttext','tab'),(b'1 label\n2 text','space')]:
            preview,bundle=inspect_data(raw,{'header':'no','time_column':None,'signal_column':0,'sample_rate':50})
            self.assertTrue(preview['valid']);self.assertEqual(preview['mapping']['delimiter'],delimiter)
            np.testing.assert_array_equal(bundle.time,[0,.02])
        for options in ({'signal_column':99},{'time_unit':'minute'},{'sample_rate':0},{'signal_column':True},{'unknown':1}):
            with self.assertRaises(ValueError):inspect_data(b'1\n2',options)
        with patch.dict(LIMITS,max_samples=2):
            with self.assertRaises(ValueError):inspect_data(b'1\n2\n3')
        with self.assertRaises(ValueError):inspect_data(b'\xff')


class StudioHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.app=server.create_app(data_dir=self.root/'data',upload_dir=self.root/'uploads')
        self.client=TestClient(self.app);self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None,None,None);self.temp.cleanup()
    def post(self,path,payload):
        r=self.client.post(path,json={'session_id':'a',**payload});self.assertEqual(r.status_code,200,r.text);return r.json()
    def experiment(self,**extra):
        return self.post('/api/experiment/run',{'template':'sine','config':{'duration':1,'sample_rate':80},**extra})
    def saved(self,name):return self.post('/api/experiments/save',{'name':name})['id']

    def test_preview_confirmation_import_and_provenance_roundtrip(self):
        raw=b't_ms,spare,voltage\n0,foo,1\n5,bar,2\n10,baz,3'
        options={'time_column':0,'signal_column':2,'time_unit':'ms'}
        form={'session_id':'a','options':json.dumps(options)};files={'file':('sensor.csv',raw)}
        preview=self.client.post('/api/data/preview',data=form,files=files).json()
        self.assertTrue(preview['valid']);self.assertFalse(self.app.state.agent.get_session('a').bundle)
        imported=self.client.post('/api/data/import',data={**form,'token':preview['token'],'request_id':'import-once'},files=files)
        self.assertEqual(imported.status_code,200,imported.text)
        replay=self.client.post('/api/data/import',data={**form,'token':preview['token'],'request_id':'import-once'},files=files)
        self.assertEqual(replay.json(),imported.json())
        state=self.app.state.agent.get_session('a');self.assertEqual(state.acquisition_plan['mapping']['signal_column'],2)
        restored=import_archive(export_archive(state,'Sensor'),'b')
        np.testing.assert_array_equal(restored.bundle.observed,[1,2,3]);self.assertEqual(restored.acquisition_plan,state.acquisition_plan)
        changed=self.client.post('/api/data/import',data={**form,'token':preview['token']},files={'file':('sensor.csv',raw+b'\n15,other,4')})
        self.assertEqual(changed.status_code,400,changed.text)
        np.testing.assert_array_equal(self.app.state.agent.get_session('a').bundle.observed,[1,2,3])

    def test_invalid_import_and_preview_do_not_replace_current_experiment(self):
        self.experiment();before=self.app.state.agent.get_session('a').bundle.observed.copy()
        for route in ('preview','import'):
            response=self.client.post('/api/data/'+route,data={'session_id':'a'},files={'file':('bad.csv',b't,x\n0,1\n1,\n2,3')})
            self.assertEqual(response.status_code,200 if route=='preview' else 400)
        np.testing.assert_array_equal(self.app.state.agent.get_session('a').bundle.observed,before)

    def test_comparison_eligibility_goals_data_and_scoring_versions(self):
        self.experiment();a=self.saved('A');b=self.saved('B')
        compare=lambda ids:self.post('/api/experiments/compare',{'ids':ids})
        self.assertTrue(compare([a,b])['score_comparable'])
        self.experiment(template='current',goal='transient');c=self.saved('Different goal')
        self.assertFalse(compare([a,c])['score_comparable'])
        self.experiment(config={'duration':1,'sample_rate':80,'seed':99});d=self.saved('Different samples')
        self.assertFalse(compare([a,d])['same_input'])
        current=self.app.state.agent.get_session('a');current.preprocess_comparison['score_version']='future'
        e=self.saved('Different scoring')
        self.assertFalse(compare([d,e])['score_comparable'])
        for row in compare([a,b])['experiments']:
            self.assertIsNotNone(row['snr_db']);self.assertLessEqual(len(row['waveform']['x']),520)

    def test_comparison_no_reference_session_isolation_and_report_escaping(self):
        upload=self.client.post('/api/upload',data={'session_id':'a'},files={'file':('s.csv',b'1\n2\n3\n2\n1\n0')})
        self.assertEqual(upload.status_code,200)
        self.experiment(template='current');a=self.saved('<script>alert(1)</script>');b=self.saved('B')
        data=self.post('/api/experiments/compare',{'ids':[a,b]})
        for row in data['experiments']:
            self.assertIsNone(row['snr_db']);self.assertIsNone(row['rmse'])
        report=self.client.post('/api/experiments/compare',json={'session_id':'a','ids':[a,b],'format':'html'})
        self.assertEqual(report.status_code,200);self.assertNotIn('<script>',report.text);self.assertIn('&lt;script&gt;',report.text)
        self.assertIn('<svg',report.text)
        self.assertEqual(self.client.post('/api/experiments/compare',json={'session_id':'other','ids':[a,b]}).status_code,404)
        self.assertEqual(self.client.post('/api/experiments/compare',json={'session_id':'a','ids':[a,a]}).status_code,400)

    def test_cancel_api_is_scoped_and_task_list_has_no_result_payload(self):
        engine=self.app.state.engine;started=threading.Event();finish=threading.Event()
        def operation():started.set();finish.wait(3);check_cancelled();return {'reply':'unexpected'}
        try:
            key=engine.submit('a','cancel-http',{'operation':'experiment'},operation);self.assertTrue(started.wait(3))
            self.assertEqual(self.client.post(f'/api/tasks/{key}/cancel',json={'session_id':'b'}).status_code,404)
            tasks=self.client.get('/api/tasks',params={'session_id':'a'}).json()['tasks']
            self.assertEqual(tasks[0]['task_id'],key);self.assertNotIn('result',tasks[0])
            self.assertTrue(self.post(f'/api/tasks/{key}/cancel',{})['cancel_requested']);finish.set()
            self.assertTrue(engine.wait(key,'a')['cancelled'])
            self.assertIn('"cancelled": true',self.client.get(f'/api/tasks/{key}/events',params={'session_id':'a'}).text)
        finally:finish.set()


class LifecycleTests(unittest.TestCase):
    def test_invalid_task_result_rolls_back_before_autosave(self):
        with tempfile.TemporaryDirectory() as temp:
            agent=RandomSignalDialogueAgent();store=ExperimentStore(Path(temp));engine=TaskEngine(agent,store)
            store.autosave(agent.get_session('a'))
            def invalid():
                agent.get_session('a').messages.append({'role':'assistant','content':'partial'})
                return {'value':float('nan')}
            try:
                key=engine.submit('a','invalid',{},invalid)
                self.assertIn('error',engine.wait(key,'a'))
                self.assertEqual(agent.get_session('a').messages,[])
                self.assertEqual(store.load(store.auto_id('a'),'a').messages,[])
            finally:engine.close()

    def test_waiting_session_does_not_occupy_other_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            engine=TaskEngine(RandomSignalDialogueAgent(),ExperimentStore(Path(temp)),workers=2,capacity=3)
            entered=threading.Event();finish=threading.Event()
            def block():entered.set();finish.wait(4);return {}
            try:
                first=engine.submit('a','first',{},block);self.assertTrue(entered.wait(3))
                queued=engine.submit('a','queued',{},lambda:{'second':True})
                other=engine.submit('b','other',{},lambda:{'other':True})
                self.assertEqual(engine.wait(other,'b'),{'other':True})
                self.assertEqual(engine.status(queued,'a')['status'],'queued')
                finish.set();engine.wait(first,'a');engine.wait(queued,'a')
            finally:finish.set();engine.close()

    def test_cancel_is_refused_once_autosave_commit_has_started(self):
        with tempfile.TemporaryDirectory() as temp:
            store=ExperimentStore(Path(temp));engine=TaskEngine(RandomSignalDialogueAgent(),store)
            entered=threading.Event();finish=threading.Event();original=store.autosave
            def save(state):entered.set();finish.wait(4);original(state)
            try:
                with patch.object(store,'autosave',side_effect=save):
                    key=engine.submit('a','commit',{},lambda:{'reply':'saved'});self.assertTrue(entered.wait(3))
                    self.assertFalse(engine.cancel(key,'a')['cancel_requested']);finish.set()
                    self.assertEqual(engine.wait(key,'a'),{'reply':'saved'})
            finally:finish.set();engine.close()

    def test_cancel_queue_frees_capacity_and_does_not_starve_other_sessions(self):
        with tempfile.TemporaryDirectory() as temp:
            engine=TaskEngine(RandomSignalDialogueAgent(),ExperimentStore(Path(temp)),workers=2,capacity=2)
            started=threading.Event();finish=threading.Event();calls=[]
            def block():started.set();finish.wait(4);return {'ok':True}
            try:
                first=engine.submit('a','first',{},block);self.assertTrue(started.wait(3))
                queued=engine.submit('a','queued',{},lambda:calls.append('should not run'))
                self.assertEqual(engine.status(queued,'a')['status'],'queued')
                self.assertTrue(engine.cancel(queued,'a')['cancel_requested'])
                other=engine.submit('b','other',{},lambda:{'ok':'other'})
                self.assertEqual(engine.wait(other,'b'),{'ok':'other'})
                self.assertFalse(finish.is_set());self.assertEqual(calls,[])
                self.assertEqual(engine.submit('a','queued',{},lambda:None),queued)
                self.assertTrue(engine.wait(queued,'a')['cancelled'])
                finish.set();engine.wait(first,'a')
            finally:finish.set();engine.close()

    def test_running_cancel_restores_memory_and_disk_then_allows_next_task(self):
        with tempfile.TemporaryDirectory() as temp:
            store=ExperimentStore(Path(temp));agent=RandomSignalDialogueAgent();engine=TaskEngine(agent,store)
            started=threading.Event();finish=threading.Event()
            state=agent.get_session('a');state.messages=[{'role':'assistant','content':'original'}];store.autosave(state)
            def operation():
                agent.get_session('a').messages.append({'role':'assistant','content':'partial'})
                started.set();finish.wait(4);check_cancelled();return {}
            try:
                key=engine.submit('a','run',{},operation);self.assertTrue(started.wait(3));engine.cancel(key,'a');finish.set()
                self.assertTrue(engine.wait(key,'a')['cancelled'])
                self.assertEqual(agent.get_session('a').messages,store.load(store.auto_id('a'),'a').messages)
                self.assertEqual(len(agent.get_session('a').messages),1)
                next_key=engine.submit('a','next',{},lambda:{'reply':'next'})
                self.assertEqual(engine.wait(next_key,'a'),{'reply':'next'})
            finally:finish.set();engine.close()

    def test_idle_eviction_restores_autosave_and_never_unloads_busy_session(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(LIMITS,session_capacity=1,idle_session_seconds=900):
            agent=RandomSignalDialogueAgent();store=ExperimentStore(Path(temp));engine=TaskEngine(agent,store)
            try:
                with engine.session_lock('a'):
                    engine.load_session('a');agent.get_session('a').messages=[{'role':'assistant','content':'durable'}];store.autosave(agent.get_session('a'))
                    with self.assertRaises(TaskBusy):
                        with engine.session_lock('b'):pass
                with engine.session_lock('b'):engine.load_session('b')
                self.assertNotIn('a',agent.sessions)
                with engine.session_lock('a'):
                    engine.load_session('a');self.assertEqual(agent.get_session('a').messages[0]['content'],'durable')
                engine.session_used['a']-=901
                self.assertEqual(engine.evict_idle(),1)
            finally:engine.close()

    def test_storage_cleanup_rechecks_references_and_rejects_stale_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            store=ExperimentStore(Path(temp))
            state=ConversationState('a',bundle=generate_random_signal(SignalConfig(duration=1)))
            first=store.save(state,'A');shared=copy.deepcopy(state);shared.session_id='b';second=store.save(shared,'B')
            store.delete(first,'a');self.assertEqual(store.storage_preview()['unused_files'],0)
            store.delete(second,'b');preview=store.storage_preview();self.assertEqual(preview['unused_files'],1)
            store.autosave(state)
            with self.assertRaises(ValueError):store.storage_cleanup(preview['token'])
            np.testing.assert_array_equal(store.load(store.auto_id('a'),'a').bundle.observed,state.bundle.observed)
            old=store.save(ConversationState('c',bundle=generate_random_signal(SignalConfig(duration=1,seed=99))),'unused')
            store.delete(old,'c');foreign=Path(temp)/'user-file.npz';foreign.write_bytes(b'keep')
            preview=store.storage_preview();result=store.storage_cleanup(preview['token'])
            self.assertEqual(result['removed_files'],1);self.assertEqual(result['freed_bytes'],preview['reclaimable_bytes'])
            self.assertTrue(foreign.exists());self.assertEqual(store.storage_preview()['unused_files'],0)
            self.assertIsNotNone(store.load(store.auto_id('a'),'a').bundle)

    def test_cleanup_cannot_delete_array_while_save_is_committing(self):
        with tempfile.TemporaryDirectory() as temp:
            store=ExperimentStore(Path(temp));state=ConversationState('a',bundle=generate_random_signal(SignalConfig(duration=1)))
            old=store.save(state,'Old');store.delete(old,'a');preview=store.storage_preview()
            entered=threading.Event();finish=threading.Event();original=store._save
            def delayed(*args,**kwargs):entered.set();finish.wait(3);return original(*args,**kwargs)
            with ThreadPoolExecutor(2) as pool,patch.object(store,'_save',side_effect=delayed):
                saved=pool.submit(store.autosave,state);self.assertTrue(entered.wait(2))
                cleanup=pool.submit(store.storage_cleanup,preview['token']);finish.set();saved.result(timeout=3)
                with self.assertRaises(ValueError):cleanup.result(timeout=3)
            self.assertIsNotNone(store.load(store.auto_id('a'),'a').bundle)

    def test_legacy_task_database_migration_retains_results_and_marks_interruptions(self):
        with tempfile.TemporaryDirectory() as temp:
            db=sqlite3.connect(Path(temp)/'experiments.sqlite3')
            db.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY,session TEXT,fingerprint TEXT,status TEXT,result TEXT,created REAL)')
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?)',('old','a','hash','done','{"reply":"saved"}',0))
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?)',('interrupted','a','hash','cancelling',None,1));db.commit();db.close()
            engine=TaskEngine(RandomSignalDialogueAgent(),ExperimentStore(Path(temp)))
            try:
                self.assertEqual(engine.status('old','a')['result'],{'reply':'saved'})
                self.assertEqual(engine.status('interrupted','a')['status'],'error')
            finally:engine.close()


if __name__=='__main__':
    log=ROOT/'logs/studio/latest.log';log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    print(log.read_text(encoding='utf-8'));sys.exit(not result.wasSuccessful())
