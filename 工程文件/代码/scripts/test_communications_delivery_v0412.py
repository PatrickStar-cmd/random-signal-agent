"""Executable course, measured records, report and portable archive acceptance."""
import base64
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import communication_delivery_v0412 as delivery, communication_workbench_v0412 as workbench
from src import communication_report as report, communication_report_materials as materials


ROOT = Path(__file__).resolve().parents[1]


def measured(key):
    doc = delivery.course(key)['document']
    result = workbench.run_document(doc)
    doc['result'] = result['result']
    doc['workbenchResult'] = result
    if result['graph_result']: doc['graphResult'] = result['graph_result']
    return doc, result


class DeliveryTests(unittest.TestCase):
    def test_twelve_courses_execute_three_seeds_and_real_acceptance(self):
        self.assertEqual(len(delivery.courses()), 12)
        for summary in delivery.courses():
            with self.subTest(course=summary['id']):
                value = delivery.course(summary['id']); lesson = value['lesson']
                for key in ('objective', 'prediction', 'steps', 'observations', 'conclusion', 'challenge'):
                    self.assertTrue(lesson[key])
                result = workbench.run_task(value['document'], {'mode': 'classroom', 'seeds': lesson['seeds'], 'frames': 1})
                self.assertTrue(result['complete']); self.assertEqual(result['completed'], 3)
                self.assertTrue(result['passed'])
                self.assertEqual([r['seed'] for r in result['rows']], lesson['seeds'])
                for row in result['rows']:
                    check = row['tools'][0]
                    self.assertEqual(check['value'], row['metrics'][lesson['metric']])
                    self.assertTrue(check['passed'])

    def test_record_is_independent_and_does_not_embed_record_history(self):
        doc, _ = measured('digital'); doc['delivery']['records'] = [{'old': True}]
        baseline = delivery.record(doc, '原始基线')
        restored = delivery.restore_record(baseline)['document']
        doc['program']['blocks'][0]['params']['count'] = 2048
        self.assertNotEqual(doc['program'], restored['program'])
        self.assertNotIn('records', restored['delivery'])
        self.assertEqual(baseline['metrics']['ber'], doc['result']['metrics']['ber'])
        self.assertNotEqual(delivery.record(restored, '原始基线')['id'], baseline['id'])
        actual = copy.deepcopy(restored); actual['program']['seed'] += 3
        value = workbench.run_document(actual)
        actual['result'] = value['result']; actual['workbenchResult'] = value
        actual['program']['seed'] -= 3; actual['result']['experience']['frame'] = 3
        saved = delivery.record(actual, '连续第 4 帧')
        self.assertEqual(saved['seed'], value['seed'])
        rerun = workbench.run_document(delivery.restore_record(saved)['document'])
        self.assertEqual(rerun['metrics'], value['metrics'])

    def test_eight_complete_sensing_records_fit_project_storage(self):
        from src import communication_studio as studio
        doc, _ = measured('sensing')
        doc['workbenchResult'] = {k:v for k,v in doc['workbenchResult'].items() if k not in ('result','graph_result')}
        for number in range(8): doc['delivery']['records'].append(delivery.record(doc, '通感基线 ' + str(number)))
        self.assertEqual(len(studio.validate_document(doc)['delivery']['records']), 8)
        restored = delivery.restore_record(doc['delivery']['records'][-1])['document']
        self.assertEqual(restored['graph'], doc['graph'])
        self.assertEqual(workbench.run_document(restored)['graph_result']['merged_result']['metrics'],doc['result']['metrics'])

    def test_graph_parameter_connection_and_metric_diff(self):
        before, _ = measured('branches'); after = copy.deepcopy(before)
        block = after['graph']['branches'][1]['blocks'][1]
        block['params']['step_size'] = .08
        value = workbench.run_document(after); after['graphResult'] = value['graph_result']; after['result'] = value['result']
        delta = delivery.compare(delivery.record(before, '基线'), after)
        self.assertEqual(len(delta['parameters']), 1)
        self.assertEqual(delta['parameters'][0]['path'], 'rx2/' + block['id'] + '.step_size')
        self.assertEqual(delta['connections'], {'added': [], 'removed': []})
        self.assertEqual(next(m for m in delta['metrics'] if m['metric'] == 'ber')['difference'],
                         after['result']['metrics']['ber'] - before['result']['metrics']['ber'])
        after['graph']['edges'].pop()
        self.assertEqual(len(delivery.compare(before, after)['connections']['removed']), 1)

    def test_report_cfar_materials_use_measured_grids_and_requested_order(self):
        doc, _ = measured('sensing'); analysis = doc['graphResult']['analyses'][0]
        raw = materials.materials(doc); cfar = [v for v in raw if v['id'].startswith('cfar-')]
        self.assertEqual(len(cfar), 3)
        self.assertEqual(cfar[0]['heatmap']['markers'], analysis['detections'])
        self.assertEqual(cfar[1]['heatmap']['valid_region'], analysis['valid_region'])
        self.assertEqual(len(cfar[0]['heatmap']['values']), len(analysis['power']))
        selected = [cfar[2]['id'], 'graph-branches', cfar[0]['id']]
        doc['report'] = {'materials': selected, 'captions': {selected[0]: '保存的图注'}, 'conclusion': '课程实测结论'}
        doc['delivery']['answers']['prediction'] = '提高门限后检测峰将减少。'
        doc['delivery']['courseResult'] = workbench.run_task(doc, {'mode': 'classroom', 'seeds': [42], 'frames': 1})
        _, figures, _ = materials.prepare(doc)
        self.assertEqual([v['id'] for v in figures], selected)
        self.assertEqual(figures[0]['caption'], '保存的图注')
        pdf = report.render(doc)
        self.assertTrue(pdf.startswith(b'%PDF'))
        from pypdf import PdfReader
        text = '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
        self.assertIn('CA-CFAR', text); self.assertIn('课程实测结论', text)
        self.assertIn('课程验收：通过', text); self.assertIn('提高门限后检测峰将减少', text)

    def test_bundle_manifest_inputs_and_import_roundtrip(self):
        doc, result = measured('iq'); archive = delivery.bundle(doc)
        restored = delivery.import_bundle(archive)
        self.assertEqual(restored['document'], doc)
        self.assertEqual(restored['manifest']['input_hash'], result['input_hash'])
        self.assertEqual(restored['manifest']['input_scope'], 'source')
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            self.assertTrue(any(name.startswith('inputs/') and name.endswith('.bin') for name in package.namelist()))
            self.assertEqual(json.loads(package.read('result.json')), result['result'])
            self.assertIn('report.pdf', restored['manifest']['files'])
            self.assertTrue(package.read('metrics.csv').startswith(b'\xef\xbb\xbf'))
        rerun = workbench.run_document(restored['document'])
        self.assertEqual(rerun['result']['metrics'], result['result']['metrics'])
        encoded = delivery.export_bundle(doc)
        self.assertEqual(delivery.import_bundle(encoded['data'])['document'], doc)

    def test_bundle_tampering_is_reported(self):
        doc, _ = measured('digital')
        with zipfile.ZipFile(io.BytesIO(delivery.bundle(doc))) as original:
            files = {name: original.read(name) for name in original.namelist()}
        files['document.json'] += b' '
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as bad:
            for name, data in files.items(): bad.writestr(name, data)
        with self.assertRaisesRegex(ValueError, '校验失败'): delivery.import_bundle(buffer.getvalue())

    def test_exported_python_runs_in_an_independent_directory(self):
        doc, expected = measured('branches')
        debug = ROOT / 'debug/v0412-delivery'; debug.mkdir(parents=True, exist_ok=True)
        (debug / 'note.md').write_text('v0.4.12 课程、成果包及独立 Python 复现验收。\n', encoding='utf-8')
        with tempfile.TemporaryDirectory(dir=debug) as name:
            folder = Path(name)
            with zipfile.ZipFile(io.BytesIO(delivery.bundle(doc))) as package: package.extractall(folder)
            process = subprocess.run([sys.executable, str(folder / 'reproduce.py'), '--runtime', str(ROOT)],
                                     cwd=folder, capture_output=True, text=True, encoding='utf-8',
                                     env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, timeout=90)
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads((folder / 'reproduced-result.json').read_text(encoding='utf-8'))
            self.assertEqual(result['metrics'], expected['metrics'])
            self.assertEqual(result['graph_result']['input_hash'], expected['graph_result']['input_hash'])
            self.assertEqual(result['tools'], expected['tools'])


if __name__ == '__main__': unittest.main()
