"""Signal contracts, connection guidance, project snapshots and shared branches."""
import copy
import hashlib
import json
import re
import threading
import uuid
from datetime import datetime,timezone
from pathlib import Path
from src import communication_runtime as runtime


def contract(kind):
    from src import communications as c
    if kind == 'iq_source': return ['起点'], '复符号'
    if kind in ('sine','square','gaussian','audio_source'): return ['起点'],'模拟样本'
    if kind in c.SOURCES: return ['起点'],'比特'
    if kind=='sink': return ['比特','模拟样本'],'信宿'
    if kind in ('pcm_encode','compand_encode','dpcm_encode','delta_encode','adpcm_encode'): return ['模拟样本'],'比特'
    if kind in ('pcm_decode','compand_decode','dpcm_decode','delta_decode','adpcm_decode'): return ['比特'],'模拟样本'
    if kind.startswith('line_'): return (['比特'],'线路电平') if kind.endswith('encode') else (['线路电平'],'比特')
    if kind=='depuncture': return ['LLR'],'LLR'
    if kind in ('conv_soft_decode','ldpc_decode','polar_decode','turbo_decode'): return ['LLR'],'比特'
    if kind in c.ENCODERS: return ['比特'],'比特'
    if kind=='deinterleave': return ['比特','LLR'],'同输入'
    if kind in c.PAIRS: return ['比特'],'比特'
    if kind=='mod_baseband': return ['线路电平'],'实波形'
    if kind=='mod_pam': return ['比特'],'实波形'
    if kind in ('demod_baseband','demod_pam'): return ['实波形'],'线路电平' if kind=='demod_baseband' else '比特'
    if kind.startswith('mod_'):
        if kind[4:] in ('am','dsb','ssb','vsb','fm','pm'): return ['模拟样本'],'模拟复包络'
        return ['比特'],'复波形' if kind in ('mod_fsk2','mod_msk','mod_gmsk') else '复符号'
    if kind.startswith('soft_'): return ['复符号'],'LLR'
    if kind.startswith('demod_'):
        if kind[6:] in ('am','dsb','ssb','vsb','fm','pm'): return ['模拟复包络'],'模拟样本'
        return ['复波形'] if kind in ('demod_fsk2','demod_msk','demod_gmsk') else ['复符号'],'比特'
    special={'tx_self_frame':(['复符号'],'复波形'),'frame_stream_channel':(['复波形'],'复波形'),'rx_self_frame':(['复波形','复采样波形'],'复符号'),
        'tx_isac_ofdm':(['复符号'],'OFDM 波形'),'isac_echo':(['OFDM 波形'],'OFDM 波形'),'rx_isac_ofdm':(['OFDM 波形'],'复符号'),
        'rx_mlse':(['复符号'],'复符号'),'rx_music':(['多天线符号'],'多天线符号'),'rx_music_mvdr':(['多天线符号'],'复符号'),
        'tdl_channel':(['复符号','复波形','OFDM 波形'],'同输入'),
        'tx_rrc':(['复符号'],'复波形'),'tx_ofdm':(['复符号'],'OFDM 波形'),
        **{k:(['复符号'],'多天线符号') for k in ('tx_array','tx_mrt','tx_svd')},
        **{k:(['多天线符号'],'多天线符号') for k in ('array_channel','array_interference')},
        'tx_scfdma':(['复符号'],'OFDM 波形'),'rx_scfdma':(['OFDM 波形'],'复符号'),
        **{k:(['OFDM 波形'],'OFDM 波形') for k in ('tx_burst_preamble','burst_clock','rx_burst_sync')},
        **{k:(['复符号'],'复符号') for k in ('tx_dft_spread','rx_dft_despread')},
        **{k:(['复符号','复波形','OFDM 波形'],'同输入') for k in ('tx_pa_probe','tx_dpd_fit','tx_dpd','tx_memory_pa')},
        **{k:(['多天线符号'],'复符号') for k in ('rx_mimo_lmmse','rx_mimo_kalman','rx_mimo_soft','rx_array_conventional','rx_array_mvdr','rx_array_svd')},
        'tx_dsss':(['复符号'],'扩频码片'),'dsss_multipath':(['扩频码片'],'扩频码片'),'rx_code_acquire':(['扩频码片'],'扩频码片'),
        'rx_despread':(['扩频码片'],'复符号'),'rx_rake':(['扩频码片'],'复符号'),
        **{k:(['复符号'],'多天线符号') for k in ('tx_simo','tx_alamouti','tx_mimo','tx_mimo_tracking','tx_mimo_ofdm')},
        **{k:(['多天线符号'],'多天线符号') for k in ('spatial_channel','spatial_dynamic','spatial_multipath')},
        **{k:(['多天线符号'],'复符号') for k in ('rx_selection','rx_mrc','rx_alamouti','rx_mimo_zf','rx_mimo_mmse','rx_mimo_zf_sic','rx_mimo_mmse_sic','rx_mimo_tracking','rx_mimo_ofdm')},
        'tx_ofdma':(['复符号'],'多用户波形'),'ofdma_channel':(['多用户波形'],'多用户波形'),'rx_ofdma':(['多用户波形'],'复符号'),
        'tx_fhss':(['复符号'],'跳频波形'),'rx_hop_sync':(['跳频波形'],'跳频波形'),'rx_dehop':(['跳频波形'],'复符号'),
        'rx_matched':(['复波形'],'复波形'),'rx_timing':(['复波形'],'复符号'),'rx_fse':(['复波形'],'复符号'),
        'rx_complete':(['复波形'],'复符号'),'rx_ofdm':(['OFDM 波形'],'复符号'),
        'rx_ofdm_frequency':(['OFDM 波形'],'OFDM 波形'),'rx_ofdm_tracking':(['OFDM 波形'],'复符号'),'resample':(['复波形'],'复波形')}
    if kind in special: return special[kind]
    if kind=='narrowband': return ['复符号','复波形','OFDM 波形','扩频码片','跳频波形'],'同输入'
    if kind in ('tx_pa','iq_imbalance','dc_offset','adc','rx_dc','rx_notch'): return ['复符号','复波形','OFDM 波形'],'同输入'
    if kind=='tx_clip_filter': return ['OFDM 波形'],'OFDM 波形'
    if kind=='rx_iq': return ['复符号'],'复符号'
    if kind.startswith('tx_') or kind in ('rx_frame','rx_carrier','rx_equalizer','rx_cma','rx_pilots','rx_noise_estimate'): return ['复符号'],'复符号'
    if kind=='rx_frequency': return ['复波形','复符号'],'同输入'
    if kind=='rx_agc': return ['复波形','复符号','OFDM 波形'],'同输入'
    if kind in ('awgn',): return ['复符号'],'同输入'
    if kind=='analog_awgn': return ['模拟复包络'],'同输入'
    if kind in ('sample_awgn','bandlimited_awgn','lowpass_channel','bandpass_channel','ac_coupling','isi_channel'): return ['实波形'],'同输入'
    return ['复符号','复波形','OFDM 波形','实波形','模拟复包络','扩频码片','跳频波形'],'同输入'


