"""Protected on-air headers, streaming capture and physical recording recovery."""
from pathlib import Path
import json
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src import communication_framing_v0410 as framing, communications as c


class FramingTests(unittest.TestCase):
    def setUp(self): self.bits=np.unpackbits(np.frombuffer(('海洋通信 🌊 连续物理帧\n'*13).encode(),np.uint8))

    def test_all_mcs_odd_lengths_and_no_transmit_metadata(self):
        for mcs in range(5):
            bits=np.r_[self.bits[:997],np.uint8(1)]; wave,tx=framing.encode_stream(bits,{'packet_bytes':29,'mcs':mcs,'gap':17})
            recovered,rx,_=framing.receive_stream(wave)
            np.testing.assert_array_equal(recovered,bits); self.assertTrue(rx['complete_payload'])
            self.assertEqual([r['payload_bits'] for r in rx['frames']],[r['payload_bits'] for r in tx['frames']])
            json.dumps(rx,allow_nan=False)

    def test_noise_unknown_gain_and_arbitrary_chunk_boundaries(self):
        wave,_=framing.encode_stream(self.bits,{'packet_bytes':31,'mcs':4,'gap':43}); rng=np.random.default_rng(12)
        wave=np.r_[np.zeros(211),wave,np.zeros(97)]*.63*np.exp(1j*.83)
        wave+=.02*(rng.normal(size=len(wave))+1j*rng.normal(size=len(wave)))
        state=None
        for start in range(0,len(wave),137):
            recovered,rx,state=framing.receive_stream(wave[start:start+137],state=state,final=start+137>=len(wave))
        np.testing.assert_array_equal(recovered,self.bits); self.assertTrue(rx['complete_payload'])
        self.assertEqual(rx['frames'][0]['start_sample'],211)
        self.assertEqual(rx['received_base64'],rx['reassembled_base64'])

    def test_truncated_payload_and_corrupt_header_reacquire_next_packets(self):
        wave,tx=framing.encode_stream(self.bits,{'packet_bytes':31,'mcs':4,'gap':43})
        # A missing section in packet 0 shifts every later physical sample.
        cut=framing.HEADER_SYMBOLS+len(framing.PREAMBLE)+19; removed=71
        damaged=np.r_[wave[:cut],wave[cut+removed:]]
        recovered,rx,_=framing.receive_stream(damaged)
        self.assertFalse(rx['complete_payload']); self.assertFalse(rx['frames'][0]['payload_crc_pass'])
        self.assertEqual(rx['accepted_packets'],len(tx['frames'])-1)
        np.testing.assert_array_equal(recovered[248:],self.bits[248:])
        wave[127:419]=0
        _,rx,_=framing.receive_stream(wave)
        self.assertEqual(rx['accepted_packets'],len(tx['frames'])-1); self.assertGreater(rx['header_failures'],0)

    def test_recording_roundtrip_raw_iq_bytes_with_missing_first_and_last_frames(self):
        wave,tx=framing.encode_stream(self.bits,{'packet_bytes':31,'mcs':4,'gap':43})
        recording=wave[tx['frames'][0]['end_sample']-13:tx['frames'][-1]['end_sample']-17]
        data=recording.astype('<c8').tobytes(); replay=np.frombuffer(data,dtype='<c8').astype(complex)
        recovered,rx,_=framing.receive_stream(replay)
        self.assertEqual(rx['total_bits'],len(self.bits)); self.assertFalse(rx['complete_payload'])
        self.assertEqual(rx['accepted_packets'],len(tx['frames'])-2)
        first,last=rx['coverage'][0][0],rx['coverage'][-1][1]
        np.testing.assert_array_equal(recovered[first:last],self.bits[first:last])

    def test_public_engine_presets(self):
        for name,entry in framing.presets(c.preset).items():
            built=c.build(entry['program']); result=c.run(built['program'],built['token']); json.dumps(result,allow_nan=False)
            rx=next(v for v in result['advanced']['wireless'].values() if v.get('kind')=='self_frame_rx')
            self.assertGreater(rx['accepted_packets'],1)
            if name=='self_describing_frames': self.assertEqual(result['metrics']['bit_errors'],0)


if __name__=='__main__': unittest.main(verbosity=2)
