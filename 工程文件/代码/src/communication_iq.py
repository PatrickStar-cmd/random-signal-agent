"""SigMF recordings and receiver-only complex sample replay."""
import base64
import copy
import hashlib
import io
import json
import math
import tarfile
import numpy as np
from src import communication_dsp as dsp, communication_algorithms as algorithms
from src import communication_rf as rf, communication_runtime as runtime

SCHEMES = ('bpsk', 'qpsk', 'qam16', 'qam64', 'psk8', 'qam256')
DOMAINS = ('复符号', '复波形', 'OFDM 波形')
MAX_SAMPLES = 262144
RECEIVERS = {'rx_agc', 'rx_frequency', 'rx_carrier', 'rx_noise_estimate', 'rx_cma',
             'rx_matched', 'rx_timing', 'rx_frame', 'rx_equalizer', 'rx_ofdm',
             'rx_ofdm_frequency', 'rx_ofdm_tracking', 'rx_dc', 'rx_notch', 'resample'}


def encoded(samples):
    return base64.b64encode(np.asarray(samples, dtype='<c8').tobytes()).decode()


def register(block, number, field, blocks):
    samples = np.tile(np.array([1+1j, -1+1j, -1-1j, 1-1j])/math.sqrt(2), 32)
    def select(label, default, labels):
        return field(label, default, 'select', choices=list(labels), choice_labels=labels)
    block('iq_source', 'I/Q 录波信源', 'source', '导入 SigMF 或原始复数采样，配置接收格式后回放同步、均衡与解调。',
          data=field('复采样数据', encoded(samples), max_length=MAX_SAMPLES*12),
          name=field('录波名称', 'QPSK 演示录波', max_length=120),
          rate_hz=number('录波采样率 / Hz', 8000, 16, 1e9),
          center_hz=number('中心频率 / Hz', 0, 0, 1e12),
          mode=select('采样格式', 0, {0:'符号采样', 1:'RRC 脉冲波形', 2:'OFDM 波形'}),
          scheme=select('接收调制', 1, {i:v.upper() for i,v in enumerate(SCHEMES)}),
          sps=number('每符号采样', 4, 2, 16, True), rolloff=number('RRC 滚降', .35, .01, 1),
          span=number('RRC 跨度 / 符号', 8, 2, 32, True),
          nfft=select('FFT 点数', 64, {32:'32', 64:'64', 128:'128', 256:'256'}),
          cp=number('循环前缀', 16, 1, 64, True),
          active_count=number('有效子载波（0=全部）', 0, 0, 255, True),
          pilot_interval=number('导频间隔', 4, 2, 16, True),
          preamble_length=number('已知帧头长度', 64, 16, 1024, True),
          framed=field('包含公共帧头', False, 'boolean'),
          matched=field('已完成匹配滤波', False, 'boolean'),
          sample_offset=number('首符号脉冲中心 / 采样点', 0, 0, MAX_SAMPLES),
          payload_symbols=number('有效符号数（0=全部）', 0, 0, MAX_SAMPLES, True))


def presets(preset):
    p=preset(['iq_source', 'rx_agc', 'rx_carrier', 'demod_qpsk', 'sink'])
    p.update(sample_rate=8000, symbol_rate=8000)
    return {'iq_replay': {'label':'实测 · I/Q 录波与接收回放', 'program':p}}


