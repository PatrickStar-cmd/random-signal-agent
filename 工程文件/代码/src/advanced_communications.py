"""Typed complex-sample pipeline for v0.4.3; old pipelines remain compatible."""
import hashlib
import json
import math
import numpy as np
from src import communication_codecs as codec, communication_dsp as dsp
from src import communication_runtime as runtime
from src import communication_algorithms as algorithms

SYMBOL_SCHEMES={'bpsk','qpsk','qam16','ook','dbpsk','dqpsk'}
WAVE_SCHEMES={'fsk2','msk','gmsk'}
TX_PROCESS={'tx_rrc','tx_frame','tx_pilots','tx_ofdm'}
RX_PROCESS={'rx_matched','rx_timing','rx_frame','rx_frequency','rx_carrier','rx_equalizer','rx_cma','rx_pilots','rx_ofdm','rx_complete','rx_agc','rx_noise_estimate','resample','rx_fse','rx_ofdm_frequency','rx_ofdm_tracking'}
EXT_ENCODERS=set(codec.PAIRS.values())-{'conv_encode'}


def source_count(block, p):
    k,q=block['kind'],block['params']
    if k in ('random_bits','pn_bits'): return q['count']
    if k=='bit_pattern': return len(q['pattern'])
    if k=='text': return len(q['text'].encode('utf-8'))*8
    return p['sample_count']


