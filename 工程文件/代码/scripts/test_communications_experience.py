"""v0.4.4 execution, persistence, comparison, algorithms and report acceptance."""
from pathlib import Path
import copy
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));os.environ['RS_AGENT_LLM_ENABLED']='0'
import numpy as np
from fastapi.testclient import TestClient
import server
from src import communications as c,communication_runtime as rt,communication_studio as studio,communication_algorithms as alg
from src.communication_jobs import Jobs
from src.communication_sweep import sweep
from src import communication_report as report

def execute(p):
    b=c.build(p);return c.run(b['program'],b['token'])

def doc(p):return {'document_schema':2,'name':'海洋通信实验','program':p}

def wait(jobs,key,status=('completed','failed','cancelled'),session='test'):
    end=time.monotonic()+15
    while time.monotonic()<end:
        value=jobs.status(session,key)
        if value['status'] in status:return value
        time.sleep(.01)
    raise AssertionError('job timed out: '+str(value))

class ExperienceTests(unittest.TestCase):
    def test_observation_keeps_existing_numerics_all_engines(self):
        for name in ('text','analog_am','line_manchester','complex_receiver','ofdm','fractional_equalizer','ofdm_cfo_tracking'):
            p=c.PRESETS[name]['program'];b=c.build(p);old=execute(p);new,ctx=rt.observe_run(p,b['token'],retain=True)
            self.assertEqual(old,{k:v for k,v in new.items() if k!='experience'},name)
            self.assertEqual([v['id'] for v in ctx.observations],[v['id'] for v in b['program']['blocks']],name)
            self.assertTrue(all(np.isfinite(v['rms']) for v in ctx.observations))
    def test_new_presets_and_catalog_contracts(self):
        catalog=c.catalog();self.assertEqual(len(catalog['blocks']),131)
        for block in catalog['blocks']:self.assertIn('inputs',block);self.assertIn('output',block)
        for name in ('agc_soft','resample_receiver','fractional_equalizer','ofdm_cfo_tracking','burst_interleave'):
            r=execute(c.PRESETS[name]['program']);self.assertLess(r['metrics']['ber'],.02,name)
    def test_connection_error_and_ofdm_tracking_port(self):
        p=c.preset(['random_bits','mod_bpsk','ideal','sink'])
        value=studio.describe(p);self.assertFalse(value['ready']);self.assertIsNotNone(value['error']['id'])
        value=studio.describe(c.PRESETS['ofdm_cfo_tracking']['program']);self.assertTrue(value['ready']);self.assertEqual(next(v for v in value['ports'] if v['id']==next(b['id'] for b in c.PRESETS['ofdm_cfo_tracking']['program']['blocks'] if b['kind']=='rx_ofdm_tracking'))['output'],'复符号')
    def test_complete_receiver_codecs_and_shaping(self):
        for name in ('text','soft_viterbi','complex_receiver','ofdm','line_manchester','agc_soft'):
            p=copy.deepcopy(c.PRESETS[name]['program']);p['blocks']=[b for b in p['blocks'] if c.BLOCKS[b['kind']]['category'] not in ('demodulator','rx_converter') and b['kind'] not in c.PAIRS]
            restored=studio.complete_receiver(p);r=execute(restored);self.assertLess(r['metrics'].get('ber',0),.1,name)
    def test_linked_decoder_and_variance(self):
        p=c.preset(['random_bits','repeat_encode','mod_bpsk','awgn','demod_bpsk','repeat_decode','sink'],{1:{'factor':5},5:{'factor':3}})
        fixed=studio.pair_parameters(p);self.assertEqual(fixed['blocks'][5]['params']['factor'],5)
    def test_project_version_isolation_and_legacy_import(self):
        with tempfile.TemporaryDirectory() as root:
            store=studio.ProjectStore(root);p=c.PRESETS['text']['program'];d=doc(p);d['sweeps']=[]
            first=store.save('a',d);second=store.save('a',{**d,'name':'第二次'},first['id'],1)
            self.assertEqual(second['version'],2);self.assertEqual(store.load('a',first['id'],1)['document']['name'],d['name'])
            with self.assertRaises(KeyError):store.load('b',first['id'])
            with self.assertRaises(ValueError):store.save('a',d,first['id'],1)
            self.assertEqual(studio.validate_document(p)['document_schema'],2)
            self.assertEqual(studio.ProjectStore(root).load('a',first['id'])['version'],2)
    def test_group_exposure_contiguity_and_overlap(self):
        p=c.PRESETS['text']['program'];d=doc(p);ids=[b['id'] for b in p['blocks']]
        d['groups']=[{'name':'发送链','members':ids[:2],'exposed':[ids[0]+':text']}];studio.validate_document(d)
        for members,exposed in [(ids[::2],[]),(ids[:2],[ids[-1]+':text']),(ids[:2],[ids[0]+':missing'])]:
            invalid=copy.deepcopy(d);invalid['groups'][0].update(members=members,exposed=exposed)
            with self.assertRaises(ValueError):studio.validate_document(invalid)
        d['groups']*=2
        with self.assertRaises(ValueError):studio.validate_document(d)
    def test_project_path_and_size_limits(self):
        with tempfile.TemporaryDirectory() as root:
            store=studio.ProjectStore(root)
            with self.assertRaises(ValueError):store.load('a','../bad')
            with patch.dict(c.CONFIG,{'max_project_bytes':100}):
                with self.assertRaises(ValueError):store.save('a',doc(c.PRESETS['text']['program']))
    def test_actual_debugger_step_and_cancellation(self):
        with tempfile.TemporaryDirectory() as root:
            jobs=Jobs(root,threading.BoundedSemaphore(1));p=c.PRESETS['text']['program'];b=c.build(p)
            try:
                job=jobs.start('test','debug',{'program':p,'token':b['token']});paused=wait(jobs,job['id'],('paused',))
                self.assertEqual(paused['observations'],[])
                jobs.control('test',job['id'],'step');paused=wait(jobs,job['id'],('paused',))
                deadline=time.monotonic()+2
                while not paused['observations'] and time.monotonic()<deadline:time.sleep(.01);paused=jobs.status('test',job['id'])
                self.assertEqual(len(paused['observations']),1);self.assertEqual(paused['observations'][0]['kind'],'text')
                jobs.control('test',job['id'],'cancel');self.assertEqual(wait(jobs,job['id'])['status'],'cancelled')
                run=jobs.start('test','run',{'program':p,'token':b['token']});self.assertEqual(wait(jobs,run['id'])['status'],'completed')
            finally:jobs.close()
    def test_debug_continue_window_and_owner(self):
        with tempfile.TemporaryDirectory() as root:
            jobs=Jobs(root,threading.BoundedSemaphore(1));p=c.PRESETS['text']['program'];b=c.build(p)
            try:
                job=jobs.start('test','debug',{'program':p,'token':b['token']});wait(jobs,job['id'],('paused',));jobs.control('test',job['id'],'continue');value=wait(jobs,job['id'])
                self.assertEqual(value['status'],'completed');block=p['blocks'][0]['id'];window=jobs.window('test',job['id'],block,8,16)
                np.testing.assert_array_equal(window['i'],jobs.get('test',job['id']).ctx.values[block][8:24])
                with self.assertRaises(KeyError):jobs.status('stranger',job['id'])
                with self.assertRaises(ValueError):jobs.window('test',job['id'],block,-1,16)
            finally:jobs.close()
    def test_shared_branch_samples_and_soft_comparison(self):
        a=c.preset(['random_bits','conv_encode','mod_bpsk','awgn','demod_bpsk','conv_decode','sink'],{0:{'count':2048},3:{'esn0_db':0}});b=copy.deepcopy(a)
        b['blocks'][4].update(kind='soft_bpsk',params={k:v['default'] for k,v in c.BLOCKS['soft_bpsk']['params'].items()});b['blocks'][5].update(kind='conv_soft_decode',params={k:v['default'] for k,v in c.BLOCKS['conv_soft_decode']['params'].items()})
        result=studio.compare_branches([a,b]);self.assertLessEqual(result['branches'][1]['result']['metrics']['ber'],result['branches'][0]['result']['metrics']['ber'])
        prefix=result['shared_prefix'];hashes=[[v['sha256'] for v in branch['result']['experience']['observations'] if v['id'] in prefix] for branch in result['branches']];self.assertEqual(*hashes)
        b['seed']+=1
        with self.assertRaises(ValueError):studio.compare_branches([a,b])
    def test_generic_numeric_enum_and_global_sweep(self):
        p=c.PRESETS['text']['program'];built=c.build(p);mod=next(b for b in p['blocks'] if b['kind'].startswith('mod_'))
        # An existing demodulator enum is swept without assuming a noise parameter.
        demod=next(b for b in p['blocks'] if b['kind'].startswith('demod_'));enum=next((k for k,s in c.BLOCKS[demod['kind']]['params'].items() if s['type']=='select'),None)
        if enum:
            settings={'block_id':demod['id'],'parameter':enum,'values':c.BLOCKS[demod['kind']]['params'][enum]['choices'],'frames':1,'target_errors':10000}
            self.assertTrue(sweep(p,built['token'],settings)['complete'])
        value=sweep(p,built['token'],{'global':'seed','values':[7,8,9],'frames':2,'target_errors':10000});self.assertEqual([r['frames'] for r in value['points']],[2,2,2])
        p=c.PRESETS['analog_am']['program'];built=c.build(p);block=next(b for b in p['blocks'] if b['kind']=='mod_am')
        key=next(k for k,s in c.BLOCKS[block['kind']]['params'].items() if s['type']=='number');spec=c.BLOCKS[block['kind']]['params'][key]
        value=sweep(p,built['token'],{'block_id':block['id'],'parameter':key,'values':[spec['default']],'frames':1});self.assertTrue(np.isfinite(value['points'][0]['rmse']))
    def test_exact_cancel_resume_counts(self):
        p=c.preset(['random_bits','mod_bpsk','awgn','demod_bpsk','sink'],{0:{'count':512},2:{'esn0_db':0}});b=c.build(p)
        settings={'block_id':p['blocks'][2]['id'],'values':[0,2,4],'frames':4,'target_errors':100000};cancel=threading.Event()
        partial=sweep(p,b['token'],settings,lambda v:cancel.set() if v['completed_frames']>=2 else None,cancel)
        self.assertFalse(partial['complete']);self.assertEqual(partial['completed_frames'],2)
        resumed=sweep(p,b['token'],settings,resume=partial);whole=sweep(p,b['token'],settings)
        self.assertEqual(resumed['points'],whole['points'])
    def test_durable_receipt_after_restart(self):
        p=c.PRESETS['text']['program'];b=c.build(p);payload={'program':p,'token':b['token'],'settings':{'global':'seed','values':[1,2],'frames':2,'target_errors':10000}}
        with tempfile.TemporaryDirectory() as root:
            jobs=Jobs(root,threading.BoundedSemaphore(1))
            with patch.dict(c.CONFIG,{'max_sweep_seconds':-1}):
                job=jobs.start('test','sweep',payload);value=wait(jobs,job['id']);self.assertFalse(value['result']['complete'])
            jobs.close();jobs=Jobs(root,threading.BoundedSemaphore(1))
            try:
                self.assertEqual(jobs.status('test',job['id'])['status'],'interrupted');resumed=jobs.control('test',job['id'],'resume-sweep');self.assertTrue(wait(jobs,resumed['id'])['result']['complete'])
            finally:jobs.close()
    def test_continuous_frames_retain_state(self):
        with tempfile.TemporaryDirectory() as root:
            jobs=Jobs(root,threading.BoundedSemaphore(1));p=c.PRESETS['agc_soft']['program'];b=c.build(p)
            try:
                job=jobs.start('test','continuous',{'program':p,'token':b['token'],'frames':3});value=wait(jobs,job['id']);self.assertEqual(value['status'],'completed',value['error']);r=value['result']
                self.assertEqual(len(r['frames']),3);self.assertGreater(r['state_count'],0);self.assertEqual(r['last']['seed'],p['seed']+2);self.assertGreater(r['bit_count'],0)
            finally:jobs.close()
    def test_experiment_job_generates_curves(self):
        with tempfile.TemporaryDirectory() as root:
            jobs=Jobs(root,threading.BoundedSemaphore(1));p=c.PRESETS['text']['program']
            try:
                job=jobs.start('test','experiments',{'programs':[p,p],'names':['A','B'],'settings':{'global':'seed','values':[1,2],'frames':1}});value=wait(jobs,job['id']);self.assertEqual(value['status'],'completed',value['error']);self.assertEqual(len(value['result']['curves']),2)
            finally:jobs.close()
    def test_http_projects_jobs_windows_reports(self):
        with tempfile.TemporaryDirectory() as root:
            with TestClient(server.create_app(data_dir=Path(root)/'data',upload_dir=Path(root)/'uploads',output_dir=Path(root)/'outputs')) as client:
                def call(action,**payload):
                    response=client.post('/api/communications/'+action,json={'session_id':'test',**payload});self.assertEqual(response.status_code,200,response.text);return response.json()
                p=c.PRESETS['text']['program'];b=c.build(p);saved=call('project-save',document=doc(p));self.assertEqual(call('project-load',id=saved['id'])['version'],1)
                job=call('job-start',kind='run',payload={'program':p,'token':b['token']});deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    value=call('job-status',id=job['id'])
                    if value['status']=='completed':break
                    time.sleep(.02)
                self.assertEqual(value['status'],'completed');self.assertEqual(call('window',id=job['id'],block_id=p['blocks'][0]['id'],offset=0,count=16)['plot_count'],16)
                d={**doc(p),'result':value['result']};self.assertTrue(call('report-preview',document=d)['summary']);response=client.post('/api/communications/report-pdf',json={'document':d});self.assertEqual(response.status_code,200,response.text[:200]);self.assertTrue(response.content.startswith(b'%PDF'))
                self.assertEqual(client.post('/api/communications/job-status',json={'session_id':'alien','id':job['id']}).status_code,404)

