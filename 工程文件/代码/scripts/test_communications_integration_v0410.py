"""v0.4.10 production registration, real traces and asynchronous API acceptance."""
import copy
import sys
import tempfile
import time
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from fastapi.testclient import TestClient
import server
from src import communications as c, communication_studio as studio, communication_runtime as rt
from src import communication_receiver_v0410 as receiver, communication_framing_v0410 as framing
from src import communication_turbo as turbo, communication_isac_v0410 as isac


class IntegrationTests(unittest.TestCase):
    def test_all_new_presets_ports_completion_and_actual_traces(self):
        for extension in (receiver,framing,turbo,isac):
            for name in extension.presets(c.preset):
                with self.subTest(name=name):
                    p=c.PRESETS[name]['program'];b=c.build(p);result,ctx=rt.observe_run(p,b['token'],retain=True)
                    self.assertEqual(result['sink']['count'],result['metrics']['bit_count'])
                    c.build(studio.complete_receiver(p))
                    desc=studio.describe(p)
                    self.assertTrue(desc['ready'],desc)
                    self.assertTrue(all(row['compatible'] for row in desc['ports']),desc['ports'])
                    for trace in result['advanced']['algorithm_traces']:
                        actual=ctx.values[trace['block_id']].ravel()[:64]
                        np.testing.assert_allclose(np.asarray(trace['output']['i'])+1j*np.asarray(trace['output']['q']),actual)

    def test_legacy_hard_viterbi_trace_uses_this_execution(self):
        p=c.preset(['random_bits','conv_encode','mod_bpsk','awgn','demod_bpsk','conv_decode','sink'])
        b=c.build(p);result,ctx=rt.observe_run(p,b['token'],retain=True)
        trace=result['algorithm_traces'][0]
        self.assertEqual(trace['block_id'],p['blocks'][-2]['id'])
        np.testing.assert_array_equal(trace['input']['i'],ctx.values[p['blocks'][-3]['id']][:64])

    def test_new_transmitters_complete_from_open_chain(self):
        for tx in ('tx_mlse_frame','tx_self_frame','tx_isac_ofdm'):
            p=c.preset(['random_bits','mod_qpsk' if tx=='tx_isac_ofdm' else 'mod_bpsk',tx,'sink'],{0:{'count':2048}})
            b=c.build(studio.complete_receiver(p));r=c.run(b['program'],b['token'])
            self.assertEqual(r['metrics']['ber'],0,tx)

    def test_hard_mlse_rejects_soft_likelihood(self):
        p=copy.deepcopy(c.PRESETS['mlse_bpsk']['program']);p['blocks'][-2]={'id':'soft','kind':'soft_bpsk','params':{}}
        with self.assertRaisesRegex(ValueError,'硬序列'):c.build(p)

    def test_real_api_jobs_and_inspection(self):
        with tempfile.TemporaryDirectory() as folder,TestClient(server.create_app(data_dir=Path(folder)/'data',upload_dir=Path(folder)/'uploads',output_dir=Path(folder)/'outputs')) as client:
            def call(action,**payload):
                response=client.post('/api/communications/'+action,json={'session_id':'v0410',**payload})
                self.assertEqual(response.status_code,200,response.text);return response.json()
            p=c.PRESETS['soft_viterbi']['program'];built=c.build(p)
            def job(kind,payload):
                receipt=call('job-start',kind=kind,payload=payload);end=time.monotonic()+20
                while time.monotonic()<end:
                    state=call('job-status',id=receipt['id'])
                    if state['status'] in ('completed','failed','cancelled'):
                        self.assertEqual(state['status'],'completed',state);return state['result']
                    time.sleep(.01)
                self.fail('job timed out')
            result=job('run',{'program':p,'token':built['token']})
            inspection=call('v0410-inspect',program=p,result=result)
            self.assertTrue(inspection['traces']);self.assertTrue(inspection['profile'])
            noise=next(b for b in p['blocks'] if b['kind']=='awgn')
            pareto=job('pareto',{'program':p,'token':built['token'],'settings':{'axes':[
                {'block_id':noise['id'],'parameter':'esn0_db','values':[2,6]},
                {'block_id':'global','parameter':'symbol_rate','values':[500,1000]}],'seeds':[42],'frames':1}})
            self.assertTrue(pareto['complete'])
            scenario=job('scenario',{'program':p,'token':built['token'],'settings':{'frames':3,'events':[
                {'frame':2,'block_id':noise['id'],'parameter':'esn0_db','value':8,'transition':'step'}]}})
            self.assertTrue(scenario['last_result']['experience']['job_id'])
            merged=job('branch-merge',{'programs':[p,p],'settings':{'domain':'llr','weights':[.5,.5]}})
            self.assertEqual(merged['merged_result']['sink'],result['sink'])
            comparison=job('protocol-compare',{'program':p,'token':built['token'],'settings':{'phy':'program','packets':1,'packet_bytes':4,'max_retries':1,'feedback_loss':0,'budget_rate':2}})
            self.assertIn('comparison',comparison)


if __name__=='__main__':unittest.main()
