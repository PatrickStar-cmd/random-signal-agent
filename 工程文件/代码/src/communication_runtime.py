"""Execution context shared by all communication engines.

Observation is opt-in. With no context, old numerical and JSON contracts are
unchanged. The gate pauses after actual block execution, never precomputing a
future block for the debugger. Receiver state contains no transmitted payload.
"""
from contextvars import ContextVar
from contextlib import contextmanager
import hashlib
import threading
import time
import numpy as np

CURRENT=ContextVar('communication_execution',default=None)


class Cancelled(Exception): pass


def enter(block):
    ctx=CURRENT.get()
    if ctx:
        ctx.block=block
        ctx.started=time.perf_counter()
        ctx.check()


def record(block,data,rate=None):
    ctx=CURRENT.get()
    return ctx.record(block,data,rate) if ctx else data


def state(name,initial):
    ctx=CURRENT.get()
    if ctx is None or ctx.states is None: return initial()
    key=ctx.block['id']+':'+name
    if key not in ctx.states: ctx.states[key]=initial()
    return ctx.states[key]


@contextmanager
def execution(ctx):
    token=CURRENT.set(ctx)
    try: yield ctx
    finally: CURRENT.reset(token)


class Observer:
    def __init__(self,compiled,points=256,cancel=None,gate=None,states=None,replay=None,retain=False):
        self.compiled=compiled; self.points=points; self.cancel=cancel or threading.Event(); self.gate=gate
        self.states=states; self.replay=replay or {}; self.retain=retain; self.values={}; self.observations=[]
        self.block=None; self.started=time.perf_counter(); self.frame=0
        self.plan={row['id']:row for row in compiled['plan']}
        rrc=next((b for b in compiled['program']['blocks'] if b['kind']=='tx_rrc'),None)
        self.rrc_delay=rrc['params']['span']/(2*compiled['program']['symbol_rate']) if rrc else 0.

    def check(self):
        if self.cancel.is_set(): raise Cancelled('实验已取消。')

    def record(self,block,data,rate):
        self.check(); array=np.asarray(data)
        if block['id'] in self.replay:
            cached=self.replay[block['id']]
            if cached.shape!=array.shape or cached.dtype!=array.dtype: raise ValueError('共享分支的信号形状发生变化。')
            array=cached.copy()
        domain=self.plan.get(block['id'],{}).get('output','模拟样本' if array.dtype.kind=='f' else '比特')
        if rate is None:
            rate=self.compiled['program']['sample_rate'] if '模拟样本' in domain else self.compiled['program']['symbol_rate']
        if domain in ('比特','LLR'): unit='index'; sample_rate=None
        else: unit='s'; sample_rate=float(rate)
        shown=array[:self.points].astype(complex); count=len(array)
        power=float(np.mean(abs(array)**2)) if count else 0.
        observation={'id':block['id'],'kind':block['kind'],'label':next((r['label'] for r in self.compiled['plan'] if r['id']==block['id']),block['kind']),
            'domain':domain,'dtype':str(array.dtype),'count':count,'sample_rate':sample_rate,'symbol_rate':self.compiled['program']['symbol_rate'],
            'unit':unit,'offset':0,'i':shown.real.tolist(),'q':shown.imag.tolist(),'plot_count':len(shown),
            'filter_delay_seconds':self.rrc_delay if block['kind'] in ('tx_rrc','rx_matched') else 0.,
            'power':power,'rms':power**.5,'peak':float(np.max(abs(array))) if count else 0.,
            'mean_i':float(np.mean(array).real) if count else 0.,'mean_q':float(np.mean(array).imag) if count else 0.,
            'elapsed_ms':(time.perf_counter()-self.started)*1000,'sha256':hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest(),'frame':self.frame}
        if self.retain:
            from src import communications as c
            if sum(v.nbytes for v in self.values.values())+array.nbytes>c.CONFIG['max_capture_bytes']: raise ValueError('观察数据超过内存上限，请减少信源或采样点。')
            self.values[block['id']]=array.copy()
        self.observations.append(observation)
        if self.gate: self.gate(observation)
        self.started=time.perf_counter()
        return array


def observe_run(program,token,**options):
    from src import communications as c
    compiled=c.build(program)
    if token!=compiled['token']: raise ValueError('配置已改变，请重新 Build。')
    ctx=Observer(compiled,points=c.CONFIG['plot_points'],**options)
    with execution(ctx): result=c.run(compiled['program'],token)
    result['experience']={'observations':ctx.observations,'frame':ctx.frame,'contract':1}
    return result,ctx
