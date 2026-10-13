"""v0.4.3 numerical acceptance, interoperability, budgets and HTTP sweeps."""
from pathlib import Path
import copy
import json
import math
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); os.environ['RS_AGENT_LLM_ENABLED']='0'
import numpy as np
from fastapi.testclient import TestClient
import server
from src import communications as c, communication_codecs as codec, communication_dsp as dsp
from src.communication_sweep import sweep, interval


def execute(p):
    built=c.build(p)
    return c.run(built['program'],built['token'])


class CodecTests(unittest.TestCase):
    def test_crc_published_check_vectors_and_every_single_bit_error(self):
        bits=np.unpackbits(np.frombuffer(b'123456789',dtype=np.uint8))
        for width,expected in [(16,0x29B1),(32,0x0376E6E7)]:
            code=codec.encode('crc_append',bits,{'width':width})
            self.assertEqual(int(codec.bits_to_words(code[-width:],width)[0]),expected)
            for i in range(len(code)):
                damaged=code.copy(); damaged[i]^=1
                self.assertFalse(codec.decode('crc_check',damaged,{'width':width})[1]['crc_pass'])

    def test_prbs_period_balance_and_periodic_correlation(self):
        for degree in (7,9,15):
            period=2**degree-1; bits=codec.pn(period+32,degree)
            np.testing.assert_array_equal(bits[:32],bits[period:])
            self.assertEqual(int(bits[:period].sum()),2**(degree-1))
            x=2*bits[:period].astype(float)-1
            corr=np.fft.ifft(abs(np.fft.fft(x))**2).real
            np.testing.assert_allclose(corr[1:],-1,atol=1e-9)

    def test_scrambling_involution_initial_state_and_baseband_interoperability(self):
        rng=np.random.default_rng(12); bits=rng.integers(0,2,513,dtype=np.uint8); q={'degree':9,'initial':123}
        np.testing.assert_array_equal(codec.decode('descramble',codec.encode('scramble',bits,q),q)[0],bits)
        for shape in ('pam','baseband'):
            line=['line_manchester_encode'] if shape=='baseband' else []
            inverse=['line_manchester_decode'] if line else []
            p=c.preset(['pn_bits','crc_append','scramble']+line+['mod_'+shape,'ideal','demod_'+shape]+inverse+['descramble','crc_check','sink'],{0:{'count':127}})
            r=execute(p);self.assertEqual(r['metrics']['ber'],0);self.assertTrue(r['metrics']['crc_pass'])

    def test_companding_inverse_and_small_signal_quantization_advantage(self):
        x=np.linspace(-1,1,1001)
        for law in (0,1):
            np.testing.assert_allclose(codec.compand(codec.compand(x,law),law,True),x,atol=1e-14)
            q={'law':law,'bits':8,'full_scale':1}; signal=.01*np.sin(np.arange(1000)*.12)
            decoded=codec.decode('compand_decode',codec.encode('compand_encode',signal,q),q)[0]
            uniform=np.rint((signal+1)*255/2)*2/255-1
            self.assertLess(np.mean((decoded-signal)**2),np.mean((uniform-signal)**2)/20)

    def test_predictive_codecs_feedback_and_pam_transport(self):
        signal=.6*np.sin(np.arange(256)*.04)
        q={'bits':6,'full_scale':.2,'predictor':1}
        decoded=codec.decode('dpcm_decode',codec.encode('dpcm_encode',signal,q),q)[0]
        self.assertLess(max(abs(decoded-signal)),.2/63+1e-12)
        q={'step':.04}; decoded=codec.decode('delta_decode',codec.encode('delta_encode',signal,q),q)[0]
        self.assertLessEqual(max(abs(decoded-signal)),.04+1e-12)
        for name in ('compand','dpcm','delta'):
            r=execute(c.preset(['sine',name+'_encode','mod_pam','ideal','demod_pam',name+'_decode','sink']))
            self.assertEqual(r['metrics']['ber'],0);self.assertTrue(np.isfinite(r['metrics']['rmse']))

    def test_ldpc_syndromes_and_correction(self):
        rng=np.random.default_rng(8); bits=rng.integers(0,2,64*8,dtype=np.uint8); encoded=codec.ldpc_encode(bits)
        np.testing.assert_array_equal((encoded.reshape(-1,128)@codec.ldpc_matrix().T)%2,0)
        for position in (0,31,63,64,97,127):
            llr=(1-2*encoded.astype(float))*8; llr.reshape(-1,128)[:,position]*=-1
            restored,info=codec.ldpc_decode(llr)
            np.testing.assert_array_equal(restored,bits);self.assertEqual(info['failed_codewords'],0)

    def test_llr_sign_gray_mapping_and_zero_tail_viterbi(self):
        for scheme in ('bpsk','qpsk','qam16'):
            labels,points=c.constellation(scheme); llr=dsp.soft_demod(points,scheme,.1)
            np.testing.assert_array_equal(llr<0,labels.ravel())
        bits=np.array([1,0,1,1,0,0,1],dtype=np.uint8)
        np.testing.assert_array_equal(codec.soft_viterbi((1-2*c.conv_encode(bits).astype(float))*3),bits)

    def test_soft_viterbi_improves_awgn_ber(self):
        hard=soft=0
        for seed in range(5):
            p=c.preset(['random_bits','conv_encode','mod_bpsk','awgn','demod_bpsk','conv_decode','sink'],{0:{'count':4096},3:{'esn0_db':-2}});p['seed']=seed
            hard+=execute(p)['metrics']['bit_errors']
            p['blocks'][4]={'id':'soft','kind':'soft_bpsk','params':{'noise_variance':10**.2,'compensate':True}}
            p['blocks'][5]={'id':'decoder','kind':'conv_soft_decode','params':{}}
            soft+=execute(p)['metrics']['bit_errors']
        self.assertLess(soft,.85*hard)


