"""Integration review: typed merge, downstream state and local ISAC reference."""
from pathlib import Path
import copy
import json
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src import communications as c, communication_flow_v0410 as flow
from src import communication_isac_v0410 as isac, communication_dsp as dsp


class IntegrationReviewTests(unittest.TestCase):
    def test_llr_merge_coded_error_metrics_match_actual_merged_bits(self):
        p=copy.deepcopy(c.PRESETS['soft_viterbi']['program']);contexts=[]
        value=flow.merge_branches([p,copy.deepcopy(p)],{'domain':'llr','weights':[-1,0]},contexts=contexts)
        ctx=contexts[-1];encoded=ctx.values[next(b['id'] for b in p['blocks'] if b['kind']=='conv_encode')]
        combined=ctx.values['merge-output']
        actual=int(np.count_nonzero(encoded!=(combined<0)))
        self.assertEqual(value['merged_result']['metrics']['coded_bit_errors'],actual)

    def test_merge_snapshot_displays_recorded_signal(self):
        p=copy.deepcopy(c.PRESETS['complex_receiver']['program']);contexts=[]
        value=flow.merge_branches([p,copy.deepcopy(p)],{'weights':[-1,0]},contexts=contexts)
        observation=next(s for s in value['merged_result']['experience']['observations'] if s['id']=='merge-output')
        np.testing.assert_allclose(np.array(observation['i'])+1j*np.array(observation['q']),contexts[-1].values['merge-output'][:len(observation['i'])])
        for stage in value['merged_result']['advanced']['stages']:
            np.testing.assert_allclose(np.array(stage['i'])+1j*np.array(stage['q']),contexts[-1].values[stage['id']][:len(stage['i'])])

    def test_different_receiver_gain_contexts_preserve_selected_path(self):
        p=c.preset(['random_bits','mod_qam16','attenuation','ideal','rx_agc','demod_qam16','sink'],
                   {0:{'count':512},2:{'db':12}})
        other=copy.deepcopy(p);other['blocks'][4].update(kind='rx_noise_estimate',params={'method':1})
        for settings in ({'mode':'select','select':1},{'mode':'weighted','weights':[0,1]}):
            with self.subTest(settings=settings):
                value=flow.merge_branches([p,other],settings)
                self.assertEqual(value['branches'][1]['result']['metrics']['ber'],0)
                self.assertEqual(value['merged_result']['sink']['values'],value['branches'][1]['result']['sink']['values'])
        contexts=[];value=flow.merge_branches([p,other],{'weights':[.2,.8]},contexts=contexts)
        canonical=.2*contexts[0].merge_input+.8*contexts[1].merge_input
        np.testing.assert_allclose(contexts[-1].values['merge-output'],canonical)
        expected=dsp.decisions(canonical,'qam16')[0]
        np.testing.assert_array_equal(value['merged_result']['sink']['values'],expected)

    def test_legacy_complex_symbol_port_merges(self):
        p=c.preset(['random_bits','mod_qpsk','awgn','demod_qpsk','sink'])
        value=flow.merge_branches([p,copy.deepcopy(p)],{'mode':'select','select':1})
        self.assertEqual(value['merged_result']['sink'],value['branches'][1]['result']['sink'])

    def test_selected_soft_path_preserves_effective_noise_variance(self):
        p=c.preset(['random_bits','conv_encode','mod_qpsk','tx_frame','awgn','rx_frame',
                    'rx_noise_estimate','soft_qpsk','conv_soft_decode','sink'],
                   {0:{'count':512},4:{'esn0_db':3},6:{'method':0},7:{'automatic_variance':True}})
        other=copy.deepcopy(p);other['blocks'][6]['params']['method']=1
        contexts=[];flow.merge_branches([p,other],{'mode':'select','select':1},contexts=contexts)
        point=p['blocks'][7]['id']
        np.testing.assert_allclose(contexts[-1].values[point],contexts[1].values[point])

    def test_llr_inputs_allow_independent_premerge_variance(self):
        p=copy.deepcopy(c.PRESETS['soft_viterbi']['program']);other=copy.deepcopy(p)
        next(b for b in other['blocks'] if b['kind']=='soft_qpsk')['params']['noise_variance']=.2
        contexts=[];value=flow.merge_branches([p,other],{'domain':'llr','weights':[.3,.7]},contexts=contexts)
        np.testing.assert_allclose(contexts[-1].values['merge-output'],.3*contexts[0].merge_input+.7*contexts[1].merge_input)
        self.assertEqual(value['merge']['input_reference'],'log_P0_over_P1')

    def test_mimo_selected_path_preserves_per_symbol_variance(self):
        for automatic in (False,True):
            p=copy.deepcopy(c.PRESETS['receiver_soft_ldpc']['program'])
            p['blocks'][6]['params']['automatic_variance']=automatic
            other=copy.deepcopy(p);other['blocks'][5]['params']['correlation']=.9
            for settings in ({'mode':'select','select':1},{'mode':'weighted','weights':[0,1]}):
                with self.subTest(automatic=automatic,settings=settings):
                    contexts=[];value=flow.merge_branches([p,other],settings,contexts=contexts)
                    np.testing.assert_allclose(contexts[-1].values['block-6'],contexts[1].values['block-6'])
                    np.testing.assert_allclose(value['merge']['noise']['variance'],contexts[1].merge_variance)
                    self.assertEqual(value['merge']['noise']['method'],'selected_receiver_variance')
                    json.dumps(value,allow_nan=False)

    def test_isac_negative_velocity_and_communication_public_reference(self):
        rng=np.random.default_rng(41016);bits=rng.integers(0,2,8192,dtype=np.uint8)
        symbols=dsp.map_bits(bits,'qpsk')[0];wave,reference=isac.transmit(symbols,{'nfft':64,'cp':16});fs=960000
        q={'range_m':4*isac.C/(2*fs),'velocity_mps':-37.5,'carrier_ghz':3,'amplitude':.25,'direct':1}
        measured,_=isac.echo(wave,q,fs)
        received,details=isac.receive(measured,reference,{'carrier_ghz':3,'threshold_db':10},fs)
        np.testing.assert_array_equal(dsp.decisions(received,'qpsk')[0],bits)
        sensing=details['sensing'];self.assertTrue(sensing['detected'])
        self.assertLess(abs(sensing['range_m']-q['range_m']),sensing['range_resolution_m'])
        self.assertLess(abs(sensing['velocity_mps']-q['velocity_mps']),sensing['velocity_resolution_mps'])
        altered=copy.deepcopy(reference);altered['grid'][2:]*=1j
        altered.update(true_range=9999,true_velocity=999)
        public_only,other=isac.receive(measured,altered,{'carrier_ghz':3,'threshold_db':10},fs)
        np.testing.assert_array_equal(public_only,received)
        self.assertEqual(other['sensing']['reference'],'local_transmit_grid')


if __name__=='__main__':unittest.main()
