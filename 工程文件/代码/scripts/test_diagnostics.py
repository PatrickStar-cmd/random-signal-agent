"""Diagnostic acceptance: independent STFT reference, blind truth and reversible trials."""
from pathlib import Path
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));os.environ['RS_AGENT_LLM_ENABLED']='0'
import numpy as np
from scipy import signal
from fastapi.testclient import TestClient
import server
from src import diagnostics as d
from src.dialogue_agent import ConversationState,RandomSignalDialogueAgent
from src.signal_processing import SignalConfig,generate_random_signal,PreprocessResult
from src.workbench import snapshot,restore,export_archive,import_archive


def state(n=1600,noise=.025):
    return ConversationState('a',bundle=generate_random_signal(SignalConfig(sample_rate=200,duration=n/200,
        base_frequency=8,amplitude=1,noise_std=noise,impulse_probability=0,seed=42)))


class DiagnosticTests(unittest.TestCase):
    def test_stft_matches_scipy_psd_with_explicit_padding(self):
        s=state(1600);r=d.analyze(s,{'window':128,'overlap':.5})
        y=np.pad(s.bundle.observed,(64,63));f,t,z=signal.spectrogram(y,fs=200,window=np.hanning(128),
            nperseg=128,noverlap=64,detrend=False,scaling='density',mode='psd')
        # Our trailing frame is permitted by explicit padding; SciPy reference uses full frames.
        self.assertEqual(len(r['spectrogram']['time']),len(t))
        expected=np.maximum(-80,10*np.log10(np.maximum(z.T,z.max()*1e-8)/z.max()))
        np.testing.assert_allclose(r['spectrogram']['db'],expected,atol=1e-10)
        np.testing.assert_allclose(r['spectrogram']['frequency'],f)
        np.testing.assert_allclose(r['spectrogram']['time'],np.arange(len(t))*.32)

    def test_chirp_tracks_frequency_and_reports_resolution(self):
        s=state();t=s.bundle.time;s.bundle.observed=signal.chirp(t,10,t[-1],60)
        r=d.analyze(s,{'window':128});g=r['spectrogram'];db=np.array(g['db']);freq=np.array(g['frequency'])
        peaks=freq[np.argmax(db,axis=1)];times=np.array(g['time']);interior=(times>.4)&(times<7.6)
        self.assertLess(np.max(np.abs(peaks[interior]-(10+50*times[interior]/t[-1]))),2.5)
        self.assertEqual(r['frequency_resolution_hz'],200/128)

    def test_short_zero_and_maximum_signal_have_bounded_finite_grid(self):
        for n in (16,200000):
            s=state(n);s.bundle.observed[:]=0;r=d.analyze(s)
            self.assertLessEqual(len(r['spectrogram']['db']),240)
            self.assertLessEqual(len(r['spectrogram']['frequency']),128)
            self.assertTrue(np.isfinite(r['spectrogram']['db']).all());self.assertEqual(r['events'],[])
            self.assertEqual(r['parameters']['effective_window'],min(128,n))

    def test_seed_reproduces_all_injections_without_accumulation(self):
        for kind in d.LABELS:
            s=state();fault=[{'kind':kind,'start':2,'end':3,'strength':.4 if kind=='clipping' else 2,'frequency':38}]
            d.inject(s,fault,17,True);first=s.bundle.observed.copy();truth=copy.deepcopy(s.diagnostic_lab['truth'])
            d.inject(s,fault,17,True);np.testing.assert_array_equal(first,s.bundle.observed)
            self.assertEqual(truth,s.diagnostic_lab['truth'])

    def test_invalid_injection_is_atomic_and_ranges_validate(self):
        s=state();before=s.bundle.observed.copy()
        for spec in ({'kind':'dropout','start':2,'end':1},{'kind':'clipping','start':2,'end':3,'strength':100},
                     {'kind':'narrowband','start':2,'end':3,'frequency':100}):
            with self.assertRaises(ValueError):d.inject(s,[{'kind':'drift','start':1,'end':2},spec])
            np.testing.assert_array_equal(before,s.bundle.observed)
        for options in ({'window':33},{'start':2,'end':2.01},{'overlap':.8},{'source':'clean'},{'end':float('nan')}):
            with self.assertRaises(ValueError):d.analyze(s,options)
        s.bundle.time[5]+=.02
        with self.assertRaises(ValueError):d.analyze(s)

    def test_detection_uses_observations_not_hidden_truth(self):
        s=state();d.inject(s,[{'kind':'narrowband','start':2.4,'end':3.5,'strength':1.8,'frequency':38},
            {'kind':'dropout','start':5.5,'end':5.85},{'kind':'impulse','start':6.7,'end':7.1,'strength':4}],42,True)
        r=d.diagnose_state(s);kinds={e['kind'] for e in r['events']}
        self.assertTrue({'narrowband','dropout','impulse'}<=kinds)
        s.diagnostic_lab['truth']=[];self.assertEqual(r['events'],d.analyze(s)['events'])
        for e in r['events']:self.assertGreater(e['end'],e['start']);self.assertIn('alternatives',e)

    def test_blind_reveal_evaluates_full_observation_after_cropped_analysis(self):
        s=state();d.inject(s,[{'kind':'dropout','start':5.5,'end':5.85}],blind=True)
        agent=RandomSignalDialogueAgent();public=agent.serialize_state(s)['diagnostic_lab']
        for key in ('seed','truth','baseline','reference_clean'):self.assertNotIn(key,public)
        self.assertFalse(s.bundle.has_clean_reference)
        d.diagnose_state(s,{'start':0,'end':2});r=d.reveal(s)
        self.assertTrue(r['revealed']);self.assertEqual(r['evaluation']['matched'],1)
        self.assertEqual(r['analysis']['parameters']['end'],8);self.assertTrue(s.bundle.has_clean_reference)
        self.assertLessEqual(r['evaluation']['precision'],1);self.assertLessEqual(r['evaluation']['recall'],1)

    def test_notch_verification_and_adoption_preserve_raw_and_outside(self):
        s=state();d.inject(s,[{'kind':'narrowband','start':2.4,'end':3.5,'strength':1.8,'frequency':38}]);raw=s.bundle.observed.copy()
        r=d.diagnose_state(s);e=next(e for e in r['events'] if e['kind']=='narrowband');v=d.verify(s,e['id'],r['token'])
        self.assertLess(v['metrics']['after_band_energy'],v['metrics']['before_band_energy'])
        self.assertLess(v['metrics']['after_rmse'],v['metrics']['before_rmse'])
        output=s.diagnostic_lab['verification']['signal'];outside=(s.bundle.time<e['start'])|(s.bundle.time>=e['end'])
        np.testing.assert_array_equal(output[outside],raw[outside]);d.adopt(s)
        np.testing.assert_array_equal(s.bundle.observed,raw);np.testing.assert_array_equal(s.processed.signal,output)
        with self.assertRaises(ValueError):d.verify(s,e['id'],'obsolete')
        d.diagnose_state(s);self.assertNotIn('verification',s.diagnostic_lab)

    def test_unreferenced_trial_does_not_claim_true_error(self):
        s=state();s.bundle.has_clean_reference=False
        d.inject(s,[{'kind':'impulse','start':2,'end':2.1,'strength':4}]);r=d.diagnose_state(s)
        e=next(e for e in r['events'] if e['kind']=='impulse');v=d.verify(s,e['id'],r['token'])
        self.assertIsNone(v['metrics']['after_rmse']);self.assertIn('不能',v['verdict'])

    def test_cancel_checkpoint_leaves_state_unmodified(self):
        s=state();raw=s.bundle.observed.copy()
        with patch.object(d,'check_cancelled',side_effect=RuntimeError('cancelled')):
            with self.assertRaises(RuntimeError):d.inject(s,[{'kind':'dropout','start':2,'end':3}])
        np.testing.assert_array_equal(s.bundle.observed,raw);self.assertEqual(s.diagnostic_lab,{})

    def test_drift_clipping_and_frequency_changes_are_localized(self):
        for kind,strength in (('drift',4),('clipping',.4),('frequency_shift',2)):
            s=state();d.inject(s,[{'kind':kind,'start':3,'end':4,'strength':strength,'frequency':38}])
            events=d.analyze(s)['events'];matches=[e for e in events if e['kind']==kind and e['start']<4 and e['end']>3]
            self.assertTrue(matches,(kind,events))

    def test_processed_source_rejects_stale_verification_on_adoption(self):
        s=state();d.inject(s,[{'kind':'impulse','start':2,'end':2.1,'strength':4}])
        s.processed=PreprocessResult(signal=s.bundle.observed.copy(),anomaly_mask=np.zeros(1600,bool),removed_mean=0,smoothing_window=1)
        r=d.diagnose_state(s,{'source':'processed'});e=next(e for e in r['events'] if e['kind']=='impulse')
        d.verify(s,e['id'],r['token']);s.processed.signal[0]+=.1
        with self.assertRaises(ValueError):d.adopt(s)

    def test_snapshot_package_roundtrip_and_older_snapshot_default(self):
        s=state();d.inject(s,[{'kind':'dropout','start':2,'end':2.4}]);d.diagnose_state(s);d.reveal(s)
        clone=import_archive(export_archive(s,'diagnostics'),'b')
        np.testing.assert_array_equal(clone.diagnostic_lab['baseline'],s.diagnostic_lab['baseline'])
        self.assertEqual(clone.diagnostic_lab['analysis'],s.diagnostic_lab['analysis'])
        document,raw=snapshot(state());old=json.loads(document);old['state']['fields'].pop('diagnostic_lab')
        self.assertEqual(restore(json.dumps(old),raw).diagnostic_lab,{})

    def test_report_escapes_evidence_and_blind_truth(self):
        s=state();d.inject(s,[{'kind':'dropout','start':2,'end':3}],blind=True);r=d.diagnose_state(s)
        r['events'][0]['alternatives']='<script>bad</script>';html=d.report_html(r,d.public_lab(s)).decode()
        self.assertNotIn('<script>',html);self.assertIn('&lt;script&gt;',html);self.assertNotIn('reference_clean',html)


class DiagnosticHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.app=server.create_app(data_dir=root/'data',upload_dir=root/'uploads');self.client=TestClient(self.app);self.client.__enter__()
    def tearDown(self):self.client.__exit__(None,None,None);self.temp.cleanup()
    def post(self,action,**extra):
        r=self.client.post('/api/diagnostics/'+action,json={'session_id':'a',**extra});self.assertEqual(r.status_code,200,r.text);return r.json()
    def test_blind_exports_and_compare_block_until_reveal(self):
        r=self.post('demo',blind=True,request_id='same');again=self.post('demo',blind=True,request_id='same')
        self.assertEqual(r['diagnostics']['token'],again['diagnostics']['token']);self.assertNotIn('truth',r['state']['diagnostic_lab'])
        for fmt in ('zip','html','csv','json'):
            response=self.client.get('/api/experiments/export',params={'session_id':'a','format':fmt});self.assertEqual(response.status_code,400)
        ids=[]
        for name in ('a','b'):ids.append(self.client.post('/api/experiments/save',json={'session_id':'a','name':name}).json()['id'])
        self.assertEqual(self.client.post('/api/experiments/compare',json={'session_id':'a','ids':ids}).status_code,400)
        self.assertEqual(self.client.get('/api/diagnostics/view',params={'session_id':'b'}).status_code,400)
        self.post('reveal');self.assertEqual(self.client.get('/api/experiments/export',params={'session_id':'a','format':'zip'}).status_code,200)
    def test_chat_and_verification_restore_via_saved_snapshot(self):
        r=self.post('demo');e=next(e for e in r['diagnostics']['events'] if e['kind']=='narrowband')
        self.post('verify',event_id=e['id'],token=r['diagnostics']['token']);self.post('adopt')
        saved=self.client.post('/api/experiments/save',json={'session_id':'a','name':'trial'}).json()
        self.post('demo');opened=self.client.post('/api/experiments/open',json={'session_id':'a','id':saved['id']}).json()
        self.assertEqual(opened['state']['preprocess']['method'],'diagnostic_trial')
        chat=self.client.post('/api/chat',json={'session_id':'a','message':'诊断信号'});self.assertEqual(chat.status_code,200,chat.text)
        self.assertIn('diagnose_signal',chat.text)
        generated=self.client.post('/api/chat',json={'session_id':'a','message':'采集一段 1 秒、采样率 200Hz、主频 8Hz 的正弦信号加高斯噪声，随机种子 42'})
        self.assertEqual(generated.status_code,200,generated.text)
        self.assertEqual(generated.json()['state']['diagnostic_lab'],{})
        self.assertEqual(self.client.post('/api/experiments/save',json={'session_id':'a','name':'new input'}).status_code,200)


if __name__=='__main__':
    log=ROOT/'logs/diagnostics/latest.log';log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    print(log.read_text(encoding='utf-8'));sys.exit(0 if result.wasSuccessful() else 1)
