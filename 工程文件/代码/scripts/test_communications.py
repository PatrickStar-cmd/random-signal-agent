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
from src import analog_modulation as a
from src import baseband as bb
from src import receiver_recovery as recovery


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


class AnalogCommunicationTests(unittest.TestCase):
    def ideal(self, scheme, changes=None):
        return c.preset(['sine', 'mod_' + scheme, 'ideal', 'demod_' + scheme, 'sink'], changes)

    def test_six_modulations_ideal_roundtrip_and_gain_phase_compensation(self):
        for scheme in a.SCHEMES:
            with self.subTest(scheme=scheme):
                p=c.preset(['sine','mod_'+scheme,'attenuation','phase_shift','demod_'+scheme,'sink'],{2:{'db':24},3:{'degrees':73}})
                result=execute(p)
                self.assertEqual(result['transport'],'analog')
                self.assertEqual(result['sink']['count'],256)
                self.assertLess(result['metrics']['rmse'],1e-12)
                self.assertNotIn('ber',result['metrics'])
                json.dumps(result,allow_nan=False)

    def test_ssb_phase_and_filter_methods_select_only_requested_sideband(self):
        n=256; t=np.arange(n)/256; message=np.cos(2*np.pi*8*t)
        for upper in (True,False):
            waves=[]
            for method in (0,1):
                wave,_=a.modulate(message,'ssb',{'amplitude':2,'upper':upper,'method':method},256)
                # A=2 and the course's 1/2 factor give one unit-amplitude exponential.
                np.testing.assert_allclose(wave,np.exp((1j if upper else -1j)*2*np.pi*8*t),atol=1e-13)
                spectrum=abs(np.fft.fft(wave))
                self.assertLess(spectrum[-8 if upper else 8],1e-11)
                self.assertAlmostEqual(spectrum[8 if upper else -8],n)
                waves.append(wave)
            np.testing.assert_allclose(waves[0],waves[1],atol=1e-13)

    def test_vsb_complementary_rolloff_residual_sideband_and_dc_nyquist(self):
        for n in (255,256):
            for upper in (True,False):
                response=a.sideband_response(n,256,upper,4)
                np.testing.assert_allclose(response+response[(-np.arange(n))%n],1)
                message=np.random.default_rng(42).normal(size=n)+.3
                wave,_=a.modulate(message,'vsb',{'amplitude':1,'upper':upper,'vestige_hz':4},256)
                np.testing.assert_allclose(2*wave.real,message,atol=1e-13)
        response=a.sideband_response(256,256,True,4)
        self.assertEqual(response[2],.75);self.assertEqual(response[-2],.25)
        self.assertEqual(response[8],1);self.assertEqual(response[-8],0)

    def test_am_envelope_overmodulation_distorts_but_coherent_recovers(self):
        p=self.ideal('am',{0:{'amplitude':2}})
        envelope=execute(p)
        self.assertGreater(envelope['metrics']['rmse'],.1)
        self.assertGreater(envelope['metrics']['overmodulated_samples'],0)
        self.assertTrue(envelope['analog']['warnings'])
        p['blocks'][3]['params']['method']=1
        self.assertLess(execute(p)['metrics']['rmse'],1e-13)
        p=c.preset(['sine','mod_am','phase_shift','demod_am','sink'],{2:{'degrees':91},3:{'compensate':False}})
        self.assertLess(execute(p)['metrics']['rmse'],1e-13)

    def test_fm_frequency_and_pm_phase_follow_message_with_nonzero_first_sample(self):
        message=np.array([.25,.5,-.25,-.5]*16)
        for scheme in ('fm','pm'):
            params={'amplitude':1.7,'sensitivity':3}
            sent,_=a.modulate(message,scheme,params,256)
            np.testing.assert_allclose(abs(sent),1.7,atol=1e-14)
            recovered=a.demodulate(sent*np.exp(.8j),scheme,params,{'cutoff_hz':0},256)
            np.testing.assert_allclose(recovered,message,atol=1e-13)
            self.assertEqual(len(sent),len(message)+1)
            if scheme=='fm':
                frequency=np.angle(sent[1:]*sent[:-1].conj())*256/(2*np.pi)
                np.testing.assert_allclose(frequency,3*message,atol=1e-13)

    def test_angle_modulation_spectral_lines_match_bessel_coefficients(self):
        from scipy.special import jv
        n=1024; fs=256; frequency=8; message=.7*np.cos(2*np.pi*frequency*np.arange(n)/fs)
        for scheme in ('fm','pm'):
            for sensitivity in ((1,16) if scheme=='fm' else (1,4)):
                params={'amplitude':1,'sensitivity':sensitivity}
                wave,_=a.modulate(message,scheme,params,fs)
                spectrum=abs(np.fft.fft(wave[1:]))/n
                beta=sensitivity*.7 if scheme=='pm' else np.pi*sensitivity*.7/(fs*np.sin(np.pi*frequency/fs))
                for order in range(4):
                    self.assertAlmostEqual(spectrum[order*32],abs(jv(order,beta)),places=10)

    def test_demodulation_lowpass_preserves_low_tone_and_rejects_high_tone(self):
        p=c.preset(['sine','sine','mod_dsb','ideal','demod_dsb','sink'],{1:{'frequency':40,'amplitude':.2},4:{'cutoff_hz':16}})
        result=execute(p)
        np.testing.assert_allclose(result['sink']['values'],.7*np.sin(2*np.pi*8*np.arange(256)/256),atol=1e-13)
        self.assertAlmostEqual(result['metrics']['rmse'],.2/math.sqrt(2))

    def test_invalid_analog_domains_pairs_noise_and_sampling_are_rejected(self):
        cases=[c.preset(['random_bits','mod_am','ideal','demod_am','sink']),
               c.preset(['sine','pcm_encode','mod_fm','ideal','demod_fm','pcm_decode','sink']),
               c.preset(['sine','mod_am','ideal','demod_dsb','sink']),
               c.preset(['sine','mod_fm','awgn','demod_fm','sink']),
               c.preset(['random_bits','mod_bpsk','analog_awgn','demod_bpsk','sink']),
               self.ideal('vsb',{1:{'vestige_hz':128}}),self.ideal('pm',{3:{'cutoff_hz':128}}),
               self.ideal('fm',{1:{'sensitivity':1000}}),self.ideal('pm',{0:{'amplitude':8,'phase':90},1:{'sensitivity':16}})]
        for p in cases:
            with self.subTest(program=p),self.assertRaises(ValueError):c.build(p)

    def test_analog_noise_is_seeded_and_referred_to_transmitter_power(self):
        errors=[]
        for seed in range(8):
            p=c.preset(['sine','mod_dsb','analog_awgn','demod_dsb','sink'],{2:{'snr_db':10}})
            p.update(seed=seed,sample_count=1024)
            result=execute(p)
            self.assertEqual(result,execute(p))
            errors.append(result['metrics']['channel_error_percent'])
        self.assertLess(abs(np.mean(np.square(errors))/10000-.1),.01)
        p=c.preset(['sine','mod_dsb','attenuation','analog_awgn','demod_dsb','sink'],{2:{'db':0}})
        clean=execute(p);p['blocks'][2]['params']['db']=20
        self.assertAlmostEqual(execute(p)['metrics']['rmse']/clean['metrics']['rmse'],10,places=10)

    def test_zero_source_and_complete_sample_loss_remain_finite(self):
        for scheme in a.SCHEMES:
            p=c.preset(['gaussian','mod_'+scheme,'dropout','demod_'+scheme,'sink'],{0:{'std':0},2:{'probability':1}})
            result=execute(p);json.dumps(result,allow_nan=False)
            if scheme in ('fm','pm'):self.assertTrue(result['analog']['warnings'])


