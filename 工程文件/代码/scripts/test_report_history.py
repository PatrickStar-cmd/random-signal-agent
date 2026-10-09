"""Multi-result retention, atomic capture, privacy and full 50-group PDF QA."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ['RS_AGENT_LLM_ENABLED']='0'
import numpy as np
from pypdf import PdfReader
from fastapi.testclient import TestClient
import server
from src import report_history as history,pdf_report as pdf,diagnostics
from src.workbench import ExperimentStore
from src.tasks import TaskEngine,TaskCancelled
from src.dialogue_agent import ConversationState,RandomSignalDialogueAgent
from src.signal_processing import generate_random_signal,SignalConfig
from src.preprocessing import preprocess_signal,PreprocessConfig


def state(session='owner', seed=42, frequency=8, reference=True):
    s=ConversationState(session,bundle=generate_random_signal(SignalConfig(sample_rate=100,duration=1,
        base_frequency=frequency,seed=seed,waveform='sine',noise_model='gaussian')))
    s.processed=preprocess_signal(s.bundle.observed,PreprocessConfig(sample_rate=100,method='fft_lowpass',lowpass_cutoff_hz=20))
    s.bundle.has_clean_reference=reference
    return s


def capture(store, key, s):
    with store.file_lock,store.connect() as db:history.capture_result(store,db,key,s)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=ExperimentStore(Path(self.temp.name))
    def tearDown(self):self.temp.cleanup()
    def choices(self):return [{'kind':'history','id':r['id']} for r in history.listing(self.store,'owner')['history']]
    def test_recent_fifty_rolling_retention_and_restart(self):
        for i in range(55):capture(self.store,str(i),state(seed=i))
        rows=history.listing(ExperimentStore(Path(self.temp.name)),'owner')['history']
        self.assertEqual(len(rows),50);self.assertEqual(rows[0]['id'],'54');self.assertEqual(rows[-1]['id'],'5')
        with self.assertRaises(KeyError):history.load_entry(self.store,'owner','history','4')
    def test_duplicate_request_and_reprocessing_identical_data(self):
        agent=RandomSignalDialogueAgent();engine=TaskEngine(agent,self.store)
        def run():agent.sessions['owner']=state();return {'ok':True}
        try:
            one=engine.submit('owner','one',{},run);engine.wait(one,'owner')
            self.assertEqual(engine.submit('owner','one',{},run),one)
            two=engine.submit('owner','two',{},run);engine.wait(two,'owner')
            self.assertEqual(len(self.choices()),2)
            chat=engine.submit('owner','question',{},lambda:{'reply':'explanation'});engine.wait(chat,'owner')
            self.assertEqual(len(self.choices()),2)
        finally:engine.close()
    def test_capture_failure_rolls_back_autosave_task_and_history(self):
        agent=RandomSignalDialogueAgent();agent.sessions['owner']=state(seed=1);self.store.autosave(agent.sessions['owner'])
        engine=TaskEngine(agent,self.store)
        def run():agent.sessions['owner']=state(seed=2);return {'ok':True}
        try:
            with patch('src.report_history.capture_result',side_effect=OSError('disk full')):
                key=engine.submit('owner','failed',{},run);self.assertIn('error',engine.wait(key,'owner'))
            self.assertEqual(agent.get_session('owner').bundle.config.seed,1)
            self.assertEqual(self.store.load(self.store.auto_id('owner'),'owner').bundle.config.seed,1)
            self.assertEqual(self.choices(),[]);self.assertEqual(engine.status(key,'owner')['status'],'error')
        finally:engine.close()
    def test_cancelled_and_error_result_do_not_create_history(self):
        agent=RandomSignalDialogueAgent();engine=TaskEngine(agent,self.store)
        def cancel():agent.sessions['owner']=state();raise TaskCancelled('cancelled')
        def error():agent.sessions['owner']=state();return {'error':'failed'}
        try:
            k=engine.submit('owner','cancel',{},cancel);engine.wait(k,'owner')
            k=engine.submit('owner','error',{},error);engine.wait(k,'owner');self.assertEqual(self.choices(),[])
        finally:engine.close()
    def test_opening_snapshot_does_not_count_as_processing(self):
        agent=RandomSignalDialogueAgent();engine=TaskEngine(agent,self.store)
        def opened():agent.sessions['owner']=state();return {'ok':True}
        try:
            k=engine.submit('owner','open',{'operation':'open'},opened);engine.wait(k,'owner');self.assertEqual(self.choices(),[])
        finally:engine.close()
    def test_history_keeps_full_arrays_but_no_chat_keys_or_paths(self):
        s=state();s.messages=[{'content':'secret-key'}];s.last_uploaded_path='C:/secret-key/file.csv';s.bundle.source='C:/secret-key/file.csv'
        s.diagnostic_lab={'private':'secret-key'};capture(self.store,'a',s)
        restored,_=history.load_entry(self.store,'owner','history','a')
        np.testing.assert_array_equal(restored.processed.signal,s.processed.signal)
        self.assertEqual(restored.messages,[]);self.assertIsNone(restored.last_uploaded_path)
        with self.store.connect() as db:document=db.execute('SELECT document FROM report_history').fetchone()[0]
        self.assertNotIn(b'secret-key',document)
    def test_storage_cleanup_protects_history_and_manual_snapshots(self):
        capture(self.store,'a',state(seed=1));saved=self.store.save(state(seed=2),'saved')
        self.store.autosave(state(seed=3));self.store.autosave(state(seed=4))
        preview=self.store.storage_preview();self.assertGreater(preview['unused_files'],0)
        self.store.storage_cleanup(preview['token'])
        history.load_entry(self.store,'owner','history','a');self.store.load(saved,'owner')
    def test_limits_and_duplicates_rejected(self):
        for value in ([],None,[{'kind':'history','id':str(i)} for i in range(51)],
                      [{'kind':'history','id':'a'}]*2,[{'kind':'other','id':'a'}]):
            with self.assertRaises(ValueError):history.selection(value)
    def test_session_ownership_of_history_snapshots_and_plots(self):
        capture(self.store,'a',state());saved=self.store.save(state(),'saved')
        for kind,key in (('history','a'),('snapshot',saved)):
            with self.assertRaises(KeyError):history.load_entry(self.store,'other',kind,key)
            with self.assertRaises(KeyError):history.plot(self.store,'other',kind,key)
    def test_blind_history_and_saved_snapshot_are_locked(self):
        s=state();diagnostics.inject(s,[{'kind':'narrowband','start':.2,'end':.5,'frequency':35,'strength':1}],blind=True)
        s.processed=preprocess_signal(s.bundle.observed);capture(self.store,'blind',s);self.store.save(s,'blind')
        listing=history.listing(self.store,'owner');self.assertTrue(listing['history'][0]['locked']);self.assertTrue(listing['snapshots'][0]['locked'])
        with self.assertRaises(ValueError):history.plot(self.store,'owner','history','blind')
        with self.assertRaises(ValueError):history.collection(self.store,'owner',self.choices(),{})
        diagnostics.reveal(s);capture(self.store,'revealed',s)
        history.collection(self.store,'owner',[{'kind':'history','id':'revealed'}],{})
    def test_selected_metrics_and_plots_are_independent(self):
        for i,f in enumerate((5,12)):
            s=state(seed=i,frequency=f,reference=i==0);capture(self.store,str(i),s)
        batch=history.collection(self.store,'owner',[{'kind':'history','id':str(i)} for i in range(2)],{})
        self.assertEqual([g['facts']['main_frequency_hz'] for g in batch['groups']],[5,12])
        self.assertEqual(batch['groups'][0]['facts']['source'],'仿真信号')
        self.assertEqual(batch['groups'][0]['facts']['configuration']['seed'],0)
        self.assertIsNone(batch['groups'][1]['facts']['after']['snr_db'])
        self.assertNotEqual(batch['groups'][0]['facts']['plots']['waveform'],batch['groups'][1]['facts']['plots']['waveform'])
    def test_saved_snapshot_supplement_and_immutable_token(self):
        capture(self.store,'a',state());saved=self.store.save(state(seed=1),'旧实验')
        chosen=[{'kind':'history','id':'a'},{'kind':'snapshot','id':saved}]
        token=history.collection(self.store,'owner',chosen,{})['token']
        self.store.autosave(state(seed=2))
        self.assertEqual(history.collection(self.store,'owner',chosen,{})['token'],token)
        self.store.rename(saved,'owner','改名实验')
        self.assertNotEqual(history.collection(self.store,'owner',chosen,{})['token'],token)
    def test_http_history_preview_download_and_invalidated_selection(self):
        app=server.create_app(data_dir=Path(self.temp.name)/'http')
        with TestClient(app) as c:
            store=app.state.store;capture(store,'a',state())
            rows=c.get('/api/reports/history?session_id=owner');self.assertEqual(len(rows.json()['history']),1)
            self.assertIn('<polyline',c.get('/api/reports/plot/history/a?session_id=owner').text)
            payload={'session_id':'owner','options':{'edition':'brief'},'selection':[{'kind':'history','id':'a'}]}
            preview=c.post('/api/reports/preview',json=payload);self.assertEqual(preview.status_code,200,preview.text)
            self.assertEqual(preview.json()['group_count'],1)
            download=c.post('/api/reports/pdf',json={**payload,'token':preview.json()['token']});self.assertEqual(download.status_code,200,download.text[:100]);self.assertTrue(download.content.startswith(b'%PDF'))
            with store.connect() as db:db.execute('DELETE FROM report_history WHERE id=?',('a',))
            self.assertEqual(c.post('/api/reports/pdf',json={**payload,'token':preview.json()['token']}).status_code,409)
    def test_fifty_groups_have_all_charts_bookmarks_links_and_page_numbers(self):
        for i in range(50):capture(self.store,str(i),state(seed=i,frequency=5+i%8))
        batch=history.collection(self.store,'owner',self.choices(),{'title':'五十组处理结果验收','edition':'brief'})
        started=time.perf_counter();raw=pdf.render(batch);reader=PdfReader(io.BytesIO(raw))
        self.assertEqual(len(reader.outline),50);self.assertGreater(len(reader.pages),100)
        text='\n'.join(p.extract_text() for p in reader.pages)
        for i in range(1,51):self.assertIn(f'第 {i} 组',text)
        for i,page in enumerate(reader.pages,1):self.assertIn(f'第 {i} 页',page.extract_text())
        self.assertTrue(any('/Annots' in p for p in reader.pages))
        out=ROOT/'debug/report-history';out.mkdir(exist_ok=True);(out/'fifty-brief.pdf').write_bytes(raw)
        (out/'fifty-performance.json').write_text(json.dumps({'groups':50,'pages':len(reader.pages),'seconds':time.perf_counter()-started,'bytes':len(raw)}),encoding='utf-8')
    def test_standard_multi_report_includes_optional_diagnosis(self):
        s=state();diagnostics.diagnose_state(s);capture(self.store,'diagnosed',s)
        capture(self.store,'no-reference',state(seed=7,reference=False))
        chosen=[{'kind':'history','id':'diagnosed'},{'kind':'history','id':'no-reference'}]
        raw=pdf.render(history.collection(self.store,'owner',chosen,{'title':'历史处理结果分析','author':'谛听实验室','purpose':'比较两组独立结果，核对指标、图表与参考条件。'}))
        reader=PdfReader(io.BytesIO(raw));text='\n'.join(p.extract_text() for p in reader.pages)
        self.assertIn('异常诊断',text);self.assertIn('数据没有干净参考',text)
        (ROOT/'debug/report-history/standard.pdf').write_bytes(raw)


if __name__=='__main__':
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(HistoryTests))
    folder=ROOT/'logs/report-history';folder.mkdir(parents=True,exist_ok=True);(folder/'latest.log').write_text(stream.getvalue(),encoding='utf-8')
    print(stream.getvalue());sys.exit(not result.wasSuccessful())
