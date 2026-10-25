"""Sampled FHSS bursts with public-pilot delay and hopping-phase acquisition."""
import math
import numpy as np
from src import communication_runtime as runtime
from src.communication_spatial import arrays

TX={'tx_fhss'};CHANNEL=set();RX={'rx_hop_sync','rx_dehop'};KINDS=TX|RX


def register(block,number,field,blocks):
    block('tx_fhss','FHSS 跳频发射','tx_converter','使用可重现的 31 跳伪随机序列，按指定频点切换载波并插入公共训练。',
          sps=field('每符号采样数',16,'select',choices=[8,16,32,64]),bins=field('跳频频点 / 符号率倍数','-3,-2,-1,1,2,3',max_length=100),
          hop_symbols=number('每跳符号数',4,1,32,True),hop_seed=number('跳频码种子',47,1,65535,True),
          phase=number('初始跳频码相位',7,0,30,True),training=field('公共训练符号数',32,'select',choices=[16,32,64]))
    block('rx_hop_sync','跳频码与帧同步','rx_converter','用公共训练同时搜索 31 个跳频码相位和样本延迟，定位接收频率切换时序。',
          search=number('最大搜索延迟 / 样本',128,0,512,True),threshold=number('归一化捕获阈值',.12,.01,.99))
    block('rx_dehop','FHSS 解跳与积分','rx_converter','按捕获跳频序列下变频、逐符号积分，再用公共训练估计复增益。')


def presets(preset):
    return {
        'fhss_antijamming':{'label':'跳频 · 同步与抗窄带干扰','program':preset(['random_bits','mod_qpsk','tx_fhss','narrowband','sample_delay','complex_awgn','rx_hop_sync','rx_dehop','demod_qpsk','sink'],
            {3:{'hz':0,'amplitude':1.5},4:{'samples':37,'fraction':0},5:{'snr_db':28},6:{'threshold':.05}})},
        'fhss_acquisition':{'label':'跳频 · 未知码相位与帧延迟','program':preset(['random_bits','mod_qam16','tx_fhss','sample_delay','complex_awgn','rx_hop_sync','rx_dehop','demod_qam16','sink'],
            {2:{'phase':19},3:{'samples':53,'fraction':0},4:{'snr_db':30}})},
    }


def bins(q):
    values=np.array([int(x.strip()) for x in q['bins'].split(',')])
    if not 2<=len(values)<=16 or len(set(values))!=len(values) or np.any(abs(values)>=q['sps']/2):raise ValueError('跳频使用 2–16 个互异整数频点，频率幅度须小于采样率一半。')
    return values


def build_stage(kind,q,domain,count,features):
    w=features.setdefault('wireless',{})
    if kind=='tx_fhss':
        if domain!='复符号' or 'tx' in w or any(k in features for k in ('tx_rrc','tx_frame','tx_ofdm','tx_pilots')):raise ValueError('FHSS 直接连接数字映射器，每条链路使用一个无线发送结构。')
        bins(q);w.update(tx=kind,input_count=count,params=q,rate_factor=q['sps']);count=(count+q['training'])*q['sps'];domain='跳频波形'
    elif kind=='rx_hop_sync':
        if domain!='跳频波形' or w.get('acquired'):raise ValueError('跳频同步连接跳频信道输出，每条链路放置一次。')
        w['acquired']=True
    else:
        if domain!='跳频波形' or not w.get('acquired'):raise ValueError('请先放置跳频码与帧同步。')
        domain='复符号';count=w['input_count'];w['rx']=kind
    features[kind]={'params':q,'count':count}
    return domain,count