class WaveformTests(unittest.TestCase):
    def test_all_new_presets_and_repeatability(self):
        for key in c.communication_catalog.presets(c.preset):
            with self.subTest(preset=key):
                p=c.PRESETS[key]['program']; r=execute(p)
                self.assertEqual(r,execute(p));json.dumps(r,allow_nan=False)
                self.assertLess(r['metrics']['ber'],.02)

    def test_ask_fsk_dpsk_msk_gmsk_ideal_roundtrip(self):
        for scheme in c.communication_catalog.MODULATIONS:
            for count in (17,257,2048):
                p=c.preset(['random_bits','mod_'+scheme,'ideal','demod_'+scheme,'sink'],{0:{'count':count}})
                self.assertEqual(execute(p)['metrics']['ber'],0,(scheme,count))
        for coherent in (True,False):
            p=c.preset(['random_bits','mod_fsk2','ideal','demod_fsk2','sink'],{3:{'coherent':coherent}})
            self.assertEqual(execute(p)['metrics']['ber'],0)

    def test_cpm_constant_envelope_frequency_and_gaussian_smoothing(self):
        bits=np.r_[np.zeros(40,dtype=np.uint8),np.ones(40,dtype=np.uint8)]
        waves={k:dsp.frequency_modulate(bits,k,{'sps':8,'bt':.3}) for k in ('msk','gmsk')}
        for wave in waves.values(): np.testing.assert_allclose(abs(wave),1,atol=1e-14)
        frequency=np.angle(waves['msk'][1:]*waves['msk'][:-1].conj())
        np.testing.assert_allclose(frequency,np.repeat(2*bits.astype(float)-1,8)*np.pi/16,atol=1e-13)
        smoothed=np.angle(waves['gmsk'][1:]*waves['gmsk'][:-1].conj())
        self.assertLess(max(abs(np.diff(smoothed))),max(abs(np.diff(frequency)))/2)

    def test_rrc_energy_and_complex_recovery_for_all_constellations(self):
        unframed=c.preset(['random_bits','mod_qpsk','tx_rrc','ideal','rx_matched','rx_timing','demod_qpsk','sink'])
        self.assertEqual(execute(unframed)['metrics']['ber'],0)
        for scheme in ('bpsk','qpsk','qam16'):
            for sps in (4,8,16):
                q={'sps':sps,'span':12,'rolloff':.35};h=dsp.rrc(q)
                self.assertAlmostEqual(float(np.sum(h*h)),1)
                p=c.preset(['random_bits','mod_'+scheme,'tx_frame','tx_rrc','sample_delay','ideal','rx_matched','rx_timing','rx_frame','demod_'+scheme,'sink'],{3:q,4:{'samples':83,'fraction':.67}})
                r=execute(p);self.assertEqual(r['metrics']['ber'],0);self.assertTrue(r['advanced']['recovery']['frame']['detected'])

    def test_unknown_carrier_phase_frequency_and_clock_recovery(self):
        for scheme in ('bpsk','qpsk'):
            p=c.preset(['random_bits','mod_'+scheme,'tx_frame','tx_rrc','frequency_offset','phase_shift','sample_delay','clock_drift','complex_awgn','rx_complete','demod_'+scheme,'sink'],{0:{'count':4096},2:{'length':512},4:{'hz':-23},5:{'degrees':125},6:{'samples':117,'fraction':.7},7:{'ppm':250},8:{'snr_db':25}})
            r=execute(p);self.assertLess(r['metrics']['ber'],.01)
            self.assertAlmostEqual(r['advanced']['recovery']['frequency']['estimated_hz'],-23,delta=.5)

    def test_frame_detector_uses_public_reference_and_reports_failure(self):
        known=dsp.public_preamble(256,'qpsk');rng=np.random.default_rng(19);payload=rng.choice([1,-1,1j,-1j],500)
        received=np.r_[np.zeros(93),np.r_[known,payload]*(.4+.7j)]
        recovered,info=dsp.frame_sync(received,known,756,.7)
        self.assertEqual(info['start_symbol'],93);self.assertTrue(info['detected']);np.testing.assert_allclose(recovered[256:],payload,atol=1e-14)
        _,info=dsp.frame_sync(rng.normal(size=1200)+1j*rng.normal(size=1200),known,756,.7)
        self.assertFalse(info['detected'])

    def test_complex_lms_nlms_rls_and_dfe_reduce_isi(self):
        rng=np.random.default_rng(51);_,points=c.constellation('qpsk');sent=rng.choice(points,4096);received=np.convolve(sent,[1,.5+.15j])[:len(sent)]
        for algorithm in (0,1,2):
            for dfe in (False,True):
                q={'half_taps':4,'feedback_taps':4,'dfe':dfe,'algorithm':algorithm,'step_size':.01 if algorithm==0 else .15,'forgetting':.998}
                equalized,info=dsp.equalize(received,points,q,sent[:1024]);region=slice(1200,-20)
                self.assertLess(np.mean(abs(equalized[region]-sent[region])**2),np.mean(abs(received[region]-sent[region])**2)/4)
                self.assertEqual(info['updates'],4096)

    def test_cma_blind_equalizer_improves_constant_modulus(self):
        rng=np.random.default_rng(52);_,points=c.constellation('qpsk');sent=rng.choice(points,12000);received=np.convolve(sent,[1,.4j])[:len(sent)]
        equalized,info=dsp.equalize(received,points,{'half_taps':4,'step_size':.02},cma=True)
        region=slice(9000,-20)
        self.assertLess(np.mean((abs(equalized[region])**2-1)**2),np.mean((abs(received[region])**2-1)**2)/3)
        self.assertEqual(info['training_symbols'],0)

    def test_fading_power_and_pilot_tracking(self):
        rng=np.random.default_rng(7)
        ray=np.array([dsp.fading(1,1000,0,rng)[0] for _ in range(12000)])
        self.assertLess(abs(np.mean(abs(ray)**2)-1),.04);self.assertLess(abs(np.mean(ray)),.03)
        _,points=c.constellation('qpsk');sent=rng.choice(points,1024);piloted=dsp.insert_pilots(sent,8)
        time=np.arange(len(piloted));gain=(.7+.1*np.cos(time*.002))*np.exp(1j*(.8+time*.003))
        restored,info=dsp.estimate_pilots(piloted*gain,8,len(sent),1e-6)
        self.assertLess(np.mean(abs(restored-sent)**2),1e-4);self.assertGreater(len(info['pilot_positions']),100)

    def test_phase_noise_seeded_and_changes_received_phase(self):
        p=c.preset(['random_bits','mod_qpsk','phase_noise','ideal','demod_qpsk','sink'],{2:{'std':1}})
        r=execute(p);self.assertEqual(r,execute(p));p['blocks'][2]['params']['std']=0
        clean=execute(p);self.assertNotEqual(r['channel'],clean['channel']);self.assertEqual(clean['metrics']['ber'],0)

    def test_ofdm_cp_ls_recovers_frequency_selective_channel(self):
        rng=np.random.default_rng(53);bits=rng.integers(0,2,2048,dtype=np.uint8);sent,_=c.modulate(bits,'qam16')
        for n in (32,64,128):
            q={'nfft':n,'cp':8};wave,_=dsp.ofdm_modulate(sent,q)
            received=np.r_[np.zeros(43),np.convolve(wave,[.8+.2j,.4,-.2j])]
            recovered,info=dsp.ofdm_demodulate(received,q,{'equalize':True,'regularization':1e-8},len(sent))
            np.testing.assert_allclose(recovered,sent,atol=1e-6);self.assertEqual(info['start_sample'],43)