class BasebandCommunicationTests(unittest.TestCase):
    def line_program(self, scheme, changes=None):
        return c.preset(['bit_pattern','line_'+scheme+'_encode','mod_baseband','ideal','demod_baseband','line_'+scheme+'_decode','sink'],changes)

    def test_basic_line_code_known_words_and_miller_course_example(self):
        bits=np.array([1,1,0,1,0,0,1,0],dtype=np.uint8)
        examples={'nrz_unipolar':bits,'nrz_polar':[1,1,-1,1,-1,-1,1,-1],
                  'manchester':[1,-1,1,-1,-1,1,1,-1,-1,1,-1,1,1,-1,-1,1],
                  'miller':[-1,1,1,-1,-1,-1,-1,1,1,1,-1,-1,-1,1,1,1],
                  'diff':[-1,1,1,-1,-1,-1,1,1], 'cmi':[1,1,-1,-1,-1,1,1,1,-1,1,-1,1,-1,-1,-1,1]}
        for scheme,expected in examples.items():
            params=self.line_program(scheme)['blocks'][1]['params']
            np.testing.assert_array_equal(bb.line_encode(bits,scheme,params),expected)
        rz=bb.line_encode(bits,'rz_polar',{})
        np.testing.assert_array_equal(rz[::2],2*bits.astype(int)-1);np.testing.assert_array_equal(rz[1::2],0)

    def test_hdb3_course_example_and_leading_zero_initial_state(self):
        bits=np.array(list(map(int,'100000110000100000000011')),dtype=np.uint8)
        params=self.line_program('hdb3')['blocks'][1]['params']
        expected=[1,0,0,0,1,0,-1,1,-1,0,0,-1,1,0,0,0,1,-1,0,0,-1,0,1,-1]
        np.testing.assert_array_equal(bb.line_encode(bits,'hdb3',params),expected)
        np.testing.assert_array_equal(bb.line_decode(expected,'hdb3',params)[0],bits)
        for parity in (0,1):
            params['initial_parity']=parity
            levels=bb.line_encode(np.zeros(12,dtype=np.uint8),'hdb3',params)
            np.testing.assert_array_equal(bb.line_decode(levels,'hdb3',params)[0],0)

    def test_all_line_codes_exhaustive_words_and_hdbn_variants(self):
        for scheme in bb.LINE_CODES:
            params=self.line_program(scheme)['blocks'][1]['params']
            for word in range(256):
                bits=((word>>np.arange(7,-1,-1))&1).astype(np.uint8)
                restored,_=bb.line_decode(bb.line_encode(bits,scheme,params),scheme,params)
                np.testing.assert_array_equal(restored,bits)
        bits=np.random.default_rng(14).integers(0,2,300,dtype=np.uint8);bits[30:80]=0
        for order in (1,2,3,8):
            for rz in (False,True):
                for positive in (False,True):
                    params={'order':order,'rz':rz,'initial_positive':positive,'initial_parity':0}
                    levels=bb.line_encode(bits,'hdb3',params)
                    np.testing.assert_array_equal(bb.line_decode(levels,'hdb3',params)[0],bits)
                    chips=levels[::2] if rz else levels
                    self.assertFalse(any(np.all(chips[i:i+order+1]==0) for i in range(len(chips)-order)))

    def test_line_and_pam_ideal_roundtrips_with_real_waveform_clocks(self):
        for scheme in bb.LINE_CODES:
            result=execute(self.line_program(scheme))
            self.assertEqual(result['metrics']['bit_errors'],0)
            self.assertEqual(result['baseband']['sample_rate'],8000)
            self.assertEqual(result['channel']['symbol_rate'],8000)
            self.assertIsNone(result['constellation']);json.dumps(result,allow_nan=False)
        for order in (2,4,8,16,256):
            for gray in (False,True):
                p=c.preset(['random_bits','mod_pam','ideal','demod_pam','sink'],{0:{'count':517},1:{'order':order,'gray':gray}})
                self.assertEqual(execute(p)['metrics']['ber'],0)

    def test_line_codes_can_wrap_existing_codecs_pcm_and_text(self):
        p=c.preset(['text','hamming_encode','interleave','line_manchester_encode','mod_baseband','ideal','demod_baseband','line_manchester_decode','deinterleave','hamming_decode','sink'],{0:{'text':'基带🐳'}})
        result=execute(p);self.assertEqual(result['text']['sent'],result['text']['received']);self.assertEqual(result['metrics']['ber'],0)
        p=c.preset(['sine','pcm_encode','conv_encode','line_hdb3_encode','mod_baseband','ideal','demod_baseband','line_hdb3_decode','conv_decode','pcm_decode','sink'])
        result=execute(p);self.assertEqual(result['metrics']['ber'],0);self.assertLessEqual(result['metrics']['rmse'],2/255)

    def test_pulse_singularities_nyquist_samples_and_rrc_cascade(self):
        tx=c.BLOCKS['mod_baseband']['params'];params={k:v['default'] for k,v in tx.items()}
        for kind in range(6):
            for alpha in (0,.25,.5,1):
                params.update(pulse=kind,rolloff=alpha);wave=bb.pulse(params)
                self.assertTrue(np.all(np.isfinite(wave)))
                if kind in (3,4):
                    samples=wave[::params['sps']].copy();samples[len(samples)//2]=0
                    self.assertLess(np.max(abs(samples)),1e-12)
        params.update(pulse=5,span=16,rolloff=.35)
        wave=bb.pulse(params);h=np.convolve(wave,wave[::-1])/np.dot(wave,wave)
        sampled=h[::params['sps']].copy();sampled[len(sampled)//2]=0
        self.assertLess(np.max(abs(sampled)),.003)
        for kind in range(6):
            p=self.line_program('nrz_polar',{2:{'pulse':kind},4:{'filter':1 if kind in (0,5) else 0}})
            self.assertEqual(execute(p)['metrics']['ber'],0)

    def test_frequency_selective_channel_responses_and_isi_origins(self):
        fs=8000;n=8000;t=np.arange(n)/fs;wave=np.cos(2*np.pi*100*t)+np.cos(2*np.pi*1000*t)
        low=bb.linear_channel(wave,'lowpass_channel',{'cutoff_hz':500},fs,8)
        np.testing.assert_allclose(low,np.cos(2*np.pi*100*t),atol=1e-11)
        band=bb.linear_channel(wave,'bandpass_channel',{'center_hz':1000,'bandwidth_hz':200},fs,8)
        np.testing.assert_allclose(band,np.cos(2*np.pi*1000*t),atol=1e-11)
        high=bb.linear_channel(np.ones(80),'ac_coupling',{'cutoff_hz':100},fs,8)
        np.testing.assert_allclose(high,0)
        impulse=np.zeros(80);impulse[32]=1
        response=bb.linear_channel(impulse,'isi_channel',{'taps':'-0.25,1,0.3333333333333333','origin':1,'spacing':8},fs,8)
        np.testing.assert_allclose(response[[24,32,40]],[-.25,1,1/3])

    def test_zf_matches_three_tap_course_example_and_reduces_isi(self):
        coefficients=bb.zf_coefficients({-1:-1/4,0:1,1:1/3},1)
        np.testing.assert_allclose(coefficients,[3/14,6/7,-2/7],atol=1e-14)
        response=np.convolve([-.25,1,1/3],coefficients)
        np.testing.assert_allclose(response,[-3/56,0,1,0,-2/21],atol=1e-14)
        result=execute(c.PRESETS['baseband_isi']['program'])
        np.testing.assert_allclose(result['baseband']['equalizer_coefficients'],coefficients,atol=1e-14)
        self.assertLess(result['metrics']['level_rmse'],result['metrics']['before_equalizer_rmse']/2)

    def test_timing_shift_lowpass_receiver_and_concatenated_sources(self):
        impulse=np.zeros(80);impulse[32]=1
        shifted=bb.linear_channel(impulse,'timing_offset',{'offset':.125},8000,8)
        self.assertEqual(shifted[33],1);self.assertEqual(shifted[32],0)
        p=self.line_program('nrz_polar',{4:{'filter':2,'cutoff_hz':1000}})
        self.assertEqual(execute(p)['metrics']['ber'],0)
        p=c.preset(['bit_pattern','text','line_manchester_encode','mod_baseband','timing_offset','demod_baseband','line_manchester_decode','sink'],{0:{'pattern':'101'},1:{'text':'A'},4:{'offset':.25},5:{'sample_offset':.25}})
        compiled=c.build(p);self.assertEqual([row['count'] for row in compiled['plan'][:2]],[3,8])
        result=execute(p);self.assertEqual(result['sink']['count'],11);self.assertEqual(result['metrics']['ber'],0)

    def test_equalization_uses_channel_response_not_clean_data(self):
        p=copy.deepcopy(c.PRESETS['baseband_isi']['program']);first=execute(p);p['seed']=7;second=execute(p)
        np.testing.assert_allclose(first['baseband']['equalizer_coefficients'],second['baseband']['equalizer_coefficients'])
        p['blocks'][4]['params']['equalizer']=2;mmse=execute(p)
        self.assertTrue(np.all(np.isfinite(mmse['baseband']['equalizer_coefficients'])))
        with self.assertRaises(ValueError):bb.zf_coefficients({0:0},1)

    def test_sample_noise_snr_seeding_attenuation_and_bandlimiting(self):
        p=c.preset(['random_bits','line_nrz_polar_encode','mod_baseband','sample_awgn','demod_baseband','line_nrz_polar_decode','sink'])
        first=execute(p);self.assertEqual(first,execute(p))
        sent=np.array(first['baseband']['transmitter']['i']);received=np.array(first['channel']['i'])
        self.assertLess(abs(np.mean((received-sent)**2)-.01),.003)
        p=c.preset(['random_bits','line_nrz_polar_encode','mod_baseband','attenuation','sample_awgn','demod_baseband','line_nrz_polar_decode','sink'],{3:{'db':0}})
        normal=execute(p);p['blocks'][3]['params']['db']=20
        self.assertAlmostEqual(execute(p)['metrics']['level_rmse']/normal['metrics']['level_rmse'],10,places=10)
        p=c.PRESETS['pam4']['program'];self.assertLess(execute(p)['metrics']['ber'],.05)

    def test_spectrum_power_eye_and_zero_message_are_finite(self):
        result=execute(self.line_program('nrz_polar'));b=result['baseband'];s=b['spectrum'];df=b['sample_rate']/len(s['frequency_hz'])
        self.assertAlmostEqual(np.sum(10**(np.array(s['density_db'])/10))*df,b['transmit_power'],places=12)
        self.assertTrue(b['eye']['traces']);self.assertEqual(len(b['eye']['traces'][0]),17)
        p=self.line_program('nrz_unipolar',{0:{'pattern':'0'*40}})
        result=execute(p);self.assertEqual(result['metrics']['ber'],0);json.dumps(result,allow_nan=False)

    def test_build_rejects_mixed_domains_pair_states_bad_taps_and_limits(self):
        cases=[c.preset(['random_bits','line_ami_encode','mod_bpsk','ideal','demod_bpsk','line_ami_decode','sink']),
               c.preset(['sine','line_ami_encode','mod_baseband','ideal','demod_baseband','line_ami_decode','sink']),
               c.preset(['random_bits','mod_bpsk','lowpass_channel','demod_bpsk','sink']),
               self.line_program('ami',{5:{'rz':False}}),self.line_program('nrz_polar',{0:{'pattern':'1'*8192},2:{'sps':32}}),
               c.preset(['random_bits','mod_pam','isi_channel','demod_pam','sink'],{2:{'taps':'nan'}}),
               c.preset(['random_bits','mod_pam','isi_channel','demod_pam','sink'],{2:{'taps':'1,2','origin':2}}),
               c.preset(['random_bits','mod_pam','lowpass_channel','demod_pam','sink'],{2:{'cutoff_hz':4000}}),
               c.preset(['random_bits','mod_pam','bandpass_channel','demod_pam','sink'],{2:{'center_hz':100,'bandwidth_hz':300}})]
        for p in cases:
            with self.subTest(p=p),self.assertRaises(ValueError):c.build(p)


class ReceiverRecoveryTests(unittest.TestCase):
    def test_nonlinear_clock_extracts_both_offset_signs_and_rectified_edges(self):
        for offset in (-.35,.35):
            p=copy.deepcopy(c.PRESETS['recovery_timing_1']['program']);p['blocks'][3]['params']['offset']=offset
            result=execute(p);timing=result['baseband']['recovery']['timing']
            self.assertLess(abs(timing['initial_phase']-offset),.025)
            self.assertEqual(result['metrics']['ber'],0)
            self.assertLess(result['metrics']['level_rmse'],result['baseband']['recovery']['before_sync_rmse']/5)
        p=c.preset(['random_bits','line_nrz_polar_encode','mod_baseband','timing_offset','demod_baseband','line_nrz_polar_decode','sink'],{3:{'offset':.375},4:{'filter':0,'timing_mode':1}})
        result=execute(p);self.assertAlmostEqual(result['baseband']['recovery']['timing']['initial_phase'],.375,places=10)
        self.assertEqual(result['metrics']['ber'],0)

    def test_early_late_and_gardner_follow_clock_drift_and_improve_ber(self):
        for mode in (2,3):
            for ppm in (-300,300):
                p=copy.deepcopy(c.PRESETS['recovery_timing_'+str(mode)]['program']);p['blocks'][4]['params']['ppm']=ppm
                result=execute(p);info=result['baseband']['recovery'];timing=info['timing']
                self.assertEqual(result['metrics']['ber'],0)
                self.assertLess(abs(timing['frequency_ppm']-ppm),100)
                self.assertLess(abs(timing['final_phase']-(.35+ppm*1e-6*(info['frame_symbols']-1))),.08)
                positions=np.array(timing['sample_positions']);self.assertTrue(np.all(np.diff(positions)>0))
                p['blocks'][6]['params']['timing_mode']=0
                manual=execute(p)
                self.assertGreater(manual['metrics']['level_rmse'],result['metrics']['level_rmse']*5)
                if ppm>0:self.assertGreater(manual['metrics']['ber'],.05)

    def test_clock_without_timing_information_is_finite_and_not_claimed_informative(self):
        for mode in (1,2,3):
            for value in (0.,1.):
                wave=np.full(4096,value)
                positions,info=recovery.synchronize(wave,100,8,300,{'sample_offset':.2,'timing_mode':mode})
                self.assertFalse(info['clock_informative']);self.assertAlmostEqual(info['final_phase'],.2)
                self.assertEqual(info['frequency_ppm'],0);self.assertTrue(np.all(np.isfinite(positions)))
        p=c.preset(['bit_pattern','line_nrz_unipolar_encode','mod_baseband','ideal','demod_baseband','line_nrz_unipolar_decode','sink'],{0:{'pattern':'0'*300},4:{'timing_mode':2}})
        result=execute(p);self.assertEqual(result['metrics']['ber'],0);self.assertTrue(result['baseband']['warnings']);json.dumps(result,allow_nan=False)

    def test_fixed_dfe_cancels_known_postcursor_and_propagates_bad_decisions(self):
        levels=np.array([-1.,1.]);original=np.array([-1.,1.,-1.,1.,-1.,1.])
        channel=np.convolve(original,[1,.9])[:len(original)]
        params={'equalizer':3,'half_taps':1,'feedback_taps':4,'regularization':1e-6}
        good,info=recovery.equalize(np.pad(channel,(1,1)),len(original),levels,np.array([]),params,{0:1,1:.9})
        np.testing.assert_allclose(good,original,atol=1e-5)
        corrupted=channel.copy();corrupted[0]=1
        bad,_=recovery.equalize(np.pad(corrupted,(1,1)),len(original),levels,np.array([]),params,{0:1,1:.9})
        self.assertGreater(np.count_nonzero(np.sign(bad)!=original),3)
        self.assertEqual(info['updates'],0)
        result=execute(c.PRESETS['recovery_fixed_dfe']['program'])
        self.assertLess(result['metrics']['level_rmse'],result['metrics']['before_equalizer_rmse']/10)

    def test_lms_nlms_rls_updates_match_independent_single_step_equations(self):
        for algorithm in (0,1,2):
            params={'equalizer':4,'half_taps':1,'regularization':.01,'adaptive_algorithm':algorithm,'step_size':.1 if algorithm==0 else .4,'forgetting_factor':.995}
            output,info=recovery.equalize(np.array([0.,2.,0.]),1,np.array([-1.,1.]),np.array([1.]),params)
            self.assertEqual(output[0],2.)
            expected=.8 if algorithm==0 else 1-.4*2/(4+1e-8) if algorithm==1 else 1-200/(.995+400)
            self.assertAlmostEqual(info['forward_coefficients'][1],expected,places=12)

    def test_all_adaptive_algorithms_converge_in_linear_and_dfe_structures(self):
        for structure in (4,5):
            for algorithm in (0,1,2):
                p=copy.deepcopy(c.PRESETS['recovery_dfe_nlms']['program'])
                p['blocks'][0]['params']['count']=512;p['blocks'][2]['params']['training_symbols']=512
                p['blocks'][3]['params']['taps']='1,0.5';p['blocks'][4]['params']['snr_db']=60
                p['blocks'][5]['params'].update(equalizer=structure,adaptive_algorithm=algorithm,half_taps=4 if structure==4 else 1,step_size=.01 if algorithm==0 else .2,adapt_after_training=False)
                result=execute(p);info=result['baseband']['recovery']['equalizer']
                self.assertEqual(result['metrics']['ber'],0);self.assertLess(result['metrics']['level_rmse'],.07)
                self.assertLess(info['training_final_mse'],info['training_initial_mse']/5)
                self.assertEqual(info['updates'],512);self.assertFalse(info['decision_directed'])

    def test_adaptive_filters_ignore_configured_csi_and_stop_updating_when_frozen(self):
        levels=np.array([-1.,1.]);training=recovery.preamble(256,levels);payload=recovery.preamble(256,levels)[::-1]
        frame=np.r_[training,payload];samples=np.pad(np.convolve(frame,[1,.5])[:len(frame)],(1,1))
        for algorithm in (0,1,2):
            params={'equalizer':5,'half_taps':1,'regularization':.01,'adaptive_algorithm':algorithm,'step_size':.01 if algorithm==0 else .2,'adapt_after_training':False}
            first,info=recovery.equalize(samples,len(frame),levels,training,params,{0:1})
            second,other=recovery.equalize(samples,len(frame),levels,training,params,{0:float('nan'),1:1000})
            np.testing.assert_array_equal(first,second);self.assertEqual(info,other)
            changed=samples.copy();changed[300:]*=-1
            _,modified=recovery.equalize(changed,len(frame),levels,training,params)
            self.assertEqual(info['forward_coefficients'],modified['forward_coefficients'])
            self.assertEqual(info['feedback_coefficients'],modified['feedback_coefficients'])
            params['adapt_after_training']=True
            _,tracking=recovery.equalize(samples,len(frame),levels,training,params)
            self.assertEqual(tracking['updates'],len(frame))

    def test_decision_directed_adaptation_tracks_a_changed_postcursor(self):
        levels=np.array([-1.,1.]);frame=recovery.preamble(2304,levels);training=frame[:256]
        channel=frame.copy();channel[1:]+=np.where(np.arange(1,len(frame))<900,.2,.8)*frame[:-1]
        params={'equalizer':5,'half_taps':1,'regularization':.01,'step_size':.2,'adapt_after_training':True}
        tracked,_=recovery.equalize(np.pad(channel,(1,1)),len(frame),levels,training,params)
        params['adapt_after_training']=False
        frozen,_=recovery.equalize(np.pad(channel,(1,1)),len(frame),levels,training,params)
        self.assertLess(np.mean((tracked[-500:]-frame[-500:])**2),np.mean((frozen[-500:]-frame[-500:])**2)/10)

    def test_public_preamble_is_transmitted_removed_and_seed_independent(self):
        p=copy.deepcopy(c.PRESETS['recovery_dfe_nlms']['program']);first=execute(p);p['seed']=7;second=execute(p)
        a=first['baseband']['recovery'];b=second['baseband']['recovery']
        self.assertEqual(a['public_preamble'],b['public_preamble'])
        self.assertEqual(a['training_symbols'],1024);self.assertEqual(a['frame_symbols'],3072)
        self.assertEqual(first['sink']['count'],2048)
        self.assertEqual(first['metrics']['bit_count'],2048)
        self.assertEqual(first['baseband']['transmitter']['i'],second['baseband']['transmitter']['i'])
        self.assertAlmostEqual(a['payload_efficiency'],2/3)

    def test_pam_pcm_and_line_code_frames_roundtrip_with_training(self):
        p=c.preset(['random_bits','mod_pam','isi_channel','sample_awgn','demod_pam','sink'],{1:{'training_symbols':512},2:{'taps':'1,0.6'},3:{'snr_db':30},4:{'equalizer':5,'adaptive_algorithm':2}})
        self.assertEqual(execute(p)['metrics']['ber'],0)
        p=c.preset(['sine','pcm_encode','line_hdb3_encode','mod_baseband','ideal','demod_baseband','line_hdb3_decode','pcm_decode','sink'],{3:{'training_symbols':128},5:{'equalizer':5}})
        result=execute(p);self.assertEqual(result['metrics']['ber'],0);self.assertLessEqual(result['metrics']['rmse'],2/255)

    def test_joint_sync_adaptive_dfe_with_noise_isi_and_clock_skew(self):
        p=c.preset(['random_bits','line_nrz_polar_encode','mod_baseband','timing_offset','clock_drift','isi_channel','sample_awgn','demod_baseband','line_nrz_polar_decode','sink'],{0:{'count':2048},2:{'pulse':5,'rolloff':.6,'training_symbols':1024},3:{'offset':.2},4:{'ppm':300},5:{'taps':'1,0.6'},6:{'snr_db':30},7:{'timing_mode':3,'loop_bandwidth':.005,'equalizer':5}})
        result=execute(p);self.assertEqual(result,execute(p));self.assertEqual(result['metrics']['ber'],0)
        self.assertLess(result['metrics']['level_rmse'],.05);json.dumps(result,allow_nan=False)

    def test_recovery_validation_budget_canonical_defaults_and_divergence(self):
        p=c.preset(['random_bits','line_nrz_polar_encode','mod_baseband','ideal','demod_baseband','line_nrz_polar_decode','sink'])
        legacy=copy.deepcopy(p)
        for block in legacy['blocks']:
            for key in recovery.TX_DEFAULT_FIELDS|recovery.RX_DEFAULT_FIELDS:block['params'].pop(key,None)
        self.assertEqual(c.build(p),c.build(legacy))
        cases=[c.preset(['random_bits','mod_pam','ideal','demod_pam','sink'],{3:{'equalizer':5}}),
               c.preset(['random_bits','mod_pam','ideal','demod_pam','sink'],{1:{'training_symbols':32},3:{'equalizer':5,'half_taps':8}}),
               c.preset(['random_bits','mod_pam','ideal','demod_pam','sink'],{1:{'training_symbols':2048,'sps':32}}),
               c.preset(['random_bits','mod_pam','clock_drift','clock_drift','clock_drift','demod_pam','sink'],{2:{'ppm':500},3:{'ppm':500},4:{'ppm':500}})]
        for case in cases:
            with self.assertRaises(ValueError):c.build(case)
        with self.assertRaisesRegex(ValueError,'发散'):
            recovery.equalize(np.full(35,1e6),32,np.array([-1.,1.]),np.ones(32),{'equalizer':4,'half_taps':1,'regularization':.01,'adaptive_algorithm':0,'step_size':1.5})


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
