"""Actual RSC termination, exact BCJR and noisy iterative recovery."""
from pathlib import Path
import itertools
import json
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src import communication_turbo as turbo, communications as c


def settings(**changes):
    return {'block_size':128,'interleaver_seed':17,'iterations':6,'algorithm':0,**changes}


class TurboTests(unittest.TestCase):
    def test_exact_bcjr_matches_enumerated_terminated_trellis(self):
        k=5; rng=np.random.default_rng(8); systematic=rng.normal(size=k+3); parity=rng.normal(size=k+3); prior=np.r_[rng.normal(size=k),np.zeros(3)]
        candidates=[turbo.rsc(np.array(bits,np.uint8)) for bits in itertools.product((0,1),repeat=k)]
        inputs=np.array([v[0] for v in candidates]); parity_bits=np.array([v[1] for v in candidates])
        scores=.5*((1-2*inputs.astype(float))@(systematic+prior)+(1-2*parity_bits.astype(float))@parity)
        for method,reduce in ((0,np.logaddexp.reduce),(1,np.max)):
            expected=np.array([reduce(scores[inputs[:,i]==0])-reduce(scores[inputs[:,i]==1]) for i in range(k)])
            np.testing.assert_allclose(turbo.bcjr(systematic,parity,prior,method)[:k],expected,atol=1e-12)

    def test_all_block_sizes_and_partial_tail(self):
        for k in (32,64,128,256,512):
            q=settings(block_size=k,iterations=2); bits=np.random.default_rng(k).integers(0,2,k+13,dtype=np.uint8)
            wire=turbo.encode('turbo_encode',bits,q)
            self.assertEqual(len(wire),turbo.encoded_count('turbo_encode',len(bits),q))
            decoded,detail=turbo.decode('turbo_decode',12*(1-2*wire.astype(float)),q)
            np.testing.assert_array_equal(bits,decoded[:len(bits)]); json.dumps(detail,allow_nan=False)

    def test_iterations_exchange_extrinsic_and_correct_noise(self):
        rng=np.random.default_rng(19); bits=rng.integers(0,2,128,dtype=np.uint8); q=settings()
        wire=turbo.encode('turbo_encode',bits,q); sigma=.95
        llr=2*((1-2*wire.astype(float))+sigma*rng.normal(size=len(wire)))/sigma**2
        one,_=turbo.decode('turbo_decode',llr,{**q,'iterations':1})
        decoded,detail=turbo.decode('turbo_decode',llr,q)
        self.assertLess(np.count_nonzero(decoded!=bits),np.count_nonzero(one!=bits))
        self.assertEqual(np.count_nonzero(decoded!=bits),0)
        h=detail['learning']['history']; self.assertTrue(np.any(np.asarray(h[1]['prior'])!=0))
        self.assertEqual(len(h),6)
        maximum,_=turbo.decode('turbo_decode',llr,{**q,'algorithm':1})
        self.assertEqual(np.count_nonzero(maximum!=bits),0)

    def test_integrated_presets(self):
        for name,preset in turbo.presets(c.preset).items():
            built=c.build(preset['program']); result=c.run(built['program'],built['token'])
            self.assertEqual(result['metrics']['bit_errors'],0,name)
            self.assertEqual(result['sink']['values'],result['sink']['reference']); json.dumps(result,allow_nan=False)


if __name__=='__main__': unittest.main(verbosity=2)
