"""Evidence-based diagnostics, reproducible fault challenges and reversible trials.

Detectors use observations only. Hidden challenge truth is never a detector input.
Times in requests/events are seconds relative to the first sample.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
from html import escape
from pathlib import Path
import numpy as np
from .signal_processing import PreprocessResult, decimate_for_export
from .tasks import check_cancelled, emit_progress

CONFIG = json.loads((Path(__file__).resolve().parents[1]/'config/diagnostics.json').read_text(encoding='utf-8'))
LABELS = {'impulse':'脉冲异常','narrowband':'局部窄带成分','drift':'基线偏移/漂移',
          'clipping':'削顶/非零平台','dropout':'信号短暂归零','frequency_shift':'主频变化'}


def identity(bundle):
    h=hashlib.sha256(str(float(bundle.config.sample_rate)).encode())
    for a in (bundle.time,bundle.observed):h.update(np.asarray(a,dtype='<f8').tobytes())
    return h.hexdigest()


def lab_for(state):
    lab=state.diagnostic_lab or {}
    if state.bundle is None or lab.get('input_sha256') != identity(state.bundle):
        return {}
    return lab


def public_lab(state):
    lab=lab_for(state)
    out={k:lab[k] for k in ('input_sha256','blind','revealed','analysis','evaluation') if k in lab}
    if 'truth' in lab:
        out['challenge']=True
        if not lab.get('blind') or lab.get('revealed'):out['truth']=lab['truth'];out['seed']=lab['seed']
    if lab.get('verification'):
        out['verification']={k:v for k,v in lab['verification'].items() if k!='signal'}
    return out


def _number(value,name,lo=None,hi=None):
    if type(value) not in (int,float) or not math.isfinite(value) or (lo is not None and value<lo) or (hi is not None and value>hi):
        raise ValueError(f'{name} 超出范围或不是有限数值')
    return float(value)


def _signal(state,source='observed'):
    b=state.bundle
    if b is None:raise ValueError('请先生成或导入信号。')
    if source not in ('observed','processed'):raise ValueError('Unknown diagnostic source')
    if source=='processed' and state.processed is None:raise ValueError('当前没有处理后的信号。')
    y=b.observed if source=='observed' else state.processed.signal
    if len(y)<16:raise ValueError('诊断至少需要 16 个采样点。')
    if not np.isfinite(y).all() or np.max(np.abs(y))>1e100:raise ValueError('信号数值超出诊断计算范围。')
    t=b.time-b.time[0];fs=b.config.sample_rate
    if not np.isfinite(fs) or not 0<fs<=192000 or not np.allclose(np.diff(t),1/fs,rtol=1e-3,atol=max(1e-12,1e-6/fs)):
        raise ValueError('时频诊断要求均匀采样，且采样率不超过 192000 Hz。')
    return b,t,y,fs


def options_for(state,options=None):
    options={} if options is None else options
    if not isinstance(options,dict) or set(options)-{'window','overlap','source','start','end'}:raise ValueError('Unknown diagnostic options')
    source=options.get('source','observed');b,t,y,fs=_signal(state,source)
    window=options.get('window',CONFIG['window'])
    if type(window) is not int or window not in (32,64,128,256,512,1024,2048):raise ValueError('窗长请选择 32–2048 之间的 2 的幂。')
    overlap=_number(options.get('overlap',CONFIG['overlap']),'overlap',0,0.75)
    start=_number(options.get('start',0),'start',0,float(t[-1]))
    end=_number(options.get('end',len(t)/fs),'end',0,len(t)/fs)
    if end<=start:raise ValueError('结束时间须大于开始时间。')
    mask=(t>=start)&(t<end)
    if int(mask.sum())<16:raise ValueError('选择区间至少需要 16 个采样点。')
    # Short signals use an explicitly reported shorter window.
    actual=min(window,2**int(math.floor(math.log2(int(mask.sum())))))
    return {'source':source,'window':window,'effective_window':actual,'overlap':overlap,'start':start,'end':end},t[mask],y[mask],fs


def _runs(mask,gap=0,minimum=1):
    indices=np.flatnonzero(mask)
    if not len(indices):return []
    groups=np.split(indices,np.flatnonzero(np.diff(indices)>gap+1)+1)
    return [(int(g[0]),int(g[-1])+1) for g in groups if len(g)>=minimum]


def _mad(x):return float(1.4826*np.median(np.abs(x-np.median(x))))


def analyze(state,options=None):
    params,t,y,fs=options_for(state,options)
    emit_progress('diagnose_signal','running')
    w=params['effective_window'];hop=max(1,int(w*(1-params['overlap'])))
    padded=np.pad(y,(w//2,w-1-w//2));starts=np.arange(0,len(y),hop)
    win=np.hanning(w);normalizer=fs*float(np.sum(win**2));spectra=[];means=[];rms=[]
    for chunk in np.array_split(starts,max(1,math.ceil(len(starts)/256))):
        check_cancelled()
        frames=padded[chunk[:,None]+np.arange(w)]
        means.extend(np.mean(frames,axis=1));rms.extend(np.sqrt(np.mean(frames**2,axis=1)))
        fft=np.fft.rfft(frames*win,axis=1)
        power=np.abs(fft)**2/normalizer;power[:,1:-1]*=2
        spectra.append(power)
    power=np.concatenate(spectra);means=np.asarray(means);rms=np.asarray(rms)
    freq=np.fft.rfftfreq(w,1/fs);frame_t=t[starts]
    global_rms=float(np.sqrt(np.mean(y**2)));scale=max(global_rms,float(np.max(np.abs(y)))*1e-8,1e-15)
    events=[]
    def add(kind,a,z,evidence,frequency=None):
        if len(events)>=CONFIG['max_events']:return
        a=max(float(t[0]),float(a));z=min(float(t[-1]+1/fs),float(z))
        if z<=a:return
        event={'kind':kind,'label':LABELS[kind],'start':a,'end':z,'evidence':evidence,
               'interpretation':'这是可计算的信号特征；是否属于故障需要结合信号来源验证。',
               'alternatives':{'narrowband':'可能是有效载波、扫频或谐波；局部频带增强本身不能证明干扰。',
                   'drift':'可能是正常低频趋势或信号直流分量。','clipping':'可能是方波或有意设置的平台。',
                   'dropout':'可能是静音/停机区间；不自动解释为丢包。','impulse':'可能是有效瞬态或边沿。',
                   'frequency_shift':'可能是有效调频信号；不建议直接滤除。'}[kind]}
        if frequency is not None:event['frequency_hz']=float(frequency)
        event['id']=hashlib.sha256(json.dumps(event,sort_keys=True).encode()).hexdigest()[:16]
        events.append(event)
    second=np.r_[0,np.diff(y,n=2),0]
    threshold=max(CONFIG['impulse_sigma']*_mad(second),1.5*scale)
    for a,z in _runs(np.abs(second)>threshold,gap=max(1,int(fs*.02))):
        add('impulse',t[a],t[min(z,len(t)-1)]+1/fs,{'curvature_peak':float(np.max(np.abs(second[a:z]))),'threshold':threshold})
    zero=np.abs(y)<=max(1e-12,scale*1e-9)
    if not np.all(zero):
        for a,z in _runs(zero,minimum=max(CONFIG['minimum_event_samples'],int(fs*.04))):
            add('dropout',t[a],t[z-1]+1/fs,{'samples':z-a,'absolute_tolerance':max(1e-12,scale*1e-9)})
    flat=np.r_[False,np.abs(np.diff(y))<=max(1e-12,scale*1e-10)]&(np.abs(y)>scale*.5)
    for a,z in _runs(flat,minimum=3):
        add('clipping',t[max(0,a-1)],t[z-1]+1/fs,{'plateau_value':float(np.mean(y[a:z])),'samples':z-a+1})
    # Exclude padded border frames from baseline estimation and drift claims.
    interior=(starts>=w//2)&(starts<len(y)-w//2)
    reference=power[interior] if np.any(interior) else power
    base_mean=float(np.median(means[interior] if np.any(interior) else means))
    drift_threshold=max(3*_mad(means[interior] if np.any(interior) else means),.6*scale)
    for a,z in _runs((np.abs(means-base_mean)>drift_threshold)&interior,minimum=2):
        add('drift',frame_t[a]-w/(2*fs),frame_t[z-1]+w/(2*fs),{'mean_departure':float(np.max(np.abs(means[a:z]-base_mean))),'threshold':drift_threshold})
    baseline=np.median(reference,axis=0);floor=max(float(np.median(np.sum(reference,axis=1)))*1e-4,1e-30)
    fractions=power/np.maximum(np.sum(power,axis=1)[:,None],1e-30)
    novel=(power>CONFIG['spectral_ratio']*np.maximum(baseline,floor))&(fractions>CONFIG['spectral_fraction'])
    novel[:,:2]=False;novel[~interior]=False
    peak_bins=np.argmax(np.where(novel,power,0),axis=1)
    active=np.any(novel,axis=1)
    for a,z in _runs(active,minimum=2):
        k=int(np.median(peak_bins[a:z]))
        add('narrowband',frame_t[a]-w/(2*fs),frame_t[z-1]+w/(2*fs),
            {'frequency_hz':float(freq[k]),'peak_band_fraction':float(np.max(fractions[a:z,k])),
             'power_ratio':float(np.max(power[a:z,k])/max(baseline[k],floor))},freq[k])
    dominant=np.argmax(power[:,1:],axis=1)+1
    if np.sum(interior)>=8:
        valid=np.flatnonzero(interior);initial=float(np.median(freq[dominant[valid[:max(2,len(valid)//4)]]]))
        change=np.abs(freq[dominant]-initial)>max(3*fs/w,2)
        for a,z in _runs(change&interior,minimum=3):
            add('frequency_shift',frame_t[a]-w/(2*fs),frame_t[z-1]+w/(2*fs),
                {'initial_frequency_hz':initial,'interval_frequency_hz':float(np.median(freq[dominant[a:z]])), 'resolution_hz':fs/w})
    events.sort(key=lambda e:(e['start'],e['kind']))
    # Max pooling preserves brief/high-energy features in a bounded browser grid.
    frame_groups=np.array_split(np.arange(len(starts)),min(len(starts),CONFIG['plot_frames']))
    bin_groups=np.array_split(np.arange(len(freq)),min(len(freq),CONFIG['plot_bins']))
    pooled=[]
    for fg in frame_groups:
        check_cancelled()
        pooled.append([float(np.max(power[np.ix_(fg,bg)])) for bg in bin_groups])
    pooled=np.asarray(pooled)
    peak=max(float(np.max(power)),1e-30)
    db=np.maximum(-80,10*np.log10(np.maximum(pooled,peak*1e-8)/peak))
    x,v=decimate_for_export(t,y,max_points=520)
    result={'version':CONFIG['version'],'input_sha256':identity(state.bundle),'parameters':params,'events':events,
        'sample_count':len(y),'rms':global_rms,'window_seconds':w/fs,'frequency_resolution_hz':fs/w,'hop_seconds':hop/fs,
        'spectrogram':{'time':[float(np.mean(frame_t[g])) for g in frame_groups],
                       'frequency':[float(np.mean(freq[g])) for g in bin_groups],'db':db.tolist(),'floor_db':-80,
                       'label':'PSD 相对本区间最大值 / dB','edge_seconds':w/(2*fs)},
        'waveform':{'time':x,'observed':v},'truncated_events':len(events)>=CONFIG['max_events'],
        'note':'启发式特征检测，不构成设备故障定论。窗长决定时频分辨率；两端半窗区域受零填充影响。未检测到事件不代表不存在故障。'}
    token=hashlib.sha256((identity(state.bundle)+json.dumps(params,sort_keys=True)+hashlib.sha256(y.tobytes()).hexdigest()).encode()).hexdigest()
    result['token']=token
    emit_progress('diagnose_signal','success',event_count=len(events))
    return result


def diagnose_state(state,options=None):
    result=analyze(state,options)
    lab=lab_for(state)
    lab.setdefault('input_sha256',identity(state.bundle))
    lab['analysis']={k:v for k,v in result.items() if k not in ('waveform','spectrogram')}
    lab.pop('verification',None)
    state.diagnostic_lab=lab
    return result


def inject(state,faults,seed=42,blind=False):
    b,t,y,fs=_signal(state)
    if type(seed) is not int or not 0<=seed<2**32-1:raise ValueError('Invalid seed')
    if type(blind) is not bool:raise ValueError('blind must be boolean')
    if not isinstance(faults,list) or not 1<=len(faults)<=CONFIG['max_faults']:raise ValueError(f"请选择 1–{CONFIG['max_faults']} 个故障事件。")
    previous=lab_for(state)
    baseline=previous.get('baseline',y).copy()
    clean=previous.get('reference_clean',b.clean).copy()
    has_reference=previous.get('original_has_reference',b.has_clean_reference)
    rng=np.random.default_rng(seed);out=baseline.copy();truth=[]
    for spec in faults:
        check_cancelled()
        if not isinstance(spec,dict) or set(spec)-{'kind','start','end','strength','frequency'}:raise ValueError('Unknown fault parameters')
        kind=spec.get('kind')
        if kind not in LABELS:raise ValueError('Unknown fault kind')
        start=_number(spec.get('start'),'start',0,float(t[-1]))
        end=_number(spec.get('end'),'end',0,len(t)/fs)
        if end<=start:raise ValueError('故障结束时间须大于开始时间。')
        strength=_number(spec.get('strength',2),'strength',1e-9,1e6)
        frequency=_number(spec.get('frequency',min(30,fs*.2)),'frequency',0,fs/2)
        if kind in ('narrowband','frequency_shift') and not 0<frequency<fs/2:raise ValueError('注入频率须在 0 和 Nyquist 频率之间。')
        indices=np.flatnonzero((t>=start)&(t<end))
        if not len(indices):raise ValueError('故障区间不包含采样点。')
        if kind=='impulse':
            selected=rng.choice(indices,size=max(1,min(len(indices),int(math.ceil((end-start)*3)))),replace=False)
            out[selected]+=rng.choice([-1,1],len(selected))*strength
            for i in sorted(selected):truth.append({'kind':kind,'start':float(t[i]),'end':float(t[i]+1/fs),'strength':strength})
            continue
        if kind=='narrowband':out[indices]+=strength*np.sin(2*np.pi*frequency*t[indices]+rng.uniform(0,2*np.pi))
        elif kind=='drift':out[indices]+=np.linspace(0,strength,len(indices))
        elif kind=='clipping':
            if not np.any(np.abs(out[indices])>strength):raise ValueError('削顶阈值高于区间所有采样值，不会产生削顶；请降低强度。')
            out[indices]=np.clip(out[indices],-strength,strength)
        elif kind=='dropout':out[indices]=0
        elif kind=='frequency_shift':out[indices]=strength*np.sin(2*np.pi*frequency*t[indices])+(baseline-clean)[indices]
        truth.append({'kind':kind,'start':float(t[indices[0]]),'end':float(t[indices[-1]]+1/fs),'strength':strength,
                      **({'frequency_hz':frequency} if kind in ('narrowband','frequency_shift') else {})})
    b.observed=out;b.impulse_mask=np.zeros(len(out),dtype=bool)
    b.has_clean_reference=bool(has_reference and not blind)
    b.clean=clean if b.has_clean_reference else out.copy();b.noise=out-b.clean
    b.source='diagnostic_challenge'
    state.processed=None;state.summary=None;state.decision=None;state.preprocess_results={};state.preprocess_comparison=None
    state.audio_result=None
    state.diagnostic_lab={'input_sha256':identity(b),'blind':blind,'revealed':False,'seed':seed,'truth':truth,
                          'baseline':baseline,'reference_clean':clean,'original_has_reference':has_reference}
    return public_lab(state)


def reveal(state):
    lab=lab_for(state)
    if 'truth' not in lab:raise ValueError('当前没有故障挑战。')
    fs=state.bundle.config.sample_rate
    p=lab.get('analysis',{}).get('parameters',{})
    if not p or p.get('source')!='observed' or p.get('start')!=0 or p.get('end')!=len(state.bundle.time)/fs:
        diagnose_state(state)
        lab=lab_for(state)
    detected=lab['analysis']['events'];truth=lab['truth'];fs=state.bundle.config.sample_rate
    pairs=[]
    # Typed interval IoU with one-sample tolerance for impulse localization.
    for i,d in enumerate(detected):
        for j,g in enumerate(truth):
            if d['kind']!=g['kind']:continue
            pad=max(1/fs,.02) if d['kind']=='impulse' else 0
            a,z=g['start']-pad,g['end']+pad
            intersection=max(0,min(d['end'],z)-max(d['start'],a))
            union=max(d['end'],z)-min(d['start'],a)
            score=intersection/union if union>0 else 0
            if score>=.2:pairs.append((score,i,j))
    used_d=set();used_g=set();errors=[]
    for score,i,j in sorted(pairs,reverse=True):
        if i in used_d or j in used_g:continue
        used_d.add(i);used_g.add(j);errors.append(abs(detected[i]['start']-truth[j]['start']))
    tp=len(used_g);precision=tp/len(detected) if detected else 0;recall=tp/len(truth) if truth else 0
    lab['revealed']=True
    lab['evaluation']={'matched':tp,'missed':len(truth)-tp,'false_alarms':len(detected)-tp,
        'precision':precision,'recall':recall,'f1':2*precision*recall/(precision+recall) if precision+recall else 0,
        'mean_start_error_seconds':float(np.mean(errors)) if errors else None,
        'rule':'按类型逐个匹配区间 IoU≥0.2；脉冲真值扩展 max(1/fs,0.02s)。检测是启发式，真值只用于揭晓评分。'}
    if lab['original_has_reference']:
        state.bundle.has_clean_reference=True;state.bundle.clean=lab['reference_clean'].copy()
        state.bundle.noise=state.bundle.observed-state.bundle.clean
        state.summary=None;state.decision=None;state.preprocess_comparison=None
    return public_lab(state)


def verify(state,event_id,token):
    lab=lab_for(state);analysis=lab.get('analysis',{})
    if analysis.get('token')!=token:raise ValueError('诊断已改变，请重新诊断再运行验证。')
    current=analyze(state,{k:v for k,v in analysis.get('parameters',{}).items() if k!='effective_window'})
    if current['token']!=token:raise ValueError('信号已改变，请重新诊断。')
    event=next((e for e in analysis.get('events',[]) if e['id']==event_id),None)
    if event is None:raise ValueError('Event not found')
    source=analysis['parameters']['source'];b,t,y,fs=_signal(state,source)
    a=max(0,int(np.searchsorted(t,event['start'])));z=min(len(y),int(np.searchsorted(t,event['end'])))
    if z-a<2:raise ValueError('事件区间太短，无法验证。')
    segment=y[a:z].copy();trial=segment.copy();kind=event['kind'];method=''
    if kind=='narrowband':
        f=event['frequency_hz'];freq=np.fft.rfftfreq(len(segment),1/fs);fft=np.fft.rfft(segment)
        width=max(fs/len(segment)*1.5,fs/analysis['parameters']['effective_window'])
        fft[np.abs(freq-f)<=width]=0;trial=np.fft.irfft(fft,n=len(segment));method=f'区间 FFT 陷波 {f:.3g}±{width:.3g} Hz'
    elif kind=='impulse':
        padded=np.pad(y,(3,3),mode='edge');trial=np.median(np.lib.stride_tricks.sliding_window_view(padded,7)[a:z],axis=1);method='区间 7 点中值滤波'
    elif kind=='drift':
        coordinates=np.arange(len(segment));coeff=np.polyfit(coordinates,segment,1)
        trial=segment-np.polyval(coeff,coordinates);method='区间线性去趋势'
    elif kind in ('clipping','dropout'):
        if a==0 or z==len(y):raise ValueError('区间两侧缺少有效样本，不能验证插值。')
        trial=np.linspace(y[a-1],y[z],z-a+2)[1:-1];method='两侧端点线性插值（无法恢复真实高频细节）'
    else:
        raise ValueError('主频变化可能属于有效信号，请先检查时频图；此卡片不自动滤除。')
    # Blend edges of spectral/detrending trials to reduce abrupt seams.
    if kind in ('narrowband','drift'):
        edge=max(1,min(len(trial)//4,int(fs*.02)));weight=np.ones(len(trial))
        weight[:edge]=np.linspace(0,1,edge);weight[-edge:]=np.linspace(1,0,edge)
        trial=segment+weight*(trial-segment)
    output=y.copy();output[a:z]=trial
    metrics={'before_rms':float(np.sqrt(np.mean(segment**2))),'after_rms':float(np.sqrt(np.mean(trial**2))),
             'change_rms':float(np.sqrt(np.mean((trial-segment)**2))),'outside_unchanged':True,
             'before_rmse':None,'after_rmse':None}
    if b.has_clean_reference and not (lab.get('blind') and not lab.get('revealed')):
        metrics['before_rmse']=float(np.sqrt(np.mean((segment-b.clean[a:z])**2)))
        metrics['after_rmse']=float(np.sqrt(np.mean((trial-b.clean[a:z])**2)))
    if kind=='narrowband':
        k=np.abs(np.fft.rfftfreq(len(segment),1/fs)-event['frequency_hz'])<=width
        metrics['before_band_energy']=float(np.sum(np.abs(np.fft.rfft(segment))[k]**2)/len(segment)**2)
        metrics['after_band_energy']=float(np.sum(np.abs(np.fft.rfft(trial))[k]**2)/len(segment)**2)
    verdict='只有观测，不能据此证明更接近真实信号；能量降低也可能损伤有效成分。'
    if metrics['after_rmse'] is not None:
        verdict='参考区间误差降低。' if metrics['after_rmse']<metrics['before_rmse'] else '参考区间误差未降低，不建议直接采用。'
    lab['verification']={'signal':output,'token':token,'event_id':event_id,'method':method,'source':source,
                          'start':event['start'],'end':event['end'],'metrics':metrics,'verdict':verdict}
    state.diagnostic_lab=lab
    return {**{k:v for k,v in lab['verification'].items() if k!='signal'},
            'plot':dict(zip(('time','before','after'),decimate_for_export(t,y,output,max_points=520)))}


def adopt(state):
    lab=lab_for(state);v=lab.get('verification')
    if not v or v['token']!=lab.get('analysis',{}).get('token'):raise ValueError('请先运行有效的验证实验。')
    current=analyze(state,{k:value for k,value in lab['analysis']['parameters'].items() if k!='effective_window'})
    if current['token']!=v['token']:raise ValueError('处理结果已改变，请重新运行验证。')
    state.processed=PreprocessResult(signal=v['signal'].copy(),anomaly_mask=np.zeros(len(v['signal']),dtype=bool),
        removed_mean=0,smoothing_window=1,method='diagnostic_trial',method_label=v['method'],parameters={k:v[k] for k in ('start','end','event_id','method')})
    state.preprocess_results={};state.preprocess_comparison=None;state.summary=None;state.decision=None
    return public_lab(state)


def report_html(result,lab):
    grid=result['spectrogram'];db=np.asarray(grid['db']);rows,cols=db.shape[1],db.shape[0]
    rectangles=[]
    for i in range(cols):
        for j in range(rows):
            value=(db[i,j]+80)/80;hue=250-190*value
            rectangles.append(f'<rect x="{i*800/cols:.2f}" y="{(rows-j-1)*300/rows:.2f}" width="{800/cols+.1:.2f}" height="{300/rows+.1:.2f}" fill="hsl({hue:.1f} 80% {18+value*42:.1f}%)"/>')
    events=''.join(f'<tr><td>{escape(e["label"])}</td><td>{e["start"]:.4g}–{e["end"]:.4g} s</td><td>{escape(json.dumps(e["evidence"],ensure_ascii=False))}</td><td>{escape(e["alternatives"])}</td></tr>' for e in result['events'])
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>谛听诊断报告</title>'
        '<style>body{max-width:1100px;margin:30px auto;padding:20px;font:15px/1.65 system-ui;color:#182238}svg{width:100%}table{border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #ddd;text-align:left}.scroll{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
        f'<h1>谛听 · 信号诊断报告</h1><p>{escape(result["note"])}</p><p>时间 {result["parameters"]["start"]:.4g}–{result["parameters"]["end"]:.4g} s；频率 0–{grid["frequency"][-1]:.4g} Hz。颜色为 {escape(grid["label"])}，紫色低、黄色高。</p>'
        f'<svg viewBox="0 0 800 300" role="img" aria-label="时频图">{"".join(rectangles)}</svg><div class="scroll"><table><tr><th>事件</th><th>相对时间</th><th>证据</th><th>其他解释</th></tr>{events}</table></div>'
        f'<h2>参数、挑战与验证</h2><pre>{escape(json.dumps({"parameters":result["parameters"],"input_sha256":result["input_sha256"],"lab":lab},ensure_ascii=False,indent=2))}</pre></html>').encode()