def oscillator(q,phase,symbol_count):
    frequencies=bins(q);sequence=np.random.default_rng(q['hop_seed']).permutation(np.tile(np.arange(len(frequencies)),math.ceil(31/len(frequencies))))[:31]
    index=sequence[(phase+np.arange(symbol_count)//q['hop_symbols'])%31]
    sample_bins=np.repeat(frequencies[index],q['sps'])
    angles=2*np.pi*np.r_[0,np.cumsum(sample_bins[:-1])]/q['sps']
    return np.exp(1j*angles),sample_bins,index


def encode(symbols,q,state,fs):
    pilot=(2*np.random.default_rng(3147).integers(0,2,q['training'])-1).astype(complex)
    memory=runtime.state('fhss_sequence',lambda:{'phase':q['phase']});phase=memory['phase']
    carrier,sample_bins,index=oscillator(q,phase,len(pilot)+len(symbols));memory['phase']=(phase+math.ceil((len(pilot)+len(symbols))/q['hop_symbols']))%31
    tx=np.repeat(np.r_[pilot,symbols],q['sps'])/math.sqrt(q['sps'])*carrier
    # Phase is deliberately excluded: the receiver searches all public codes.
    public={k:v for k,v in q.items() if k!='phase'};state['fhss']={'params':public,'pilot':pilot,'count':len(symbols)}
    return tx,{'hops':{'frequencies_hz':(sample_bins[::q['sps']*q['hop_symbols']]*fs).tolist(),
        'hop_samples':q['sps']*q['hop_symbols'],'hop_indices':index[::q['hop_symbols']].tolist(),'sample_rate':fs*q['sps']},
        'transmitted_phase':phase,'training_symbols':len(pilot),'full_tx':arrays(tx[:,None])}


def acquire(x,s,q):
    p=s['params'];size=len(s['pilot'])*p['sps'];last=max(0,min(q['search'],len(x)-size))
    window=np.pad(x[:size+last],(0,max(0,size+last-len(x))));energy=np.convolve(abs(window)**2,np.ones(size),'valid');scores=[];profiles=[];best=(-1,0,0)
    for phase in range(31):
        carrier,_,_=oscillator(p,phase,len(s['pilot']));template=np.repeat(s['pilot'],p['sps'])/math.sqrt(p['sps'])*carrier
        score=abs(np.correlate(window,template,'valid'))/np.sqrt(np.maximum(energy*len(s['pilot']),1e-30));delay=int(np.argmax(score))
        scores.append(float(score[delay]));profiles.append(score)
        if score[delay]>best[0]:best=(float(score[delay]),delay,phase)
    peak,delay,phase=best
    detected=peak>=q['threshold'] and len(x)>=size;s.update(delay=delay,phase=phase,detected=detected)
    return {'sync':{'delay_samples':delay,'code_phase':phase,'correlation_peak':peak,'detected':detected,'delay_scores':profiles[phase].tolist(),'phase_scores':scores}}


def decode(x,s):
    q=s['params'];count=len(s['pilot'])+s['count'];size=count*q['sps'];segment=x[s['delay']:s['delay']+size]
    segment=np.pad(segment,(0,size-len(segment)))
    carrier,_,_=oscillator(q,s['phase'],count);baseband=segment*carrier.conj();symbols=baseband.reshape(count,q['sps']).sum(axis=1)/math.sqrt(q['sps'])
    gain=np.vdot(s['pilot'],symbols[:len(s['pilot'])])/len(s['pilot'])
    valid=bool(abs(gain)>=1e-10)
    out=symbols[len(s['pilot']):]/gain if valid else np.zeros(s['count'],complex)
    s['detected']=s.get('detected',True) and valid
    return out,{'recovered_symbols':arrays(out),'estimated_gain':arrays([gain]),'dehopped':arrays(baseband),
        'training_mse':float(np.mean(abs((symbols[:len(s['pilot'])]/gain if valid else np.zeros(len(s['pilot'])))-s['pilot'])**2)),
        'sync':{'delay_samples':s['delay'],'code_phase':s['phase'],'detected':s.get('detected',True)}}


def run_stage(kind,data,q,state,rng,fs):
    if kind=='tx_fhss':data,details=encode(data,q,state,fs);return data,details,fs*q['sps']
    s=state['fhss']
    if kind=='rx_hop_sync':return data,acquire(data,s,q),fs
    data,details=decode(data,s);return data,details,fs/s['params']['sps']