def describe(program):
    from src import communications as c
    p=c.normalize(program,draft=True); domain='起点'; fs=p['sample_rate']; rs=p['symbol_rate']; rows=[]
    for b in p['blocks']:
        accepts,output=contract(b['kind']); compatible=domain in accepts or b['kind'] in c.SOURCES
        if b['kind'] == 'iq_source':
            q=b['params'];output=('复符号', '复波形', 'OFDM 波形','复波形')[q['mode']];fs=q['rate_hz'];rs=fs/(q['sps'] if q['mode']==1 else q['nfft'] if q['mode']==2 else 1)
        if b['kind'] in ('tx_rrc','mod_pam','mod_baseband','mod_fsk2','mod_msk','mod_gmsk'): fs=(p['symbol_rate'] or 1)*(b['params'].get('sps') or 1)
        elif b['kind']=='tx_dsss': fs=(p['symbol_rate'] or 1)*(2**b['params']['degree']-1)
        elif b['kind'] in ('tx_ofdm','tx_scfdma','tx_isac_ofdm'): fs=(p['symbol_rate'] or 1)*(b['params'].get('nfft') or 1)
        elif b['kind']=='tx_fhss': fs=p['symbol_rate']*b['params']['sps']
        elif b['kind'] in ('tx_mimo_ofdm','tx_ofdma'): fs=p['symbol_rate']*b['params']['nfft']
        elif b['kind'] in ('rx_timing','rx_complete','rx_fse','rx_isac_ofdm','rx_ofdm','rx_ofdm_tracking','rx_scfdma','rx_despread','rx_rake','rx_dehop','rx_mimo_ofdm','rx_ofdma','rx_mimo_soft','rx_mimo_lmmse'): fs=rs
        elif b['kind']=='resample': fs=fs*b['params']['up']/b['params']['down'] if fs else None
        if output=='同输入': output=domain
        if output=='信宿': output=domain
        rows.append({'id':b['id'],'input':domain,'accepts':accepts,'output':output,'compatible':compatible,
                     'sample_rate':fs if '波形' in output or output in ('模拟样本','模拟复包络','扩频码片') else None,'symbol_rate':rs})
        domain=output
    error=None; compiled=None
    try: compiled=c.build(program)
    except ValueError as exc:
        message=str(exc); match=re.search(r'第\s*(\d+)\s*块',message)
        index=min(len(rows)-1,int(match.group(1))-1) if match else next((i for i,r in enumerate(rows) if not r['compatible']),len(rows)-1)
        error={'id':rows[index]['id'],'message':message}
    if compiled:
        counts={r['id']:r.get('count') for r in compiled['plan']}
        tx_rrc=next((b for b in p['blocks'] if b['kind']=='tx_rrc'),None)
        for row,block in zip(rows,p['blocks']):
            row['count']=counts.get(row['id'])
            row['filter_delay_seconds']=tx_rrc['params']['span']/(2*p['symbol_rate']) if tx_rrc and block['kind'] in ('tx_rrc','rx_matched') else 0.
    return {'ports':rows,'error':error,'ready':compiled is not None,'plan':compiled['plan'] if compiled else []}


