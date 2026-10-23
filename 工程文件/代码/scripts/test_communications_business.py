"""Core v0.4.7 business payload and finite-field codec checks."""
import base64
import copy
import io
import itertools
import json
from pathlib import Path
import sys
import unittest
import wave
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from src import communication_business as b, communication_codecs as codec
from src import communications as c, communication_studio as studio, communication_runtime as runtime


def execute(program):
    compiled=c.build(program)
    return compiled,c.run(compiled['program'],compiled['token'])


class BusinessTests(unittest.TestCase):
    def test_huffman_self_describing_roundtrip_and_exact_build_counts(self):
        rng=np.random.default_rng(12)
        for data in (np.zeros(47,dtype=np.uint8),rng.integers(0,2,137,dtype=np.uint8),b.byte_bits(bytes(range(256)))):
            encoded,trace=b.huffman_encode(data,True)
            np.testing.assert_array_equal(b.huffman_decode(encoded),data)
            self.assertEqual(len(encoded),trace['header_bits']+trace['payload_bits'])
        p=copy.deepcopy(c.PRESETS['business_huffman']['program'])
        compiled,result=execute(p)
        row=next(row for row in compiled['plan'] if row['kind']=='huffman_encode')
        self.assertEqual(row['count'],result['metrics']['coded_bit_count'])
        self.assertLess(result['advanced']['learning'][0]['average_length'],2)
        self.assertEqual(result['metrics']['ber'],0)

    def test_huffman_after_channel_code_composes(self):
        p=c.preset(['random_bits','bch_encode','huffman_encode','mod_qpsk','ideal','demod_qpsk','huffman_decode','bch_decode','sink'],{0:{'count':117}})
        compiled,result=execute(p)
        self.assertEqual(result['metrics']['ber'],0)
        self.assertEqual(next(r['count'] for r in compiled['plan'] if r['kind']=='huffman_encode'),result['metrics']['coded_bit_count'])

    def test_ima_adpcm_fixed_code_and_audio_quality(self):
        decoded,trace=b.adpcm(codec.words_to_bits([7,7,7,7],4),1,True)
        np.testing.assert_array_equal(np.rint(decoded*32768),[11,41,104,240])
        _,result=execute(c.PRESETS['business_audio']['program'])
        self.assertEqual(result['metrics']['ber'],0)
        media=result['sink']['media']
        self.assertGreater(media['metrics']['snr_db'],15)
        for name in ('original_base64','received_base64'):
            with wave.open(io.BytesIO(base64.b64decode(media[name]))) as wav:
                self.assertEqual((wav.getnchannels(),wav.getframerate(),wav.getnframes()),(1,8000,1024))

    def test_bch_all_messages_and_every_double_error(self):
        messages=codec.words_to_bits(range(128),7).reshape(128,7)
        encoded=np.array([b.bch_encode(m) for m in messages])
        # Every cyclic codeword has zero polynomial remainder.
        self.assertTrue(all(b.binary_remainder(int(v))==0 for v in codec.bits_to_words(encoded.ravel(),15)))
        for positions in itertools.combinations(range(15),2):
            damaged=encoded.copy();damaged[:,positions]^=1
            decoded,info=b.bch_decode(damaged.ravel())
            np.testing.assert_array_equal(decoded,messages.ravel())
            self.assertEqual(info['corrected_bits'],256)

    def test_rs_all_syndromes_zero_and_sixteen_symbol_errors(self):
        rng=np.random.default_rng(55)
        data=rng.integers(0,2,223*8*2,dtype=np.uint8)
        encoded=b.rs_encode(data);words=np.packbits(encoded).reshape(-1,255)
        for row in words:
            self.assertTrue(all(b.gf_poly(row,b.GF_EXP[i])==0 for i in range(32)))
            positions=rng.choice(255,16,replace=False);row[positions]^=rng.integers(1,256,16,dtype=np.uint8)
        decoded,info=b.rs_decode(np.unpackbits(words.ravel()))
        np.testing.assert_array_equal(decoded,data)
        self.assertEqual(info,{'corrected_bytes':32,'failed_codewords':0})

    def test_rs_short_payload_preserves_nonbyte_bit_length(self):
        p=c.preset(['random_bits','rs_encode','mod_qpsk','ideal','demod_qpsk','rs_decode','sink'],{0:{'count':113}})
        _,result=execute(p)
        self.assertEqual(result['sink']['count'],113);self.assertEqual(result['metrics']['ber'],0)

    def test_image_and_file_uploads_and_reconstructed_hashes(self):
        for kind,raw,q in [('image_source',bytes(range(64)),{'width':8,'height':8,'filename':'test.png'}),('file_source',b'\x00\xffOcean\x80',{'filename':'test.bin'})]:
            p=c.preset([kind,'rs_encode','mod_qpsk','ideal','demod_qpsk','rs_decode','sink'],{0:{**q,'data':base64.b64encode(raw).decode()}})
            _,result=execute(p);media=result['sink']['media']
            self.assertTrue(media['metrics']['identical'])
            received=base64.b64decode(media['received_base64'])
            if kind=='image_source': received=Image.open(io.BytesIO(received)).tobytes()
            self.assertEqual(received,raw)

    def test_audio_upload_and_invalid_payloads(self):
        samples=np.arange(-512,512,dtype='<i2');p=copy.deepcopy(c.PRESETS['business_audio']['program'])
        p['blocks'][0]['params']['data']=base64.b64encode(samples.tobytes()).decode()
        _,result=execute(p)
        np.testing.assert_array_equal(result['sink']['reference'],samples/32768)
        p['blocks'][0]['params']['data']='bad!'
        with self.assertRaisesRegex(ValueError,'Base64'): c.build(p)

    def test_full_second_audio_upload_and_empty_file_message(self):
        samples=np.rint(12000*np.sin(2*np.pi*440*np.arange(8192)/8192)).astype('<i2')
        p=copy.deepcopy(c.PRESETS['business_audio']['program']);p.update(sample_count=8192,sample_rate=8192)
        p['blocks'][0]['params']['data']=base64.b64encode(samples.tobytes()).decode()
        compiled,result=execute(p)
        self.assertEqual(result['sink']['count'],8192);self.assertEqual(result['sink']['media']['metrics']['duration_seconds'],1)
        self.assertEqual(compiled['plan'][1]['count'],32768)
        p=copy.deepcopy(c.PRESETS['business_file']['program']);p['blocks'][0]['params']['data']=''
        with self.assertRaisesRegex(ValueError,'文件需要至少一个字节'):c.build(p)

    def test_audio_observer_uses_reconstructed_sample_rate(self):
        p=c.PRESETS['business_audio']['program'];_,context=runtime.observe_run(p,c.build(p)['token'])
        samples=[row for row in context.observations if row['domain']=='模拟样本']
        self.assertEqual([row['sample_rate'] for row in samples],[8000,8000,8000])

    def test_source_probability_and_isolated_media_validation(self):
        p=c.preset(['discrete_source','mod_bpsk','ideal','demod_bpsk','sink'],{0:{'probabilities':'0.7,0.15,0.1,0.1'}})
        with self.assertRaisesRegex(ValueError,'概率'): c.build(p)
        p=c.preset(['file_source','text','mod_bpsk','ideal','demod_bpsk','sink'])
        with self.assertRaisesRegex(ValueError,'独立链路'): c.build(p)

    def test_packet_payloads_crc_loss_and_partial_byte(self):
        data=np.random.default_rng(7).integers(0,2,811,dtype=np.uint8);q={'packet_bytes':32}
        encoded=b.encode('packet_encode',data,q);decoded,info=b.decode('packet_decode',encoded,q)
        np.testing.assert_array_equal(decoded[:len(data)],data);self.assertEqual(info['packet_count'],4)
        encoded[100]^=1;decoded,info=b.decode('packet_decode',encoded,q)
        self.assertEqual(info['packet_loss'],1);self.assertFalse(info['crc_pass']);self.assertFalse(np.any(decoded[:256]))

    def test_learning_traces_are_real_decoding_steps(self):
        _,soft=execute(c.PRESETS['soft_viterbi']['program'])
        trace=soft['advanced']['learning'][0]
        self.assertEqual(trace['kind'],'viterbi');self.assertEqual(len(trace['history']),64)
        self.assertEqual(trace['survivor'][0]['bit'],soft['sink']['values'][0])
        _,ldpc=execute(c.PRESETS['ldpc']['program'])
        history=ldpc['advanced']['learning'][0]['history']
        self.assertEqual(history[-1]['unsatisfied_checks'],0)

    def test_new_presets_have_valid_ports_and_autocomplete(self):
        for key,preset in b.presets(c.preset).items():
            with self.subTest(key=key):
                report=studio.describe(preset['program'])
                self.assertTrue(report['ready']);self.assertTrue(all(r['compatible'] for r in report['ports']))
                p=copy.deepcopy(preset['program']);p['blocks']=[row for row in p['blocks'] if row['kind'] not in c.PAIRS and not row['kind'].startswith(('demod_','soft_'))]
                _,result=execute(studio.complete_receiver(p));self.assertEqual(result['metrics']['ber'],0)
                json.dumps(result,allow_nan=False)

    def test_business_codecs_compose_with_existing_pam_and_audio_am(self):
        for source,codec_name in [('audio_source','adpcm'),('image_source','rs'),('file_source','bch'),('discrete_source','huffman')]:
            p=c.preset([source,codec_name+'_encode','mod_pam','ideal','demod_pam',codec_name+'_decode','sink'])
            _,result=execute(p);self.assertEqual(result['metrics']['ber'],0)
        _,result=execute(c.preset(['audio_source','mod_am','ideal','demod_am','sink']))
        self.assertLess(result['metrics']['rmse'],1e-12);self.assertEqual(result['sink']['media']['kind'],'audio')


if __name__=='__main__': unittest.main()
