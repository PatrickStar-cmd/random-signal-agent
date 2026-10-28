"""True RV selection, mother LLR buffering and paired actual-PHY budgets."""
from pathlib import Path
import json
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src import communications as c, communication_protocols as protocol


def program(snr=1):
    return c.preset(['random_bits','conv_encode','puncture','mod_qpsk','awgn','soft_qpsk','depuncture','conv_soft_decode','sink'],
                    {0:{'count':512},4:{'esn0_db':snr}})


class HarqTests(unittest.TestCase):
    def test_rv_budget_and_union_cover_mother(self):
        for length in (100,102,358):
            for rate in (2,3):
                indices=[protocol.redundancy_indices(length,rv,rate) for rv in range(4)]
                self.assertEqual(len({len(v) for v in indices}),1)
                self.assertEqual(len(set(np.concatenate(indices))),length)
                self.assertFalse(np.array_equal(indices[0],indices[1]))

    def test_reference_equal_resource_and_actual_buffer_accumulation(self):
        result=protocol.compare_ir_chase(program(),{'phy':'reference','snr_db':-1,'packets':3,'max_retries':3,
            'feedback_loss':1,'packet_bytes':16,'scheme':'qpsk','budget_rate':2})
        chase,ir=result['chase'],result['ir_harq']; self.assertTrue(ir['metrics']['complete_payload'])
        self.assertEqual(ir['metrics']['total_symbols'],chase['metrics']['total_symbols'])
        self.assertEqual(ir['metrics']['total_tx_energy'],chase['metrics']['total_tx_energy'])
        self.assertEqual([v['rv'] for v in ir['events'][:4]],[0,1,2,3])
        self.assertEqual(ir['events'][1]['mother_coverage'],1.)
        self.assertLess(chase['events'][1]['mother_coverage'],1.)
        # Previously unseen mother indices become nonzero only on the next RV.
        a,b=ir['events'][:2]; new=sorted(set(b['mother_indices'])-set(a['mother_indices']))
        self.assertTrue(new); self.assertTrue(all(a['llr_buffer'][i]==0 for i in new))
        self.assertTrue(any(b['llr_buffer'][i]!=0 for i in new)); json.dumps(result,allow_nan=False)

    def test_program_phy_preserves_blocks_and_combines_real_llr(self):
        settings={'phy':'program','packets':2,'max_retries':2,'feedback_loss':1,'packet_bytes':16,'budget_rate':2}
        compared=protocol.compare_ir_chase(program(9),settings); chase,ir=compared['chase'],compared['ir_harq']
        self.assertTrue(ir['metrics']['complete_payload']); self.assertEqual(ir['source_base64'],ir['received_base64'])
        self.assertEqual(ir['metrics']['total_symbols'],chase['metrics']['total_symbols'])
        self.assertAlmostEqual(ir['metrics']['total_tx_energy'],chase['metrics']['total_tx_energy'])
        self.assertTrue({'conv_encode','puncture','mod_qpsk','awgn','soft_qpsk','depuncture','conv_soft_decode'}<=set(ir['events'][0]['executed_kinds']))
        self.assertEqual(ir['events'][1]['mother_coverage'],1.); self.assertEqual(ir['events'][1]['rv'],1)
        json.dumps(compared,allow_nan=False)

    def test_program_inserts_rate_match_and_rejects_other_mother_codes(self):
        p=c.preset(['random_bits','conv_encode','mod_bpsk','awgn','soft_bpsk','conv_soft_decode','sink'],{3:{'esn0_db':15}})
        result=protocol.protocol(p,{'phy':'program','mode':'ir_harq','packets':1,'feedback_loss':0})
        self.assertTrue(result['metrics']['complete_payload']); self.assertIn('puncture',result['events'][0]['executed_kinds'])
        p=c.preset(['random_bits','polar_encode','mod_bpsk','awgn','soft_bpsk','polar_decode','sink'])
        with self.assertRaisesRegex(ValueError,'卷积母码'): protocol.protocol(p,{'phy':'program','mode':'ir_harq'})

    def test_actual_qam_ofdm_waveform_and_partial_constellation_word(self):
        p=c.preset(['random_bits','conv_encode','mod_qam16','tx_ofdm','complex_awgn','rx_ofdm',
                    'soft_qam16','conv_soft_decode','sink'],{4:{'snr_db':40}})
        result=protocol.protocol(p,{'phy':'program','mode':'ir_harq','packets':2,'packet_bytes':13,
                                    'budget_rate':2,'feedback_loss':1,'max_retries':2})
        self.assertTrue(result['metrics']['complete_payload'])
        self.assertEqual(result['source_base64'],result['received_base64'])
        self.assertIn('tx_ofdm',result['events'][0]['executed_kinds'])
        self.assertIn('rx_ofdm',result['events'][1]['executed_kinds'])
        self.assertEqual(result['events'][1]['mother_coverage'],1.)
        self.assertGreater(result['events'][0]['symbols'],result['events'][0]['coded_bits']/4)


if __name__=='__main__': unittest.main(verbosity=2)
