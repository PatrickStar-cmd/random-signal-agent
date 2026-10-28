"""Numeric acceptance of sequence MLSE, observed MUSIC and streaming standard TDL."""
from pathlib import Path
import itertools
import sys
import unittest
import numpy as np
from scipy.special import j0
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src import communication_receiver_v0410 as receiver
from src import communication_array_v049 as array, communication_dsp as dsp


class ReceiverV0410Tests(unittest.TestCase):
    def test_mlse_sequence_matches_exhaustive_likelihood(self):
        rng=np.random.default_rng(4101)
        for scheme in ('bpsk','qpsk'):
            points=dsp.constellation(scheme)[1];history=points[[0,1]];tail=points[[0,0]]
            for taps in (2,3):
                h=np.array([1,.85+.12j,-.2j])[:taps];payload=points[rng.integers(len(points),size=4)]
                observed=np.convolve(np.r_[history,payload,tail],h)[len(history):len(history)+6]
                observed+=.6*(rng.normal(size=6)+1j*rng.normal(size=6))
                recovered,trace=receiver.viterbi_sequence(observed,h,points,history,tail)
                choices=list(itertools.product(range(len(points)),repeat=4))
                costs=[np.sum(abs(observed-np.convolve(np.r_[history,points[list(path)],tail],h)[len(history):len(history)+6])**2) for path in choices]
                np.testing.assert_array_equal(recovered[:4],points[list(choices[int(np.argmin(costs))])])
                self.assertAlmostEqual(trace['sequence_metric'],min(costs),places=10)
                self.assertEqual(trace['metric_evaluations'],6*len(points)**taps)

    def test_mlse_public_training_recovers_unknown_complex_channel(self):
        rng=np.random.default_rng(4102)
        for scheme in ('bpsk','qpsk'):
            symbols=dsp.map_bits(rng.integers(0,2,1024),scheme)[0]
            tx,public=receiver.mlse_frame(symbols,scheme,128);h=np.array([.7+.3j,.4-.2j,-.25j])
            y=np.convolve(tx,h);decoded,info=receiver.mlse_decode(y,public,3)
            np.testing.assert_array_equal(decoded,symbols)
            np.testing.assert_allclose(np.array(info['channel_estimate']['i'])+1j*np.array(info['channel_estimate']['q']),h,atol=1e-12)
            # Extra sender-only diagnostic fields have no effect on reception.
            other,_=receiver.mlse_decode(y,{**public,'true_channel':np.ones(3)*99,'payload':np.zeros_like(symbols)},3)
            np.testing.assert_array_equal(other,decoded)

    def test_music_identifies_public_pilot_target_and_drives_mvdr(self):
        rng=np.random.default_rng(4103);pilot=np.ones((256,1),complex)
        symbols=dsp.map_bits(rng.integers(0,2,4096),'qpsk')[0];frame=np.r_[pilot[:,0],symbols]
        jammer=dsp.map_bits(rng.integers(0,2,2*len(frame)),'qpsk')[0]*3
        y=frame[:,None]*array.steering(8,.5,17.5)+jammer[:,None]*array.steering(8,.5,-28)
        y+=.01*(rng.normal(size=y.shape)+1j*rng.normal(size=y.shape))
        public={'pilot':pilot,'prefix':0,'count':len(symbols),'spacing':.5}
        q={'sources':2,'step_deg':.25,'subarray':0,'forward_backward':True}
        info=receiver.music_estimate(y,public,q)['music']
        np.testing.assert_allclose(sorted(info['estimated_angles']),[-28,17.5],atol=.25)
        self.assertAlmostEqual(info['target_angle'],17.5,delta=.25)
        changed=receiver.music_estimate(y,{**public,'arrival_angles':[-60],'true_channel':np.zeros(8)},q)['music']
        self.assertEqual(info,changed)
        recovered,details=array.receive(y,public,'rx_array_mvdr',{'look_angle':info['target_angle'],'loading':.001})
        np.testing.assert_array_equal(dsp.decisions(recovered,'qpsk')[0],dsp.decisions(symbols,'qpsk')[0])
        self.assertGreater(details['rejection_db'],25)

    def test_music_spatial_smoothing_resolves_coherent_paths(self):
        rng=np.random.default_rng(4104);pilot=np.ones((256,1),complex)
        x=dsp.map_bits(rng.integers(0,2,4096),'qpsk')[0];frame=np.r_[pilot[:,0],x]
        h=array.steering(8,.5,12)+.35j*array.steering(8,.5,42)
        jammer=dsp.map_bits(rng.integers(0,2,2*len(frame)),'qpsk')[0]*2
        y=frame[:,None]*h+jammer[:,None]*array.steering(8,.5,-30)
        public={'pilot':pilot,'prefix':0,'count':len(x),'spacing':.5}
        info=receiver.music_estimate(y,public,{'sources':3,'step_deg':.25,'subarray':5,'forward_backward':True})['music']
        np.testing.assert_allclose(sorted(info['estimated_angles']),[-30,12,42],atol=.25)
        self.assertAlmostEqual(info['target_angle'],12,delta=.25)

    def test_standard_pdp_and_fractional_delay_response(self):
        for profile,count in enumerate((23,23,24)):
            p=receiver.tdl_parameters({'profile':profile,'delay_spread_ns':300,'doppler_hz':5},64000)
            self.assertEqual(len(p['powers']),count);self.assertAlmostEqual(sum(p['powers']),1)
            self.assertAlmostEqual(p['rms_delay_ns'],300,delta=.02)
        np.testing.assert_allclose(receiver.TDL_PROFILES['A'][0][-3:],[5.0066,5.3043,9.6586])
        np.testing.assert_allclose(receiver.TDL_PROFILES['B'][1][-3:],[-14.9,-9.2,-11.3])
        np.testing.assert_allclose(receiver.TDL_PROFILES['C'][0][-3:],[6.6374,7.0427,8.6523])
        for delay in (.13,2.37,7.9):
            h=receiver.fractional_kernel(delay);frequency=.15
            response=np.sum(h*np.exp(-2j*np.pi*frequency*np.arange(len(h))))
            self.assertLess(abs(response-np.exp(-2j*np.pi*frequency*(delay+8))),.002)

    def test_tdl_chunked_state_matches_single_stream(self):
        q={'profile':2,'delay_spread_ns':20000,'doppler_hz':21};fs=64000
        rng=np.random.default_rng(4105);data=rng.normal(size=2000)+1j*rng.normal(size=2000)
        whole,detail=receiver.tdl_process(data,q,fs,np.random.default_rng(77),{})
        memory={};random=np.random.default_rng(77)
        a,_=receiver.tdl_process(data[:777],q,fs,random,memory)
        b,detail2=receiver.tdl_process(data[777:],q,fs,random,memory)
        np.testing.assert_allclose(np.r_[a,b],whole,atol=2e-12)
        self.assertEqual(detail2['processed_samples'],detail['processed_samples'])

    def test_jakes_correlation_and_mean_path_power(self):
        q={'profile':0,'delay_spread_ns':300,'doppler_hz':50};fs=2000
        # Full traced sequences are formed from the same stored sinusoid bank.
        memory={};receiver.tdl_process(np.zeros(1),q,fs,np.random.default_rng(4106),memory)
        t=np.arange(12000)/fs;h=np.zeros((23,len(t)),complex)
        for wave in range(32):
            h+=np.exp(1j*(memory['phases'][:,wave,None]+2*np.pi*q['doppler_hz']*np.cos(memory['angles'][:,wave,None])*t))/np.sqrt(32)
        self.assertAlmostEqual(float(np.mean(abs(h)**2)),1,delta=.08)
        for lag in (2,5,10):
            observed=np.mean(h[:,lag:]*h[:,:-lag].conj())/np.mean(abs(h)**2)
            self.assertLess(abs(observed-j0(2*np.pi*q['doppler_hz']*lag/fs)),.08)

    def test_presets_execute_and_builder_requires_public_pairing(self):
        from src import communications as c
        results={}
        for key,entry in receiver.presets(c.preset).items():
            built=c.build(entry['program']);results[key]=c.run(built['program'],built['token'])
            self.assertTrue(np.isfinite(results[key]['metrics']['ber']),key)
        for key in ('mlse_bpsk','mlse_qpsk','music_mvdr','music_smoothing'):
            self.assertEqual(results[key]['metrics']['ber'],0,key)
        for key in ('tdl_a','tdl_b','tdl_c'):
            self.assertLess(results[key]['metrics']['ber'],.08,key)
        raw=c.preset(['random_bits','mod_qpsk','ideal','rx_mlse','demod_qpsk','sink'])
        with self.assertRaisesRegex(ValueError,'公共训练帧'):c.build(raw)

    def test_tdl_rrc_and_scfdma_observation_lengths(self):
        from src import communications as c, communication_runtime as runtime
        programs=[c.preset(['random_bits','mod_qpsk','tx_frame','tx_rrc','tdl_channel','complex_awgn','rx_complete','demod_qpsk','sink'],{4:{'doppler_hz':0},5:{'snr_db':35}}),
                  c.preset(['random_bits','mod_qpsk','tx_dft_spread','tx_scfdma','tdl_channel','complex_awgn','rx_scfdma','rx_dft_despread','demod_qpsk','sink'],{4:{'doppler_hz':0},5:{'snr_db':35}})]
        for program in programs:
            built=c.build(program);result,observer=runtime.observe_run(built['program'],built['token'],retain=True)
            plan=next(row for row in built['plan'] if row['kind']=='tdl_channel')
            self.assertEqual(len(observer.values[plan['id']]),plan['count'])
            self.assertEqual(result['metrics']['ber'],0)


if __name__=='__main__':unittest.main()
