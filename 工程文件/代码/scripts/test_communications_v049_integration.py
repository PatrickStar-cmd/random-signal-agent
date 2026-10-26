"""v0.4.9 acceptance across the real catalog, receiver completion and reports."""
import copy
import io
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from pypdf import PdfReader
import numpy as np
import server
from src import communications as c, communication_studio as studio
from src import communication_report as report, communication_experiments as experiments
from src import communication_receiver_v049 as receiver, communication_array_v049 as array
from src import communication_waveform_v049 as wave, communication_polar as polar
from src import communication_runtime as runtime, communication_iq as iq
from src.communication_protocols import protocol,run_packet
from src.communication_report_materials import materials


class IntegrationTests(unittest.TestCase):
    def test_complete_new_transmitters_from_open_chain(self):
        for kind in ('tx_array','tx_mrt','tx_svd'):
            with self.subTest(kind=kind):
                p=c.preset(['random_bits','mod_qpsk',kind,'sink'])
                built=c.build(studio.complete_receiver(p))
                result=c.run(built['program'],built['token'])
                self.assertEqual(result['metrics']['bit_count'],512)

    def test_new_presets_build_run_and_complete_receiver(self):
        for extension in (receiver,array,wave,polar):
            for name in extension.presets(c.preset):
                with self.subTest(name=name):
                    built=c.build(c.PRESETS[name]['program'])
                    result=c.run(built['program'],built['token'])
                    self.assertEqual(result['sink']['count'],result['metrics']['bit_count'])
                    self.assertGreater(result['metrics']['bit_count'],0)
                    self.assertTrue(np.isfinite(result['metrics']['ber']))
                    c.build(studio.complete_receiver(built['program']))
                    ports=studio.describe(built['program'])['ports']
                    self.assertTrue(all(p['compatible'] for p in ports),[(p['id'],p['input'],p['accepts']) for p in ports if not p['compatible']])

    def test_soft_mimo_actual_chain_harq(self):
        p=copy.deepcopy(c.PRESETS['receiver_soft_ldpc']['program'])
        result=protocol(p,{'phy':'program','mode':'harq','packets':2,'packet_bytes':8,'max_retries':1,'feedback_loss':0})
        self.assertTrue(result['complete'])
        self.assertTrue(all('rx_mimo_soft' in row['executed_kinds'] for row in result['events']))
        self.assertGreater(result['metrics']['goodput_bps'],0)

    def test_hard_receiver_preserves_public_noise_estimate(self):
        p=c.preset(['random_bits','mod_qpsk','tx_frame','awgn','rx_frame','rx_noise_estimate','demod_qpsk','sink'])
        _,rx,_=run_packet(p,{'wire':np.zeros(64,np.uint8)},42,None,{})
        self.assertEqual(rx.method,'接收有效噪声估计')

    def test_iq_report_summarizes_received_data(self):
        p=c.PRESETS['iq_replay']['program'];b=c.build(p);r=c.run(p,b['token'])
        doc={'document_schema':2,'name':'I/Q 录波报告','program':p,'result':r}
        self.assertIn('录波接收',report.facts(doc)['summary'][0])
        self.assertTrue(report.render(doc).startswith(b'%PDF'))

    def test_report_ber_material_uses_measured_bits(self):
        replay=c.PRESETS['iq_replay']['program']
        iq_batch=experiments.batch([replay],{'seeds':[42],'frames':1})
        self.assertNotIn('batch-ber',[m['id'] for m in materials({'experiments':{'batchResult':iq_batch}})])
        mixed=experiments.batch([replay,c.PRESETS['text']['program']],{'seeds':[42],'frames':1})
        item=next(m for m in materials({'experiments':{'batchResult':mixed}}) if m['id']=='batch-ber')
        self.assertEqual(item['series'][0]['x'],[2])
        self.assertEqual(item['series'][0]['y'],[mixed['summaries'][1]['ber']])
        self.assertEqual(item['series'][0]['interval'],[mixed['summaries'][1]['ber_interval']])

    def test_iq_recording_burst_sync_replay(self):
        p=copy.deepcopy(c.PRESETS['burst_zadoff_chu']['program'])
        next(b for b in p['blocks'] if b['kind']=='burst_clock')['params'].update(ppm=100,hz=23)
        built=c.build(p);result,ctx=runtime.observe_run(p,built['token'],retain=True)
        payload_id=next(b['id'] for b in p['blocks'] if b['kind']=='tx_ofdm')
        channel_id=next(b['id'] for b in p['blocks'] if b['kind']=='complex_awgn')
        template=next(b['params'] for b in p['blocks'] if b['kind']=='tx_ofdm')
        replay=c.preset(['iq_source','rx_burst_sync','rx_ofdm','demod_qpsk','sink'])
        source=replay['blocks'][0]['params'];source.update(template,mode=2,data=iq.encoded(ctx.values[channel_id]),rate_hz=p['symbol_rate']*template['nfft'],scheme=1,payload_symbols=result['metrics']['symbol_count'])
        replay['blocks'][1]['params'].update(method=1,payload_samples=len(ctx.values[payload_id]))
        rb=c.build(replay);received=c.run(rb['program'],rb['token'])
        self.assertEqual(received['sink']['values'],result['sink']['values'][:received['sink']['plot_count']])
        self.assertLess(abs(received['advanced']['recovery']['burst_sync']['clock_ppm']-100),40)

    def test_report_selected_figures_pdf_and_http(self):
        p=c.PRESETS['ofdma_queue']['program']
        built=c.build(p);result=c.run(p,built['token'])
        doc={'document_schema':2,'name':'通信实验分析','program':p,'result':result,
             'experiments':{'batchResult':experiments.batch([c.PRESETS['text']['program']],{'seeds':[42,43],'frames':1})}}
        facts=report.facts(doc);ids=[item['id'] for item in facts['materials']]
        queue=next(key for key in ids if key.endswith('-queues'))
        doc['report']={'materials':['batch-ber',queue],'captions':{queue:'观察用户队列随时隙变化。'},'conclusion':'本次实验比较了误码和排队过程。'}
        pdf=report.render(doc);text=''.join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
        self.assertIn('观察用户队列',text);self.assertIn('本次实验比较',text);self.assertIn('批量实验 BER',text)
        self.assertEqual([v['id'] for v in report.facts(doc)['selected_materials']],['batch-ber',queue])
        with tempfile.TemporaryDirectory() as folder:
            with TestClient(server.create_app(data_dir=Path(folder)/'data',upload_dir=Path(folder)/'uploads',output_dir=Path(folder)/'outputs')) as client:
                response=client.post('/api/communications/report-preview',json={'document':doc})
                self.assertEqual(response.status_code,200,response.text[:300]);self.assertEqual(len(response.json()['selected_materials']),2)


if __name__=='__main__':unittest.main()
