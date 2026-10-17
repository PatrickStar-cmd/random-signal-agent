"""Owned background simulations, cooperative debugger and durable sweep receipts."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import threading
import time
import uuid
import numpy as np
from src import communication_runtime as runtime, communication_studio as studio


class Job:
    def __init__(self,session,kind,payload):
        self.id=uuid.uuid4().hex;self.session=session;self.kind=kind;self.payload=copy.deepcopy(payload)
        self.cancel=threading.Event();self.condition=threading.Condition();self.status='queued';self.revision=0
        self.progress={};self.result=None;self.error=None;self.ctx=None;self.mode='step' if kind=='debug' else 'run';self.permits=0
        self.created=time.monotonic();self.accessed=self.created;self.contexts=[]
    def update(self,**changes):
        with self.condition:
            for k,v in changes.items(): setattr(self,k,copy.deepcopy(v))
            self.revision+=1;self.condition.notify_all()
    def gate(self,observation=None):
        from src import communications as c
        if observation is not None:
            self.update(progress={'observation':observation,'completed':len(self.ctx.observations),'total':len(self.ctx.compiled['program']['blocks'])})
        with self.condition:
            if self.mode=='run' or observation and observation['kind']=='sink': return
            self.status='paused';self.revision+=1;self.condition.notify_all()
            deadline=time.monotonic()+c.CONFIG['max_debug_idle_seconds']
            while self.mode=='step' and self.permits==0 and not self.cancel.is_set():
                remaining=deadline-time.monotonic()
                if remaining<=0: self.cancel.set();break
                self.condition.wait(min(1,remaining))
            if self.cancel.is_set(): raise runtime.Cancelled('调试已取消或等待超时。')
            if self.mode=='step': self.permits-=1
            self.status='running'
    def public(self,include_result=True):
        with self.condition:
            self.accessed=time.monotonic()
            return {'id':self.id,'kind':self.kind,'status':self.status,'revision':self.revision,'progress':copy.deepcopy(self.progress),
                'result':copy.deepcopy(self.result) if include_result else None,'error':self.error,
                'observations':copy.deepcopy(self.ctx.observations) if self.ctx else []}


class Jobs:
    def __init__(self,root,slots):
        from pathlib import Path
        from src import communications as c
        self.root=Path(root)/'communication-jobs';self.slots=slots;self.lock=threading.RLock();self.jobs={}
        self.executor=ThreadPoolExecutor(max_workers=c.CONFIG['max_studio_jobs'],thread_name_prefix='communication')
    def receipt(self,session,key):
        import re
        if not isinstance(key,str) or not re.fullmatch('[a-f0-9]{32}',key): raise ValueError('任务标识无效。')
        if not isinstance(session,str) or not 1<=len(session)<=256: raise ValueError('会话标识无效。')
        return self.root/hashlib.sha256(session.encode()).hexdigest()/(key+'.json')
    def get(self,session,key):
        with self.lock:
            job=self.jobs.get(key)
            if job is None or job.session!=session: raise KeyError('任务不存在或不属于当前会话。')
            return job
    def status(self,session,key):
        try: return self.get(session,key).public()
        except KeyError:
            p=self.receipt(session,key)
            if not p.exists(): raise
            value=json.loads(p.read_text(encoding='utf-8'))
            return {'id':key,'kind':'sweep','status':'completed' if value['checkpoint'].get('complete') else 'interrupted','revision':0,'progress':value['checkpoint'],'result':value['checkpoint'],'error':None,'observations':[]}
    def persist(self,job,value):
        p=self.receipt(job.session,job.id);p.parent.mkdir(parents=True,exist_ok=True)
        receipt={'payload':job.payload,'checkpoint':value};temporary=p.with_suffix('.tmp')
        temporary.write_text(json.dumps(receipt,ensure_ascii=False,allow_nan=False),encoding='utf-8');temporary.replace(p)
        # Bounded receipt retention per browser session.
        for old in sorted(p.parent.glob('*.json'),key=lambda q:q.stat().st_mtime,reverse=True)[30:]: old.unlink()
    def start(self,session,kind,payload):
        from src import communications as c
        if kind not in ('debug','run','sweep','continuous','branches','experiments'): raise ValueError('未知通信任务类型。')
        if not isinstance(payload,dict): raise ValueError('任务参数无效。')
        if kind not in ('branches','experiments'):
            built=c.build(payload.get('program'))
            if payload.get('token')!=built['token']: raise ValueError('配置已改变，请重新 Build。')
        elif kind=='branches': studio.shared_prefix(payload.get('programs',[]))
        else:
            programs=payload.get('programs',[])
            if not isinstance(programs,list) or not 2<=len(programs)<=4: raise ValueError('自动对照需要 2–4 个方案。')
            for program in programs: c.build(program)
        if kind=='continuous': c.numeric(payload.get('frames',10),'多帧数量',1,c.CONFIG['max_continuous_frames'],True)
        if kind=='sweep':
            from src.communication_sweep import parameter
            parameter(built['program'],payload.get('settings'))
        with self.lock:
            active=[j for j in self.jobs.values() if j.status in ('queued','running','paused')]
            if len(active)>=c.CONFIG['max_studio_jobs']: raise ValueError('通信任务队列已满，请完成或取消已有任务。')
            # Retain bounded completed observations for paging.
            completed=sorted((j for j in self.jobs.values() if j not in active),key=lambda j:j.accessed,reverse=True)
            for j in completed[12:]: self.jobs.pop(j.id,None)
            job=Job(session,kind,payload);self.jobs[job.id]=job;self.executor.submit(self.execute,job)
        return job.public(False)
    def control(self,session,key,action):
        if action=='resume-sweep':
            with self.lock:
                original=self.jobs.get(key)
                if original and original.status in ('queued','running','paused'): raise ValueError('请先停止正在运行的扫描。')
            p=self.receipt(session,key)
            if not p.exists(): raise KeyError('没有可续跑的扫描检查点。')
            value=json.loads(p.read_text(encoding='utf-8'));payload=value['payload'];payload['resume']=value['checkpoint']
            return self.start(session,'sweep',payload)
        job=self.get(session,key)
        with job.condition:
            if action=='cancel': job.cancel.set()
            elif action=='step': job.mode='step';job.permits+=1
            elif action=='continue': job.mode='run'
            elif action=='pause': job.mode='step';job.permits=0
            else: raise ValueError('未知任务控制操作。')
            job.condition.notify_all()
        return job.public(False)
    def window(self,session,key,block,offset,count,branch=None):
        from src import communications as c
        job=self.get(session,key)
        ctx=job.ctx if branch is None else job.contexts[c.numeric(branch,'分支序号',0,max(0,len(job.contexts)-1),True)] if job.contexts else None
        if not ctx or block not in ctx.values: raise KeyError('该积木尚未执行或数据已过期。')
        data=ctx.values[block];offset=c.numeric(offset,'窗口起点',0,max(0,len(data)-1),True);count=c.numeric(count,'窗口长度',1,1024,True)
        values=data[offset:offset+count].astype(complex);base=next(v for v in ctx.observations if v['id']==block)
        return {**base,'offset':offset,'i':values.real.tolist(),'q':values.imag.tolist(),'plot_count':len(values)}
    def execute(self,job):
        from src import communications as c
        acquired=False
        try:
            while not job.cancel.is_set():
                if self.slots.acquire(timeout=.1): acquired=True;break
            if not acquired: raise runtime.Cancelled('任务已取消。')
            job.update(status='running')
            p=job.payload
            if job.kind=='sweep':
                from src.communication_sweep import sweep
                def progress(value):
                    job.update(progress=value);self.persist(job,value)
                result=sweep(p['program'],p['token'],p['settings'],progress,job.cancel,p.get('resume'))
            elif job.kind=='branches': result=studio.compare_branches(p['programs'],p.get('names'),job.cancel,lambda v:job.update(progress=v),job.contexts)
            elif job.kind=='experiments':
                from src.communication_sweep import sweep
                curves=[]
                for index,program in enumerate(p['programs']):
                    if job.cancel.is_set():break
                    built=c.build(program)
                    curve=sweep(program,built['token'],p['settings'],lambda v:job.update(progress={'index':index,'curve':v,'curves':curves}),job.cancel)
                    curve['name']=p.get('names',[])[index] if p.get('names') else f'方案 {index+1}';curves.append(curve)
                result={'curves':curves,'complete':len(curves)==len(p['programs']) and all(v['complete'] for v in curves)}
            elif job.kind=='continuous': result=self.continuous(job)
            else:
                from src import communications as c
                compiled=c.build(p['program']);ctx=runtime.Observer(compiled,points=c.CONFIG['plot_points'],cancel=job.cancel,retain=True,gate=job.gate if job.kind=='debug' else None)
                job.ctx=ctx
                if job.kind=='debug': job.gate()
                with runtime.execution(ctx): result=c.run(compiled['program'],compiled['token'])
                result['experience']={'observations':ctx.observations,'contract':1,'job_id':job.id}
            job.update(result=result,status='cancelled' if job.cancel.is_set() else 'completed')
        except runtime.Cancelled as exc: job.update(status='cancelled',error=str(exc))
        except Exception as exc: job.update(status='failed',error=str(exc))
        finally:
            if acquired: self.slots.release()
    def continuous(self,job):
        from src import communications as c
        p=job.payload;states={};rows=[];bits=errors=symbols=symbol_errors=failed=0;last=None
        for index in range(p.get('frames',10)):
            if job.cancel.is_set(): break
            candidate=copy.deepcopy(p['program']);candidate['seed']=(candidate.get('seed',42)+index)%4294967295;built=c.build(candidate)
            ctx=runtime.Observer(built,points=c.CONFIG['plot_points'],cancel=job.cancel,states=states,retain=True);ctx.frame=index
            job.ctx=ctx
            try:
                with runtime.execution(ctx): last=c.run(built['program'],built['token'])
            except runtime.Cancelled:
                break
            m=last['metrics'];bits+=m.get('bit_count',0);errors+=m.get('bit_errors',0);symbols+=m.get('symbol_count',0);symbol_errors+=m.get('symbol_errors',0);failed+=m.get('frame_errors',int(m.get('bit_errors',0)>0))
            rows.append({'frame':index+1,'ber':m.get('ber'),'rmse':m.get('rmse'),'evm_percent':m.get('evm_percent'),'state_count':len(states),
                'carrier':last.get('advanced',{}).get('recovery',{}).get('carrier'),'equalizer':last.get('advanced',{}).get('recovery',{}).get('equalizer')})
            last['experience']={'observations':ctx.observations,'frame':index,'contract':1,'job_id':job.id}
            job.update(progress={'completed':index+1,'total':p.get('frames',10),'frames':rows,'ber':errors/max(1,bits),'fer':failed/(index+1),'state_count':len(states)})
        return {'last':last,'frames':rows,'state_count':len(states),'bit_count':bits,'bit_errors':errors,'ber':errors/max(1,bits),'ser':symbol_errors/max(1,symbols),'fer':failed/max(1,len(rows)),'complete':len(rows)==p.get('frames',10)}
    def close(self):
        with self.lock:
            for job in self.jobs.values():
                job.cancel.set()
                with job.condition: job.condition.notify_all()
        self.executor.shutdown(wait=True,cancel_futures=True)
