"""Core signal recovery, measured DPD learning, and Polar decoding checks."""
from pathlib import Path
import copy
import json
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src import communications as c, communication_dsp as dsp
from src import communication_waveform_v049 as w, communication_polar as polar


def params(kind,**changes):
    return {**{k:v['default'] for k,v in c.BLOCKS[kind]['params'].items()},**changes}


def execute(program):
    built=c.build(program);return c.run(built['program'],built['token'])


class WaveformTests(unittest.TestCase):
    def test_presets_full_pipeline_json_and_zero_errors(self):
        for module in (w,polar):
            for key,preset in module.presets(c.preset).items():
                result=execute(preset['program']);json.dumps(result,allow_nan=False)
                self.assertEqual(result['metrics']['ber'],0,key)
                self.assertEqual(result['sink']['values'],result['sink']['reference'],key)

    def test_scfdma_maps_both_allocations_and_preserves_partial_group(self):
        rng=np.random.default_rng(91);symbols=dsp.map_bits(rng.integers(0,2,398,dtype=np.uint8),'qpsk')[0]
        for mapping in (0,1):
            q=params('tx_scfdma',mapping=mapping);expanded=w.spread(symbols,q['size']);wave,state=w.scfdma_encode(expanded,q)
            recovered,detail=w.scfdma_decode(wave,state,{'regularization':0})
            decoded=w.spread(recovered,q['size'],True)[:len(symbols)]
            np.testing.assert_allclose(decoded,symbols,atol=1e-12)
            self.assertEqual(len(set(detail['carriers'])),q['size'])
            self.assertEqual(detail['start_sample'],0)

    def test_interleaved_dft_waveform_reduces_papr(self):
        rng=np.random.default_rng(77);symbols=dsp.map_bits(rng.integers(0,2,8192,dtype=np.uint8),'qpsk')[0]
        q=params('tx_scfdma',mapping=1)
        plain,_=w.scfdma_encode(symbols,q);spread,_=w.scfdma_encode(w.spread(symbols,q['size']),q)
        skip=2*(q['nfft']+q['cp'])
        papr=lambda x:np.max(abs(x)**2)/np.mean(abs(x)**2)
        self.assertLess(papr(spread[skip:]),papr(plain[skip:])*.5)

    def test_measured_dpd_inverse_improves_independent_validation_waveform(self):
        rng=np.random.default_rng(8);q=params('tx_memory_pa')
        training=(rng.normal(size=4096)+1j*rng.normal(size=4096))*.48
        measured=w.pa_model(training,q);coeff,error=w.train_dpd(training,measured,5,3,1e-6)
        validation=(rng.normal(size=4096)+1j*rng.normal(size=4096))*.34
        before=w.pa_model(validation,q);after=w.pa_model(w.basis(validation,5,3)@coeff,q)
        def evm(y):
            gain=np.vdot(validation,y)/np.vdot(validation,validation)
            return np.linalg.norm(y/gain-validation)/np.linalg.norm(validation)
        self.assertLess(error,.02);self.assertLess(evm(after),evm(before)*.35)
        self.assertLess(np.linalg.norm(after-validation),np.linalg.norm(before-validation)*.1)

    def test_memory_pa_split_execution_matches_full_convolution(self):
        rng=np.random.default_rng(7);x=rng.normal(size=100)+1j*rng.normal(size=100);q=params('tx_memory_pa')
        full=w.pa_model(x,q);split=37;history=x[split-q['depth']+1:split]*10**(-q['backoff_db']/20)
        parts=np.r_[w.pa_model(x[:split],q),w.pa_model(x[split:],q,history)]
        np.testing.assert_allclose(parts,full,atol=1e-12)

    def test_public_marker_recovery_estimates_actual_clock_and_carrier(self):
        rng=np.random.default_rng(9);symbols=dsp.map_bits(rng.integers(0,2,2048,dtype=np.uint8),'qpsk')[0]
        ofdm=params('tx_ofdm',active_count=48);wave,_=dsp.ofdm_modulate(symbols,ofdm)
        for method in (0,1):
            for ppm in (-600,450):
                q=params('rx_burst_sync',method=method);packet,_=w.burst_encode(wave,q)
                received=w.burst_impair(packet,{'delay':43,'ppm':ppm,'hz':-59},64000)
                recovered,detail=w.synchronize(received,q,64000,len(wave))
                self.assertTrue(detail['detected']);self.assertAlmostEqual(detail['start_sample'],43,delta=.02)
                self.assertAlmostEqual(detail['clock_ppm'],ppm,delta=5)
                self.assertAlmostEqual(detail['frequency_hz'],-59,delta=.5)
                decoded,_=dsp.ofdm_demodulate(recovered,ofdm,params('rx_ofdm'),len(symbols))
                np.testing.assert_array_equal(dsp.decisions(decoded,'qpsk')[0],dsp.decisions(symbols,'qpsk')[0])

    def test_replay_synchronizer_uses_configuration_and_recording_only(self):
        rng=np.random.default_rng(90);ofdm=params('tx_ofdm',active_count=48)
        symbols=dsp.map_bits(rng.integers(0,2,512,dtype=np.uint8),'qpsk')[0];wave,_=dsp.ofdm_modulate(symbols,ofdm)
        q=params('rx_burst_sync',payload_samples=len(wave));packet,_=w.burst_encode(wave,q)
        recorded=w.burst_impair(packet,{'delay':21,'ppm':200,'hz':22},64000)
        result,detail,rate=w.run_stage('rx_burst_sync',recorded,q,{},None,64000)
        self.assertEqual(len(result),len(wave));self.assertTrue(detail['detected']);self.assertEqual(rate,64000)

    def test_pairing_rejects_mismatched_transform_and_dpd_plant(self):
        p=copy.deepcopy(c.PRESETS['scfdma_localized']['program']);p['blocks'][3]['params']['size']=32
        with self.assertRaises(ValueError):c.build(p)
        p=copy.deepcopy(c.PRESETS['memory_pa_dpd']['program']);p['blocks'][7]['params']['memory']=.2
        with self.assertRaises(ValueError):c.build(p)
        p=copy.deepcopy(c.PRESETS['scfdma_localized']['program']);p['blocks'].pop(6)
        with self.assertRaises(ValueError):c.build(p)