def samples(q):
    try:
        raw=base64.b64decode(q['data'], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError('I/Q 数据需要 Base64 复数 float32 采样。') from exc
    if len(raw)%8 or not 8<=len(raw)<=MAX_SAMPLES*8:
        raise ValueError(f'I/Q 数据需要 1–{MAX_SAMPLES} 个复采样点。')
    values=np.frombuffer(raw,dtype='<c8').astype(complex)
    if not np.isfinite(values).all(): raise ValueError('I/Q 采样需要有限数值。')
    return values


def import_recording(data, metadata=None, name='录波', datatype='cf32_le', sample_rate=8000):
    """Read complex float32/int16 raw data or a SigMF tar without extracting files."""
    from src import communications as c
    if not isinstance(name,str) or not name: raise ValueError('录波名称需要非空字符串。')
    try: raw=base64.b64decode(data,validate=True)
    except (ValueError, TypeError) as exc: raise ValueError('录波数据需要有效的 Base64 字符串。') from exc
    if len(raw)>MAX_SAMPLES*16+1048576: raise ValueError('录波文件超过采样容量。')
    if name.lower().endswith('.sigmf'):
        try:
            with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
                members=[m for m in archive.getmembers() if m.isfile()]
                metas=[m for m in members if m.name.endswith('.sigmf-meta')]
                if len(metas)!=1 or metas[0].size>65536: raise ValueError('请选择包含一组数据的 SigMF 录波。')
                metadata=json.loads(archive.extractfile(metas[0]).read())
                expected=metas[0].name[:-len('.sigmf-meta')]+'.sigmf-data'
                matching=[m for m in members if m.name==expected]
                if len(matching)!=1 or matching[0].size>MAX_SAMPLES*16: raise ValueError('SigMF 采样文件大小或配对名称无效。')
                raw=archive.extractfile(matching[0]).read()
        except (tarfile.TarError, UnicodeDecodeError) as exc: raise ValueError('SigMF 录波需要包含数据与元数据的有效 TAR 包。') from exc
    meta=metadata if metadata is not None else {'global':{'core:datatype':datatype,'core:sample_rate':sample_rate}}
    if not isinstance(meta,dict) or not isinstance(meta.get('global'),dict) or any(k not in meta['global'] for k in ('core:datatype','core:sample_rate')):
        raise ValueError('SigMF 元数据需要 global 中的 core:datatype 和 core:sample_rate。')
    header=meta['global']; datatype=header['core:datatype']; fs=c.numeric(header['core:sample_rate'],'采样率',16,1e9)
    if header.get('core:num_channels',1)!=1: raise ValueError('请选择单通道复数 I/Q 录波。')
    if 'core:offset' in header and header['core:offset']!=0: raise ValueError('导入录波请从第 0 个采样开始。')
    types={'cf32_le':('<c8',1.),'cf64_le':('<c16',1.),'ci16_le':('<i2',32768.)}
    if not isinstance(datatype,str) or datatype not in types: raise ValueError('录波格式请选择 cf32_le、cf64_le 或 ci16_le。')
    dtype,scale=types[datatype]; stride=4 if datatype=='ci16_le' else np.dtype(dtype).itemsize
    if len(raw)%stride or not 1<=len(raw)//stride<=MAX_SAMPLES: raise ValueError('录波长度需要完整的 I/Q 采样对。')
    values=np.frombuffer(raw,dtype=dtype)
    if datatype=='ci16_le': values=(values[::2].astype(float)+1j*values[1::2])/scale
    if not np.isfinite(values).all(): raise ValueError('录波采样需要有限数值。')
    if header.get('core:sha512') and hashlib.sha512(raw).hexdigest()!=header['core:sha512']:
        raise ValueError('SigMF 数据 SHA-512 与元数据校验值不一致。')
    q={k:v['default'] for k,v in c.BLOCKS['iq_source']['params'].items()}
    receiver=header.get('randomsign:receiver',{})
    if not isinstance(receiver,dict): raise ValueError('randomsign:receiver 需要接收格式对象。')
    for key in ('mode','scheme','sps','rolloff','span','nfft','cp','active_count','pilot_interval','preamble_length','framed','matched','sample_offset','payload_symbols'):
        if key in receiver: q[key]=receiver[key]
    captures=meta.get('captures',[])
    if not isinstance(captures,list) or len(captures)>1 or any(not isinstance(item,dict) for item in captures): raise ValueError('SigMF captures 需要一段连续采集记录。')
    if any(item.get('core:sample_start',0)!=0 or item.get('core:header_bytes',0)!=0 for item in captures):
        raise ValueError('请选择从采样 0 开始、格式连续的单段录波。')
    q.update(data=encoded(values),name=name[:120],rate_hz=fs,center_hz=captures[0].get('core:frequency',0) if captures else 0)
    # Validate receiver metadata before using enum values as indexes.
    q=c.normalize(c.preset(['iq_source','demod_qpsk','sink'],{0:q}))['blocks'][0]['params']
    kinds=['iq_source']+(([] if q['matched'] else ['rx_matched'])+['rx_timing'] if q['mode']==1 else ['rx_ofdm'] if q['mode']==2 else [])+(['rx_frame'] if q['framed'] else [])+['demod_'+SCHEMES[q['scheme']],'sink']
    p=c.preset(kinds,{0:q});p.update(sample_rate=min(48000,fs),symbol_rate=min(100000,fs/(q['sps'] if q['mode']==1 else q['nfft'] if q['mode']==2 else 1)))
    built=c.build(p)
    return {'program':built['program'],'count':len(values),'sample_rate':fs,'metadata':meta,'sha256':hashlib.sha256(raw).hexdigest()}


def export_recording(values, rate, program, block_id, domain):
    from src import communications as c
    domain={'复采样波形':'复波形','复基带符号':'复符号'}.get(domain,domain)
    values=np.asarray(values)
    if values.ndim!=1 or domain not in DOMAINS: raise ValueError('选择复符号、复波形或 OFDM 波形观察点后导出 I/Q。')
    if not 1<=len(values)<=MAX_SAMPLES or not np.isfinite(values).all(): raise ValueError('导出需要容量范围内的有限复采样。')
    c.numeric(rate,'采样率',16,1e9)
    selected=next((i for i,b in enumerate(program['blocks']) if b['id']==block_id),None)
    if selected is None: raise ValueError('导出观察点需要属于当前工程。')
    prefix=program['blocks'][:selected+1]
    q={k:v['default'] for k,v in c.BLOCKS['iq_source']['params'].items() if k not in ('data','name')}
    mod=next((b for b in prefix if b['kind'].startswith('mod_')),None)
    if mod and mod['kind'][4:] in SCHEMES: q['scheme']=SCHEMES.index(mod['kind'][4:])
    original=next((b for b in prefix if b['kind']=='iq_source'),None)
    if original: q.update({k:v for k,v in original['params'].items() if k in q})
    q['mode']=DOMAINS.index(domain) if domain in DOMAINS else 0
    built=c.build(program); plans={row['id']:row for row in built['plan']}
    q.update(matched=False,sample_offset=0,payload_symbols=len(values) if domain=='复符号' else 0,framed=False)
    if original and domain!='复符号':
        q.update({k:original['params'][k] for k in ('matched','sample_offset','payload_symbols','framed')})
    elif original: q['framed']=original['params']['framed']
    for b in prefix:
        if b['kind'] in ('tx_rrc','tx_ofdm'): q.update({k:v for k,v in b['params'].items() if k in q})
        if b['kind']=='tx_frame': q.update(framed=True,preamble_length=b['params']['length'])
        if b['kind']=='tx_rrc' and domain=='复波形':
            q.update(sample_offset=1.5*b['params']['span']*b['params']['sps'],payload_symbols=plans[b['id']]['input_count'])
        if b['kind']=='tx_ofdm' and domain=='OFDM 波形': q['payload_symbols']=plans[b['id']]['input_count']
        if b['kind']=='rx_matched' and domain=='复波形':
            q['matched']=True;q['sample_offset']+=(len(dsp.rrc(q))-1)/2
        if b['kind']=='resample' and domain=='复波形': q['sample_offset']*=b['params']['up']/b['params']['down']
        if original and b['kind']=='rx_frame': q['framed']=True
    if domain=='复波形':
        sps=rate/program['symbol_rate'] if not original else q['sps']*rate/original['params']['rate_hz']
        if not float(sps).is_integer() or not 2<=sps<=16: raise ValueError('RRC 导出需要每符号 2–16 个整数采样点。')
        q['sps']=int(sps)
    q['rate_hz']=rate
    data=np.asarray(values,dtype='<c8').tobytes()
    meta={'global':{'core:datatype':'cf32_le','core:sample_rate':rate,'core:version':'1.2.6',
                   'core:description':f'RandomSign 积木观察点 {block_id}', 'core:sha512':hashlib.sha512(data).hexdigest(),
                   'core:extensions':[{'name':'randomsign','version':'0.4.8','optional':True}], 'randomsign:receiver':q},
          'captures':[{'core:sample_start':0,'core:frequency':q.get('center_hz',0)}],'annotations':[]}
    output=io.BytesIO()
    with tarfile.open(fileobj=output,mode='w') as archive:
        for name,content in [('recording.sigmf-data',data),('recording.sigmf-meta',json.dumps(meta,ensure_ascii=False,indent=2).encode())]:
            entry=tarfile.TarInfo(name);entry.size=len(content);archive.addfile(entry,io.BytesIO(content))
    return {'filename':'recording.sigmf','data':base64.b64encode(output.getvalue()).decode(),'count':len(values),'metadata':meta}


def build(p):
    from src import communications as c
    blocks=p['blocks']; q=blocks[0]['params']; plan=[]
    if blocks[0]['kind']!='iq_source' or blocks[-1]['kind']!='sink': raise ValueError('I/Q 链路以录波信源开始、信宿结束。')
    count=len(samples(q));domain=DOMAINS[q['mode']];scheme=SCHEMES[q['scheme']];consumed={'rx_matched'} if q['matched'] else set()
    if q['sample_offset']>=count: raise ValueError('首符号位置须位于录波采样范围内。')
    if q['mode']==0 and q['payload_symbols']>count: raise ValueError('有效符号数超过录波符号数。')
    if q['mode']==2:
        if q['cp']>q['nfft']: raise ValueError('循环前缀须小于等于 FFT 点数。')
        dsp.ofdm_indices(q['nfft'],q)
        if count<2*(q['nfft']+q['cp']): raise ValueError('OFDM 录波需要训练符号和数据符号。')
    for index,b in enumerate(blocks):
        k=b['kind']; before=count
        def fail(message): raise ValueError(f'第 {index+1} 块：{message}')
        if index==0: pass
        elif k in RECEIVERS:
            if domain in ('比特','LLR'): fail('接收处理位于解调之前。')
            if k in ('rx_matched','rx_timing') and domain!='复波形': fail('匹配滤波与定时恢复需要 RRC 波形。')
            if k=='rx_matched':
                if 'rx_matched' in consumed: fail('录波已经完成匹配滤波，可继续符号同步。')
                count+=len(dsp.rrc(q))-1;consumed.add(k)
            if k=='rx_timing':
                if 'rx_matched' not in consumed: fail('先进行匹配滤波。')
                count=q['payload_symbols'] or math.ceil(count/q['sps']);domain='复符号'
            if k.startswith('rx_ofdm'):
                if domain!='OFDM 波形': fail('OFDM 接收需要 OFDM 录波。')
                if k!='rx_ofdm_frequency': count=q['payload_symbols'] or (count//(q['nfft']+q['cp'])-1)*len(dsp.ofdm_indices(q['nfft'],q)[2]);domain='复符号'
            if k in ('rx_carrier','rx_equalizer','rx_cma','rx_frame','rx_noise_estimate') and domain!='复符号': fail('该处理需要符号采样。')
            if k=='rx_frame':
                if count<=q['preamble_length']: fail('帧头后需要至少一个接收符号。')
                consumed.add(k)
            if (k=='rx_equalizer' or k=='rx_noise_estimate' and b['params']['method']==0) and 'rx_frame' not in consumed:
                fail('公共前导训练需要先完成帧同步。')
            if k=='resample': count=math.ceil(count*b['params']['up']/b['params']['down'])
        elif k=='demod_'+scheme:
            if domain!='复符号': fail('先完成抽样或 OFDM 解调。')
            count=(count-(q['preamble_length'] if 'rx_frame' in consumed else 0))*len(dsp.constellation(scheme)[0][0]);domain='比特'
        elif k=='sink':
            if index!=len(blocks)-1 or domain!='比特': fail('录波接收链路以匹配解调和信宿结束。')
        else: fail('录波链路请选择接收处理、匹配解调与信宿。')
        if count>MAX_SAMPLES*8: fail('请减少录波长度或重采样倍率。')
        plan.append({'id':b['id'],'kind':k,'label':c.BLOCKS[k]['label'],'input_count':before,'count':count,'output':domain})
    token=hashlib.sha256(json.dumps(p,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()
    return {'program':p,'token':token,'plan':plan,'source_kind':'digital','transport':'iq','model':'I/Q 录波 · 接收回放',
            'summary':f'{len(blocks)} 个积木 · {len(samples(q))} 个录波采样 · {count} 个接收比特'}


def run(compiled):
    from src import communications as c
    from src.advanced_communications import view
    p=compiled['program']; first=p['blocks'][0]; q=first['params']; data=samples(q); original=data.copy(); fs=q['rate_hz']; snapshots=[]; recovery={}
    plan=copy.deepcopy(compiled['plan']); sample_offset=q['sample_offset']; receive_sps=float(q['sps']); prefix=0
    scheme=SCHEMES[q['scheme']]; _,points=dsp.constellation(scheme); preamble=dsp.public_preamble(q['preamble_length'],scheme)
    for index,b in enumerate(p['blocks']):
        runtime.enter(b); k=b['kind']; params=b['params']
        before=len(data)
        if k=='rx_agc': data,recovery['agc']=algorithms.agc(data,params)
        elif k=='rx_frequency': data,recovery['frequency']=dsp.coarse_frequency(data,fs,scheme)
        elif k=='rx_carrier': data,recovery['carrier']=dsp.carrier_recover(data,scheme,params['bandwidth'])
        elif k=='rx_noise_estimate': _,recovery['noise_estimate']=algorithms.noise_estimate(data,points,preamble if params['method']==0 else None)
        elif k=='rx_matched':
            pulse=dsp.rrc({**q,'sps':receive_sps});data=np.convolve(data,pulse[::-1]);sample_offset+=(len(pulse)-1)/2
        elif k=='rx_timing':
            if sample_offset:
                data=dsp.interp(data,np.arange(math.floor(len(data)-sample_offset))+sample_offset)
            data,recovery['timing']=dsp.timing_recover(data,receive_sps,params['bandwidth'],params['manual'],params['offset']);fs/=receive_sps
            if q['payload_symbols']:
                if len(data)<q['payload_symbols']: raise ValueError('录波恢复符号数少于元数据的有效符号数。')
                data=data[:q['payload_symbols']]
        elif k=='rx_frame':
            available=len(data);data,recovery['frame']=dsp.frame_sync(data,preamble,available,params['threshold'])
            data=data[:available-recovery['frame']['start_symbol']];prefix=len(preamble)
        elif k in ('rx_cma','rx_equalizer'): data,recovery['equalizer']=dsp.equalize(data,points,params,preamble if k=='rx_equalizer' else None,k=='rx_cma')
        elif k=='resample':
            ratio=params['up']/params['down'];data=algorithms.resample(data,params['up'],params['down']);fs*=ratio;receive_sps*=ratio;sample_offset*=ratio
        elif k=='rx_ofdm_frequency': data,recovery['frequency']=algorithms.ofdm_frequency(data,q,fs,params['search'])
        elif k in ('rx_ofdm','rx_ofdm_tracking'):
            if k=='rx_ofdm_tracking': start,_=algorithms.ofdm_acquire(data,q)
            else:
                training,_=dsp.ofdm_modulate(np.zeros(1,dtype=complex),q)
                start=int(np.argmax(abs(np.correlate(data,training[:q['nfft']+q['cp']],mode='valid'))))
            capacity=((len(data)-start)//(q['nfft']+q['cp'])-1)*len(dsp.ofdm_indices(q['nfft'],q)[2])
            count=q['payload_symbols'] or capacity
            if count<1 or count>capacity: raise ValueError('录波的完整 OFDM 数据符号不足，请核对有效符号数和 FFT / CP 配置。')
            if k=='rx_ofdm': data,recovery['ofdm']=dsp.ofdm_demodulate(data,q,params,count)
            else: data,recovery['ofdm']=algorithms.ofdm_tracking(data,q,params,count)
            fs=fs/q['nfft']
        elif k in ('rx_dc','rx_notch'): data,recovery[k]=rf.process(k,data,params,fs)
        elif k.startswith('demod_'): decisions=data[prefix:].copy();data,_=dsp.decisions(decisions,scheme)
        data=runtime.record(b,data,fs)
        plan[index].update(input_count=before,count=len(data))
        if k in RECEIVERS: snapshots.append({'id':b['id'],'label':c.BLOCKS[k]['label'],**view(data,c.CONFIG['plot_points'],fs)})
    spectrum=rf.measure(original,q['rate_hz']); decision_power=float(np.mean(abs(decisions)**2))
    metrics={'bit_count':0,'bit_errors':0,'ber':None,'symbol_count':len(decisions),'symbol_errors':0,'ser':None,
             'evm_percent':None,'rmse':None,'frame_count':1,'frame_errors':0,'fer':None,'received_bits':len(data),
             'rx_power':decision_power,'papr_db':spectrum['papr_db'],'tx_sample_count':0}
    return {'token':compiled['token'],'seed':p['seed'],'summary':f'{len(p["blocks"])} 个积木 · {len(original)} 个录波采样 · {len(data)} 个接收比特','model':compiled['model'],'transport':'iq','plan':plan,'metrics':metrics,
            'sink':{'kind':'digital','values':data[:256].tolist(),'reference':[],'count':len(data),'plot_count':min(256,len(data)),'sample_rate':None},
            'channel':view(original,c.CONFIG['plot_points'],q['rate_hz']),
            'advanced':{'scheme':scheme.upper(),'sample_rate':q['rate_hz'],'transmitter':view(original,256,q['rate_hz']),
                        'warnings':[],'spectrum':spectrum,'recovery':recovery,'stages':snapshots,'iq':{'name':q['name'],'samples':len(original),'center_hz':q['center_hz'],'metric_reference':'接收录波'}},
            'constellation':{'scheme':scheme,'count':min(1000,len(decisions)),'i':decisions[:1000].real.tolist(),'q':decisions[:1000].imag.tolist(),'ideal_i':points.real.tolist(),'ideal_q':points.imag.tolist(),'labels':[]},'text':None}
