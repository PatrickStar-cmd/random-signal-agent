"""One shared signal fork, two real receiver paths, one typed merge."""
import hashlib
import numpy as np
from src import communication_studio as studio, communication_runtime as runtime


def merge_branches(programs,settings=None,progress=None,cancel=None,contexts=None):
    from src import communications as c
    q=settings or {}
    if len(programs)!=2:raise ValueError('汇合实验使用两条接收分支。')
    builds,shared=studio.shared_prefix(programs)
    domain=q.get('domain','symbols');mode=q.get('mode','weighted')
    if domain not in ('symbols','llr') or mode not in ('weighted','select'):raise ValueError('请选择复符号 / LLR 以及加权 / 选择汇合。')
    weights=q.get('weights',[.5,.5])
    if not isinstance(weights,list) or len(weights)!=2 or any(type(v) not in (int,float) or not np.isfinite(v) or abs(v)>10 for v in weights) or not any(weights):raise ValueError('填写两个有限汇合权重（绝对值 ≤ 10）。')
    choice=c.numeric(q.get('select',0),'选择分支',0,1,True)
    points=[];tails=[];rates=[];schemes=[];variances=[]
    for built in builds:
        blocks=built['program']['blocks']
        index=next((i for i,b in enumerate(blocks) if b['kind'].startswith(('soft_','demod_'))),None)
        if index is None:raise ValueError('每条分支需要数字解调器。')
        if domain=='llr':
            if not blocks[index]['kind'].startswith('soft_'):raise ValueError('LLR 汇合点选择软解调器输出。')
        point=blocks[index];input_port=next(row for row in built['plan'] if row['id']==blocks[index-1]['id'])
        if domain=='symbols' and input_port['output'] not in ('复符号','复基带符号'):raise ValueError('复符号汇合使用 PSK / QAM 数字解调器。')
        points.append(point['id']);schemes.append(point['kind'].split('_',1)[1]);tails.append([(b['kind'],b['params']) for b in blocks[index+(domain=='llr'):]])
        rates.append(built['program']['symbol_rate'])
    if tails[0]!=tails[1] or schemes[0]!=schemes[1]:raise ValueError('汇合后的解调与译码配置须相同。')
    results=[];observers=[];cache={};arrays=[]
    def execute(built,replay,merged=None):
        ctx=runtime.Observer(built,points=c.CONFIG['plot_points'],retain=True,replay=replay,cancel=cancel)
        captured={};noise_details={}
        def collect(data):
            captured['values']=np.asarray(data).copy()
            if merged is None:return data
            ctx.plan['merge-output']={'output':'复符号' if domain=='symbols' else 'LLR'}
            value=ctx.record({'id':'merge-output','kind':'branch_merge'},merged,built['program']['symbol_rate'])
            ctx.observations[-1]['label']='🔗 接收分支汇合'
            return value
        def noise(block,symbols,scheme,variance):
            captured['variance']=variance
            if merged is None or domain=='llr':return variance
            chosen=choice if mode=='select' else 0 if weights==[1,0] else 1 if weights==[0,1] else None
            if chosen is not None:
                value=variances[chosen];method='selected_receiver_variance'
            elif not block['params'].get('automatic_variance') and np.ndim(variance)==0:
                return variance
            else:
                from src import communication_algorithms as algorithms, communication_dsp as dsp
                value,_=algorithms.noise_estimate(symbols,dsp.constellation(scheme)[1]);method='merged_decision_residual'
            noise_details.update(variance=np.asarray(value).tolist(),method=method)
            return value
        ctx.on_decision_noise_variance=noise
        if domain=='symbols':ctx.on_decision_samples=lambda block,symbols,scheme:collect(symbols)
        else:ctx.on_decision=lambda block,symbols,scheme,data,variance:collect(data)
        with runtime.execution(ctx):result=c.run(built['program'],built['token'])
        if 'values' not in captured:raise ValueError('汇合需要复符号数字接收链路。')
        result['experience']={'observations':ctx.observations,'frame':ctx.frame,'contract':1}
        ctx.merge_input=captured['values'];ctx.merge_variance=captured.get('variance');ctx.merge_noise=noise_details
        return result,ctx
    for i,built in enumerate(builds):
        result,ctx=execute(built,cache)
        if i==0:cache={key:ctx.values[key] for key in shared}
        results.append(result);observers.append(ctx);arrays.append(ctx.merge_input);variances.append(ctx.merge_variance)
        if contexts is not None:contexts.append(ctx)
        if progress:progress({'completed':i+1,'total':3})
    if arrays[0].shape!=arrays[1].shape or arrays[0].ndim!=1 or arrays[0].dtype.kind!=arrays[1].dtype.kind or rates[0]!=rates[1]:
        raise ValueError('两路汇合输入的类型、点数与采样率须一致。')
    merged=arrays[choice].copy() if mode=='select' else weights[0]*arrays[0]+weights[1]*arrays[1]
    result,ctx=execute(builds[0],cache,merged)
    if contexts is not None:contexts.append(ctx)
    view=merged[:64].astype(complex)
    merge={'mode':mode,'domain':domain,'weights':weights,'select':choice,'block_ids':points,'count':len(merged),
           'sample_rate':rates[0] if domain=='symbols' else None,'i':view.real.tolist(),'q':view.imag.tolist(),
           'noise':ctx.merge_noise,'observation_id':'merge-output','input_reference':'demodulator_samples_after_prefix_and_gain' if domain=='symbols' else 'log_P0_over_P1',
           'sha256':hashlib.sha256(merged.tobytes()).hexdigest()}
    result['experience']['merge']=merge
    if progress:progress({'completed':3,'total':3})
    return {'branches':[{'name':f'接收分支 {i+1}','result':v} for i,v in enumerate(results)],'merged_result':result,'merge':merge,
            'programs':[v['program'] for v in builds],'settings':q,'shared_prefix':shared,
            'shared_hashes':{k:hashlib.sha256(v.tobytes()).hexdigest() for k,v in cache.items()},'complete':True}
