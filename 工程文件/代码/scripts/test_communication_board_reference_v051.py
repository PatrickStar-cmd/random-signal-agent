"""Desktop reference vectors used by the exported RP2040 teaching experiments."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import communications as c, communication_studio as studio
from src import communication_runtime as runtime


def observe(program):
    return runtime.observe_run(program, c.build(program)['token'], retain=True)


class BoardReferenceTests(unittest.TestCase):
    def test_utf8_and_several_text_sources_use_msb_first(self):
        for sources in (['你好，Pico'], ['测', '🐳abc']):
            kinds = ['text'] * len(sources) + ['uart_loopback', 'sink']
            program = c.preset(kinds, {i: {'text': s} for i, s in enumerate(sources)})
            result, ctx = observe(program)
            message = ''.join(sources)
            self.assertEqual(result['text'], {'sent': message, 'received': message})
            self.assertEqual(result['uart']['packed_bytes'], list(message.encode()))
            for block, source in zip(program['blocks'], sources):
                expected = np.unpackbits(np.frombuffer(source.encode(), dtype=np.uint8))
                np.testing.assert_array_equal(ctx.values[block['id']], expected)

    def test_three_pn_polynomials_over_uart(self):
        for degree, tap in ((7, 1), (9, 4), (15, 1)):
            for initial in (1, 2 ** degree - 2):
                program = c.preset(['pn_bits', 'uart_loopback', 'sink'],
                                   {0: {'count': 127, 'degree': degree, 'initial': initial}})
                expected = [(initial >> i) & 1 for i in range(degree)]
                for i in range(127 - degree):
                    expected.append(expected[i] ^ expected[i + tap])
                result, ctx = observe(program)
                self.assertEqual(result['sink']['values'], expected)
                self.assertEqual(result['uart']['valid_bits'], 127)
                self.assertEqual(len(ctx.values['block-1']), 127)
        with self.assertRaisesRegex(ValueError, 'LFSR'):
            c.build(c.preset(['pn_bits', 'uart_loopback', 'sink'], {0: {'initial': 128}}))

    def test_hamming_all_positions_and_tail_padding(self):
        kinds = ['bit_pattern', 'hamming_encode', 'uart_loopback', 'bit_flip', 'hamming_decode', 'sink']
        for position in range(1, 8):
            program = c.preset(kinds, {0: {'pattern': '10111'}, 3: {'codeword': 2, 'position': position}})
            result, ctx = observe(program)
            raw = ctx.values['block-2']
            flipped = ctx.values['block-3']
            self.assertEqual(raw[:7].tolist(), [0, 1, 1, 0, 0, 1, 1])
            self.assertEqual(np.flatnonzero(flipped != raw).tolist(), [7 + position - 1])
            self.assertEqual(result['node_details']['block-4'], {'syndromes': [0, position], 'valid_bits': 5})
            self.assertEqual(result['metrics']['coded_bit_errors'], 0)  # physical reference, before injection
            self.assertEqual(result['metrics']['hamming_syndromes'], 1)
            self.assertEqual(result['sink']['values'], [1, 0, 1, 1, 1])
        with self.assertRaisesRegex(ValueError, '码字号'):
            c.build(c.preset(kinds, {0: {'pattern': '1011'}, 3: {'codeword': 2}}))
        for kinds in (['bit_pattern', 'hamming_encode', 'bit_flip', 'uart_loopback', 'hamming_decode', 'sink'],
                      ['bit_pattern', 'uart_loopback', 'bit_flip', 'sink']):
            with self.assertRaisesRegex(ValueError, 'Hamming'):
                c.build(c.preset(kinds))

    def test_qpsk_gray_quadrants_and_odd_payload(self):
        program = c.preset(['bit_pattern', 'mod_qpsk', 'ideal', 'demod_qpsk', 'sink'], {0: {'pattern': '000111101'}})
        result, ctx = observe(program)
        expected = np.array([1 + 1j, 1 - 1j, -1 - 1j, -1 + 1j, -1 + 1j]) / np.sqrt(2)
        np.testing.assert_allclose(ctx.values['block-1'], expected)
        self.assertEqual(result['sink']['values'], [0, 0, 0, 1, 1, 1, 1, 0, 1])

    def test_fault_placement_with_mapped_sources_and_nested_codes(self):
        for source, mod in [('bit_pattern', 'bpsk'), ('pn_bits', 'qpsk'), ('bit_pattern', 'pam')]:
            kinds = [source, 'hamming_encode', 'repeat_encode', 'mod_' + mod, 'ideal',
                     'demod_' + mod, 'repeat_decode', 'bit_flip', 'hamming_decode', 'sink']
            p = c.preset(kinds, {0: {'count': 15} if source == 'pn_bits' else {'pattern': '10111'}})
            restored = studio.complete_receiver(p)
            self.assertEqual([b['kind'] for b in restored['blocks']], kinds)
            result, _ = observe(restored)
            self.assertEqual(result['metrics']['ber'], 0)
            self.assertEqual(result['node_details']['block-8']['syndromes'][0], 5)


if __name__ == '__main__':
    unittest.main()