class SweepAndValidationTests(unittest.TestCase):
    def test_wilson_interval_zero_errors_is_not_zero_uncertainty(self):
        lo,hi=interval(0,1000);self.assertAlmostEqual(lo,0);self.assertGreater(hi,.003);self.assertLess(hi,.004)
        lo,hi=interval(500,1000);self.assertLess(lo,.5);self.assertGreater(hi,.5)

    def test_seeded_sweep_theory_energy_conversion_and_stop(self):
        p=c.preset(['random_bits','mod_qpsk','awgn','demod_qpsk','sink'],{0:{'count':8192}});built=c.build(p)
        settings={'block_id':'block-2','mode':'ebn0','start':0,'stop':4,'step':2,'frames':4,'target_errors':100000}
        r=sweep(p,built['token'],settings);again=sweep(p,built['token'],settings)
        self.assertEqual(r['points'],again['points']);self.assertAlmostEqual(r['noise_db_shift'],10*math.log10(2))
        self.assertTrue(r['complete']);self.assertEqual(len(r['points']),3)
        for point in r['points']:
            theory=.5*math.erfc(math.sqrt(10**(point['db']/10)))
            self.assertAlmostEqual(point['theory_ber'],theory)
            self.assertLess(abs(point['ber']-theory),5*math.sqrt(theory*(1-theory)/point['bit_count']))
        r=sweep(p,built['token'],{**settings,'target_errors':1});self.assertTrue(all(x['frames']==1 for x in r['points']))

    def test_invalid_pair_types_order_and_resource_limits(self):
        cases=[['random_bits','ldpc_encode','mod_bpsk','ideal','demod_bpsk','ldpc_decode','sink'],
               ['random_bits','mod_qpsk','tx_rrc','ideal','demod_qpsk','sink'],
               ['random_bits','mod_qpsk','ideal','rx_frame','demod_qpsk','sink'],
               ['random_bits','mod_qpsk','tx_frame','ideal','demod_qpsk','sink'],
               ['random_bits','mod_qpsk','ideal','rx_matched','demod_qpsk','sink'],
               ['random_bits','mod_qam16','ideal','rx_frequency','demod_qam16','sink'],
               ['random_bits','line_nrz_polar_encode','mod_baseband','rayleigh','demod_baseband','line_nrz_polar_decode','sink']]
        for kinds in cases:
            with self.subTest(kinds=kinds),self.assertRaises(ValueError): c.build(c.preset(kinds))
        with self.assertRaises(ValueError): c.build(c.preset(['pn_bits','mod_bpsk','ideal','demod_bpsk','sink'],{0:{'degree':7,'initial':128}}))
        with self.assertRaises(ValueError): c.build(c.preset(['random_bits','mod_qpsk','tx_ofdm','ideal','rx_ofdm','demod_qpsk','sink'],{2:{'nfft':32,'cp':32}}))
        with self.assertRaises(ValueError): c.build(c.preset(['random_bits','repeat_encode','mod_bpsk','tx_rrc','ideal','rx_matched','rx_timing','demod_bpsk','repeat_decode','sink'],{0:{'count':8192},1:{'factor':7},3:{'sps':16},8:{'factor':7}}))

    def test_sweep_api_token_validation_limits_and_isolation(self):
        p=c.preset(['random_bits','crc_append','mod_bpsk','awgn','demod_bpsk','crc_check','sink'])
        with tempfile.TemporaryDirectory() as temp:
            with TestClient(server.create_app(data_dir=Path(temp)/'data',upload_dir=Path(temp)/'uploads',output_dir=Path(temp)/'outputs')) as client:
                built=client.post('/api/communications/build',json={'program':p}).json()
                settings={'block_id':'block-3','start':0,'stop':2,'step':2,'frames':2,'target_errors':1000}
                payload={'program':p,'token':built['token'],'settings':settings}
                response=client.post('/api/communications/sweep',json=payload)
                self.assertEqual(response.status_code,200,response.text);self.assertEqual(len(response.json()['points']),2)
                self.assertEqual(client.post('/api/communications/sweep',json={**payload,'token':'stale'}).status_code,400)
                self.assertEqual(client.post('/api/communications/sweep',json={**payload,'settings':{**settings,'frames':100,'stop':40}}).status_code,400)
                with patch.dict(c.CONFIG,{'max_sweep_seconds':-1}):
                    response=client.post('/api/communications/sweep',json=payload)
                self.assertEqual(response.status_code,200);self.assertFalse(response.json()['complete'])


if __name__=='__main__':
    log=ROOT/'logs/communications/advanced.log';log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    print(log.read_text(encoding='utf-8'));sys.exit(not result.wasSuccessful())