def complete_receiver(raw):
    from src import communications as c
    p=c.normalize(raw,draft=True); blocks=p['blocks']; tx=next((b for b in blocks if b['kind'].startswith('mod_')),None)
    if blocks[0]['kind']=='iq_source': return complete_iq_receiver(p)
    if tx is None: raise ValueError('请先添加调制器，再补齐接收链路。')
    def make(k,q=None):
        return {'id':'auto-'+uuid.uuid4().hex[:12],'kind':k,'params':{name:(q or {}).get(name,s['default']) for name,s in c.BLOCKS[k]['params'].items()}}
    channel_end=max((i for i,b in enumerate(blocks) if b['kind'] in c.CHANNELS),default=-1)
    if channel_end<0:
        channel_end=max(i for i,b in enumerate(blocks) if c.BLOCKS[b['kind']]['category'] in ('modulator','tx_converter','source'))+1
        blocks.insert(channel_end,make('ideal'))
    existing={b['kind'] for b in blocks}; steps=[]
    if 'tx_dsss' in existing:
        if 'rx_code_acquire' not in existing: steps.append(make('rx_code_acquire',{'threshold':.05} if 'narrowband' in existing else None))
        if not existing&{'rx_despread','rx_rake'}: steps.append(make('rx_rake' if 'dsss_multipath' in existing else 'rx_despread'))
    if 'tx_fhss' in existing:
        if 'rx_hop_sync' not in existing: steps.append(make('rx_hop_sync',{'threshold':.05} if 'narrowband' in existing else None))
        if 'rx_dehop' not in existing: steps.append(make('rx_dehop'))
    enhanced_receivers={'rx_mimo_lmmse','rx_mimo_kalman','rx_mimo_soft'}
    for transmitter,channel,receiver in [('tx_mimo_tracking','spatial_dynamic','rx_mimo_tracking'),('tx_mimo_ofdm','spatial_multipath','rx_mimo_ofdm'),('tx_ofdma','ofdma_channel','rx_ofdma'),('tx_array','array_channel','rx_array_mvdr'),('tx_mrt','array_channel','rx_array_mvdr'),('tx_svd','array_channel','rx_array_svd')]:
        if transmitter in existing:
            if channel not in existing:
                defaults={'branches':1} if transmitter=='tx_mrt' else {'arrival':'10,-35','departure':'20,50','gains':'1,0.6+0.2j'} if transmitter=='tx_svd' else None
                blocks[channel_end]=make(channel,defaults)
            alternatives=enhanced_receivers if transmitter.startswith('tx_mimo') else {'rx_array_conventional','rx_array_mvdr','rx_array_svd','rx_music','rx_music_mvdr'} if transmitter in ('tx_array','tx_mrt','tx_svd') else set()
            if receiver not in existing and not existing&alternatives: steps.append(make(receiver))
    for transmitter,receivers in [('tx_simo',('rx_mrc','rx_selection')),('tx_alamouti',('rx_alamouti',)),('tx_mimo',('rx_mimo_mmse','rx_mimo_zf','rx_mimo_zf_sic','rx_mimo_mmse_sic'))]:
        if transmitter in existing:
            if 'spatial_channel' not in existing:
                blocks[channel_end]=make('spatial_channel')
            if not existing&(set(receivers)|(enhanced_receivers if transmitter=='tx_mimo' else set())): steps.append(make(receivers[0]))
    for a,z in [('tx_mlse_frame','rx_mlse'),('tx_self_frame','rx_self_frame'),('tx_isac_ofdm','rx_isac_ofdm'),('rx_music','rx_music_mvdr')]:
        if a in existing and z not in existing: steps.append(make(z))
    digital=tx['kind'][4:] in ('bpsk','qpsk','psk8','qam16','qam64','qam256')
    if tx['kind'] in ('mod_bpsk','mod_qpsk') and 'frequency_offset' in existing and 'rx_frequency' not in existing and 'tx_ofdm' not in existing: steps.append(make('rx_frequency'))
    for a,z in [('tx_rrc','rx_matched'),('tx_rrc','rx_timing'),('tx_frame','rx_frame'),('tx_pilots','rx_pilots'),('tx_ofdm','rx_ofdm')]:
        replacement=(z=='rx_timing' and 'rx_fse' in existing) or (z=='rx_ofdm' and 'rx_ofdm_tracking' in existing)
        if a in existing and z not in existing and 'rx_complete' not in existing and not replacement: steps.append(make(z))
    if digital and 'tx_rrc' in existing and 'rx_carrier' not in existing and 'rx_complete' not in existing: steps.append(make('rx_carrier'))
    if 'tx_ofdm' in existing and 'frequency_offset' in existing and 'rx_ofdm_frequency' not in existing: steps.append(make('rx_ofdm_frequency'))
    if 'tx_scfdma' in existing and 'rx_scfdma' not in existing: steps.append(make('rx_scfdma'))
    if 'tx_dft_spread' in existing and 'rx_dft_despread' not in existing: steps.append(make('rx_dft_despread'))
    if 'tx_burst_preamble' in existing and 'rx_burst_sync' not in existing:
        preamble=next(b for b in blocks if b['kind']=='tx_burst_preamble')
        steps.append(make('rx_burst_sync',preamble['params']))
    order=['rx_mlse','rx_self_frame','rx_isac_ofdm','rx_music','rx_music_mvdr','rx_code_acquire','rx_despread','rx_rake','rx_hop_sync','rx_dehop','rx_selection','rx_mrc','rx_alamouti','rx_mimo_zf','rx_mimo_mmse','rx_mimo_zf_sic','rx_mimo_mmse_sic','rx_mimo_tracking','rx_mimo_ofdm','rx_ofdma','rx_frequency','rx_agc','resample','rx_matched','rx_timing','rx_fse','rx_carrier','rx_frame','rx_equalizer','rx_cma','rx_pilots','rx_ofdm_frequency','rx_ofdm','rx_ofdm_tracking','rx_noise_estimate','rx_iq','rx_dc','rx_notch']
    order[order.index('rx_frequency'):order.index('rx_frequency')]=['rx_mimo_lmmse','rx_mimo_kalman','rx_mimo_soft','rx_array_conventional','rx_array_mvdr','rx_array_svd']
    order[order.index('rx_ofdm_frequency'):order.index('rx_ofdm_frequency')]=['rx_burst_sync','rx_scfdma','rx_dft_despread']
    for step in sorted(steps,key=lambda b:order.index(b['kind'])):
        rank=order.index(step['kind']);index=next((i for i,b in enumerate(blocks) if i>channel_end and (b['kind'] in order and order.index(b['kind'])>rank or b['kind'].startswith(('demod_','soft_')) or b['kind'] in c.PAIRS or b['kind']=='sink')),len(blocks))
        blocks.insert(index,step)
    soft=any(b['kind'] in ('ldpc_encode','puncture','polar_encode','turbo_encode','rx_mimo_soft') for b in blocks)
    demod=next((b for b in blocks if b['kind'].startswith(('demod_','soft_'))),None)
    kind=('soft_' if soft else 'demod_')+tx['kind'][4:]
    if demod is None:
        index=next((i for i,b in enumerate(blocks) if c.BLOCKS[b['kind']]['category'] in ('decoder','sink')),len(blocks))
        blocks.insert(index,make(kind)); demod=blocks[index]
    elif soft and demod['kind'].startswith('demod_') and kind in c.BLOCKS:
        demod.update(kind=kind,params=make(kind)['params'])
    encoders=[b for b in blocks[:blocks.index(tx)] if b['kind'] in c.ENCODERS]
    old_rx=[b for b in blocks if b['kind'] in c.PAIRS]; rebuilt=[]
    for encoder in reversed(encoders):
        inverse='conv_soft_decode' if encoder['kind']=='conv_encode' and demod['kind'].startswith('soft_') else next(k for k,v in c.PAIRS.items() if v==encoder['kind'])
        rx=next((b for b in old_rx if c.PAIRS[b['kind']]==encoder['kind'] and b not in rebuilt),None)
        if rx is None: rx=make(inverse,encoder['params'])
        elif rx['kind']=='conv_decode' and inverse=='conv_soft_decode': rx.update(kind=inverse,params=make(inverse,encoder['params'])['params'])
        elif rx['kind']=='turbo_decode': rx['params'].update(encoder['params'])
        elif rx['kind']=='polar_decode': rx['params'].update(encoder['params'])
        elif rx['kind'] not in ('ldpc_decode','conv_soft_decode'): rx['params']=make(rx['kind'],encoder['params'])['params']
        rebuilt.append(rx)
    blocks[:]=[b for b in blocks if b['kind'] not in c.PAIRS and b['kind']!='sink']+rebuilt+[next((b for b in raw['blocks'] if b['kind']=='sink'),make('sink'))]
    return c.normalize(p,draft=True)


