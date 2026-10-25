"""v0.4.5 numerical and integration acceptance, including legacy presets."""
from pathlib import Path
import copy
import json
import os
import sys
import tempfile
import threading
import time
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ['RS_AGENT_LLM_ENABLED']='0'
import numpy as np
from src import communications as c, communication_dsp as dsp, communication_rf as rf, communication_codecs as codec
from src import communication_runtime as rt, communication_studio as studio, communication_v045 as extension
from src.communication_jobs import Jobs
from src.communication_sweep import sweep


def execute(p):
    built=c.build(p);return c.run(built['program'],built['token'])


def q(kind,**values):return {**{k:s['default'] for k,s in c.BLOCKS[kind]['params'].items()},**values}


class RFTests(unittest.TestCase):
    def test_gray_energy_roundtrip_and_llr(self):
        for scheme in ('psk8','qam64','qam256'):
            labels,points=dsp.constellation(scheme)
            self.assertAlmostEqual(float(np.mean(abs(points)**2)),1)
            distances=abs(points[:,None]-points);np.fill_diagonal(distances,np.inf)
            neighbors=np.isclose(distances,distances.min())
            for a,b in zip(*np.where(neighbors)): self.assertEqual(np.count_nonzero(labels[a]!=labels[b]),1)
            mapped,_=dsp.map_bits(labels.ravel(),scheme);np.testing.assert_allclose(mapped,points)
            bits,_=dsp.decisions(points,scheme);np.testing.assert_array_equal(bits,labels.ravel())
            np.testing.assert_array_equal(dsp.soft_demod(points,scheme,.1)<0,labels.ravel())

    def test_high_order_soft_coding_ofdm_and_rrc(self):
        for scheme in ('psk8','qam64','qam256'):
            for ofdm in (False,True):
                kinds=['random_bits','conv_encode','mod_'+scheme]+(['tx_ofdm'] if ofdm else [])+['ideal']+(['rx_ofdm'] if ofdm else [])+['soft_'+scheme,'conv_soft_decode','sink']
                self.assertEqual(execute(c.preset(kinds))['metrics']['ber'],0)
            p=c.preset(['random_bits','mod_'+scheme,'tx_frame','tx_rrc','ideal','rx_matched','rx_timing','rx_frame','demod_'+scheme,'sink'],{6:{'manual':True}})
            self.assertLess(execute(p)['metrics']['ber'],.005)

    def test_iq_inverse_uses_training(self):
        rng=np.random.default_rng(5);x=rng.normal(size=1000)+1j*rng.normal(size=1000)
        impaired,_=rf.process('iq_imbalance',x,q('iq_imbalance',gain_db=5,phase_deg=25),1000)
        fixed,_=rf.process('rx_iq',impaired,{},1000,training=x[:200])
        np.testing.assert_allclose(fixed,x,atol=1e-13)
        p=copy.deepcopy(c.PRESETS['rf_iq']['program']);good=execute(p)['metrics']['evm_percent'];p['blocks']=[b for b in p['blocks'] if b['kind']!='rx_iq'];bad=execute(p)['metrics']['evm_percent'];self.assertLess(good,bad/3)

    def test_dc_and_adc_quantization(self):
        x=np.tile([1+1j,-1-1j],1000);biased,_=rf.process('dc_offset',x,q('dc_offset'),1000)
        fixed,_=rf.process('rx_dc',biased,q('rx_dc'),1000);np.testing.assert_allclose(fixed,x,atol=1e-14)
        rng=np.random.default_rng(4);x=rng.uniform(-1,1,10000)+1j*rng.uniform(-1,1,10000)
        a,_=rf.process('adc',x,q('adc',bits=4,full_scale=1),1000);b,_=rf.process('adc',x,q('adc',bits=10,full_scale=1),1000)
        self.assertLess(np.mean(abs(b-x)**2),np.mean(abs(a-x)**2)/1000)
        _,stats=rf.process('adc',np.array([2+0j,0+3j,.2+.2j]),q('adc',full_scale=1),1000);self.assertEqual(stats['clipped_samples'],2)

    def test_pa_models_small_signal_and_saturation(self):
        x=np.array([1e-5,.1,1,10],complex)
        for model in (0,1):
            y,_=rf.process('tx_pa',x,q('tx_pa',backoff_db=0,model=model),1000)
            self.assertAlmostEqual(abs(y[0])/abs(x[0]),1,places=7);self.assertLess(abs(y[-1]),1.01)
            if model: self.assertGreater(np.angle(y[-1]),.4)
        low,_=rf.process('tx_pa',x,q('tx_pa',backoff_db=12),1000);self.assertLess(abs(low[2]),.26)

    def test_tone_and_notch_rejection(self):
        x=np.zeros(10000,complex);tone,_=rf.process('narrowband',x,q('narrowband',hz=123),1000)
        filtered,_=rf.process('rx_notch',tone,q('rx_notch',hz=123),1000)
        self.assertLess(np.mean(abs(filtered[2000:])**2),1e-20)
        other=np.exp(2j*np.pi*300*np.arange(10000)/1000);y,_=rf.process('rx_notch',other,q('rx_notch',hz=123),1000)
        self.assertGreater(np.mean(abs(y[2000:])**2),.9)

    def test_ofdm_allocation_roundtrip_and_tracking(self):
        from src import communication_algorithms as alg
        symbols,_=dsp.map_bits(np.random.default_rng(4).integers(0,2,1200,dtype=np.uint8),'qam64')
        for n in (32,64,128):
            for spacing in (2,4,8):
                config=q('tx_ofdm',nfft=n,cp=8,active_count=n-8,pilot_interval=spacing)
                wave,info=dsp.ofdm_modulate(symbols,config);active,pilots,data=dsp.ofdm_indices(n,config)
                self.assertEqual(len(active),n-8);self.assertEqual(info['roles'][0],'dc');self.assertGreater(info['roles'].count('guard'),0)
                out,_=dsp.ofdm_demodulate(wave,config,{'equalize':True,'regularization':1e-12},len(symbols));np.testing.assert_allclose(out,symbols,atol=1e-10)
                out,_=alg.ofdm_tracking(wave,config,q('rx_ofdm_tracking',regularization=1e-12),len(symbols));np.testing.assert_allclose(out,symbols,atol=1e-9)

    def test_clipping_reduces_peaks_and_preserves_cp(self):
        bits=np.random.default_rng(1).integers(0,2,8192,dtype=np.uint8);symbols,_=dsp.map_bits(bits,'qam16');config=q('tx_ofdm',active_count=48)
        wave,_=dsp.ofdm_modulate(symbols,config);fixed,_=rf.process('tx_clip_filter',wave,q('tx_clip_filter',threshold_db=3,iterations=4),64000,config)
        self.assertLess(rf.measure(fixed,64000)['papr_db'],rf.measure(wave,64000)['papr_db']-1)
        rows=fixed.reshape(-1,80);np.testing.assert_allclose(rows[:,:16],rows[:,-16:])
        spectrum=np.fft.fft(rows[:,16:],axis=1);self.assertLess(np.max(abs(spectrum[:,0])),1e-12)

    def test_puncture_arbitrary_lengths_and_neutral_llrs(self):
        rng=np.random.default_rng(8)
        for count in (1,3,7,31,129):
            bits=rng.integers(0,2,count,dtype=np.uint8);encoded=c.conv_encode(bits)
            for rate in (2,3):
                masked=codec.encode('puncture',encoded,{'rate':rate});llr=20*(1-2*masked.astype(float))
                restored=codec.depuncture(llr,len(encoded),rate)
                self.assertTrue(np.all(restored[~codec.puncture_mask(len(encoded),rate)]==0))
                np.testing.assert_array_equal(codec.soft_viterbi(restored),bits)

    def test_invalid_connections_and_parameters(self):
        cases=[c.preset(['random_bits','puncture','mod_qpsk','ideal','soft_qpsk','depuncture','sink']),
               c.preset(['random_bits','mod_qpsk','tx_clip_filter','ideal','demod_qpsk','sink']),
               c.preset(['random_bits','mod_bpsk','tx_frame','iq_imbalance','rx_frame','rx_iq','demod_bpsk','sink']),
               c.preset(['random_bits','mod_qpsk','narrowband','demod_qpsk','sink'],{2:{'hz':500}}),
               c.preset(['random_bits','mod_qpsk','tx_ofdm','ideal','rx_ofdm','demod_qpsk','sink'],{2:{'active_count':64}})]
        for p in cases:
            with self.assertRaises(ValueError):c.build(p)

    def test_welch_parseval_and_occupied_bandwidth(self):
        from scipy.signal import welch
        fs=1024;x=np.exp(2j*np.pi*128*np.arange(16384)/fs);m=rf.measure(x,fs)
        self.assertAlmostEqual(sum(m['density'])*fs/len(m['density']),1,places=9)
        self.assertAlmostEqual(m['papr_db'],0,places=10);self.assertLess(m['occupied_bandwidth_hz'],5)
        self.assertEqual(m['frequency_hz'][int(np.argmax(m['density']))],128)
        self.assertTrue(all(a>=b for a,b in zip(m['ccdf'],m['ccdf'][1:])))
        self.assertEqual(rf.measure(np.zeros(50),fs)['occupied_bandwidth_hz'],0)
        x=np.random.default_rng(17).normal(size=4096)+1j*np.random.default_rng(19).normal(size=4096)
        _,expected=welch(x,fs=fs,window=np.hanning(1024),nperseg=1024,noverlap=512,detrend=False,return_onesided=False)
        np.testing.assert_allclose(rf.measure(x,fs)['density'],np.fft.fftshift(expected),rtol=1e-12,atol=1e-14)

    def test_efficiency_includes_cp_and_reference_evm(self):
        p=copy.deepcopy(c.PRESETS['rf_pa']['program']);p['blocks']=[b for b in p['blocks'] if b['kind']!='tx_pa'];a=execute(p)
        next(b for b in p['blocks'] if b['kind']=='tx_ofdm')['params']['cp']=32;b=execute(p)
        self.assertLess(b['metrics']['net_bit_rate'],a['metrics']['net_bit_rate'])
        m=a['metrics'];self.assertAlmostEqual(m['net_bit_rate'],m['bit_count']/(m['tx_sample_count']/a['advanced']['sample_rate']))
        self.assertEqual(len(a['analysis']['ofdm_evm']['percent']),len(a['advanced']['ofdm']['data_carriers']))
        built=c.build(p);_,ctx=rt.observe_run(p,built['token'])
        mapping=next(v for v in ctx.observations if v['kind']=='mod_qam64')
        output=next(v for v in ctx.observations if v['kind']=='rx_ofdm')
        self.assertEqual(mapping['sample_rate'],output['sample_rate'])

    def test_theory_and_sweep_metrics(self):
        self.assertAlmostEqual(rf.theory_ber('bpsk',0),.0786496035,places=9)
        self.assertAlmostEqual(rf.theory_ber('qpsk',10*np.log10(2)),rf.theory_ber('bpsk',0))
        p=c.PRESETS['rf_qam64']['program'];built=c.build(p);out=sweep(p,built['token'],{'block_id':'block-2','parameter':'esn0_db','values':[10,20],'frames':2})
        self.assertIn('近似',out['theory_label']);self.assertGreater(out['points'][0]['theory_ber'],out['points'][1]['theory_ber'])
        for row in out['points']:self.assertGreater(row['net_bit_rate'],0);self.assertGreater(row['evm_percent'],0)

    def test_all_presets_and_complete_receiver(self):
        for name,value in c.PRESETS.items():
            result=execute(value['program']);json.dumps(result,allow_nan=False)
            if result.get('transport') == 'iq':
                self.assertIsNone(result['metrics']['ber']);self.assertGreater(result['sink']['count'],0)
            else: self.assertTrue(np.isfinite(result['metrics'].get('ber',0)),name)
        for name in ('rf_qam64','rf_qam256','rf_puncture'):
            p=copy.deepcopy(c.PRESETS[name]['program']);p['blocks']=[b for b in p['blocks'] if c.BLOCKS[b['kind']]['category'] not in ('demodulator','rx_converter')]
            p=studio.complete_receiver(p);self.assertLess(execute(p)['metrics']['ber'],.1,name)

    def test_task_jobs_ownership_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            jobs=Jobs(temp,threading.BoundedSemaphore(2))
            try:
                for task in extension.TASKS:
                    p=c.PRESETS[task['preset']]['program'];b=c.build(p);j=jobs.start('owner','rf-task',{'program':p,'token':b['token'],'task_id':task['id']})
                    deadline=time.monotonic()+20
                    while time.monotonic()<deadline:
                        value=jobs.status('owner',j['id'])
                        if value['status'] in ('failed','completed'):break
                        time.sleep(.01)
                    self.assertEqual(value['status'],'completed',value.get('error'));self.assertTrue(value['result']['complete'])
                    observations=value['result']['baseline']['experience']['observations']
                    self.assertEqual(len(observations),len(p['blocks']))
                    window=jobs.window('owner',j['id'],observations[0]['id'],0,16)
                    self.assertEqual(len(window['i']),16)
                    with self.assertRaises(KeyError):jobs.status('other',j['id'])
                    doc={'document_schema':2,'name':'RF experiment','program':p,'rfComparisons':value['result']}
                    saved=studio.ProjectStore(temp).save('owner',doc);self.assertEqual(saved['document']['rfComparisons'],value['result'])
            finally:jobs.close()

    def test_stateful_notch_matches_one_pass(self):
        p=c.preset(['random_bits','mod_qpsk','narrowband','rx_notch','demod_qpsk','sink']);built=c.build(p)
        rng=np.random.default_rng(2);x=rng.normal(size=1000)+1j*rng.normal(size=1000);params=q('rx_notch')
        whole,_=rf.process('rx_notch',x,params,1000);states={};parts=[]
        ctx=rt.Observer(built,states=states)
        with rt.execution(ctx):
            rt.enter(p['blocks'][3])
            for part in np.array_split(x,5):parts.append(rf.process('rx_notch',part,params,1000)[0])
        np.testing.assert_allclose(np.concatenate(parts),whole)


if __name__=='__main__':
    log=ROOT/'logs/communications-rf/latest.log';log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w',encoding='utf-8') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    print(log.read_text(encoding='utf-8'));sys.exit(not result.wasSuccessful())
