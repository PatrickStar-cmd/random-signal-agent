"""Export actual stage samples, import SigMF and replay the remaining receiver."""
from pathlib import Path
import copy
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src import communications as c, communication_iq as iq, communication_runtime as runtime
from src import communication_studio as studio


def observed(p):
    b=c.build(p);r,ctx=runtime.observe_run(b['program'],b['token'],retain=True);return b,r,ctx


def restore(b,ctx,point):
    observation=next(o for o in ctx.observations if o['id']==point)
    archive=iq.export_recording(ctx.values[point],observation['sample_rate'],b['program'],point,observation['domain'])
    return archive,iq.import_recording(archive['data'],name='capture.sigmf')['program']


class WaveformRecordingTests(unittest.TestCase):
    def test_scfdma_partial_dft_group_replays_from_each_processing_boundary(self):
        for preset in ('scfdma_localized','scfdma_interleaved','ofdm_unspread_reference'):
            p=copy.deepcopy(c.PRESETS[preset]['program']);p['blocks'][0]['params']['count']=514
            b,r,ctx=observed(p);expected=ctx.values[b['program']['blocks'][-1]['id']]
            for block in b['program']['blocks']:
                if block['kind'] not in ('tx_dft_spread','tx_scfdma','complex_awgn','rx_scfdma','rx_dft_despread'):continue
                with self.subTest(preset=preset,stage=block['kind']):
                    archive,restored=restore(b,ctx,block['id']);rb,rr,rx=observed(restored)
                    np.testing.assert_array_equal(rx.values[rb['program']['blocks'][-1]['id']],expected)
                    self.assertEqual(rr['metrics']['received_bits'],514)
                    self.assertEqual(rr['plan'][-1]['count'],514)
                    q=archive['metadata']['global']['randomsign:receiver']
                    self.assertEqual(q['dft_spread'],preset!='ofdm_unspread_reference' and block['kind']!='rx_dft_despread')
                    self.assertEqual(q['ofdm_format'],int(block['kind'] in ('tx_scfdma','complex_awgn')))

    def test_burst_metadata_captures_and_removes_only_pending_synchronization(self):
        for preset in ('burst_schmidl_cox','burst_zadoff_chu'):
            b,_,ctx=observed(c.PRESETS[preset]['program']);expected=ctx.values[b['program']['blocks'][-1]['id']]
            for block in b['program']['blocks']:
                if block['kind'] not in ('tx_ofdm','tx_burst_preamble','complex_awgn','rx_burst_sync','rx_ofdm'):continue
                with self.subTest(preset=preset,stage=block['kind']):
                    archive,restored=restore(b,ctx,block['id']);rb,rr,rx=observed(restored)
                    np.testing.assert_array_equal(rx.values[rb['program']['blocks'][-1]['id']],expected)
                    self.assertEqual(rr['plan'][-1]['count'],len(expected))
                    pending=block['kind'] in ('tx_burst_preamble','complex_awgn')
                    self.assertEqual(archive['metadata']['global']['randomsign:receiver']['burst_framed'],pending)
                    self.assertEqual(any(v['kind']=='rx_burst_sync' for v in restored['blocks']),pending)

    def test_short_burst_and_nondefault_capture_window_roundtrip(self):
        p=copy.deepcopy(c.PRESETS['burst_zadoff_chu']['program']);p['blocks'][0]['params']['count']=16
        p['blocks'][4]['params'].update(delay=900,ppm=-1500);p['blocks'][6]['params'].update(search=1200,max_ppm=2000)
        b,_,ctx=observed(p);archive,restored=restore(b,ctx,'block-5');rb,_,rx=observed(restored)
        np.testing.assert_array_equal(rx.values[rb['program']['blocks'][-1]['id']],ctx.values['block-9'])
        receiver=next(v for v in restored['blocks'] if v['kind']=='rx_burst_sync')
        self.assertEqual(receiver['params']['search'],1200);self.assertEqual(receiver['params']['max_ppm'],2000)

    def test_iq_receiver_completion_restores_new_formats_from_source(self):
        for preset in ('scfdma_interleaved','burst_zadoff_chu'):
            b,_,ctx=observed(c.PRESETS[preset]['program']);point=next(v['id'] for v in b['program']['blocks'] if v['kind']=='complex_awgn')
            _,restored=restore(b,ctx,point);draft=copy.deepcopy(restored);draft['blocks']=[draft['blocks'][0],draft['blocks'][-1]]
            complete=studio.complete_iq_receiver(draft);rb,_,rx=observed(complete)
            np.testing.assert_array_equal(rx.values[rb['program']['blocks'][-1]['id']],ctx.values[b['program']['blocks'][-1]['id']])
            self.assertEqual([v['kind'] for v in complete['blocks']],[v['kind'] for v in restored['blocks']])

    def test_recording_export_after_scfdma_receive_preserves_remaining_idft(self):
        b,_,ctx=observed(c.PRESETS['scfdma_localized']['program']);_,restored=restore(b,ctx,'block-4')
        rb,_,rx=observed(restored);point=next(v['id'] for v in rb['program']['blocks'] if v['kind']=='rx_scfdma')
        archive,next_program=restore(rb,rx,point);nb,_,nctx=observed(next_program)
        self.assertEqual(archive['metadata']['global']['randomsign:receiver']['mode'],0)
        self.assertEqual([v['kind'] for v in next_program['blocks']],['iq_source','rx_dft_despread','demod_qpsk','sink'])
        np.testing.assert_array_equal(nctx.values[nb['program']['blocks'][-1]['id']],ctx.values['block-8'])

    def test_completion_pairs_an_existing_default_sync_block_with_capture(self):
        b,_,ctx=observed(c.PRESETS['burst_zadoff_chu']['program']);_,restored=restore(b,ctx,'block-5')
        sync=next(v for v in restored['blocks'] if v['kind']=='rx_burst_sync')
        sync['params']={key:spec['default'] for key,spec in c.BLOCKS['rx_burst_sync']['params'].items()}
        complete=studio.complete_iq_receiver(restored);rb,_,rx=observed(complete)
        np.testing.assert_array_equal(rx.values[rb['program']['blocks'][-1]['id']],ctx.values['block-9'])


if __name__=='__main__':unittest.main()