def complete_iq_receiver(program):
    """Complete a receive-only chain from public recording format metadata."""
    from src import communications as c, communication_iq as iq
    p=copy.deepcopy(program); source=p['blocks'][0]; q=source['params']
    def make(kind):
        return {'id':'auto-'+uuid.uuid4().hex[:12],'kind':kind,'params':{k:v['default'] for k,v in c.BLOCKS[kind]['params'].items()}}
    stages=[b for b in p['blocks'][1:] if b['kind'] in iq.RECEIVERS]
    if any(b['kind'] not in iq.RECEIVERS and not b['kind'].startswith(('demod_','soft_')) and b['kind']!='sink' for b in p['blocks'][1:]): raise ValueError('录波链路请保留接收处理、解调器和信宿。')
    existing={b['kind'] for b in stages}
    required=iq.receive_stages(q)
    if 'rx_ofdm_tracking' in existing: required=[item for item in required if item[0]!='rx_ofdm']
    for kind,params in required:
        if kind not in existing:
            stage=make(kind);stage['params'].update(params);stages.append(stage)
        elif kind=='rx_burst_sync':
            next(stage for stage in stages if stage['kind']==kind)['params'].update(params)
    order=['rx_dc','rx_notch','rx_agc','resample','rx_frequency','rx_matched','rx_timing','rx_burst_sync','rx_self_frame','rx_ofdm_frequency','rx_ofdm','rx_ofdm_tracking','rx_scfdma','rx_dft_despread','rx_carrier','rx_cma','rx_frame','rx_equalizer','rx_noise_estimate']
    stages.sort(key=lambda b:order.index(b['kind']))
    kind='demod_bpsk' if q['mode']==3 else 'demod_'+iq.SCHEMES[q['scheme']]
    demod=next((b for b in p['blocks'] if b['kind'].startswith(('demod_','soft_'))),None)
    if demod is None: demod=make(kind)
    elif demod['kind']!=kind: demod={'id':demod['id'],'kind':kind,'params':make(kind)['params']}
    sink=next((b for b in p['blocks'] if b['kind']=='sink'),None) or make('sink')
    p['blocks']=[source]+stages+[demod,sink]
    return c.normalize(p,draft=True)


