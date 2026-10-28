import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import copy
import unittest
import numpy as np
from src import communications as c, communication_flow_v0410 as flow
from src import communication_isac_v0410 as isac


class FlowTests(unittest.TestCase):
    def programs(self):
        p=c.PRESETS['complex_receiver']['program']
        return [copy.deepcopy(p),copy.deepcopy(p)]

    def test_shared_samples_weighted_merge_and_selection(self):
        programs=self.programs();contexts=[]
        value=flow.merge_branches(programs,{'weights':[.25,.75]},contexts=contexts)
        a,b=[ctx.merge_input for ctx in contexts[:2]]
        np.testing.assert_allclose(contexts[-1].values['merge-output'],.25*a+.75*b)
        self.assertEqual(value['merged_result']['sink'],value['branches'][0]['result']['sink'])
        selected=flow.merge_branches(programs,{'mode':'select','select':1})
        self.assertEqual(selected['merged_result']['sink'],selected['branches'][1]['result']['sink'])
        self.assertTrue(value['shared_hashes'])

    def test_soft_information_merge(self):
        p=c.PRESETS['soft_viterbi']['program'];v=flow.merge_branches([p,copy.deepcopy(p)],{'domain':'llr','weights':[.5,.5]})
        self.assertEqual(v['merged_result']['sink'],v['branches'][0]['result']['sink'])
        self.assertEqual(v['merge']['domain'],'llr')

    def test_reject_mismatched_prefix_and_tail(self):
        programs=self.programs();programs[1]['seed']+=1
        with self.assertRaises(ValueError):flow.merge_branches(programs)
        programs=self.programs();programs[1]['blocks'][-2]['params']['compensate']=not programs[1]['blocks'][-2]['params']['compensate']
        with self.assertRaises(ValueError):flow.merge_branches(programs)


class IsacTests(unittest.TestCase):
    def test_measured_range_speed_and_bits(self):
        p=copy.deepcopy(c.PRESETS['ofdm_isac']['program']);b=c.build(p);r=c.run(b['program'],b['token'])
        self.assertEqual(r['metrics']['bit_errors'],0)
        sense=r['advanced']['wireless']['rx_isac_ofdm']['sensing']
        self.assertTrue(sense['detected'])
        self.assertLess(abs(sense['range_m']-625),sense['range_resolution_m'])
        self.assertLess(abs(sense['velocity_mps']-37.5),sense['velocity_resolution_mps'])
        self.assertEqual(sense['reference'],'local_transmit_grid')

    def test_stationary_target_and_absent_echo(self):
        rng=np.random.default_rng(4);symbols=np.exp(1j*(np.pi/4+np.pi/2*rng.integers(0,4,2048)))
        wave,ref=isac.transmit(symbols,{'nfft':64,'cp':16});fs=960000
        q={'range_m':4*isac.C/(2*fs),'velocity_mps':0,'carrier_ghz':3,'amplitude':.25,'direct':1}
        received,_=isac.echo(wave,q,fs);out,d=isac.receive(received,ref,{'carrier_ghz':3,'threshold_db':10},fs)
        self.assertTrue(d['sensing']['detected']);self.assertEqual(d['sensing']['velocity_mps'],0)
        np.testing.assert_allclose(out,symbols,atol=1e-7)
        _,d=isac.receive(wave,ref,{'carrier_ghz':3,'threshold_db':10},fs)
        self.assertFalse(d['sensing']['detected'])


if __name__=='__main__':unittest.main()
