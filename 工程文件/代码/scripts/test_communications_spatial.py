"""v0.4.8 wireless numerical and typed-pipeline regression."""
from pathlib import Path
from types import SimpleNamespace
import copy
import json
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src import communications as c, communication_dsp as dsp, communication_runtime as runtime
from src import communication_spatial as spatial, communication_ofdma as ofdma, communication_hopping as hopping


def params(kind,**changes):
    return {**{key:spec['default'] for key,spec in c.BLOCKS[kind]['params'].items()},**changes}


def execute(program):
    built=c.build(program)
    return c.run(built['program'],built['token'])


def complex_array(value):return np.array(value['i'])+1j*np.array(value['q'])


class SpatialTests(unittest.TestCase):
    def test_all_eleven_presets_real_pipeline_and_retained_arrays(self):
        seen=[]
        for module in (spatial,ofdma,hopping):
            for key,preset in module.presets(c.preset).items():
                result=execute(preset['program']);json.dumps(result,allow_nan=False)
                self.assertEqual(result['metrics']['ber'],0,key)
                self.assertEqual(len(result['sink']['values']),len(result['sink']['reference']))
                details=result['advanced']['wireless']
                receiver=next(v for k,v in details.items() if k in module.RX and 'recovered_symbols' in v)
                self.assertGreater(receiver['recovered_symbols']['shape'][0],0)
                for entry in details.values():
                    for name in ('full_tx','full_rx','stream_symbols'):
                        if name in entry:self.assertEqual(list(complex_array(entry[name]).shape),entry[name]['shape'])
                seen.append(key)
        self.assertEqual(len(seen),11)

    def test_sic_exact_recovery_and_noise_improvement(self):
        rng=np.random.default_rng(17);bits=rng.integers(0,2,16000,dtype=np.uint8);symbols,_=dsp.map_bits(bits,'qpsk')
        h=np.array([[1,.8],[.2,1]],complex);clean=symbols.reshape(-1,2)@h.T/np.sqrt(2)
        for method in (0,1,2,3):
            decoded,trace=spatial.detect(clean,h,0,'qpsk',method)
            np.testing.assert_allclose(decoded.ravel(),symbols,atol=1e-12)
            if method>=2:
                self.assertEqual(sorted(trace['orders'][0]),[0,1])
                np.testing.assert_allclose(np.array(trace['residual_power'])[:,-1],0,atol=1e-25)
        variance=.2;received=clean+np.sqrt(variance/2)*(rng.normal(size=clean.shape)+1j*rng.normal(size=clean.shape))
        errors=[]
        for method in range(4):
            decoded,_=spatial.detect(received,h,variance,'qpsk',method);hard,_=dsp.decisions(decoded.ravel(),'qpsk');errors.append(int(np.sum(hard!=bits)))
        self.assertLess(errors[2],errors[0]*.85)
        self.assertLess(errors[3],errors[1]*.9)
        with self.assertRaises(ValueError):spatial.detect(clean,np.ones((2,2)),0,'qpsk',2)
        with self.assertRaises(ValueError):spatial.detect(clean,np.diag([1,0]),.1,'qpsk',3)

    def test_mobile_time_and_spatial_correlation_continuity(self):
        q=params('spatial_dynamic',noise=False,velocity_kmh=30,tx_correlation=.7,rx_correlation=.6)
        tx=np.ones((6000,2),complex)/np.sqrt(2)
        full,_=spatial.dynamic_channel(tx,q,np.random.default_rng(9),1000)
        ctx=SimpleNamespace(states={},block={'id':'mobile'})
        with runtime.execution(ctx):
            rng=np.random.default_rng(9);a,da=spatial.dynamic_channel(tx[:2500],q,rng,1000);b,db=spatial.dynamic_channel(tx[2500:],q,rng,1000)
        np.testing.assert_allclose(np.vstack([a,b]),full,atol=1e-13)
        self.assertAlmostEqual(db['time_seconds'][0],2.5)
        self.assertAlmostEqual(da['doppler_hz'],30/3.6*2.4e9/299792458)
        h=np.concatenate([complex_array(da['channel_trace']),complex_array(db['channel_trace'])])
        correlation=lambda a,b:abs(np.vdot(a,b))/np.sqrt(np.vdot(a,a).real*np.vdot(b,b).real)
        self.assertAlmostEqual(correlation(h[:,0,0],h[:,0,1]),.7,delta=.13)
        self.assertAlmostEqual(correlation(h[:,0,0],h[:,1,0]),.6,delta=.13)

    def test_periodic_pilots_track_actual_mobile_channel(self):
        rng=np.random.default_rng(5);symbols,_=dsp.map_bits(rng.integers(0,2,4000,dtype=np.uint8),'qpsk')
        tx,state=spatial.tracking_encode(symbols,params('tx_mimo_tracking',interval=4))
        received,_=spatial.dynamic_channel(tx,params('spatial_dynamic',noise=False,velocity_kmh=6),rng,1000)
        tracked,details=spatial.tracking_decode(received,state,params('rx_mimo_tracking',detector=0),'qpsk')
        h=np.linalg.lstsq(state['pilot'],received[state['pilot_slots'][0]],rcond=None)[0].T
        stale,_=spatial.detect(received[state['data_slots']],h,0,'qpsk',0)
        self.assertLess(np.mean(abs(tracked-symbols)**2),np.mean(abs(stale.ravel()-symbols)**2)*.01)
        self.assertGreater(len(details['tracking']['pilot_slots']),20)
        # Receiver output is independent of simulation truth and payload fields.
        altered={**state,'tx':np.zeros_like(tx),'channel_matrix':np.zeros((2,2))}
        again,_=spatial.tracking_decode(received,altered,params('rx_mimo_tracking',detector=0),'qpsk')
        np.testing.assert_array_equal(tracked,again)

    def test_mimo_ofdm_matrix_estimation_and_four_detectors(self):
        rng=np.random.default_rng(38);symbols,_=dsp.map_bits(rng.integers(0,2,2052,dtype=np.uint8),'qam16')
        q=params('tx_mimo_ofdm');tx,state=spatial.ofdm_encode(symbols,q)
        received,channel=spatial.multipath_channel(tx,params('spatial_multipath',noise=False),rng)
        taps=np.zeros((q['nfft'],2,2),complex);taps[channel['path_delays']]=complex_array(channel['path_matrices']);truth=np.fft.fft(taps,axis=0)
        for method in range(4):
            decoded,details=spatial.ofdm_decode(received,state,params('rx_mimo_ofdm',detector=method),'qam16')
            np.testing.assert_allclose(decoded,symbols,atol=2e-12)
            np.testing.assert_allclose(complex_array(details['channel_estimate']),truth,atol=2e-12)
        self.assertEqual(details['recovered_grid']['shape'][2],2)

    def test_ofdma_independent_users_power_scheduling_and_metrics(self):
        base=copy.deepcopy(c.PRESETS['ofdma_fair']['program'])
        for scheduler in range(4):
            p=copy.deepcopy(base);p['blocks'][4]['params'].update(scheduler=scheduler,powers='0.5,2,1');p['blocks'][5]['params']['noise']=False
            result=execute(p);details=result['advanced']['wireless']['rx_ofdma'];self.assertEqual(result['metrics']['ber'],0)
            self.assertEqual([user['source_bits'] for user in details['users']],[256,384,256])
            self.assertEqual(sum(user['delivered_bits'] for user in details['users']),896)
            self.assertGreater(details['fairness'],.9);self.assertLessEqual(details['fairness'],1)
            owners=np.array(details['resources']['owners']);power=np.array(details['resources']['power'])
            for user in details['users']:
                mask=owners==user['id'];np.testing.assert_allclose(power[mask],user['power'])
                self.assertEqual(int(mask.sum())*2,user['source_bits']);self.assertGreater(user['mean_delay_seconds'],0)
                self.assertAlmostEqual(user['throughput_bps']*details['duration_seconds'],user['delivered_bits'])
        row,owner,queue,_=ofdma.schedule(np.array([100,100,100]),params('tx_ofdma',arrival_gap=0,weights='1,2,1'))
        np.testing.assert_array_equal(np.sort(row[row>=0]),np.arange(300))
        self.assertGreater(np.count_nonzero(owner[0]==1),np.count_nonzero(owner[0]==0))
        self.assertEqual(queue[0].tolist(),[100,100,100])

    def test_ofdma_user_noise_affects_its_real_delivery(self):
        p=copy.deepcopy(c.PRESETS['ofdma_fair']['program']);p['blocks'][5]['params']['snrs']='60,-6,60'
        details=execute(p)['advanced']['wireless']['rx_ofdma'];users=details['users']
        self.assertEqual(users[0]['ber'],0);self.assertEqual(users[2]['ber'],0)
        self.assertGreater(users[1]['ber'],.1);self.assertLess(users[1]['delivered_bits'],users[1]['source_bits'])
        self.assertLess(details['fairness'],.8)

    def test_fhss_joint_phase_delay_and_strong_tone_recovery(self):
        rng=np.random.default_rng(33);bits=rng.integers(0,2,2048,dtype=np.uint8);symbols,_=dsp.map_bits(bits,'qpsk');state={}
        tx,_=hopping.encode(symbols,params('tx_fhss',phase=19),state,1000)
        received=np.pad(tx+2,(53,0));details=hopping.acquire(received,state['fhss'],params('rx_hop_sync',threshold=.01))
        self.assertEqual(details['sync']['code_phase'],19);self.assertEqual(details['sync']['delay_samples'],53)
        restored,_=hopping.decode(received,state['fhss']);np.testing.assert_allclose(restored,symbols,atol=2e-11)
        plain=symbols+2*np.sqrt(16);plain_bits,_=dsp.decisions(plain,'qpsk');self.assertGreater(np.mean(plain_bits!=bits),.2)

    def test_continuous_frames_keep_mobile_and_hop_state(self):
        for preset in ('mimo_mobile_tracking','fhss_acquisition'):
            p=c.PRESETS[preset]['program'];built=c.build(p);states={};results=[]
            for _ in range(2):
                result,_=runtime.observe_run(built['program'],built['token'],states=states);results.append(result)
                self.assertLess(result['metrics']['ber'],.03)
            a,b=[r['advanced']['wireless'] for r in results]
            if preset.startswith('mimo'):
                self.assertGreater(b['spatial_dynamic']['time_seconds'][0],a['spatial_dynamic']['time_seconds'][-1])
            else:
                self.assertNotEqual(a['tx_fhss']['transmitted_phase'],b['tx_fhss']['transmitted_phase'])
                self.assertEqual(b['tx_fhss']['transmitted_phase'],b['rx_hop_sync']['sync']['code_phase'])

    def test_bad_parameters_and_typed_pairs_fail_at_build(self):
        cases=[('mimo_ofdm_zf','tx_mimo_ofdm',{'cp':2}),('mimo_mobile_tracking','spatial_dynamic',{'velocity_kmh':350,'carrier_ghz':100}),
               ('ofdma_fair','tx_ofdma',{'weights':'1,2'}),('ofdma_fair','tx_ofdma',{'powers':'0,1,1'}),
               ('ofdma_fair','ofdma_channel',{'gains':'1,0,1'}),('fhss_acquisition','tx_fhss',{'bins':'-8,8'}),
               ('mimo_ofdm_zf','spatial_multipath',{'delays':'0,-1,7'})]
        for preset,kind,changes in cases:
            p=copy.deepcopy(c.PRESETS[preset]['program']);next(b for b in p['blocks'] if b['kind']==kind)['params'].update(changes)
            with self.subTest(preset=preset,changes=changes),self.assertRaises(ValueError):c.build(p)
        p=copy.deepcopy(c.PRESETS['ofdma_fair']['program']);p['blocks'][0]['params']['count']=255
        with self.assertRaises(ValueError):c.build(p)

    def test_capture_confidence_failure_completes_real_receiver_for_arq(self):
        for preset,receiver in [('fhss_acquisition','rx_hop_sync'),('dsss_interference','rx_code_acquire')]:
            p=copy.deepcopy(c.PRESETS[preset]['program']);next(b for b in p['blocks'] if b['kind']==receiver)['params']['threshold']=.99
            for block in p['blocks']:
                if block['kind']=='complex_awgn':block['params']['snr_db']=-3
            result=execute(p);details=result['advanced']['wireless'][receiver]
            detected=details['sync']['detected'] if 'sync' in details else details['detected']
            self.assertFalse(detected);self.assertEqual(result['metrics']['fer'],1)
            self.assertEqual(len(result['sink']['values']),len(result['sink']['reference']))
        state={};hopping.encode(np.ones(16,complex),params('tx_fhss'),state,1000)
        details=hopping.acquire(np.zeros(0,complex),state['fhss'],params('rx_hop_sync'))
        decoded,details=hopping.decode(np.zeros(0,complex),state['fhss'])
        self.assertFalse(details['sync']['detected']);np.testing.assert_array_equal(decoded,np.zeros(16))
        p=copy.deepcopy(c.PRESETS['fhss_acquisition']['program']);p['blocks']=[b for b in p['blocks'] if b['kind']!='rx_hop_sync']
        with self.assertRaises(ValueError):c.build(p)


if __name__=='__main__':unittest.main()