def pair_parameters(raw):
    from src import communications as c
    p=c.normalize(raw,draft=True); stack=[]
    for b in p['blocks']:
        if b['kind'] in c.ENCODERS: stack.append(b)
        elif b['kind'] in c.PAIRS and stack:
            tx=stack.pop()
            if c.PAIRS[b['kind']]==tx['kind']:
                for name in c.BLOCKS[b['kind']]['params']:
                    if name in tx['params']: b['params'][name]=tx['params'][name]
    noise=[b for b in p['blocks'] if b['kind']=='awgn']
    if len(noise)==1 and all(b['kind'] not in c.CHANNELS or b['kind'] in ('awgn','ideal') for b in p['blocks']):
        for b in p['blocks']:
            if b['kind'].startswith('soft_'): b['params']['noise_variance']=max(.000001,min(100,10**(-noise[0]['params']['esn0_db']/10)))
    return p


def validate_document(raw):
    from src import communications as c
    if not isinstance(raw,dict): raise ValueError('工程文档须为 JSON 对象。')
    if raw.get('schema')==1 and 'blocks' in raw: raw={'document_schema':2,'name':'导入的通信工程','program':raw}
    if raw.get('document_schema')!=2: raise ValueError('工程文档版本不匹配。')
    document=copy.deepcopy(raw); document['program']=c.normalize(document.get('program'),draft=True)
    from src.communication_subprojects import validate_document as validate_subprojects
    validate_subprojects(document)
    name=document.get('name','我的通信工程')
    if not isinstance(name,str) or not 1<=len(name.strip())<=120: raise ValueError('工程名称需要 1–120 个字符。')
    document['name']=name.strip(); ids=[b['id'] for b in document['program']['blocks']]
    def validate_exposed(item,blocks):
        exposed=item.get('exposed',[]); lookup={b['id']:b for b in blocks}
        if not isinstance(exposed,list) or len(exposed)>128: raise ValueError('对外参数格式无效。')
        for value in exposed:
            if not isinstance(value,str) or ':' not in value: raise ValueError('对外参数格式无效。')
            key,param=value.rsplit(':',1)
            if key not in lookup or param not in c.BLOCKS[lookup[key]['kind']]['params']: raise ValueError('对外参数须属于组合内的积木。')
    groups=document.get('groups',[])
    if not isinstance(groups,list) or len(groups)>16: raise ValueError('最多保存 16 个组合积木。')
    used=set()
    for group in groups:
        if not isinstance(group,dict) or not isinstance(group.get('name'),str) or not 1<=len(group['name'])<=80: raise ValueError('组合积木名称无效。')
        members=group.get('members',[])
        if not isinstance(members,list) or not members or len(set(members))!=len(members) or any(i not in ids or i in used for i in members): raise ValueError('组合积木成员无效或重叠。')
        positions=[ids.index(i) for i in members]
        if positions!=list(range(positions[0],positions[0]+len(positions))) or any(next(b for b in document['program']['blocks'] if b['id']==i)['kind']=='sink' for i in members): raise ValueError('组合积木需要相邻的非信宿积木。')
        used.update(members)
        validate_exposed(group,[b for b in document['program']['blocks'] if b['id'] in members])
    library=document.get('library',[])
    if not isinstance(library,list) or len(library)>16: raise ValueError('最多保存 16 个自定义模块。')
    for item in library:
        if not isinstance(item,dict) or not isinstance(item.get('name'),str) or not 1<=len(item['name'])<=80: raise ValueError('自定义模块格式无效。')
        normalized=c.normalize({**document['program'],'blocks':item.get('blocks',[])},draft=True)
        item['blocks']=normalized['blocks'];validate_exposed(item,item['blocks'])
    branches=document.get('branches',[])
    if not isinstance(branches,list) or len(branches)>c.CONFIG['max_branches']: raise ValueError('分支数量超过上限。')
    for branch in branches:
        if not isinstance(branch,dict) or not isinstance(branch.get('name'),str) or not 1<=len(branch['name'])<=80: raise ValueError('分支名称无效。')
        branch['program']=c.normalize(branch.get('program'),draft=True)
    encoded=json.dumps(document,ensure_ascii=False,allow_nan=False).encode('utf-8')
    if len(encoded)>c.CONFIG['max_project_bytes']: raise ValueError('工程文档超过大小上限，请减少保存的结果。')
    return document


