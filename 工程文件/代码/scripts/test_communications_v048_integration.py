"""Exercise the public v0.4.8 APIs, owned jobs and saved project round trips."""
import base64
import copy
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['RS_AGENT_LLM_ENABLED']='0'
from fastapi.testclient import TestClient
import server
from src import communications as c


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.client=TestClient(server.create_app(data_dir=Path(self.temp.name)))
        self.client.__enter__()
        self.p=c.preset(['random_bits','mod_qpsk','awgn','demod_qpsk','sink'],{0:{'count':128},2:{'esn0_db':30}})

    def tearDown(self):
        self.client.__exit__(None,None,None);self.temp.cleanup()

    def request(self,action,**payload):
        r=self.client.post('/api/communications/'+action,json={'session_id':'v048-integration',**payload})
        self.assertEqual(r.status_code,200,r.text[:1200]);return r.json()

    def job(self,kind,**payload):
        if 'program' in payload:
            built=c.build(payload['program']);payload['token']=built['token']
        job=self.request('job-start',kind=kind,payload=payload)
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            state=self.request('job-status',id=job['id'])
            if state['status'] in ('completed','cancelled','failed'):
                self.assertEqual(state['status'],'completed',state.get('error'));return job['id'],state['result']
            time.sleep(.01)
        self.fail('job timeout')

    def test_subproject_creation_insertion_update_and_snapshot(self):
        d=self.request('subproject-create',program=self.p,block_ids=['block-1'],name='QPSK 映射')
        p=copy.deepcopy(self.p);p['blocks'].pop(1)
        inserted=self.request('subproject-insert',program=p,definition=d,index=1)
        self.assertEqual(c.build(inserted['program'])['plan'][1]['output'],'复基带符号')
        updated=self.request('subproject-update',**inserted,definition=d,parameters={})
        document={'document_schema':2,'name':'子工程接口测试','program':updated['program'],
                  'subprojects':{'definitions':[d],'instances':[updated['instance']]}}
        saved=self.request('project-save',document=document)
        loaded=self.request('project-load',id=saved['id'])
        self.assertEqual(loaded['document']['subprojects'],document['subprojects'])
        _,result=self.job('run',program=loaded['document']['program'])
        self.assertEqual(result['metrics']['bit_errors'],0)

    def test_classroom_batch_and_target_search_jobs(self):
        task={'title':'零误码传输','objective':'提高信噪比恢复比特','kind':'experiment','initial_program':self.p,
              'editable':['blocks.block-2.esn0_db'],'seeds':[3,4],
              'stages':[{'name':'接收完整','goals':[{'metric':'ber','operator':'<=','value':0}],'hint':'提高 SNR','weight':1}]}
        task=self.request('classroom-validate',task=task)
        _,checked=self.job('classroom',program=self.p,task=task,settings={})
        self.assertTrue(checked['passed']);self.assertEqual(checked['score'],100)
        _,batch=self.job('batch',programs=[self.p,self.p],settings={'seeds':[3,4],'frames':1,'names':['A','B']})
        self.assertTrue(batch['complete']);self.assertEqual(len(batch['rows']),4)
        _,search=self.job('target-search',program=self.p,settings={'block_id':'block-2','parameter':'esn0_db','start':10,'stop':20,'step':5,'target_ber':.1,'seeds':[3],'frames':1})
        self.assertTrue(search['complete']);self.assertIsNotNone(search['selected'])

    def test_sigmf_export_import_and_owned_capture(self):
        job,result=self.job('run',program=self.p)
        recording=self.request('iq-export',id=job,block_id='block-2')
        self.assertGreater(len(base64.b64decode(recording['data'])),1000)
        imported=self.request('iq-import',data=recording['data'],name='capture.sigmf')
        _,replayed=self.job('run',program=imported['program'])
        self.assertEqual(replayed['sink']['values'],result['sink']['reference'])
        self.assertIsNone(replayed['metrics']['ber'])
        denied=self.client.post('/api/communications/iq-export',json={'session_id':'other','id':job,'block_id':'block-2'})
        self.assertEqual(denied.status_code,404)

    def test_custom_phy_protocol_and_amc_jobs(self):
        _,result=self.job('protocol',program=self.p,settings={'phy':'program','packets':2,'packet_bytes':8,'feedback_loss':0,'max_retries':1})
        self.assertTrue(result['metrics']['complete_payload']);self.assertEqual(result['config']['phy'],'program')
        _,amc=self.job('amc',program=self.p,settings={'phy':'program','coding':'preserve','frames':3,'snr_start':24,'snr_stop':30,'packet_bytes':8,'noise_block_id':'block-2'})
        self.assertTrue(amc['complete']);self.assertEqual(amc['config']['phy'],'program')


if __name__=='__main__': unittest.main(verbosity=2)