def build(p):
    from src import communications as c
    items=p['blocks']; sources=[]
    for b in items:
        if b['kind'] not in c.SOURCES: break
        sources.append(b)
    if not sources: raise ValueError('链路开头需要信源。')
    analog=sources[0]['kind'] in ('sine','square','gaussian')
    if any((b['kind'] in ('sine','square','gaussian'))!=analog for b in sources): raise ValueError('模拟与数字信源不能直接混合。')
    count=p['sample_count'] if analog else sum(source_count(b,p) for b in sources)
    if not analog and count>c.CONFIG['max_source_bits']: raise ValueError('合并信源超过比特上限。')
    for b in sources:
        if b['kind']=='pn_bits': codec.pn(1,b['params']['degree'],b['params']['initial'])
    domain='模拟样本' if analog else '比特'; direction='tx'; stack=[]; channels=0; scheme=None; features={}; consumed=set(); attenuation=0;receive_sps=1
    plan=[{'id':b['id'],'label':c.BLOCKS[b['kind']]['label'],'kind':b['kind'],'output':domain,'count':source_count(b,p)} for b in sources]
    for index,b in enumerate(items[len(sources):],len(sources)):
        k,q=b['kind'],b['params']; before=count
        def fail(message): raise ValueError(f'第 {index+1} 块「{c.BLOCKS[k]["label"]}」：{message}')
        if k in c.ENCODERS:
            if direction!='tx': fail('编码器须位于调制映射之前。')
            if k.startswith('line_'): fail('线路编码请连接实基带形成器。')
            if k in codec.SOURCE_CODECS or k=='pcm_encode':
                if domain!='模拟样本': fail('该信源编码需要模拟样本。')
                domain='比特'
            elif domain!='比特': fail('先将模拟信源编码成比特。')
            stack.append((k,q,count))
            if k in EXT_ENCODERS: count=codec.encoded_count(k,count,q)
            elif k=='pcm_encode': count*=q['bits']
            elif k=='repeat_encode': count*=q['factor']
            elif k=='hamming_encode': count=math.ceil(count/4)*7
            elif k=='conv_encode': count=(count+2)*2
            elif k=='interleave': count=math.ceil(count/q['columns'])*q['columns']
            else: fail('不支持该编码组合。')
            if k=='scramble': codec.pn(1,q['degree'],q['initial'])
        elif k.startswith('mod_'):
            if direction!='tx' or domain!='比特' or scheme: fail('数字映射需要编码后的比特，每条链路放置一个映射器。')
            scheme=k[4:]
            if scheme not in SYMBOL_SCHEMES|WAVE_SCHEMES: fail('该链路需要数字调制器。')
            features['modulator']=b; features['coded_count']=count
            if scheme in WAVE_SCHEMES:
                count=count*q['sps']+int(scheme in ('msk','gmsk')); domain='复采样波形'
            else:
                count=math.ceil(count/dsp.constellation(scheme)[0].shape[1])+int(scheme.startswith('d')); domain='复符号'
            features['mapped_count']=count; direction='signal_tx'
        elif k in TX_PROCESS:
            if direction!='signal_tx' or domain!='复符号' or k in features: fail('发送处理须位于映射器与信道之间，每种处理只放一次。')
            if scheme not in ('bpsk','qpsk','qam16'): fail('该处理支持 BPSK、QPSK 和 16QAM。')
            if k=='tx_pilots':
                if 'tx_frame' in features: fail('周期导频放在公共前导之前。')
                count+=math.ceil(count/q['interval'])
            elif k=='tx_frame': count+=q['length']
            elif k=='tx_rrc': count=count*q['sps']+3*q['span']*q['sps']; domain='复采样波形';receive_sps=q['sps']
            elif k=='tx_ofdm':
                if 'tx_frame' in features or 'tx_pilots' in features: fail('OFDM 自带训练和导频，请移除单载波组帧/导频。')
                if q['cp']>=q['nfft']: fail('CP 长度须小于 FFT 点数。')
                count=(math.ceil(count/len(dsp.ofdm_indices(q['nfft'])[2]))+1)*(q['nfft']+q['cp']); domain='OFDM 波形'
            features[k]={'params':q,'input_count':before,'count':count}
        elif k in c.CHANNELS:
            if direction not in ('signal_tx','channel'): fail('信道须放在发送处理之后、接收处理之前。')
            if domain not in ('复符号','复采样波形','OFDM 波形'): fail('信道输入须为复符号或波形。')
            allowed={'ideal','awgn','complex_awgn','attenuation','phase_shift','dropout','frequency_offset','phase_noise','sample_delay','complex_multipath','rayleigh','rician','clock_drift','timing_offset','time_multipath','burst_noise'}
            if k not in allowed: fail('该信道用于实基带或模拟链路。')
            if k=='awgn' and domain!='复符号': fail('过采样波形请选择复波形白噪声。')
            if k in ('clock_drift','timing_offset','sample_delay') and 'tx_rrc' not in features and 'tx_ofdm' not in features: fail('未知定时请使用 RRC 成形或 OFDM。')
            if k in ('clock_drift','timing_offset','sample_delay') and 'tx_rrc' in features and 'tx_frame' not in features: fail('未知定时接收需要公共前导组帧与帧同步。')
            if 'tx_ofdm' in features and k in ('clock_drift','timing_offset'): fail('OFDM 暂使用帧延迟，时钟漂移实验请选择 RRC。')
            if k=='complex_multipath': count+=len(dsp.complex_taps(q))-1
            if k=='time_multipath': algorithms.parse_paths(q)
            if k=='burst_noise' and q['bad_snr']>q['good_snr']: fail('坏状态 SNR 应不大于好状态 SNR。')
            if k=='sample_delay': count+=q['samples']+1
            if k=='clock_drift': count=math.ceil(count*(1+q['ppm']*1e-6))+1
            if k=='attenuation':
                attenuation+=q['db']
                if attenuation>100: fail('总衰减须不超过 100 dB。')
            fs=p['symbol_rate']*features.get('tx_rrc',{}).get('params',{}).get('sps',features.get('tx_ofdm',{}).get('params',{}).get('nfft',features['modulator']['params'].get('sps',1)))
            if k=='frequency_offset' and abs(q['hz'])>=fs/2: fail('频偏须小于采样率的一半。')
            if k in ('rayleigh','rician','time_multipath') and q['doppler']>=fs/2: fail('多普勒须小于采样率的一半。')
            channels+=1; direction='channel'
        elif k in RX_PROCESS:
            if direction not in ('channel','signal_rx') or not channels or k in consumed: fail('接收处理须位于信道之后、解调之前，每种处理只放一次。')
            direction='signal_rx'; consumed.add(k)
            if k=='rx_agc':
                if domain not in ('复符号','复采样波形','OFDM 波形'): fail('AGC 需要复符号或波形。')
            elif k=='rx_noise_estimate':
                if domain!='复符号' or scheme not in ('bpsk','qpsk','qam16'): fail('噪声估计需要 PSK/QAM 符号。')
                if q['method']==0 and 'rx_frame' not in consumed: fail('前导残差估计需要先完成帧同步。')
            elif k=='resample':
                if domain!='复采样波形' or 'tx_rrc' not in features or 'rx_matched' in consumed: fail('重采样放在 RRC 链路信道之后、匹配滤波之前。')
                receive_sps*=q['up']/q['down']
                if not 2<=receive_sps<=64: fail('重采样后每码元采样点须为 2–64。')
                count=math.ceil(count*q['up']/q['down']);features['receiver_sps']=receive_sps
            elif k=='rx_fse':
                if domain!='复采样波形' or not {'rx_matched'}<=consumed or 'tx_frame' not in features: fail('T/2 均衡需要公共前导和匹配滤波输出。')
                count=features['tx_frame']['count'];domain='复符号';consumed.add('rx_timing')
            elif k=='rx_ofdm_frequency':
                if domain!='OFDM 波形': fail('OFDM 频偏估计需要 OFDM 波形。')
            elif k=='rx_complete':
                if not {'tx_rrc','tx_frame'}<=features.keys() or domain!='复采样波形' or consumed!={'rx_complete'}: fail('一体接收需要 RRC 与公共前导，且不重复连接独立接收处理。')
                if scheme not in ('bpsk','qpsk'): fail('一体载波恢复支持 BPSK / QPSK。')
                consumed.update({'rx_matched','rx_timing','rx_frame','rx_frequency','rx_carrier'})
                domain='复符号'; count=features['tx_frame']['count']
            elif k=='rx_matched':
                if domain!='复采样波形' or 'tx_rrc' not in features: fail('匹配滤波需要发送 RRC。')
                count+=math.ceil(receive_sps*features['tx_rrc']['params']['span'])
            elif k=='rx_timing':
                if domain!='复采样波形' or 'rx_matched' not in consumed: fail('符号同步放在 RRC 匹配滤波之后。')
                count=math.ceil(count/receive_sps); domain='复符号'
            elif k=='rx_frequency':
                if scheme not in ('bpsk','qpsk') or domain=='OFDM 波形': fail('幂次粗频偏估计支持单载波 BPSK/QPSK。')
            elif k=='rx_carrier':
                if domain!='复符号' or scheme not in ('bpsk','qpsk','qam16'): fail('载波环需要抽样后的 PSK/QAM 符号。')
            elif k=='rx_frame':
                if domain!='复符号' or 'tx_frame' not in features: fail('帧同步需要公共前导和符号序列。')
                count=features['tx_frame']['count']
            elif k in ('rx_equalizer','rx_cma'):
                if domain!='复符号' or scheme not in ('bpsk','qpsk','qam16'): fail('均衡器需要 PSK/QAM 复符号。')
                if k=='rx_equalizer' and 'rx_frame' not in consumed: fail('训练均衡先进行帧同步。')
                if k=='rx_cma' and 'rx_frame' in consumed: fail('CMA 放在帧同步之前，由前导修正盲均衡的相位。')
            elif k=='rx_pilots':
                if domain!='复符号' or 'tx_pilots' not in features: fail('需要配对的周期导频插入。')
                if 'tx_frame' in features and 'rx_frame' not in consumed: fail('先定位帧，再做周期导频估计。')
                count=features['tx_pilots']['input_count']+features.get('tx_frame',{}).get('params',{}).get('length',0)
            elif k in ('rx_ofdm','rx_ofdm_tracking'):
                if domain!='OFDM 波形' or 'tx_ofdm' not in features: fail('OFDM 接收需要配对的发送 OFDM。')
                count=features['tx_ofdm']['input_count']; domain='复符号';consumed.add('rx_ofdm')
        elif k.startswith('demod_') or k.startswith('soft_'):
            requested=k.split('_',1)[1]
            if direction not in ('channel','signal_rx') or not channels or requested!=scheme: fail('解调方式须与发送映射匹配。')
            if scheme in SYMBOL_SCHEMES and domain!='复符号': fail('先完成波形接收滤波 / 抽样或 OFDM 解调。')
            if q.get('automatic_variance') and 'rx_noise_estimate' not in consumed: fail('自动 LLR 方差需要接收噪声方差估计积木。')
            for tx,rx in [('tx_frame','rx_frame'),('tx_rrc','rx_timing'),('tx_pilots','rx_pilots'),('tx_ofdm','rx_ofdm')]:
                if tx in features and rx not in consumed: fail('缺少 '+c.BLOCKS[rx]['label']+'。')
            count=features['coded_count']; domain='LLR' if k.startswith('soft_') else '比特'; direction='rx'
        elif k in c.PAIRS:
            if direction!='rx' or not stack: fail('缺少配对发送编码器。')
            expected,params,original=stack.pop()
            if c.PAIRS[k]!=expected: fail('须按发送编码的相反顺序译码。')
            if k not in ('ldpc_decode','conv_soft_decode') and q!=params: fail('配对编码参数须一致。')
            if k in ('ldpc_decode','conv_soft_decode'):
                if domain!='LLR': fail('该译码需要软解调输出的 LLR。')
                domain='比特'
            elif k=='deinterleave' and domain=='LLR': pass
            elif domain!='比特': fail('先将软信息译码为比特。')
            if expected in codec.SOURCE_CODECS or expected=='pcm_encode': domain='模拟样本'
            count=original
        elif k=='sink':
            if index!=len(items)-1 or direction!='rx' or stack or domain!=('模拟样本' if analog else '比特'): fail('信宿需要完整配对的收发链路。')
        else: fail('当前信号类型无法连接此积木。')
        limit=c.CONFIG['max_bits'] if domain in ('比特','LLR') else c.CONFIG['max_wave_samples']
        if count>limit: fail(f'中间数据超过 {limit} 点/位，请减少信源或采样点。')
        plan.append({'id':b['id'],'kind':k,'label':c.BLOCKS[k]['label'],'input_count':before,'count':count,'output':domain})
    if items[-1]['kind']!='sink' or scheme is None: raise ValueError('请完成收发链路并以信宿结束。')
    token=hashlib.sha256(json.dumps(p,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()
    return {'program':p,'token':token,'plan':plan,'source_kind':'analog' if analog else 'digital','transport':'advanced','features':features,'model':'数字复基带 · 独立处理积木 · 帧 / 导频 / 软信息', 'summary':f'{len(sources)} 个信源 · {len(items)} 个积木 · {count} 个接收'+('样本' if analog else '比特')}


def view(data, limit, fs):
    data=np.asarray(data,dtype=complex); shown=data[:limit]
    return {'count':len(data),'plot_count':len(shown),'symbol_rate':fs,'i':shown.real.tolist(),'q':shown.imag.tolist()}


def run(compiled, source, texts, source_count, rng):
    from src import communications as c
    p=compiled['program']; f=compiled['features']; data=source.copy(); analog=compiled['source_kind']=='analog'
    reference=None if analog else source.copy(); stack=[]; info={}; snapshots=[]; recovery={}; gain=1+0j; prefix=0
    fs=p['symbol_rate']; tx=None; channel=None; tx_power=1.; in_channel=False; decoded_bits=None; clipped=corrections=0; eye=None;noise_estimate=None
    receive_sps=f.get('receiver_sps',f.get('tx_rrc',{}).get('params',{}).get('sps',1))
    for b in p['blocks'][source_count:]:
        runtime.enter(b)
        k,q=b['kind'],b['params']; before=len(data)
        if k in c.ENCODERS:
            stack.append((k,q,before))
            if k in EXT_ENCODERS:
                if k=='compand_encode': clipped=int(np.count_nonzero(abs(data)>q['full_scale']))
                data=codec.encode(k,data,q)
                if k in codec.SOURCE_CODECS: reference=data.copy()
            elif k=='pcm_encode':
                clipped=int(np.count_nonzero(abs(data)>q['full_scale']))
                data=codec.words_to_bits(np.rint((np.clip(data,-q['full_scale'],q['full_scale'])+q['full_scale'])/(2*q['full_scale'])*(2**q['bits']-1)),q['bits']); reference=data.copy()
            elif k=='repeat_encode': data=np.repeat(data,q['factor'])
            elif k=='hamming_encode': data=c.hamming_encode(data)
            elif k=='conv_encode': data=c.conv_encode(data)
            elif k=='interleave': data=np.pad(data,(0,-len(data)%q['columns'])).reshape(-1,q['columns']).T.ravel()
        elif k.startswith('mod_'):
            encoded=data.copy(); scheme=k[4:]; modulation=q
            if scheme in WAVE_SCHEMES:
                data=dsp.frequency_modulate(data,scheme,q); transmitted_indices=encoded.copy(); mapped=data.copy(); fs*=q['sps']
            else: data,transmitted_indices=dsp.map_bits(data,scheme); mapped=data.copy()
        elif k=='tx_pilots': data=dsp.insert_pilots(data,q['interval'])
        elif k=='tx_frame':
            preamble=dsp.public_preamble(q['length'],scheme); data=np.r_[preamble,data]
        elif k=='tx_rrc':
            h=dsp.rrc(q); up=np.zeros(len(data)*q['sps'],dtype=complex); up[::q['sps']]=data
            guard=q['sps']*q['span']; data=np.convolve(np.pad(up,(guard,guard)),h); fs=p['symbol_rate']*q['sps']
        elif k=='tx_ofdm':
            data,info['ofdm']=dsp.ofdm_modulate(data,q); fs=p['symbol_rate']*q['nfft']
        elif k in c.CHANNELS:
            if not in_channel:
                tx=data.copy(); tx_power=float(np.mean(abs(tx)**2)); in_channel=True
            if k=='awgn':
                variance=10**(-q['esn0_db']/10); data=data+math.sqrt(variance/2)*(rng.normal(size=len(data))+1j*rng.normal(size=len(data)))
            elif k=='complex_awgn':
                variance=tx_power*10**(-q['snr_db']/10); data=data+math.sqrt(variance/2)*(rng.normal(size=len(data))+1j*rng.normal(size=len(data)))
            elif k in ('attenuation','phase_shift'):
                factor=10**(-q['db']/20) if k=='attenuation' else np.exp(1j*np.deg2rad(q['degrees'])); gain*=factor; data=data*factor
            elif k=='dropout': data=data*(rng.random(len(data))>=q['probability'])
            elif k=='frequency_offset':
                memory=runtime.state('frequency_offset',lambda:{'phase':0.});phases=memory['phase']+2*np.pi*q['hz']*np.arange(len(data))/fs
                memory['phase']=float((memory['phase']+2*np.pi*q['hz']*len(data)/fs)%(2*np.pi));data=data*np.exp(1j*phases)
            elif k=='phase_noise':
                memory=runtime.state('phase_noise',lambda:{'phase':0.});phases=memory['phase']+np.cumsum(rng.normal(0,np.deg2rad(q['std']),len(data)))
                memory['phase']=float(phases[-1]%(2*np.pi));data=data*np.exp(1j*phases)
            elif k=='sample_delay': data=dsp.interp(data,np.arange(len(data)+q['samples']+1)-q['samples']-q['fraction'])
            elif k=='timing_offset': data=dsp.interp(data,np.arange(len(data))-q['offset']*f['tx_rrc']['params']['sps'])
            elif k=='clock_drift':
                scale=1+q['ppm']*1e-6; data=dsp.interp(data,np.arange(math.ceil(len(data)*scale)+1)/scale)
            elif k=='complex_multipath': data=np.convolve(data,dsp.complex_taps(q))
            elif k in ('rayleigh','rician'): data=data*dsp.fading(len(data),fs,q['doppler'],rng,q.get('k_db'))
            elif k=='time_multipath': data=algorithms.time_multipath(data,q,fs,rng)
            elif k=='burst_noise': data,info['burst']=algorithms.burst_noise(data,q,tx_power,rng)
            channel=data.copy()
        elif k in RX_PROCESS:
            if k=='rx_agc':
                data,info['agc']=algorithms.agc(data,q);gain=gain/abs(gain)
            elif k=='rx_noise_estimate': noise_estimate,info['noise_estimate']=algorithms.noise_estimate(data,dsp.constellation(scheme)[1],preamble if q['method']==0 else None)
            elif k=='resample': data=algorithms.resample(data,q['up'],q['down']);fs*=q['up']/q['down']
            elif k=='rx_fse':
                data,recovery['equalizer']=algorithms.fse(data,receive_sps,preamble,f['tx_frame']['count'],dsp.constellation(scheme)[1],q);fs=p['symbol_rate'];gain=1+0j
            elif k=='rx_ofdm_frequency': data,recovery['frequency']=algorithms.ofdm_frequency(data,f['tx_ofdm']['params'],fs,q['search'])
            elif k=='rx_ofdm_tracking':
                data,estimate=algorithms.ofdm_tracking(data,f['tx_ofdm']['params'],q,f['tx_ofdm']['input_count']);info['ofdm'].update(estimate);gain=1+0j;fs=p['symbol_rate']
            elif k=='rx_frequency': data,recovery['frequency']=dsp.coarse_frequency(data,fs,scheme)
            elif k=='rx_matched':
                receive_pulse={**f['tx_rrc']['params'],'sps':receive_sps};data=np.convolve(data,dsp.rrc(receive_pulse)[::-1]);eye=eye_view(data,receive_pulse)
            elif k=='rx_timing':
                data,recovery['timing']=dsp.timing_recover(data,receive_sps,q['bandwidth'],q['manual'],q['offset']); fs=p['symbol_rate']
                if 'tx_frame' not in f: data=data[2*f['tx_rrc']['params']['span']:][:f['tx_rrc']['input_count']]
            elif k=='rx_carrier':
                data,recovery['carrier']=dsp.carrier_recover(data,scheme,q['bandwidth']); gain=abs(gain)
            elif k=='rx_frame':
                data,recovery['frame']=dsp.frame_sync(data,preamble,f['tx_frame']['count'],q['threshold']); prefix=len(preamble); gain=1+0j
            elif k in ('rx_equalizer','rx_cma'):
                data,recovery['equalizer']=dsp.equalize(data,dsp.constellation(scheme)[1],q,None if k=='rx_cma' else preamble,k=='rx_cma')
            elif k=='rx_pilots':
                payload,info['pilots']=dsp.estimate_pilots(data[prefix:],f['tx_pilots']['params']['interval'],f['tx_pilots']['input_count'],q['floor'])
                data=np.r_[data[:prefix],payload]; gain=1+0j
            elif k=='rx_ofdm':
                data,estimate=dsp.ofdm_demodulate(data,f['tx_ofdm']['params'],q,f['tx_ofdm']['input_count']); info['ofdm'].update(estimate)
                if q['equalize']: gain=1+0j
            elif k=='rx_complete':
                data,recovery['frequency']=dsp.coarse_frequency(data,fs,scheme)
                data=np.convolve(data,dsp.rrc(f['tx_rrc']['params'])[::-1])
                eye=eye_view(data,f['tx_rrc']['params'])
                data,recovery['timing']=dsp.timing_recover(data,f['tx_rrc']['params']['sps']); fs=p['symbol_rate']
                data,recovery['carrier']=dsp.carrier_recover(data,scheme,q['bandwidth'])
                data,recovery['frame']=dsp.frame_sync(data,preamble,f['tx_frame']['count'],.45); prefix=len(preamble); gain=1+0j
            snapshots.append({'id':b['id'],'label':c.BLOCKS[k]['label'],**view(data,c.CONFIG['plot_points'],fs)})
        elif k.startswith('demod_') or k.startswith('soft_'):
            received=data[prefix:]; received=received/gain if q.get('compensate',False) else received
            if scheme in WAVE_SCHEMES:
                received=np.pad(received[:len(mapped)],(0,max(0,len(mapped)-len(received))))
                data=dsp.frequency_demodulate(received,scheme,modulation,q.get('coherent',False)); decided_indices=data.copy(); decision_symbols=received; points=np.array([-1,1],dtype=complex)
            else:
                received=np.pad(received[:len(mapped)],(0,max(0,len(mapped)-len(received))))
                hard,decided_indices=dsp.decisions(received,scheme); decision_symbols=received; _,points=dsp.constellation(scheme)
                data=dsp.soft_demod(received,scheme,noise_estimate if q.get('automatic_variance') else q['noise_variance']) if k.startswith('soft_') else hard
            data=data[:len(encoded)]; demapped=(data<0).astype(np.uint8) if k.startswith('soft_') else data.copy()
        elif k in c.PAIRS:
            encoder,params,size=stack.pop()
            if encoder in codec.SOURCE_CODECS or encoder=='pcm_encode': decoded_bits=data.copy()
            if k in codec.PAIRS:
                data,details=codec.decode(k,data,q); info.setdefault('codecs',[]).append({'kind':k,**details})
            elif k=='repeat_decode': data=(data.reshape(-1,q['factor']).sum(axis=1)>q['factor']//2).astype(np.uint8)
            elif k=='hamming_decode': data,n=c.hamming_decode(data); corrections+=n
            elif k=='conv_decode': data=c.viterbi_decode(data)
            elif k=='deinterleave': data=data.reshape(q['columns'],-1).T.ravel()
            elif k=='pcm_decode': data=codec.bits_to_words(data,q['bits'])/(2**q['bits']-1)*2*q['full_scale']-q['full_scale']
            data=data[:size]
        data=runtime.record(b,data,fs)
    if not analog: decoded_bits=data.astype(np.uint8)
    errors=int(np.count_nonzero(reference!=decoded_bits)); coded_errors=int(np.count_nonzero(encoded!=demapped))
    bit_count=len(reference); symbol_errors=int(np.count_nonzero(transmitted_indices!=decided_indices))
    crc_results=[v['crc_pass'] for v in info.get('codecs',[]) if 'crc_pass' in v]
    frame_error=int(errors>0 or not recovery.get('frame',{}).get('detected',True))
    metrics={'bit_count':bit_count,'bit_errors':errors,'ber':errors/bit_count,'coded_bit_count':len(encoded),'coded_bit_errors':coded_errors,'coded_ber':coded_errors/len(encoded),
             'symbol_count':len(transmitted_indices),'symbol_errors':symbol_errors,'ser':symbol_errors/len(transmitted_indices),'effective_rate':bit_count/len(encoded),
             'evm_percent':float(100*np.linalg.norm(decision_symbols-mapped)/max(np.linalg.norm(mapped),1e-12)),
             'rmse':float(np.sqrt(np.mean((data-source)**2))) if analog else None,'clipped_samples':clipped,'hamming_syndromes':corrections,
             'frame_errors':frame_error,'frame_count':1,'fer':float(frame_error),'crc_pass':all(crc_results) if crc_results else None,
             'crc_detected_frame_errors':int(not all(crc_results)) if crc_results else None,'tx_energy':float(np.sum(abs(tx)**2)), 'tx_sample_count':len(tx)}
    scatter=min(len(decision_symbols),c.CONFIG['scatter_points']); n=min(len(tx),1024)
    spectrum=abs(np.fft.fftshift(np.fft.fft(tx)))**2/(len(tx)*channel_fs(compiled))
    frequency=np.fft.fftshift(np.fft.fftfreq(len(tx),1/channel_fs(compiled)))
    selected=np.linspace(0,len(tx)-1,min(1024,len(tx)),dtype=int); spectrum=spectrum[selected]; frequency=frequency[selected]
    shown=c.CONFIG['plot_points']
    advanced={'scheme':scheme.upper(),'sample_rate':channel_fs(compiled),'transmitter':view(tx,shown,channel_fs(compiled)), 'warnings':[], 'spectrum':{'frequency_hz':frequency.tolist(),'density_db':(10*np.log10(np.maximum(spectrum,1e-12))).tolist()},'recovery':recovery,'stages':snapshots,**info}
    if eye is not None: advanced['eye']=eye
    if any(b['kind']=='pn_bits' for b in p['blocks']):
        bits=2*source.astype(float)-1; autocorr=np.fft.ifft(abs(np.fft.fft(bits))**2).real/len(bits)
        advanced['source_correlation']=autocorr[:min(256,len(bits))].tolist()
    result={'token':compiled['token'],'seed':p['seed'],'summary':compiled['summary'],'model':compiled['model'],'transport':'advanced','plan':compiled['plan'],'metrics':metrics,
            'sink':{'kind':compiled['source_kind'],'values':data.tolist(),'reference':source.tolist(),'sample_rate':p['sample_rate'] if analog else None,'count':len(data),'plot_count':min(len(data),shown)},
            'channel':view(channel,shown,channel_fs(compiled)), 'advanced':advanced,
            'constellation':{'scheme':scheme,'count':scatter,'i':decision_symbols[:scatter].real.tolist(),'q':decision_symbols[:scatter].imag.tolist(),'ideal_i':points.real.tolist(),'ideal_q':points.imag.tolist(),'labels':[]},'text':None}
    if not analog and len(texts)==source_count: result['text']={'sent':b''.join(texts).decode('utf-8'),'received':np.packbits(decoded_bits).tobytes().decode('utf-8',errors='replace')}
    json.dumps(result,allow_nan=False)
    return result


def channel_fs(compiled):
    f=compiled['features']; return compiled['program']['symbol_rate']*f.get('tx_rrc',{}).get('params',{}).get('sps',f.get('tx_ofdm',{}).get('params',{}).get('nfft',f['modulator']['params'].get('sps',1)))


def eye_view(wave,q):
    sps=q['sps']; start=2*q['span']*sps; traces=[]
    for i in range(64):
        positions=start+i*sps+np.linspace(0,2*sps,int(round(2*sps))+1)
        if positions[-1]>=len(wave): break
        segment=dsp.interp(wave,positions)
        traces.extend([segment.real.tolist(),segment.imag.tolist()])
    return {'samples_per_symbol':sps,'traces':traces}
