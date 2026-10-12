"""Communication lab acceptance: codewords, Gray constellations, theory and API isolation."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import math
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); os.environ['RS_AGENT_LLM_ENABLED'] = '0'
import numpy as np
from fastapi.testclient import TestClient
import server
from src import communications as c


def execute(p):
    compiled=c.build(p)
    return c.run(compiled['program'],compiled['token'])


class CommunicationTests(unittest.TestCase):
    def test_hamming_all_codewords_and_every_single_bit_error(self):
        # Independent parity-check matrix for positions p1,p2,d1,p4,d2,d3,d4.
        h=np.array([[1,0,1,0,1,0,1],[0,1,1,0,0,1,1],[0,0,0,1,1,1,1]])
        for value in range(16):
            data=np.array([(value>>shift)&1 for shift in (3,2,1,0)],dtype=np.uint8)
            code=c.hamming_encode(data)
            np.testing.assert_array_equal(h.dot(code)%2,[0,0,0])
            for i in range(7):
                damaged=code.copy();damaged[i]^=1
                restored,corrected=c.hamming_decode(damaged)
                np.testing.assert_array_equal(restored,data);self.assertEqual(corrected,1)

    def test_convolutional_known_codeword_and_exhaustive_short_messages(self):
        # (7,5) octal, newest input is the high register bit; two tail zeros.
        np.testing.assert_array_equal(c.conv_encode(np.array([1,0,1,1],dtype=np.uint8)),[1,1,1,0,0,0,0,1,0,1,1,1])
        for value in range(64):
            bits=np.array([(value>>shift)&1 for shift in range(5,-1,-1)],dtype=np.uint8)
            encoded=c.conv_encode(bits)
            np.testing.assert_array_equal(c.viterbi_decode(encoded),bits)
            for i in range(len(encoded)):
                wrong=encoded.copy();wrong[i]^=1
                np.testing.assert_array_equal(c.viterbi_decode(wrong),bits)

    def test_constellations_unit_average_energy_gray_neighbors_roundtrip(self):
        for scheme in ('bpsk','qpsk','qam16'):
            labels,points=c.constellation(scheme)
            self.assertAlmostEqual(float(np.mean(abs(points)**2)),1)
            mapped,indices=c.modulate(labels.ravel(),scheme)
            np.testing.assert_allclose(mapped,points)
            recovered,_=c.demodulate(mapped,scheme)
            np.testing.assert_array_equal(recovered,labels.ravel())
            distances=abs(points[:,None]-points[None,:]);distance=np.min(distances[distances>1e-8])
            for a,b in zip(*np.where(np.isclose(distances,distance))):
                self.assertEqual(np.count_nonzero(labels[a]!=labels[b]),1)

    def test_combined_codecs_padding_and_utf8_ideal_roundtrip(self):
        p=c.preset(['text','hamming_encode','interleave','conv_encode','repeat_encode','mod_qam16','ideal','demod_qam16','repeat_decode','conv_decode','deinterleave','hamming_decode','sink'],{0:{'text':'你好🐳abc'}})
        result=execute(p)
        self.assertEqual(result['metrics']['bit_errors'],0)
        self.assertEqual(result['text']['sent'],result['text']['received'])
        self.assertEqual(result['sink']['count'],len('你好🐳abc'.encode())*8)

    def test_analog_mixing_pcm_quantization_bound_and_saturation(self):
        p=c.preset(['sine','square','pcm_encode','mod_qpsk','ideal','demod_qpsk','pcm_decode','sink'],{1:{'amplitude':.2,'frequency':24}})
        result=execute(p);t=np.arange(256)/256
        expected=.7*np.sin(2*np.pi*8*t)+.2*np.where(np.sin(2*np.pi*24*t)>=0,1,-1)
        np.testing.assert_allclose(result['sink']['reference'],expected)
        self.assertEqual(result['metrics']['bit_errors'],0)
        self.assertLessEqual(result['metrics']['rmse'],2/255)
        p['blocks'][2]['params']['full_scale']=.1;p['blocks'][-2]['params']['full_scale']=.1
        result=execute(p);self.assertGreater(result['metrics']['clipped_samples'],0)
        self.assertLessEqual(max(abs(v) for v in result['sink']['values']),.1)

    def test_seed_repeats_noise_and_source_and_changes_on_new_seed(self):
        p=copy.deepcopy(c.PRESETS['digital']['program']);first=execute(p)
        self.assertEqual(first,execute(p));p['seed']+=1
        self.assertNotEqual(first['sink']['reference'],execute(p)['sink']['reference'])

    def test_awgn_bpsk_ber_matches_theory_with_confidence(self):
        # 64k independent bits over eight seeds; expected P_b=0.5 erfc(sqrt(Es/N0)).
        errors=total=0
        for seed in range(8):
            p=c.preset(['random_bits','mod_bpsk','awgn','demod_bpsk','sink'],{0:{'count':8192},2:{'esn0_db':0}});p['seed']=seed
            result=execute(p);errors+=result['metrics']['bit_errors'];total+=result['metrics']['bit_count']
        probability=.5*math.erfc(1)
        self.assertLess(abs(errors/total-probability),5*math.sqrt(probability*(1-probability)/total))

    def test_attenuation_degrades_fixed_transmit_noise_and_compensation(self):
        p=c.preset(['random_bits','mod_qpsk','attenuation','awgn','demod_qpsk','sink'],{0:{'count':8192},2:{'db':0},3:{'esn0_db':8}})
        clean=execute(p);p['blocks'][2]['params']['db']=18;attenuated=execute(p)
        self.assertGreater(attenuated['metrics']['ber'],clean['metrics']['ber']+.1)
        p=c.preset(['random_bits','mod_qam16','attenuation','phase_shift','ideal','demod_qam16','sink'],{2:{'db':24},3:{'degrees':80}})
        self.assertEqual(execute(p)['metrics']['ber'],0)
        p['blocks'][5]['params']['compensate']=False
        self.assertGreater(execute(p)['metrics']['ber'],.1)

    def test_build_rejects_invalid_order_pairs_domains_aliasing_and_limits(self):
        cases=[c.preset(['sink']),c.preset(['random_bits','sink']),c.preset(['sine','mod_bpsk','ideal','demod_bpsk','sink']),c.preset(['random_bits','mod_bpsk','ideal','demod_qpsk','sink']),c.preset(['random_bits','hamming_encode','mod_bpsk','ideal','demod_bpsk','sink']),c.preset(['sine','text','pcm_encode','mod_bpsk','ideal','demod_bpsk','pcm_decode','sink']),c.preset(['random_bits','repeat_encode','mod_bpsk','ideal','demod_bpsk','repeat_decode','sink'],{5:{'factor':5}}),c.preset(['sine','pcm_encode','mod_bpsk','ideal','demod_bpsk','pcm_decode','sink'],{0:{'frequency':128}}),c.preset(['random_bits','repeat_encode','repeat_encode','mod_bpsk','ideal','demod_bpsk','repeat_decode','repeat_decode','sink'],{0:{'count':8192},1:{'factor':7},2:{'factor':7},6:{'factor':7},7:{'factor':7}})]
        for p in cases:
            with self.subTest(p=p),self.assertRaises(ValueError):c.build(p)

    def test_parameters_reject_nonfinite_wrong_types_unknown_fields_and_ids(self):
        original=c.PRESETS['digital']['program']
        for key,value in [('seed',True),('sample_rate',float('nan')),('sample_count',1025),('symbol_rate',float('inf')),('schema',True),('schema',2),('unknown',1)]:
            p=copy.deepcopy(original);p[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):c.build(p)
        p=copy.deepcopy(original);p['blocks'][0]['params']['surprise']=1
        with self.assertRaises(ValueError):c.build(p)
        p=copy.deepcopy(original);p['blocks'][1]['id']=p['blocks'][0]['id']
        with self.assertRaises(ValueError):c.build(p)
        p=c.preset(['bit_pattern','mod_bpsk','ideal','demod_bpsk','sink'],{0:{'pattern':'0102'}})
        with self.assertRaises(ValueError):c.build(p)

    def test_stale_build_fails_and_finite_zero_source(self):
        p=c.preset(['gaussian','pcm_encode','mod_bpsk','ideal','demod_bpsk','pcm_decode','sink'],{0:{'std':0}})
        built=c.build(p);p['seed']+=1
        with self.assertRaises(ValueError):c.run(p,built['token'])
        json.dumps(execute(p),allow_nan=False)

    def test_incomplete_drafts_roundtrip_but_cannot_build_or_run(self):
        for value in (None, -1, 1.5):
            p=copy.deepcopy(c.PRESETS['digital']['program']);p['blocks'][0]['params']['count']=value
            self.assertEqual(c.normalize(p,draft=True)['blocks'][0]['params']['count'],value)
            with self.assertRaises(ValueError):c.build(p)
        p=c.preset(['bit_pattern','mod_bpsk','ideal','demod_bpsk','sink'],{0:{'pattern':''}})
        self.assertEqual(c.normalize(p,draft=True)['blocks'][0]['params']['pattern'],'')
        with self.assertRaises(ValueError):c.build(p)


class CommunicationAPI(unittest.TestCase):
    def test_concurrency_limit_and_failed_runs_release_capacity(self):
        with tempfile.TemporaryDirectory() as temp:
            app=server.create_app(data_dir=Path(temp)/'data',upload_dir=Path(temp)/'upload',output_dir=Path(temp)/'out')
            compiled=c.build(c.PRESETS['text']['program'])
            payload={'program':compiled['program'],'token':compiled['token']}
            entered=threading.Barrier(c.CONFIG['concurrent_runs']+1);release=threading.Event()
            def blocked_run(*args):
                entered.wait(timeout=10)
                if not release.wait(timeout=15): raise RuntimeError('test worker timed out')
                raise ValueError('模拟运行失败')
            with TestClient(app) as client, ThreadPoolExecutor(max_workers=c.CONFIG['concurrent_runs']) as pool:
                with patch.object(c,'run',side_effect=blocked_run):
                    futures=[pool.submit(client.post,'/api/communications/run',json=payload) for _ in range(c.CONFIG['concurrent_runs'])]
                    try:
                        entered.wait(timeout=10)
                        self.assertEqual(client.post('/api/communications/run',json=payload).status_code,429)
                    finally:
                        release.set()
                    self.assertTrue(all(f.result(timeout=10).status_code==400 for f in futures))
                self.assertEqual(client.post('/api/communications/run',json=payload).status_code,200)

    def test_catalog_build_run_validation_and_workbench_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            app=server.create_app(data_dir=Path(temp)/'data',upload_dir=Path(temp)/'upload',output_dir=Path(temp)/'out')
            with TestClient(app) as client:
                before=client.get('/api/state?session_id=comm-qa').json()
                self.assertEqual(client.get('/api/communications/catalog').status_code,200)
                for preset in c.PRESETS.values():
                    build=client.post('/api/communications/build',json={'program':preset['program']})
                    self.assertEqual(build.status_code,200,build.text)
                    response=client.post('/api/communications/run',json={'program':build.json()['program'],'token':build.json()['token']})
                    self.assertEqual(response.status_code,200,response.text)
                    self.assertGreater(response.json()['sink']['count'],0)
                self.assertEqual(client.get('/api/state?session_id=comm-qa').json(),before)
                self.assertEqual(client.post('/api/communications/run',json={'program':preset['program'],'token':'old'}).status_code,400)
                self.assertEqual(client.post('/api/communications/build',json={'program':preset['program'],'unknown':1}).status_code,400)
                self.assertEqual(client.post('/api/communications/build',content='null',headers={'Content-Type':'application/json'}).status_code,400)
                self.assertEqual(client.post('/api/communications/build',content='{}',headers={'Content-Type':'text/plain'}).status_code,400)
                self.assertEqual(client.post('/api/communications/unknown',json={}).status_code,400)


if __name__=='__main__':
    log=ROOT/'logs/communications/latest.log';log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    print(log.read_text(encoding='utf-8'));sys.exit(not result.wasSuccessful())
