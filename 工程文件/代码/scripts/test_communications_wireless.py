"""v0.4.7 wireless numerical, typed-chain and retained-array acceptance."""
from pathlib import Path
import copy
import json
import sys
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src import communications as c, communication_wireless as w
from src import communication_studio as studio


def execute(program):
    built=c.build(program)
    return c.run(built['program'],built['token'])


def parameters(kind, **values):
    return {**{k:v['default'] for k,v in c.BLOCKS[kind]['params'].items()},**values}


class WirelessTests(unittest.TestCase):
    def test_pn_period_energy_and_unknown_code_phase(self):
        rng=np.random.default_rng(17)
        symbols=(2*rng.integers(0,2,128)-1+1j*(2*rng.integers(0,2,128)-1))/np.sqrt(2)
        for degree in (5,6,7):
            code=w.pn_code(degree,1); length=len(code)
            autocorr=np.fft.ifft(abs(np.fft.fft(code))**2).real
            np.testing.assert_allclose(autocorr[1:],-1,atol=1e-12)
            tx,state=w.spread(symbols,parameters('tx_dsss',degree=degree,phase=19))
            self.assertAlmostEqual(float(np.sum(abs(tx)**2)),len(symbols)+16)
            received=np.pad(tx,(13,0))*np.exp(.7j)
            details=w.acquire(received,state,parameters('rx_code_acquire',search=48))
            self.assertEqual((details['code_phase'],details['delay_chips']),(19,13))
            recovered,_,_=w.run_stage('rx_despread',received,{}, {'dsss':state},rng,1000*length)
            np.testing.assert_allclose(recovered,symbols,atol=1e-12)

    def test_dsss_suppresses_narrowband_interference(self):
        rng=np.random.default_rng(24); symbols=(2*rng.integers(0,2,4096)-1).astype(complex)
        tx,state=w.spread(symbols,parameters('tx_dsss',phase=11,training=32))
        interfered=tx+1.5*np.exp(2j*np.pi*.001*np.arange(len(tx)))
        w.acquire(interfered,state,parameters('rx_code_acquire',threshold=.05))
        recovered,_,_=w.run_stage('rx_despread',interfered,{}, {'dsss':state},rng,31000)
        # Same jammer amplitude and observation duration per unspread symbol.
        plain=symbols+1.5*np.exp(2j*np.pi*.031*np.arange(len(symbols)))
        self.assertLess(float(np.mean(abs(recovered-symbols)**2)),float(np.mean(abs(plain-symbols)**2))/10)
        self.assertEqual(np.count_nonzero((recovered.real>0)!=(symbols.real>0)),0)
        self.assertGreater(np.mean((plain.real>0)!=(symbols.real>0)),.1)

    def test_rake_estimates_delays_and_combines_noisy_paths(self):
        rng=np.random.default_rng(43); symbols=(2*rng.integers(0,2,4096)-1).astype(complex)
        tx,state=w.spread(symbols,parameters('tx_dsss',phase=9,training=64))
        q=parameters('dsss_multipath'); delays,gains=w.paths(q)
        taps=np.zeros(delays.max()+1,complex); taps[delays]=gains
        received=np.convolve(tx,taps)
        w.acquire(received,state,parameters('rx_code_acquire'))
        recovered,details=w.rake(received,state,parameters('rx_rake'))
        self.assertEqual(details['finger_delays'],delays.tolist())
        np.testing.assert_allclose(np.array(details['finger_gains']['i'])+1j*np.array(details['finger_gains']['q']),gains,atol=1e-12)
        self.assertEqual(np.count_nonzero((recovered.real>0)!=(symbols.real>0)),0)
        received+=np.sqrt(.3/2)*(rng.normal(size=len(received))+1j*rng.normal(size=len(received)))
        w.acquire(received,state,parameters('rx_code_acquire',threshold=.05))
        combined,_=w.rake(received,state,parameters('rx_rake'))
        selected,_,_=w.run_stage('rx_despread',received,{}, {'dsss':state},rng,31000)
        self.assertLess(np.mean(abs(combined-symbols)**2),np.mean(abs(selected-symbols)**2)*.9)

    def test_all_spatial_receivers_use_pilots_and_recover_noiseless(self):
        rng=np.random.default_rng(26); symbols=rng.normal(size=513)+1j*rng.normal(size=513)
        for tx_kind,receivers in [('tx_simo',('rx_selection','rx_mrc')),('tx_alamouti',('rx_alamouti',)),('tx_mimo',('rx_mimo_zf','rx_mimo_mmse'))]:
            tx,state=w.spatial_encode(symbols,tx_kind,parameters(tx_kind))
            received,channel=w.spatial_channel(tx,tx_kind,parameters('spatial_channel',noise=False),rng)
            # State exposes public training and length; no channel/payload values.
            self.assertEqual(set(state),{'mode','pilot','count'})
            for rx_kind in receivers:
                recovered,details=w.spatial_decode(received,state,rx_kind)
                np.testing.assert_allclose(recovered,symbols,atol=1e-11)
                np.testing.assert_allclose(details['channel_estimate']['i'],channel['channel_matrix']['i'],atol=1e-12)
                np.testing.assert_allclose(details['channel_estimate']['q'],channel['channel_matrix']['q'],atol=1e-12)

    def test_mrc_noise_improvement_and_mmse_noise_regularization(self):
        rng=np.random.default_rng(52); symbols=(2*rng.integers(0,2,16000)-1+1j*(2*rng.integers(0,2,16000)-1))/np.sqrt(2)
        tx,state=w.spatial_encode(symbols,'tx_simo',parameters('tx_simo',training=128))
        received,_=w.spatial_channel(tx,'tx_simo',parameters('spatial_channel',gains='1,1',snr_db=6),rng)
        selected,_=w.spatial_decode(received,state,'rx_selection');combined,_=w.spatial_decode(received,state,'rx_mrc')
        self.assertLess(np.mean(abs(combined-symbols)**2),np.mean(abs(selected-symbols)**2)*.65)
        tx,state=w.spatial_encode(symbols,'tx_mimo',parameters('tx_mimo',training=128))
        received,_=w.spatial_channel(tx,'tx_mimo',parameters('spatial_channel',gains='1,.95,.95,1',snr_db=10),rng)
        zero_forcing,_=w.spatial_decode(received,state,'rx_mimo_zf');mmse,details=w.spatial_decode(received,state,'rx_mimo_mmse')
        self.assertGreater(details['estimated_noise_variance'],0)
        self.assertLess(np.mean(abs(mmse-symbols)**2),np.mean(abs(zero_forcing-symbols)**2)*.2)

    def test_end_to_end_presets_rates_metrics_and_full_antenna_arrays(self):
        for key in ('dsss_interference','dsss_rake','diversity_selection','diversity_mrc','diversity_alamouti','mimo_zf','mimo_mmse'):
            result=execute(c.PRESETS[key]['program']); json.dumps(result,allow_nan=False)
            self.assertEqual(result['sink']['count'],512)
            self.assertLessEqual(result['metrics']['ber'],.02)
            details=result['advanced']['wireless']
            if 'spatial_channel' in details:
                tx_kind=next(kind for kind in w.SPATIAL_TX if kind in details)
                full=details[tx_kind]['full_tx'];x=np.array(full['i'])+1j*np.array(full['q'])
                self.assertEqual(list(x.shape),full['shape'])
                self.assertAlmostEqual(result['metrics']['tx_energy'],float(np.sum(abs(x)**2)))
                self.assertEqual(details['spatial_channel']['full_rx']['shape'][0],len(x))
            else: self.assertEqual(result['advanced']['sample_rate'],31000)

    def test_type_validation_rejects_mismatched_or_incomplete_receiver(self):
        for kinds in [
            ['random_bits','mod_qpsk','tx_dsss','ideal','rx_despread','demod_qpsk','sink'],
            ['random_bits','mod_qpsk','tx_mimo','spatial_channel','rx_mrc','demod_qpsk','sink'],
            ['random_bits','mod_qpsk','tx_mimo','spatial_channel','demod_qpsk','sink'],
            ['random_bits','mod_qpsk','tx_mimo','spatial_channel','rx_dc','rx_mimo_zf','demod_qpsk','sink'],
        ]:
            with self.assertRaises(ValueError): c.build(c.preset(kinds))
        program=copy.deepcopy(c.PRESETS['dsss_rake']['program']);program['blocks'][2]['params']['initial']=32
        with self.assertRaises(ValueError): c.build(program)

    def test_receiver_branches_reuse_identical_spatial_arrays(self):
        first=copy.deepcopy(c.PRESETS['diversity_mrc']['program']); second=copy.deepcopy(first)
        next(block for block in second['blocks'] if block['kind']=='rx_mrc')['kind']='rx_selection'
        result=studio.compare_branches([first,second])
        a,b=[entry['result'] for entry in result['branches']]
        self.assertEqual(a['advanced']['wireless']['spatial_channel']['full_rx'],b['advanced']['wireless']['spatial_channel']['full_rx'])
        self.assertLess(a['metrics']['evm_percent'],b['metrics']['evm_percent'])


if __name__=='__main__': unittest.main()