class ProjectStore:
    def __init__(self,root): self.root=Path(root)/'communication-projects';self.lock=threading.RLock()
    def directory(self,session):
        if not isinstance(session,str) or not 1<=len(session)<=256: raise ValueError('会话标识无效。')
        return self.root/hashlib.sha256(session.encode()).hexdigest()
    def path(self,session,key):
        if not isinstance(key,str) or not re.fullmatch('[a-f0-9]{32}',key): raise ValueError('工程标识无效。')
        return self.directory(session)/(key+'.json')
    def listing(self,session):
        with self.lock:
            result=[]
            for p in self.directory(session).glob('*.json'):
                value=json.loads(p.read_text(encoding='utf-8'))
                result.append({'id':p.stem,'name':value['document']['name'],'updated':value['updated'],'version':value['version'],'versions':[{'version':v['version'],'updated':v['updated']} for v in value['history']]})
            return sorted(result,key=lambda r:r['updated'],reverse=True)
    def load(self,session,key,version=None):
        with self.lock:
            p=self.path(session,key)
            if not p.exists(): raise KeyError('工程不存在。')
            value=json.loads(p.read_text(encoding='utf-8'))
            if version is not None and version!=value['version']:
                value=next((v for v in value['history'] if v['version']==version),None)
                if value is None: raise KeyError('该快照已不在保留范围内。')
            return {'id':key,'version':value['version'],'updated':value['updated'],'document':value['document']}
    def save(self,session,raw,key=None,expected=None):
        from src import communications as c
        document=validate_document(raw)
        with self.lock:
            key=key or uuid.uuid4().hex;p=self.path(session,key); history=[];version=1
            if p.exists():
                old=json.loads(p.read_text(encoding='utf-8'))
                if expected is not None and expected!=old['version']: raise ValueError('工程已被另一个窗口更新，请重新打开后保存。')
                history=(old['history']+[{'version':old['version'],'updated':old['updated'],'document':old['document']}])[-c.CONFIG['max_project_versions']:];version=old['version']+1
            elif len(self.listing(session))>=c.CONFIG['max_projects']: raise ValueError('工程数量已达上限。')
            value={'document':document,'version':version,'updated':datetime.now(timezone.utc).isoformat(),'history':history}
            p.parent.mkdir(parents=True,exist_ok=True); temporary=p.with_suffix('.tmp')
            temporary.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8');temporary.replace(p)
            return {'id':key,'version':version,'updated':value['updated'],'document':document}


