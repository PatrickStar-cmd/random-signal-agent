"""PDF acceptance: numerical evidence, privacy, stale previews and fonts."""
from pathlib import Path
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ['RS_AGENT_LLM_ENABLED']='0'
import numpy as np
from pypdf import PdfReader
from fastapi.testclient import TestClient
import server
from src import pdf_report as r, diagnostics
from src.dialogue_agent import ConversationState
from src.signal_processing import SignalConfig,generate_random_signal
from src.preprocessing import preprocess_signal,PreprocessConfig


def signal_state():
    s=ConversationState('report-test',bundle=generate_random_signal(SignalConfig(sample_rate=200,duration=8,seed=42,waveform='sine',noise_model='gaussian')))
    s.processed=preprocess_signal(s.bundle.observed,PreprocessConfig(sample_rate=200))
    return s


class ReportTests(unittest.TestCase):
    def pdf(self,state,options=None):
        facts=r.build(state,options);raw=r.render(facts);reader=PdfReader(io.BytesIO(raw))
        return facts,reader,'\n'.join(p.extract_text() for p in reader.pages)

    def test_numeric_evidence_and_natural_text(self):
        state=signal_state();facts,reader,text=self.pdf(state)
        self.assertAlmostEqual(facts['before']['rmse'],np.sqrt(np.mean((state.bundle.observed-state.bundle.clean)**2)))
        self.assertAlmostEqual(facts['after']['rms'],np.sqrt(np.mean(state.processed.signal**2)))
        self.assertEqual(facts['main_frequency_hz'],8)
        self.assertEqual(facts['parameters']['window'],7)
        lowpass=signal_state();lowpass.processed=preprocess_signal(lowpass.bundle.observed,PreprocessConfig(method='fft_lowpass',sample_rate=200,lowpass_cutoff_hz=25))
        self.assertEqual(r.build(lowpass)['parameters']['cutoff_hz'],25)
        self.assertIn('主要频率成分位于 8 Hz',text)
        self.assertIn('采样与处理参数',text)
        self.assertTrue(4<=len(reader.pages)<=7)

    def test_chinese_font_embedded_and_searchable(self):
        _,reader,text=self.pdf(signal_state(),{'title':'随机信号课程实验','author':'派大星'})
        self.assertIn('随机信号课程实验',text);self.assertIn('派大星',text)
        embedded=False
        for page in reader.pages:
            for ref in page['/Resources']['/Font'].values():
                font=ref.get_object();desc=font.get('/FontDescriptor')
                if desc and '/FontFile2' in desc.get_object():embedded=True
        self.assertTrue(embedded)

    def test_unreferenced_upload_never_claims_true_error(self):
        s=signal_state();s.bundle.has_clean_reference=False;s.bundle.source='uploaded.csv'
        facts,_,text=self.pdf(s)
        self.assertIsNone(facts['before']['snr_db']);self.assertIsNone(facts['after']['rmse'])
        self.assertIn('数据没有干净参考',text);self.assertNotIn('提高 ',text)
        self.assertEqual(facts['configuration'],{'sample_rate':200})

    def test_unprocessed_is_explicit(self):
        s=signal_state();s.processed=None;facts,_,text=self.pdf(s)
        self.assertIsNone(facts['after']);self.assertIn('尚未执行信号处理',text)

    def test_degraded_processing_reports_decrease(self):
        s=signal_state();s.processed.signal=s.bundle.observed*10
        facts=r.build(s);self.assertTrue(any('下降' in t for t in facts['summary']))

    def test_constant_and_zero_reference_do_not_invent_frequency_or_snr(self):
        s=signal_state();s.bundle.observed[:]=0;s.bundle.clean[:]=0;s.processed.signal[:]=0
        facts,_,text=self.pdf(s)
        self.assertIsNone(facts['main_frequency_hz']);self.assertIsNone(facts['before']['snr_db'])
        self.assertNotIn('correlation',facts['plots']);self.assertIn('自相关未定义',text)

    def test_short_and_nonuniform_signals_skip_invalid_frequency(self):
        for size in (1,3):
            s=signal_state();s.processed=None
            for key in ('time','clean','noise','observed','impulse_mask'):setattr(s.bundle,key,getattr(s.bundle,key)[:size])
            self.assertNotIn('spectrum',r.build(s)['plots'])
        s=signal_state();s.bundle.time[2]+=.1
        facts=r.build(s);self.assertFalse(facts['uniform']);self.assertNotIn('spectrum',facts['plots'])

    def test_blind_report_rejected_until_reveal(self):
        s=signal_state();diagnostics.inject(s,[{'kind':'narrowband','start':2,'end':3,'strength':1,'frequency':35}],blind=True);diagnostics.diagnose_state(s)
        with self.assertRaisesRegex(ValueError,'揭晓'):r.build(s)
        diagnostics.reveal(s);facts,_,text=self.pdf(s)
        self.assertIsNotNone(facts['diagnosis']);self.assertIn('异常诊断',text)
        heatmap=r.Heatmap(facts['diagnosis']['spectrogram'])
        self.assertGreaterEqual(heatmap.wrap(491,700)[1],175, 'Heatmap must reserve vertical space for all cells and axes')

    def test_no_chat_credentials_paths_or_state_mutation(self):
        s=signal_state();s.messages=[{'role':'user','content':'private-key-secret'}];s.last_uploaded_path='C:/private/path.csv'
        before=copy.deepcopy(s);facts,_,text=self.pdf(s)
        self.assertNotIn('private',json.dumps(facts)+text)
        np.testing.assert_array_equal(s.bundle.observed,before.bundle.observed);self.assertEqual(s.messages,before.messages)

    def test_long_and_markup_titles_are_plain_text(self):
        _,reader,text=self.pdf(signal_state(),{'title':'<实验> & '+('长标题'*30),'purpose':'验证目的。'*200})
        self.assertIn('<实验> &',text);self.assertLessEqual(len(reader.pages),r.CONFIG['max_pages'])
        for opts in ({'title':''},{'purpose':'x'*1201},{'unknown':True},{'edition':'fake'}):
            with self.assertRaises(ValueError):r.options(opts)

    def test_brief_two_pages_and_standard_has_more_detail(self):
        _,brief,text=self.pdf(signal_state(),{'edition':'brief'});_,standard,_=self.pdf(signal_state())
        self.assertEqual(len(brief.pages),2);self.assertGreater(len(standard.pages),len(brief.pages));self.assertNotIn('Welch',text)

    def test_maximum_input_has_bounded_charts(self):
        s=signal_state();s.bundle=generate_random_signal(SignalConfig(sample_rate=20000,duration=10));s.processed=None
        facts=r.build(s)
        self.assertEqual(facts['sample_count'],200000)
        self.assertLessEqual(len(facts['plots']['waveform']['x']),r.CONFIG['plot_points'])
        self.assertTrue(np.isfinite(facts['before']['rms']))

    def test_api_preview_download_and_stale_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            app=server.create_app(data_dir=Path(folder))
            with TestClient(app) as c:
                app.state.agent.sessions['report-test']=signal_state()
                payload={'session_id':'report-test','options':{'title':'HTTP实验'}}
                preview=c.post('/api/reports/preview',json=payload);self.assertEqual(preview.status_code,200,preview.text)
                token=preview.json()['token'];data=c.post('/api/reports/pdf',json={**payload,'token':token})
                self.assertEqual(data.status_code,200,data.text[:100]);self.assertTrue(data.content.startswith(b'%PDF'))
                self.assertIn('application/pdf',data.headers['content-type'])
                self.assertEqual(c.post('/api/reports/pdf',json={**payload,'options':{'title':'changed'},'token':token}).status_code,409)
                app.state.agent.sessions['report-test'].bundle.observed[0]+=1
                self.assertEqual(c.post('/api/reports/pdf',json={**payload,'token':token}).status_code,409)
                self.assertEqual(c.post('/api/reports/preview',json={'session_id':'empty'}).status_code,400)
                self.assertEqual(c.post('/api/reports/fake',json=payload).status_code,400)

    def test_render_capacity_is_bounded(self):
        facts=r.build(signal_state())
        with patch.object(r,'RENDER_LIMIT') as limiter:
            limiter.acquire.return_value=False
            with self.assertRaisesRegex(ValueError,'繁忙'):r.render(facts)


if __name__=='__main__':
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReportTests))
    folder=ROOT/'logs/pdf-report';folder.mkdir(parents=True,exist_ok=True);(folder/'latest.log').write_text(stream.getvalue(),encoding='utf-8')
    print(stream.getvalue());sys.exit(not result.wasSuccessful())
