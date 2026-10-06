"""Session-scoped model configuration, separate from experiments and task history."""
from __future__ import annotations
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
import inspect
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
from urllib.parse import urlsplit
from .llm_client import OpenAICompatibleClient, LLMClientError

CONFIG=json.loads((Path(__file__).resolve().parents[1]/'config/model-providers.json').read_text(encoding='utf-8'))
PROVIDERS={p['id']:p for p in CONFIG['providers']}


def session_model(function):
    """Keep each chat's client stable, including generators and concurrent sessions."""
    def client(self,session_id):
        manager=getattr(self,'model_settings',None)
        return manager.client(session_id) if manager else self._default_llm
    if inspect.isgeneratorfunction(function):
        @wraps(function)
        def wrapped(self,session_id,*args,**kwargs):
            token=self._model_context.set(client(self,session_id))
            try:yield from function(self,session_id,*args,**kwargs)
            finally:self._model_context.reset(token)
    else:
        @wraps(function)
        def wrapped(self,session_id,*args,**kwargs):
            token=self._model_context.set(client(self,session_id))
            try:return function(self,session_id,*args,**kwargs)
            finally:self._model_context.reset(token)
    return wrapped


def base_url(value):
    if not isinstance(value,str) or len(value)>1000 or any(ord(c)<=32 for c in value):raise ValueError('API 地址格式无效。')
    value=value.rstrip('/');parts=urlsplit(value)
    if parts.scheme not in ('https','http') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('请填写不含密钥、查询参数或用户信息的 HTTP(S) API Base URL。')
    try:parts.port
    except ValueError:raise ValueError('API 地址端口无效。') from None
    if parts.scheme=='http' and parts.hostname not in ('localhost','127.0.0.1','::1'):
        raise ValueError('远程 API 请使用 HTTPS；HTTP 仅支持本机 localhost。')
    if parts.path.endswith(('/chat/completions','/models','/responses')):
        raise ValueError('请填写 Base URL，而不是 /chat/completions、/models 或 /responses 地址。')
    return value