class PolarTests(unittest.TestCase):
    def test_transform_known_word_and_inverse(self):
        word=np.array([1,0,1,1,0,0,1,0],np.uint8)
        np.testing.assert_array_equal(polar.transform(word),[0,1,1,1,1,0,1,0])
        np.testing.assert_array_equal(polar.transform(polar.transform(word)),word)

    def test_lengths_rates_and_padding_roundtrip(self):
        bits=np.random.default_rng(71).integers(0,2,71,dtype=np.uint8)
        for n,rate in ((64,2),(64,3),(128,1),(128,2),(256,3)):
            q=params('polar_decode',n=n,rate=rate,method=0);encoded=polar.encode('polar_encode',bits,q)
            decoded,details=polar.decode('polar_decode',30*(1-2*encoded.astype(float)),q)
            self.assertEqual(len(encoded),polar.encoded_count('polar_encode',len(bits),q))
            np.testing.assert_array_equal(decoded[:len(bits)],bits);self.assertTrue(details['crc_pass'])

    def test_crc_list_paths_correct_errors_left_by_sc(self):
        rng=np.random.default_rng(17);bits=rng.integers(0,2,960,dtype=np.uint8);q=params('polar_decode')
        encoded=polar.encode('polar_encode',bits,q);sigma=.8
        llr=2*((1-2*encoded.astype(float))+rng.normal(size=len(encoded))*sigma)/sigma**2
        sc,sc_detail=polar.decode('polar_decode',llr,{**q,'method':0});scl,scl_detail=polar.decode('polar_decode',llr,q)
        self.assertGreater(np.count_nonzero(sc!=bits),0);np.testing.assert_array_equal(scl,bits)
        self.assertGreater(sc_detail['failed_codewords'],0);self.assertEqual(scl_detail['failed_codewords'],0)

    def test_soft_pairing_checks_public_code_parameters(self):
        p=copy.deepcopy(c.PRESETS['polar_scl']['program']);p['blocks'][5]['params']['n']=256
        with self.assertRaises(ValueError):c.build(p)


if __name__=='__main__':unittest.main()
