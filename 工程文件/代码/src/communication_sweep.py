"""Seeded parameter sweeps with live checkpoints and exact resume positions."""
import copy
import math
import time
import numpy as np

NOISE_FIELDS={'awgn':'esn0_db','complex_awgn':'snr_db','sample_awgn':'snr_db','bandlimited_awgn':'snr_db'}


def interval(errors,total):
    if not total: return [0.,1.]
    z=1.959963984540054;p=errors/total;d=1+z*z/total
    center=(p+z*z/(2*total))/d;half=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/d
    return [max(0.,center-half),min(1.,center+half)]


def parameter(raw,settings):
    from src import communications as c
    if not isinstance(settings,dict) or set(settings)-{'block_id','parameter','global','mode','start','stop','step','values','frames','target_errors'}: raise ValueError('扫描参数格式无效。')
    if settings.get('global'):
        key=settings['global'];specs={'seed':(0,4294967294,True),'sample_rate':(16,48000,False),'sample_count':(32,c.CONFIG['max_samples'],True),'symbol_rate':(1,100000,False)}
        if key not in specs: raise ValueError('未知全局扫描参数。')
        lo,hi,integer=specs[key];return None,key,{'min':lo,'max':hi,'type':'integer' if integer else 'number','label':key}
    block=next((b for b in raw['blocks'] if b['id']==settings.get('block_id')),None)
    if block is None: raise ValueError('请选择扫描积木。')
    key=settings.get('parameter') or NOISE_FIELDS.get(block['kind'])
    spec=c.BLOCKS[block['kind']]['params'].get(key)
    if spec is None or spec['type'] not in ('number','integer','select'): raise ValueError('请选择数值或枚举参数。')
    return block,key,spec


