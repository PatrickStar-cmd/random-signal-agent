"""Local HTTP integration: credentials, provider compatibility and session isolation."""
from pathlib import Path
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ['RS_AGENT_LLM_ENABLED']='0'
from fastapi.testclient import TestClient
import server
from src.llm_client import OpenAICompatibleClient,LLMClientError
from src.dialogue_agent import RandomSignalDialogueAgent
from src.model_settings import ModelSettings,session_model


class Provider(BaseHTTPRequestHandler):
    records=[]
    def log_message(self,*args):pass
    def respond(self,code,data):
        body=json.dumps(data).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
    def do_GET(self):
        self.records.append((self.path,self.headers.get('Authorization'),None))
        if self.path=='/v1/models':self.respond(200,{'data':[{'id':'chat-a'},{'id':'chat-b'},{'id':'chat-a'},{'id':self.headers.get('Authorization','').removeprefix('Bearer ')}]})
        else:self.respond(404,{})
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));auth=self.headers.get('Authorization');self.records.append((self.path,auth,data))
        if auth=='Bearer invalid':return self.respond(401,{'error':auth})
        if data['model']=='redirect':
            self.send_response(302);self.send_header('Location',self.server.base+'/v1/models');self.end_headers();return
        if data['model']=='broken':
            self.send_response(200);self.end_headers();self.wfile.write((auth or '').encode());return
        if data['model']=='empty':return self.respond(200,{'choices':[{'message':{'content':''}}]})
        self.respond(200,{'choices':[{'message':{'content':'API answer '+data['model']},'finish_reason':'stop'}]})


class SettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider=ThreadingHTTPServer(('127.0.0.1',0),Provider);cls.provider.base='http://127.0.0.1:'+str(cls.provider.server_port)
        cls.thread=threading.Thread(target=cls.provider.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):cls.provider.shutdown();cls.provider.server_close();cls.thread.join()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.agent=RandomSignalDialogueAgent()
        self.app=server.create_app(agent=self.agent,data_dir=self.root/'data',upload_dir=self.root/'uploads');self.client=TestClient(self.app);self.client.__enter__()
        Provider.records.clear();self.config={'provider':'custom','base_url':self.provider.base+'/v1','model':'chat-a','api_key':'test-only-secret-key','remember':False}
    def tearDown(self):self.client.__exit__(None,None,None);self.temp.cleanup()
    def post(self,action,config=None,session='a'):
        return self.client.post('/api/model/'+action,json={'session_id':session,'configuration':config if config is not None else self.config})
    def test_models_test_save_and_real_chat_use_current_session(self):
        response=self.post('models',{**self.config,'model':''});self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['models'],['chat-a','chat-b']);self.assertNotIn(self.config['api_key'],response.text)
        self.assertTrue(self.post('test').json()['ok']);saved=self.post('save');self.assertEqual(saved.status_code,200,saved.text)
        self.assertNotIn('api_key',saved.text);self.assertFalse(saved.json()['settings']['remember'])
        Provider.records.clear()
        chat=self.client.post('/api/chat',json={'session_id':'a','message':'调用外部API回答：只回复你好'})
        self.assertEqual(chat.status_code,200,chat.text);self.assertIn('API answer chat-a',chat.json()['reply'])
        self.assertTrue(any(r[1]=='Bearer test-only-secret-key' for r in Provider.records))
        self.assertFalse(self.agent.model_settings.client('b').configured)
        self.assertFalse(self.client.get('/api/health').json()['llm']['configured'])
    def test_remember_restart_delete_and_disable(self):
        self.post('save',{**self.config,'remember':True})
        manager=ModelSettings(self.root/'data',self.agent.llm);self.assertTrue(manager.client('a').configured)
        self.assertEqual(manager.client('a').api_key,self.config['api_key']);self.assertFalse(manager.client('b').configured)
        manager.disable('a');self.assertFalse(ModelSettings(self.root/'data',self.agent.llm).client('a').configured)
        manager.clear('a');self.assertFalse(manager.client('a').configured);self.assertIsNone(manager.get('a'))
    def test_memory_only_key_is_not_persisted_and_checkbox_can_remove_saved_key(self):
        self.post('save');manager=ModelSettings(self.root/'data',self.agent.llm);self.assertIsNone(manager.get('a'))
        self.post('save',{**self.config,'remember':True});self.post('save',{**self.config,'api_key':'','remember':False})
        self.assertIsNone(manager.get('a'));self.assertTrue(self.agent.model_settings.client('a').configured)
    def test_key_reuse_only_same_endpoint_and_never_environment(self):
        self.post('save');response=self.post('test',{**self.config,'api_key':''});self.assertEqual(response.status_code,200,response.text)
        response=self.post('test',{**self.config,'base_url':self.provider.base+'/other','api_key':''});self.assertEqual(response.status_code,400)
        self.assertEqual(len([r for r in Provider.records if r[0].startswith('/other')]),0)
        self.assertEqual(self.post('save',{**self.config,'api_key':''},session='b').status_code,400)
    def test_failed_test_redacts_provider_errors_and_does_not_change_saved_settings(self):
        self.post('save')
        for extra in ({'api_key':'invalid'},{'model':'broken'},{'model':'empty'},{'model':'redirect'}):
            response=self.post('test',{**self.config,**extra});self.assertEqual(response.status_code,400,response.text)
            self.assertNotIn('Bearer',response.text);self.assertNotIn('test-only-secret-key',response.text)
        self.assertEqual(self.agent.model_settings.client('a').model,'chat-a')
        self.assertEqual(len([r for r in Provider.records if r[0]=='/v1/models']),0)
    def test_validation_provider_override_url_and_secret_fields(self):
        cases=[{'base_url':'https://u:p@example.com/v1'},{'base_url':'https://example.com/v1?key=abc'},
               {'base_url':'http://example.com/v1'},{'base_url':self.provider.base+'/chat/completions'},
               {'api_key':'secret\nkey'},{'model':''},{'timeout':1},{'remember':'yes'},{'token_parameter':'unknown'},
               {'provider':'openai'},{'unknown':'value'}]
        for extra in cases:self.assertEqual(self.post('save',{**self.config,**extra}).status_code,400,extra)
    def test_openai_compatible_token_parameter_without_temperature(self):
        response=self.post('test',{**self.config,'token_parameter':'max_completion_tokens','send_temperature':False})
        self.assertEqual(response.status_code,200,response.text);payload=Provider.records[-1][2]
        self.assertIn('max_completion_tokens',payload);self.assertNotIn('max_tokens',payload);self.assertNotIn('temperature',payload)
    def test_key_not_in_tasks_snapshots_health_or_export(self):
        self.post('save',{**self.config,'remember':True})
        self.client.post('/api/diagnostics/demo',json={'session_id':'a'})
        response=self.client.get('/api/experiments/export',params={'session_id':'a','format':'zip'})
        self.assertEqual(response.status_code,200,response.text if response.status_code!=200 else '')
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for name in archive.namelist():self.assertNotIn(self.config['api_key'].encode(),archive.read(name),name)
        for path in ('/api/health','/api/state?session_id=a','/api/tasks?session_id=a','/api/model/settings?session_id=a'):
            self.assertNotIn(self.config['api_key'],self.client.get(path).text)
        with self.app.state.store.connect() as db:
            self.assertNotIn(self.config['api_key'],str(db.execute('SELECT * FROM tasks').fetchall()))
    def test_cross_origin_rejected_before_network_and_models_response_bound(self):
        response=self.client.post('/api/model/test',json={'session_id':'a','configuration':self.config},headers={'Origin':'https://other.example'})
        self.assertEqual(response.status_code,403);self.assertEqual(Provider.records,[])
        client=OpenAICompatibleClient(base_url=self.config['base_url'],api_key=self.config['api_key'],model='a',response_bytes=1)
        with self.assertRaises(LLMClientError):client.models()
    def test_parallel_clients_and_generator_context_restore(self):
        self.post('save');self.post('save',{**self.config,'model':'chat-b','api_key':'second-test-key'},session='b')
        class Reader(RandomSignalDialogueAgent):
            @session_model
            def read(self,session_id):return self.llm.model,self.llm.api_key
            @session_model
            def read_stream(self,session_id):yield self.llm.model;yield self.llm.model
        reader=Reader();reader.model_settings=self.agent.model_settings
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(list(pool.map(reader.read,['a','b'])),[('chat-a','test-only-secret-key'),('chat-b','second-test-key')])
        self.assertEqual(list(reader.read_stream('b')),['chat-b','chat-b']);self.assertFalse(reader.llm.configured)


if __name__=='__main__':
    log=ROOT/'logs/model-settings/latest.log';log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    print(log.read_text(encoding='utf-8'));sys.exit(0 if result.wasSuccessful() else 1)
