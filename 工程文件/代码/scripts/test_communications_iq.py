"""Actual IQ samples, public receiver metadata and source-independent replay."""
from pathlib import Path
import base64
import copy
import hashlib
import io
import json
import sys
import tarfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import communications as c, communication_iq as iq, communication_dsp as dsp
from src import communication_runtime as runtime


def replay(program):
    built = c.build(program)
    result, ctx = runtime.observe_run(built['program'], built['token'], retain=True)
    return result, ctx, built


def recording(values, receiver=None, rate=192000, datatype='cf32_le'):
    raw = np.asarray(values, dtype='<c8' if datatype == 'cf32_le' else '<c16').tobytes()
    return iq.import_recording(base64.b64encode(raw).decode(),
        metadata={'global': {'core:datatype': datatype, 'core:sample_rate': rate,
                             'randomsign:receiver': receiver or {}},
                  'captures': [{'core:sample_start': 0, 'core:frequency': 915000000}]})


class IQTests(unittest.TestCase):
    def test_catalog_select_choices_are_json_arrays_with_valid_defaults(self):
        catalog=json.loads(json.dumps(c.catalog(),ensure_ascii=False))
        for block in catalog['blocks']:
            for name,spec in block['params'].items():
                if spec['type']=='select':
                    with self.subTest(block=block['kind'],parameter=name):
                        self.assertIsInstance(spec['choices'],list)
                        self.assertIn(spec['default'],spec['choices'])

    def test_float_and_integer_raw_import_preserve_samples(self):
        values = np.array([.125+.25j, -.5+.75j, .5-.125j], dtype=np.complex64)
        for dtype in ('cf32_le', 'cf64_le'):
            imported = recording(values, datatype=dtype)
            np.testing.assert_array_equal(iq.samples(imported['program']['blocks'][0]['params']), values)
            self.assertEqual(imported['count'], 3)
        pairs = np.column_stack((values.real * 32768, values.imag * 32768)).astype('<i2').ravel()
        imported = iq.import_recording(base64.b64encode(pairs.tobytes()).decode(), datatype='ci16_le', sample_rate=96000)
        np.testing.assert_array_equal(iq.samples(imported['program']['blocks'][0]['params']), values)
        self.assertEqual(imported['sample_rate'], 96000)

    def test_actual_symbol_replay_at_high_sample_rate(self):
        bits = np.random.default_rng(4).integers(0, 2, 1000, dtype=np.uint8)
        symbols = c.modulate(bits, 'qpsk')[0]
        imported = recording(symbols, rate=2400000)
        result, ctx, built = replay(imported['program'])
        np.testing.assert_array_equal(ctx.values[built['program']['blocks'][-1]['id']], bits)
        self.assertEqual(result['metrics']['received_bits'], 1000)
        self.assertEqual(result['advanced']['sample_rate'], 2400000)
        self.assertEqual(ctx.observations[0]['sample_rate'], 2400000)
        self.assertEqual(result['sink']['count'], 1000)
        self.assertEqual(len(result['sink']['values']), 256)
        self.assertEqual(result['plan'][-1]['count'], 1000)

    def test_sigmf_export_import_roundtrip_and_hash(self):
        source = recording(np.tile([.5+.5j, -.5-.5j], 25))
        result, ctx, built = replay(source['program'])
        first = built['program']['blocks'][0]['id']
        exported = iq.export_recording(ctx.values[first], 192000, built['program'], first, '复符号')
        self.assertEqual(exported['count'], 50)
        archive = base64.b64decode(exported['data'])
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as handle:
            data = handle.extractfile('recording.sigmf-data').read()
            meta = json.load(handle.extractfile('recording.sigmf-meta'))
        self.assertEqual(len(data), 50 * 8)
        self.assertEqual(meta['global']['core:sha512'], hashlib.sha512(data).hexdigest())
        self.assertEqual(meta['captures'][0]['core:frequency'], 915000000)
        restored = iq.import_recording(exported['data'], name='recording.sigmf')
        np.testing.assert_array_equal(iq.samples(restored['program']['blocks'][0]['params']), ctx.values[first])
        receiver = meta['global']['randomsign:receiver']
        self.assertEqual(receiver['payload_symbols'], 50)
        self.assertNotIn('bits', receiver); self.assertNotIn('reference', receiver)

    def test_rrc_channel_and_matched_capture_restore_payload(self):
        p = c.preset(['random_bits','mod_qpsk','tx_rrc','ideal','rx_matched','rx_timing','demod_qpsk','sink'],
                    {0: {'count': 1024}, 2: {'sps': 8, 'span': 8}})
        result, ctx, built = replay(p)
        expected = ctx.values['block-7']
        for point in ('block-3','block-4'):
            with self.subTest(point=point):
                observation = next(o for o in ctx.observations if o['id'] == point)
                exported = iq.export_recording(ctx.values[point], observation['sample_rate'], built['program'], point, observation['domain'])
                restored = iq.import_recording(exported['data'], name='rrc.sigmf')
                received, observed, rb = replay(restored['program'])
                np.testing.assert_array_equal(observed.values[rb['program']['blocks'][-1]['id']], expected)
                self.assertEqual(received['plan'][-1]['count'], 1024)
                self.assertEqual(sum(b['kind']=='rx_matched' for b in rb['program']['blocks']), int(point=='block-3'))

    def test_framed_rrc_capture_uses_public_training_and_length(self):
        p = c.preset(['random_bits','mod_qpsk','tx_frame','tx_rrc','ideal','rx_matched','rx_timing','rx_frame','demod_qpsk','sink'],
                    {0: {'count': 510}, 2: {'length': 128}})
        _, ctx, built = replay(p)
        observation = next(o for o in ctx.observations if o['id']=='block-4')
        exported = iq.export_recording(ctx.values['block-4'], observation['sample_rate'], built['program'], 'block-4', observation['domain'])
        restored = iq.import_recording(exported['data'], name='rrc.sigmf')
        result, received, rb = replay(restored['program'])
        np.testing.assert_array_equal(received.values[rb['program']['blocks'][-1]['id']], ctx.values['block-9'])
        self.assertTrue(result['advanced']['recovery']['frame']['detected'])
        self.assertEqual(result['metrics']['received_bits'], 510)

    def test_ofdm_capture_discards_only_public_padding(self):
        p = c.preset(['random_bits','mod_qpsk','tx_ofdm','ideal','rx_ofdm','demod_qpsk','sink'],
                    {0: {'count': 534}, 2: {'nfft': 64, 'cp': 8, 'active_count': 48, 'pilot_interval': 4}})
        _, ctx, built = replay(p)
        observation = next(o for o in ctx.observations if o['id']=='block-3')
        exported = iq.export_recording(ctx.values['block-3'], observation['sample_rate'], built['program'], 'block-3', observation['domain'])
        restored = iq.import_recording(exported['data'], name='ofdm.sigmf')
        result, received, rb = replay(restored['program'])
        np.testing.assert_array_equal(received.values[rb['program']['blocks'][-1]['id']], ctx.values['block-6'])
        self.assertEqual(result['metrics']['received_bits'], 534)
        self.assertEqual(result['plan'][-1]['count'], 534)

    def test_raw_frame_recovers_every_payload_symbol_after_delay(self):
        bits = np.random.default_rng(11).integers(0, 2, 254, dtype=np.uint8)
        symbols = c.modulate(bits, 'qpsk')[0]
        wave = np.r_[np.zeros(13), dsp.public_preamble(64, 'qpsk'), symbols] * np.exp(.4j) * 1.3
        imported = recording(wave, {'framed': True, 'preamble_length': 64})
        result, ctx, built = replay(imported['program'])
        np.testing.assert_array_equal(ctx.values[built['program']['blocks'][-1]['id']], bits)
        self.assertEqual(result['advanced']['recovery']['frame']['start_symbol'], 13)
        self.assertEqual(result['metrics']['received_bits'], 254)

    def test_public_training_remains_available_to_equalizer_and_noise_estimator(self):
        bits=np.random.default_rng(48).integers(0,2,512,dtype=np.uint8)
        wave=np.r_[dsp.public_preamble(128,'qpsk'),c.modulate(bits,'qpsk')[0]]
        imported=recording(wave,{'framed':True,'preamble_length':128})
        p=c.preset(['iq_source','rx_frame','rx_equalizer','rx_noise_estimate','demod_qpsk','sink'],
                   {0:imported['program']['blocks'][0]['params']})
        result,ctx,built=replay(p)
        np.testing.assert_array_equal(ctx.values[built['program']['blocks'][-1]['id']],bits)
        self.assertEqual(result['advanced']['recovery']['equalizer']['training_symbols'],128)
        self.assertEqual(result['metrics']['received_bits'],512)

    def test_legacy_qpsk_observation_domain_exports_to_symbol_recording(self):
        p=c.preset(['random_bits','mod_qpsk','ideal','demod_qpsk','sink'],{0:{'count':256}})
        _,ctx,built=replay(p);observation=ctx.observations[1]
        exported=iq.export_recording(ctx.values[observation['id']],observation['sample_rate'],built['program'],observation['id'],observation['domain'])
        self.assertEqual(exported['metadata']['global']['randomsign:receiver']['mode'],0)
        imported=iq.import_recording(exported['data'],name='symbols.sigmf')
        _,rx,rb=replay(imported['program'])
        np.testing.assert_array_equal(rx.values[rb['program']['blocks'][-1]['id']],ctx.values['block-4'])

    def test_iq_has_no_transmitter_reference_or_fabricated_error_rate(self):
        imported = recording(np.random.default_rng(12).normal(size=100) + 1j*np.random.default_rng(13).normal(size=100))
        for seed in (1, 1234):
            p = copy.deepcopy(imported['program']); p['seed'] = seed
            result, _, _ = replay(p)
            self.assertEqual(result['metrics']['bit_count'], 0)
            for metric in ('ber','ser','fer','evm_percent','rmse'):
                self.assertIsNone(result['metrics'][metric])
            self.assertEqual(result['sink']['reference'], [])
            if seed == 1: first = result['sink']['values']
            else: self.assertEqual(first, result['sink']['values'])

    def test_bad_metadata_raw_data_and_incomplete_recordings(self):
        data = iq.encoded(np.ones(32, dtype=complex))
        invalid = [({}, 'global'), ({'global': {'core:datatype':'cf32_le','core:sample_rate':0}}, '采样率'),
                   ({'global': {'core:datatype':'cf32_le','core:sample_rate':8000,'randomsign:receiver':{'scheme':100}}}, '可选范围'),
                   ({'global': {'core:datatype':'cf32_le','core:sample_rate':8000,'core:sha512':'wrong'}}, 'SHA-512'),
                   ({'global': {'core:datatype':'cf32_le','core:sample_rate':8000,'randomsign:receiver':{'payload_symbols':100}}}, '超过录波')]
        for metadata, message in invalid:
            with self.subTest(metadata=metadata), self.assertRaisesRegex(ValueError, message):
                iq.import_recording(data, metadata)
        for value in ('bad-base64!', base64.b64encode(b'123').decode(), iq.encoded([complex(float('nan'),0)])):
            with self.assertRaises(ValueError): iq.import_recording(value)
        with self.assertRaises(ValueError): iq.import_recording(data, name='corrupt.sigmf')
        q = {'mode':2, 'nfft':64, 'cp':16, 'payload_symbols':1000}
        wave, _ = dsp.ofdm_modulate(np.ones(30), q)
        imported = recording(wave, q)
        with self.assertRaisesRegex(ValueError, '完整 OFDM'):
            replay(imported['program'])

    def test_export_checks_domain_shape_and_preserves_source_metadata(self):
        imported = recording(np.ones(32,dtype=complex)); program = imported['program']; first=program['blocks'][0]['id']
        for values, domain in ((np.ones((32,2)), '复符号'), (np.ones(32),'比特'), (np.array([np.nan]),'复符号')):
            with self.assertRaises(ValueError): iq.export_recording(values,8000,program,first,domain)
        with self.assertRaises(ValueError): iq.export_recording(np.ones(32),8000,program,'missing','复符号')


if __name__ == '__main__':
    unittest.main()
