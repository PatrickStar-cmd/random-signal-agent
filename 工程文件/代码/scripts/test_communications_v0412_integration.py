"""HTTP and background-job acceptance for the final workbench."""
import base64
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src import communication_graph_v0411 as graph
from src import communication_workbench_v0412 as wb
from src.communication_jobs import Jobs


class WorkbenchIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.jobs=Jobs(self.tmp.name,threading.BoundedSemaphore(2))
        self.doc={'document_schema':2,'name':'分支验收','graph':graph.demo(),
                  'tools':[{'id':'check','kind':'assertion','metric':'merged.ber','operator':'<=','value':.1}]}
        self.built=wb.build_document(self.doc)

    def tearDown(self):
        for job in self.jobs.jobs.values():
            job.cancel.set()
            with job.condition: job.condition.notify_all()
        self.jobs.executor.shutdown(wait=True)
        self.tmp.cleanup()

    def wait(self,key,statuses=('completed','failed','cancelled')):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            value=self.jobs.status('acceptance',key)
            if value['status'] in statuses:return value
            time.sleep(.02)
        self.fail('job timed out')

    def start(self,kind,**kw):
        return self.jobs.start('acceptance',kind,{'document':self.doc,'token':self.built['token'],**kw})['id']

    def test_run_and_scoped_windows_match_full_graph(self):
        key=self.start('workbench-run');value=self.wait(key)
        self.assertEqual(value['status'],'completed',value.get('error'))
        result=value['result']; self.assertEqual(result['graph_result']['merged_result']['metrics'],result['result']['metrics'])
        sources=['shared/'+self.doc['graph']['prefix'][-1]['id'],
                 'rx1/'+self.doc['graph']['branches'][0]['blocks'][-1]['id'],
                 'rx2/'+self.doc['graph']['branches'][1]['blocks'][-1]['id'],'merge']
        for source in sources:
            window=self.jobs.window('acceptance',key,source,0,16)
            self.assertEqual(len(window['i']),16)
        with self.assertRaises(KeyError): self.jobs.window('other',key,sources[0],0,16)

    def test_debug_stops_at_merge_and_finishes_same_result(self):
        key=self.start('workbench-debug',debug_mode='continue',breakpoints=[{'block_id':'merge','metric':'always'}])
        paused=self.wait(key,('paused','failed'))
        self.assertEqual(paused['status'],'paused',paused.get('error'))
        self.assertEqual(paused['progress']['breakpoint']['block_id'],'merge')
        self.jobs.control('acceptance',key,'continue')
        result=self.wait(key);self.assertEqual(result['status'],'completed',result.get('error'))
        direct=wb.run_document(self.doc)
        self.assertEqual(result['result']['result']['metrics'],direct['result']['metrics'])
        self.assertTrue(any(o['id'].startswith('rx2/') for o in result['observations']))

    def test_task_receipt_survives_new_manager(self):
        key=self.start('workbench-task',settings={'mode':'batch','seeds':[42],'frames':1})
        value=self.wait(key);self.assertEqual(value['status'],'completed',value.get('error'))
        other=Jobs(self.tmp.name,threading.BoundedSemaphore(1))
        try:
            restored=other.status('acceptance',key)
            self.assertEqual(restored['result']['rows'],value['result']['rows'])
        finally:other.executor.shutdown(wait=True)

    def test_http_build_course_bundle_and_restore(self):
        from fastapi.testclient import TestClient
        from server import create_app
        with TestClient(create_app(data_dir=Path(self.tmp.name)/'http')) as client:
            def post(action,**payload):
                response=client.post('/api/communications/'+action,json={'session_id':'acceptance',**payload})
                self.assertEqual(response.status_code,200,response.text[:300]);return response.json()
            result=post('workbench-build',document=self.doc)
            self.assertEqual(result['token'],self.built['token'])
            course=post('delivery-course',id=post('delivery-courses')['courses'][0]['id'])
            self.assertIn('program',course['document'])
            archive=post('delivery-export',document=self.doc)
            self.assertTrue(base64.b64decode(archive['data']).startswith(b'PK'))
            restored=post('delivery-import',data=archive['data'])
            self.assertEqual(wb.build_document(restored['document'])['token'],self.built['token'])
            record=post('delivery-record',document=restored['document'],name='保存完整分支')
            self.assertEqual(record['document_encoding'],'gzip-base64')
            restored_record=post('delivery-restore',record=record)['document']
            self.assertEqual(wb.build_document(restored_record)['token'],self.built['token'])
            task=wb.run_task(self.doc,{'mode':'batch','seeds':[52],'frames':1})
            document=post('workbench-restore',task=task,index=0)['document']
            self.assertEqual(document['graph']['globals']['seed'],52)


if __name__=='__main__':unittest.main()