class ModelSettings:
    def __init__(self,root,default):
        self.default=default;self.lock=threading.RLock();self.memory={};self.path=Path(root)/'model-settings.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:db.execute('CREATE TABLE IF NOT EXISTS settings (session TEXT PRIMARY KEY, configuration TEXT NOT NULL)')
        try:os.chmod(self.path,0o600)
        except OSError:pass

    @contextmanager
    def connect(self):
        connection=sqlite3.connect(self.path,timeout=10)
        try:
            connection.execute('PRAGMA secure_delete=ON')
            with connection:yield connection
        finally:connection.close()

    def get(self,session):
        with self.lock:
            if session in self.memory:return dict(self.memory[session])
            with self.connect() as db:row=db.execute('SELECT configuration FROM settings WHERE session=?',(session,)).fetchone()
            return json.loads(row[0]) if row else None

    def public(self,session):
        current=self.get(session)
        if current:
            return {**{k:v for k,v in current.items() if k!='api_key'},'has_key':bool(current.get('api_key')),
                    'configured':self.make_client(current).configured,'source':'session'}
        return {**self.default.status(),'provider':'custom','timeout':self.default.timeout,
                'token_parameter':self.default.token_parameter,'send_temperature':self.default.send_temperature,
                'has_key':bool(self.default.api_key),'remember':False,'source':'environment'}

    def draft(self,session,payload,require_model=True):
        allowed={'provider','base_url','model','api_key','timeout','enabled','remember','token_parameter','send_temperature'}
        if not isinstance(payload,dict) or set(payload)-allowed:raise ValueError('未知的模型配置字段。')
        provider=payload.get('provider','custom')
        if provider not in PROVIDERS:raise ValueError('请选择有效的服务商。')
        preset=PROVIDERS[provider];url=base_url(payload.get('base_url') or preset['base_url'])
        if provider!='custom' and url!=preset['base_url']:raise ValueError('预设服务商地址不能修改；其他地址请选择自定义接口。')
        previous=self.get(session)
        key=payload.get('api_key')
        if key is None or key=='':
            # Never forward a saved key to a different endpoint.
            key=(previous or {}).get('api_key','') if previous and previous['base_url']==url else ''
        if not isinstance(key,str) or len(key)>8192 or any(ord(c)<33 or ord(c)>126 for c in key):raise ValueError('Key 包含空白或无效字符。')
        if not key:raise ValueError('请输入此服务的 API Key；Key 不会自动复制到其他地址。')
        model=payload.get('model','').strip() if isinstance(payload.get('model',''),str) else None
        if model is None or len(model)>200 or any(ord(c)<32 for c in model) or (require_model and not model):raise ValueError('请选择或填写有效的模型 ID。')
        if key in model or key in url:raise ValueError('请勿将 Key 填入模型 ID 或 API 地址。')
        timeout=payload.get('timeout',CONFIG['default_timeout'])
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 5<=timeout<=120:raise ValueError('超时请选择 5–120 秒。')
        for field in ('enabled','remember','send_temperature'):
            if field in payload and type(payload[field]) is not bool:raise ValueError(f'{field} 必须为布尔值。')
        parameter=payload.get('token_parameter',preset['token_parameter'])
        if parameter not in ('max_tokens','max_completion_tokens'):raise ValueError('输出限制参数无效。')
        return {'provider':provider,'base_url':url,'model':model,'api_key':key,'timeout':float(timeout),
                'enabled':payload.get('enabled',True),'remember':payload.get('remember',False),
                'token_parameter':parameter,'send_temperature':payload.get('send_temperature',preset['send_temperature'])}

    @staticmethod
    def make_client(configuration):
        return OpenAICompatibleClient(**{k:v for k,v in configuration.items() if k not in ('provider','remember')},response_bytes=CONFIG['response_bytes'])

    def client(self,session):
        configuration=self.get(session)
        return self.make_client(configuration) if configuration else self.default

    def save(self,session,payload):
        with self.lock:
            value=self.draft(session,payload)
            with self.connect() as db:
                if value['remember']:db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(session,json.dumps(value)))
                else:db.execute('DELETE FROM settings WHERE session=?',(session,))
            self.memory[session]=value
        return self.public(session)

    def disable(self,session):
        with self.lock:
            value=self.get(session)
            if value:
                value['enabled']=False
                with self.connect() as db:
                    if value['remember']:db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(session,json.dumps(value)))
                self.memory[session]=value
            else:self.memory[session]={'provider':'custom','base_url':'','model':'','api_key':'','timeout':45,
                'enabled':False,'remember':False,'token_parameter':'max_tokens','send_temperature':True}
        return self.public(session)

    def clear(self,session):
        with self.lock:
            self.memory.pop(session,None)
            with self.connect() as db:db.execute('DELETE FROM settings WHERE session=?',(session,))
        return self.public(session)

    def models(self,session,payload):
        value=self.draft(session,payload,require_model=False);client=self.make_client({**value,'enabled':True,'model':'list'})
        data=client.models();ids=data.get('data')
        if not isinstance(ids,list):raise ValueError('此接口没有返回有效模型列表，可手动填写模型 ID。')
        models=sorted({m['id'] for m in ids if isinstance(m,dict) and isinstance(m.get('id'),str)
                       and 0<len(m['id'])<=200 and not any(ord(c)<32 for c in m['id']) and value['api_key'] not in m['id']})
        return {'models':models[:CONFIG['max_models']],'truncated':len(models)>CONFIG['max_models']}

    def test(self,session,payload):
        value=self.draft(session,payload);client=self.make_client({**value,'enabled':True})
        result=client.complete([{'role':'user','content':'Reply with OK only.'}],max_tokens=CONFIG['test_tokens'])
        if not result.content:raise ValueError('接口已响应，但未返回文本。请检查模型是否支持 Chat Completions，或选择其他模型。')
        # Don't return provider text/raw objects: they may echo user credentials.
        return {'ok':True,'model':value['model'],'message':'文本对话测试通过；工具调用能力由所选模型决定。'}