def sweep(raw,token,settings,progress=None,cancel=None,resume=None):
    from src import communications as c
    from src.communication_runtime import Cancelled
    compiled=c.build(raw)
    if token!=compiled['token']: raise ValueError('配置已改变，请重新 Build 后扫描。')
    p=compiled['program'];block,key,spec=parameter(p,settings)
    frames=c.numeric(settings.get('frames',10),'每点帧数',1,c.CONFIG['max_sweep_frames'],True)
    target=c.numeric(settings.get('target_errors',100),'目标错误数',1,100000,True)
    mode=settings.get('mode','native')
    noise=block is not None and NOISE_FIELDS.get(block['kind'])==key
    if mode not in ('native','ebn0') or mode=='ebn0' and not noise: raise ValueError('Eb/N₀ 模式需要选择噪声参数。')
    explicit=settings.get('values')
    if explicit is not None:
        if not isinstance(explicit,list) or not 1<=len(explicit)<=c.CONFIG['max_sweep_points']: raise ValueError('扫描值列表需要 1–21 项。')
        values=[c.numeric(v,'扫描值',-1e9,4294967294) for v in explicit]
    else:
        lo,hi=(-10,40) if noise else (spec.get('min',min(spec.get('choices',[0]))),spec.get('max',max(spec.get('choices',[1]))))
        start=c.numeric(settings.get('start',max(0,lo)),'起始值',lo,hi);stop=c.numeric(settings.get('stop',min(12,hi)),'结束值',lo,hi)
        step=c.numeric(settings.get('step',2),'步长',.000001,max(1,hi-lo))
        count=math.floor((stop-start)/step+1e-9)+1
        if count<1 or count>c.CONFIG['max_sweep_points']: raise ValueError('扫描需要 1–21 个递增参数值。')
        values=[start+i*step for i in range(count)]
    if len(values)*frames>c.CONFIG['max_sweep_runs']: raise ValueError('扫描总计最多 300 帧，请减少点数或帧数。')
    baseline=c.run(p,token);m=baseline['metrics'];real=baseline.get('transport')=='baseband'
    if 'bit_count' not in m and mode=='ebn0': raise ValueError('Eb/N₀ 标定需要数字信息比特。')
    shift=0.;eb=None
    if mode=='ebn0':
        if real:
            wave=baseline['baseband'];energy=wave['transmit_power']*wave['transmitter']['count'];power=wave['data_power']
        elif baseline.get('transport')=='advanced': energy=m['tx_energy'];power=energy/m['tx_sample_count']
        else:
            from src import advanced_communications as advanced
            source,texts,n=c.source_data(p);cal=advanced.run(advanced.build(p),source,texts,n,np.random.default_rng(np.random.SeedSequence(p['seed']).spawn(2)[1]))
            energy=cal['metrics']['tx_energy'];power=energy/cal['metrics']['tx_sample_count']
        if energy<=1e-20: raise ValueError('Eb/N₀ 标定需要非零发送能量。')
        eb=energy/m['bit_count'];shift=10*math.log10((1 if key=='esn0_db' else power)*(2 if real else 1)/eb)
    candidates=[]
    for value in values:
        candidate=copy.deepcopy(p);actual=value+shift
        if spec['type']=='integer': actual=c.numeric(actual,spec['label'],spec['min'],spec['max'],True)
        elif spec['type']=='select':
            if int(actual)!=actual or int(actual) not in spec['choices']: raise ValueError('扫描值不在该枚举参数的可选范围内。')
            actual=int(actual)
        else: actual=c.numeric(actual,spec['label'],spec['min'],spec['max'])
        if block is None: candidate[key]=actual
        else: next(b for b in candidate['blocks'] if b['id']==block['id'])['params'][key]=actual
        pure=noise and block['kind']=='awgn' and all(b['kind'] not in c.CHANNELS or b['kind'] in ('ideal','awgn') for b in candidate['blocks']) and sum(b['kind']=='awgn' for b in candidate['blocks'])==1
        if pure:
            for b in candidate['blocks']:
                if b['kind'].startswith('soft_'): b['params']['noise_variance']=max(.000001,min(100,10**(-actual/10)))
        c.build(candidate);candidates.append(candidate)
    from src import communication_rf as rf
    allowed={'random_bits','pn_bits','bit_pattern','text','mod_bpsk','mod_qpsk','awgn','ideal','demod_bpsk','demod_qpsk','sink'}
    allowed |= {'mod_'+s for s in rf.SCHEMES}|{'demod_'+s for s in rf.SCHEMES}
    scheme=next((b['kind'][4:] for b in p['blocks'] if b['kind'].startswith('mod_')),'bpsk')
    theory=noise and block['kind']=='awgn' and all(b['kind'] in allowed for b in p['blocks']) and sum(b['kind']=='awgn' for b in p['blocks'])==1
    rows=copy.deepcopy(resume.get('points',[])) if resume else [];started=time.monotonic();complete=True
    if resume and (resume.get('token')!=token or resume.get('settings')!=settings): raise ValueError('续跑配置与检查点不一致。')
    axis='Eb/N₀ / dB' if mode=='ebn0' else 'Es/N₀ / dB' if noise and key=='esn0_db' else '采样 SNR / dB' if noise else spec['label']
    result={'program':p,'token':token,'settings':settings,'mode':mode,'axis':axis,'parameter':key,'confidence':.95,'interval_method':'Wilson',
        'reference_eb':eb,'noise_db_shift':shift,'energy_reference':'发送参考帧总能量 / 信息比特数（含前导、导频、CP、尾位和填充）',
        'seed_policy':'每个扫描点使用相同种子序列 seed + 帧序号','points':rows,'complete':False,'elapsed_seconds':0.}
    for point_index,(value,candidate) in enumerate(zip(values,candidates)):
        old=rows[point_index] if point_index<len(rows) else None
        if old and old['db']==value and old['stop_reason'] in ('target_errors','frame_limit'): continue
        if old and old['db']!=value: raise ValueError('续跑参数点与检查点不一致。')
        counters={k:(old or {}).get(k,0) for k in ('bit_count','bit_errors','symbol_count','symbol_errors','frames','frame_errors','crc_detected_errors','rmse_sum','evm_sum','papr_sum','rate_sum','efficiency_sum')}
        reason='frame_limit'
        for iteration in range(counters['frames'],frames):
            if cancel is not None and cancel.is_set(): reason='cancelled';complete=False;break
            if time.monotonic()-started>c.CONFIG['max_sweep_seconds']: reason='time_limit';complete=False;break
            trial=copy.deepcopy(candidate);trial['seed']=(candidate['seed']+iteration)%4294967295
            built=c.build(trial)
            try: measured=c.run(built['program'],built['token'])['metrics']
            except Cancelled: reason='cancelled';complete=False;break
            for k in ('bit_count','bit_errors','symbol_count','symbol_errors'): counters[k]+=measured.get(k,0)
            counters['frames']+=1;counters['frame_errors']+=measured.get('frame_errors',int(measured.get('bit_errors',0)>0))
            counters['crc_detected_errors']+=measured.get('crc_detected_frame_errors') or 0;counters['rmse_sum']+=measured.get('rmse') or 0.
            for field,total in [('evm_percent','evm_sum'),('papr_db','papr_sum'),('net_bit_rate','rate_sum'),('spectral_efficiency','efficiency_sum')]: counters[total]+=measured.get(field) or 0.
            reason='target_errors' if counters['bit_errors']>=target else 'frame_limit' if counters['frames']==frames else 'running'
            row={'db':value,'noise_db':value+shift,**counters,'ber':counters['bit_errors']/max(1,counters['bit_count']),'ber_interval':interval(counters['bit_errors'],counters['bit_count']),
                'ser':counters['symbol_errors']/max(1,counters['symbol_count']),'ser_interval':interval(counters['symbol_errors'],counters['symbol_count']),
                'fer':counters['frame_errors']/counters['frames'],'fer_interval':interval(counters['frame_errors'],counters['frames']),
                'rmse':counters['rmse_sum']/counters['frames'],'evm_percent':counters['evm_sum']/counters['frames'],'papr_db':counters['papr_sum']/counters['frames'],'net_bit_rate':counters['rate_sum']/counters['frames'],'spectral_efficiency':counters['efficiency_sum']/counters['frames'],'stop_reason':reason}
            if theory:
                row['theory_ber']=rf.theory_ber(scheme,value+shift)
                result['theory_label']='相干 AWGN 精确 BER' if scheme in ('bpsk','qpsk') else 'Gray 映射 AWGN 最近邻 BER 近似（中高 SNR）'
            if old is None: rows.append(row);old=row
            else: rows[point_index]=row
            result.update(elapsed_seconds=time.monotonic()-started,completed_frames=sum(r['frames'] for r in rows),total_frames=len(values)*frames)
            if progress: progress(result)
            if reason=='target_errors': break
        if not complete:
            if point_index<len(rows): rows[point_index]['stop_reason']=reason
            break
    result.update(complete=complete,elapsed_seconds=time.monotonic()-started,completed_frames=sum(r['frames'] for r in rows),total_frames=len(values)*frames)
    if progress: progress(result)
    return result