def shared_prefix(programs):
    from src import communications as c
    if not 2<=len(programs)<=c.CONFIG['max_branches']: raise ValueError('分支对比需要 2–4 条链路。')
    builds=[c.build(p) for p in programs]; split=next((i for i,b in enumerate(builds[0]['program']['blocks']) if c.BLOCKS[b['kind']]['category'] in ('demodulator','rx_converter')),None)
    if split is None: raise ValueError('分支需要接收处理。')
    prefix=builds[0]['program']['blocks'][:split]
    if not any(b['kind'] in c.CHANNELS for b in prefix): raise ValueError('分支需要共享信道。')
    globals=('seed','sample_rate','sample_count','symbol_rate')
    for built in builds[1:]:
        if built['program']['blocks'][:split]!=prefix or any(built['program'][k]!=builds[0]['program'][k] for k in globals): raise ValueError('分支须共享完全相同的信源、发送处理、信道和全局参数。')
    return builds,[b['id'] for b in prefix]


def compare_branches(programs,names=None,cancel=None,progress=None,contexts=None):
    builds,ids=shared_prefix(programs); cache={}; results=[];names=names or [f'接收分支 {i+1}' for i in range(len(builds))]
    for index,built in enumerate(builds):
        result,ctx=runtime.observe_run(built['program'],built['token'],retain=True,replay=cache,cancel=cancel)
        if contexts is not None: contexts.append(ctx)
        if index==0: cache={key:ctx.values[key] for key in ids}
        results.append({'name':names[index],'result':result})
        if progress: progress({'branches':results,'completed':index+1,'total':len(builds)})
    return {'branches':results,'shared_prefix':ids,'shared_hashes':{k:hashlib.sha256(v.tobytes()).hexdigest() for k,v in cache.items()}}
