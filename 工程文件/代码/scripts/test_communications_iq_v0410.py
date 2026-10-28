"""Independent IQ reception of public self-describing physical frames."""
from pathlib import Path
import copy
import json
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src import communications as c, communication_iq as iq, communication_runtime as runtime
from src import communication_framing_v0410 as framing, communication_studio as studio


def observed(program):
    built=c.build(program)
    result,ctx=runtime.observe_run(built['program'],built['token'],retain=True)
    return built,result,ctx


def export_point(built,ctx,point):
    observation=next(o for o in ctx.observations if o['id']==point)
    return iq.export_recording(ctx.values[point],observation['sample_rate'],built['program'],point,observation['domain'])


def recording(wave,receiver=None):
    return iq.import_recording(iq.encoded(wave),metadata={'global':{
        'core:datatype':'cf32_le','core:sample_rate':32000,
        'randomsign:receiver':{'mode':3,**(receiver or {})}}})['program']


class SelfFrameIQTests(unittest.TestCase):
    def test_sigmf_observed_waveform_roundtrip_uses_only_public_format(self):
        built,_,ctx=observed(c.PRESETS['self_describing_frames']['program'])
        expected=ctx.values[built['program']['blocks'][-1]['id']]
        for block in built['program']['blocks']:
            if block['kind'] not in ('tx_self_frame','frame_stream_channel'):continue
            with self.subTest(point=block['kind']):
                archive=export_point(built,ctx,block['id'])
                metadata=archive['metadata']['global']['randomsign:receiver']
                self.assertEqual(set(metadata),{'mode','scheme','rate_hz','center_hz'})
                self.assertEqual(metadata['mode'],3)
                restored=iq.import_recording(archive['data'],name='continuous.sigmf')['program']
                self.assertEqual([b['kind'] for b in restored['blocks']],['iq_source','rx_self_frame','demod_bpsk','sink'])
                rb,result,received=observed(restored)
                np.testing.assert_array_equal(received.values[rb['program']['blocks'][-1]['id']],expected)
                self.assertEqual(result['metrics']['received_bits'],2048)
                self.assertEqual(result['metrics']['accepted_packets'],8)
                self.assertEqual(result['metrics']['bit_count'],0)
                self.assertIsNone(result['metrics']['ber'])
                self.assertEqual({r['mcs'] for r in result['advanced']['wireless']['rx_self_frame']['frames']},{0,1,2,3})

    def test_variable_payload_with_noise_gaps_ignores_external_length_and_mcs(self):
        rng=np.random.default_rng(41011);bits=rng.integers(0,2,2053,dtype=np.uint8)
        wave,_=framing.encode_stream(bits,{'packet_bytes':29,'mcs':4,'gap':43})
        wave=np.r_[np.zeros(241),wave,np.zeros(173)]*.7*np.exp(.7j)
        wave+=.012*(rng.normal(size=len(wave))+1j*rng.normal(size=len(wave)))
        p=recording(wave,{'payload_symbols':1,'scheme':3,'sample_offset':len(wave)+10})
        built,result,ctx=observed(p)
        self.assertIn('实际帧头',built['summary'])
        self.assertTrue(built['plan'][1]['dynamic_count'])
        np.testing.assert_array_equal(ctx.values[built['program']['blocks'][-1]['id']],bits)
        self.assertEqual(result['plan'][-1]['count'],2053)
        self.assertNotIn('dynamic_count',result['plan'][-1])
        frames=result['advanced']['recovery']['self_frame']['frames']
        self.assertEqual(frames[0]['start_sample'],241)
        self.assertEqual(frames[-1]['payload_bits'],197)

    def test_truncated_first_packet_and_missing_capture_tail_reacquire_later_packets(self):
        rng=np.random.default_rng(41012);bits=rng.integers(0,2,1797,dtype=np.uint8)
        wave,tx=framing.encode_stream(bits,{'packet_bytes':32,'mcs':4,'gap':17})
        # Capture starts inside packet 0 and ends inside the final packet.
        wave=wave[tx['frames'][0]['start_sample']+530:-10]
        p=recording(wave);built,result,ctx=observed(p)
        details=result['advanced']['recovery']['self_frame']
        self.assertEqual(details['accepted_packets'],6)
        self.assertEqual(details['coverage'],[[i*256,(i+1)*256] for i in range(1,7)])
        self.assertEqual(result['metrics']['received_bits'],1536)
        self.assertEqual(result['metrics']['reassembled_bits'],1797)
        recovered=ctx.values[built['program']['blocks'][-1]['id']]
        np.testing.assert_array_equal(recovered[256:1792],bits[256:1792])
        self.assertTrue(np.all(recovered[:256]==0))
        self.assertTrue(np.all(recovered[1792:]==0))
        self.assertEqual(details['frames'][-1]['truncated'],True)
        self.assertFalse(result['metrics']['complete_payload'])

    def test_reexport_before_and_after_frame_receive_preserves_remaining_operations(self):
        bits=np.random.default_rng(41013).integers(0,2,1027,dtype=np.uint8)
        wave,_=framing.encode_stream(bits,{'packet_bytes':31,'mcs':4,'gap':9})
        built,_,ctx=observed(recording(wave,{'framed':True,'dft_spread':True,'burst_framed':True}))
        for kind,mode in (('iq_source',3),('rx_self_frame',0)):
            point=next(b['id'] for b in built['program']['blocks'] if b['kind']==kind)
            with self.subTest(point=kind):
                archive=export_point(built,ctx,point)
                self.assertEqual(archive['metadata']['global']['randomsign:receiver']['mode'],mode)
                restored=iq.import_recording(archive['data'],name='again.sigmf')['program']
                rb,_,rx=observed(restored)
                np.testing.assert_array_equal(rx.values[rb['program']['blocks'][-1]['id']],bits)
                self.assertEqual(sum(b['kind']=='rx_self_frame' for b in restored['blocks']),int(mode==3))

    def test_noise_only_recording_has_finite_empty_result_and_invalid_chain_is_rejected(self):
        rng=np.random.default_rng(41014);p=recording(rng.normal(size=2000)+1j*rng.normal(size=2000))
        _,result,_=observed(p)
        self.assertEqual(result['metrics']['received_bits'],0)
        self.assertEqual(result['sink']['count'],0)
        self.assertEqual(result['metrics']['rx_power'],0)
        json.dumps(result,allow_nan=False)
        wrong=copy.deepcopy(p);wrong['blocks']=[wrong['blocks'][0]]+wrong['blocks'][2:]
        with self.assertRaisesRegex(ValueError,'抽样'):c.build(wrong)

    def test_auto_completion_builds_header_driven_receiver_from_iq_source(self):
        bits=np.random.default_rng(41015).integers(0,2,777,dtype=np.uint8)
        wave,_=framing.encode_stream(bits,{'packet_bytes':21,'mcs':4,'gap':33})
        p=recording(wave);p['blocks']=[p['blocks'][0],p['blocks'][-1]]
        built,_,ctx=observed(studio.complete_iq_receiver(p))
        np.testing.assert_array_equal(ctx.values[built['program']['blocks'][-1]['id']],bits)
        self.assertEqual([b['kind'] for b in built['program']['blocks']],['iq_source','rx_self_frame','demod_bpsk','sink'])


if __name__=='__main__':unittest.main()
