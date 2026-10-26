"""Numerical acceptance for pilot estimators, calibrated MIMO and ULA processing."""
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src import communication_receiver_v049 as receiver, communication_array_v049 as array
from src import communication_wireless as wireless, communication_spatial as spatial, communication_dsp as dsp


def registry(module):
    from src.communications import block, number, field
    entries={}
    def collect(kind,label,category,description,**params):entries[kind]={k:v['default'] for k,v in params.items()}
    module.register(collect,number,field,{})
    return entries


class ReceiverTests(unittest.TestCase):
    def test_lmmse_reduces_noisy_pilot_estimation_mse(self):
        rng=np.random.default_rng(94);p=array.public_pilots(8,2);ls_error=lmmse_error=0.
        for _ in range(200):
            h=(rng.normal(size=(2,2))+1j*rng.normal(size=(2,2)))/np.sqrt(2)
            y=p@h.T+rng.normal(size=(8,2))+1j*rng.normal(size=(8,2))
            ls,_=receiver.pilot_estimate(p,y);estimated,_=receiver.pilot_estimate(p,y,'lmmse')
            ls_error+=np.sum(abs(ls-h)**2);lmmse_error+=np.sum(abs(estimated-h)**2)
        self.assertLess(lmmse_error,ls_error*.85)

    def test_kalman_is_causal_and_recovers_static_complex_matrix(self):
        q=registry(receiver)['rx_mimo_kalman'];q.update(rho=1.,process_noise=0.)
        symbols=np.tile([1+1j,-1+1j],50)/np.sqrt(2)
        tx,s=spatial.tracking_encode(symbols,{'training':8,'interval':8})
        h=np.array([[1,.2+.1j],[-.3j,.9]])
        y=tx@h.T
        estimates,trace=receiver.kalman_channels(y,s['pilot'],s['pilot_slots'],s['data_slots'],q,0.)
        np.testing.assert_allclose(estimates,np.broadcast_to(h,estimates.shape),atol=1e-11)
        altered=y.copy();altered[30:]*=4j
        changed,_=receiver.kalman_channels(altered,s['pilot'],s['pilot_slots'],s['data_slots'],q,.01)
        baseline,_=receiver.kalman_channels(y,s['pilot'],s['pilot_slots'],s['data_slots'],q,.01)
        before=np.array(s['data_slots'])<30
        np.testing.assert_array_equal(changed[before],baseline[before])
        self.assertEqual(len(trace['covariance_trace']),len(s['data_slots']))

    def test_mmse_effective_noise_matches_empirical_stream_errors(self):
        rng=np.random.default_rng(147);bits=rng.integers(0,2,160000)
        values=dsp.map_bits(bits,'qpsk')[0].reshape(-1,2);h=np.array([[1,.6j],[.2,.25]])
        sigma=.12;y=values@h.T/np.sqrt(2)+np.sqrt(sigma/2)*(rng.normal(size=values.shape)+1j*rng.normal(size=values.shape))
        recovered,noise,_=receiver.calibrated_mmse(y,h,sigma)
        empirical=np.mean(abs(recovered-values)**2,axis=0)
        np.testing.assert_allclose(noise,empirical,rtol=.05)
        self.assertGreater(noise[1],noise[0]*2)

    def test_soft_receiver_recovers_static_and_ofdm_using_public_training(self):
        rng=np.random.default_rng(39);symbols=dsp.map_bits(rng.integers(0,2,514),'qpsk')[0]
        q=registry(receiver)['rx_mimo_soft']
        tx,public=wireless.spatial_encode(symbols,'tx_mimo',{'training':64})
        h=np.array([[1,.1j],[.15,1]])
        decoded,details=receiver.decode(tx@h.T,public,'rx_mimo_soft',q,'qpsk')
        np.testing.assert_allclose(decoded,symbols,atol=1e-11)
        np.testing.assert_array_equal(np.array(details['llr'])<0,dsp.decisions(symbols,'qpsk')[0])
        tx,public=spatial.ofdm_encode(symbols,{'nfft':16,'cp':4})
        received=np.pad(tx@h.T,((0,2),(0,0)));received[2:]+=tx@(.15*h).T
        decoded,details=receiver.decode(received,public,'rx_mimo_soft',q,'qpsk')
        np.testing.assert_allclose(decoded,symbols,atol=1e-11)
        self.assertEqual(len(details['effective_noise_variance']),len(symbols))

    def test_reciprocal_sounding_and_mrt_svd_energy_and_recovery(self):
        rng=np.random.default_rng(62);defs=registry(array);symbols=dsp.map_bits(rng.integers(0,2,516),'qpsk')[0]
        for kind in ('tx_mrt','tx_svd'):
            channel={**defs['array_channel'],'noise':False,'branches':1 if kind=='tx_mrt' else 4}
            if kind=='tx_svd':channel.update(arrival='10,-35',departure='20,50',gains='1,.6+.2j')
            tx,s,details=array.encode(symbols,kind,defs[kind],channel,rng)
            h=array.geometry(channel,4);y=tx@h.T
            estimated=details['sounding']['estimated_channel'];np.testing.assert_allclose(np.array(estimated['i'])+1j*np.array(estimated['q']),h,atol=1e-12)
            self.assertAlmostEqual(float(np.sum(abs(tx)**2)),defs[kind]['training']+len(symbols)/s['streams'],places=10)
            public={k:s[k] for k in ('pilot','count','prefix','spacing')}
            rx='rx_array_conventional' if kind=='tx_mrt' else 'rx_array_svd'
            decoded,_=array.receive(y,public,rx,defs[rx]);np.testing.assert_allclose(decoded,symbols,atol=1e-10)

    def test_mvdr_suppresses_directional_interference(self):
        rng=np.random.default_rng(81);defs=registry(array);symbols=dsp.map_bits(rng.integers(0,2,8192),'qpsk')[0]
        channel={**defs['array_channel'],'noise':False}
        tx,s,_=array.encode(symbols,'tx_array',defs['tx_array'],channel,rng)
        y=tx@array.geometry(channel,1).T
        jammer=3*(rng.normal(size=len(y))+1j*rng.normal(size=len(y)))/np.sqrt(2)
        y+=jammer[:,None]*array.steering(4,.5,-35)
        y+=.02*(rng.normal(size=y.shape)+1j*rng.normal(size=y.shape))
        public={k:s[k] for k in ('pilot','count','prefix','spacing')}
        conventional,_=array.receive(y,public,'rx_array_conventional',defs['rx_array_conventional'])
        mvdr,details=array.receive(y,public,'rx_array_mvdr',defs['rx_array_mvdr'])
        self.assertLess(np.mean(abs(mvdr-symbols)**2),np.mean(abs(conventional-symbols)**2)*.04)
        self.assertGreater(details['rejection_db'],20)
        w=np.array(details['beam_weights']['i'])+1j*np.array(details['beam_weights']['q'])
        self.assertAlmostEqual(abs(np.vdot(w,array.steering(4,.5,10))),1.,places=10)

    def test_registered_presets_and_soft_fec_end_to_end(self):
        from src import communications as c
        results={}
        for extension in (receiver,array):
            for key,entry in extension.presets(c.preset).items():
                built=c.build(entry['program']);results[key]=c.run(built['program'],built['token'])
                self.assertTrue(np.isfinite(results[key]['metrics']['ber']))
        for key in ('receiver_soft_ldpc','receiver_soft_viterbi','receiver_kalman_soft','array_mvdr','array_mrt','array_svd'):
            self.assertEqual(results[key]['metrics']['ber'],0,key)
        self.assertLess(results['array_mvdr']['metrics']['ber'],results['array_conventional']['metrics']['ber'])

    def test_array_and_kalman_build_contracts(self):
        from src import communications as c
        from copy import deepcopy
        p=deepcopy(receiver.presets(c.preset)['receiver_lmmse']['program']);p['blocks'][4]['kind']='rx_mimo_kalman';p['blocks'][4]['params']=registry(receiver)['rx_mimo_kalman']
        with self.assertRaisesRegex(ValueError,'周期正交导频'):c.build(p)
        p=deepcopy(array.presets(c.preset)['array_svd']['program']);p['blocks'][3]['params'].update(arrival='10',departure='20',gains='1')
        with self.assertRaisesRegex(ValueError,'独立空间路径'):c.build(p)

    def test_receiver_completion_upgrades_existing_hard_viterbi(self):
        from src import communications as c, communication_studio as studio
        from copy import deepcopy
        program=deepcopy(c.PRESETS['receiver_soft_viterbi']['program'])
        for block in program['blocks']:
            if block['kind']=='soft_qpsk':
                block.update(kind='demod_qpsk',params={k:v['default'] for k,v in c.BLOCKS['demod_qpsk']['params'].items()})
            elif block['kind']=='conv_soft_decode':
                decoder_id=block['id'];block.update(kind='conv_decode',params={})
        c.build(program)
        completed=studio.complete_receiver(program)
        decoder=next(block for block in completed['blocks'] if block['id']==decoder_id)
        self.assertEqual(decoder['kind'],'conv_soft_decode')
        self.assertIn('soft_qpsk',[block['kind'] for block in completed['blocks']])
        built=c.build(completed);result=c.run(built['program'],built['token'])
        self.assertEqual(result['metrics']['ber'],0)


if __name__=='__main__':unittest.main()