class NumericalTests(unittest.TestCase):
    def test_agc_reaches_target_and_retains_gain(self):
        x=np.full(2000,.05+0j);out,info=alg.agc(x,{'target':1.,'step':.03});self.assertAlmostEqual(np.mean(abs(out[-500:])),1.,places=5)
        p=c.build(c.PRESETS['agc_soft']['program']);states={};ctx=rt.Observer(p,states=states);rtblock={'id':'agc','kind':'rx_agc'}
        with rt.execution(ctx):
            rt.enter(rtblock);alg.agc(x,{'target':1.,'step':.03});gain=states['agc:agc']['log_gain'];alg.agc(x[:1],{'target':1.,'step':.03});self.assertAlmostEqual(states['agc:agc']['log_gain'],gain,places=8)
    def test_training_noise_variance_known_complex_gaussian(self):
        rng=np.random.default_rng(31);x=rng.choice([-1,1],50000);noise=(rng.normal(size=len(x))+1j*rng.normal(size=len(x)))*np.sqrt(.2/2)
        variance,info=alg.noise_estimate(.4*np.exp(.5j)*x+noise,np.array([-1,1]),x);self.assertAlmostEqual(variance,.2,delta=.004);self.assertIn('LS',info['method'])
    def test_resampler_tone_length_and_antialias(self):
        x=np.exp(2j*np.pi*.04*np.arange(1024));y=alg.resample(x,3,2);self.assertEqual(len(y),1536);expected=np.exp(2j*np.pi*.04*np.arange(1536)*2/3);self.assertLess(np.mean(abs(y[32:-32]-expected[32:-32])**2),1e-6)
        low=alg.resample(x,1,2);high=alg.resample(np.exp(2j*np.pi*.4*np.arange(1024)),1,2);self.assertGreater(np.mean(abs(low[32:-32])**2),.99);self.assertLess(np.mean(abs(high[32:-32])**2),.0001)
    def test_fse_receiver_fractional_sps_and_low_error(self):
        for name in ('fractional_equalizer','resample_receiver'):
            r=execute(c.PRESETS[name]['program']);self.assertLess(r['metrics']['ber'],.01)
    def test_ofdm_frequency_acquisition_across_seeds(self):
        for seed in (0,1,2,42):
            p=copy.deepcopy(c.PRESETS['ofdm_cfo_tracking']['program']);p['seed']=seed;self.assertLess(execute(p)['metrics']['ber'],.02)
    def test_time_multipath_and_burst_seed_reproducibility(self):
        for name in ('ofdm_cfo_tracking','burst_interleave'):
            p=c.PRESETS[name]['program'];self.assertEqual(execute(p),execute(p))
    def test_pdf_contains_chinese_and_rejects_stale_result(self):
        from pypdf import PdfReader
        p=c.PRESETS['text']['program'];d={**doc(p),'result':execute(p)};pdf=report.render(d);reader=PdfReader(io.BytesIO(pdf));text=''.join(page.extract_text() for page in reader.pages)
        self.assertIn('海洋通信实验',text);self.assertIn('复现信息',text);self.assertIn('BER',text)
        d['program']=copy.deepcopy(p);d['program']['seed']+=1
        with self.assertRaises(ValueError):report.render(d)

if __name__=='__main__':
    log=ROOT/'logs/communications/experience.log';log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w',encoding='utf-8') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    print(log.read_text(encoding='utf-8'));sys.exit(not result.wasSuccessful())
