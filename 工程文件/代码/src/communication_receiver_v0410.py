"""Public-training MLSE, MUSIC steering and 3GPP TR 38.901 TDL-A/B/C."""
import itertools
import math
import numpy as np
from src import communication_dsp as dsp, communication_runtime as runtime
from src import communication_array_v049 as array
from src.communication_spatial import arrays

TX={'tx_mlse_frame'}
RX={'rx_mlse','rx_music','rx_music_mvdr'}
CHANNEL={'tdl_channel'}
KINDS=TX|RX|CHANNEL

# TR 38.901 V18.0.0, Tables 7.7.2-1/2/3. Delays are normalized to RMS DS.
TDL_PROFILES={
    'A':([0,.3819,.4025,.5868,.4610,.5375,.6708,.575,.7618,1.5375,1.8978,2.2242,2.1718,2.4942,2.5119,3.0582,4.081,4.4579,4.5695,4.7966,5.0066,5.3043,9.6586],
         [-13.4,0,-2.2,-4,-6,-8.2,-9.9,-10.5,-7.5,-15.9,-6.6,-16.7,-12.4,-15.2,-10.8,-11.3,-12.7,-16.2,-18.3,-18.9,-16.6,-19.9,-29.7]),
    'B':([0,.1072,.2155,.2095,.287,.2986,.3752,.5055,.3681,.3697,.57,.5283,1.1021,1.2756,1.5474,1.7842,2.0169,2.8294,3.0219,3.6187,4.1067,4.279,4.7834],
         [0,-2.2,-4,-3.2,-9.8,-1.2,-3.4,-5.2,-7.6,-3,-8.9,-9,-4.8,-5.7,-7.5,-1.9,-7.6,-12.2,-9.8,-11.4,-14.9,-9.2,-11.3]),
    'C':([0,.2099,.2219,.2329,.2176,.6366,.6448,.656,.6584,.7935,.8213,.9336,1.2285,1.3083,2.1704,2.7105,4.2589,4.6003,5.4902,5.6077,6.3065,6.6374,7.0427,8.6523],
         [-4.4,-1.2,-3.5,-5.2,-2.5,0,-2.2,-3.9,-7.4,-7.1,-10.7,-11.1,-5.1,-6.8,-8.7,-13.2,-13.9,-13.9,-15.8,-17.1,-16,-15.7,-21.6,-22.8])}


def register(block,number,field,blocks):
    block('tx_mlse_frame','🧵 MLSE 公共训练帧','tx_converter','BPSK / QPSK 前置公开训练，末尾添加两个公开终止符号，为信道估计和序列检测提供边界。',
          training=field('训练符号数',128,'select',choices=[32,64,128,256]))
    block('rx_mlse','🧭 MLSE 序列均衡','rx_converter','仅用公开前导最小二乘估计复 FIR，以 Viterbi 最小欧氏距离检测完整数据序列，展示状态路径与分支运算量。',
          taps=field('估计信道抽头数',3,'select',choices=[2,3]))
    block('rx_music','📐 MUSIC 到达角估计','rx_converter','接收阵列协方差分解为信号与噪声子空间，扫描角谱；公开导频估计各峰复增益并选择目标。',
          sources=number('信号源数量',2,1,7,True),step_deg=number('角度扫描步长 / °',.25,.1,1),
          subarray=number('平滑子阵长度（0 为完整阵列）',0,0,8,True),forward_backward=field('前后向平均',True,'boolean'))
    block('rx_music_mvdr','🎯 MUSIC 引导 MVDR','rx_converter','使用前置 MUSIC 从接收观测选出的目标角，公开训练残差估计干扰协方差并形成自适应零陷。',
          loading=number('协方差对角加载 / 平均功率',.001,.000001,1))
    block('tdl_channel','🌊 3GPP TDL-A / B / C','channel','按标准功率时延谱产生逐路径 Jakes 衰落；17 点 sinc 分数延迟、8 点公共滤波延迟；帧末零保护区释放滤波尾部。',
          profile=field('标准信道模型',0,'select',choices=[0,1,2],choice_labels={0:'TDL-A',1:'TDL-B',2:'TDL-C'}),
          delay_spread_ns=number('RMS 时延扩展 / ns',1000,1,1000000),doppler_hz=number('最大多普勒 / Hz',5,0,10000))


def presets(preset):
    def entry(label,kinds,changes=None):return {'label':label,'program':preset(kinds,changes)}
    out={}
    for scheme,taps,gains in [('bpsk',2,'1,0.9'),('qpsk',3,'1,0.65+0.25j,-0.25j')]:
        out['mlse_'+scheme]=entry('序列检测 · '+scheme.upper()+' / MLSE',
            ['random_bits','mod_'+scheme,'tx_mlse_frame','complex_multipath','awgn','rx_mlse','demod_'+scheme,'sink'],
            {3:{'taps':gains},4:{'esn0_db':20},5:{'taps':taps}})
    out['music_mvdr']=entry('阵列 · MUSIC 测角与自动 MVDR',
        ['random_bits','mod_qpsk','tx_array','array_channel','array_interference','rx_music','rx_music_mvdr','demod_qpsk','sink'],
        {0:{'count':2048},2:{'training':256},3:{'branches':8,'arrival':'17.5','snr_db':24},4:{'angle':-28,'amplitude':3}})
    out['music_smoothing']=entry('阵列 · 相干多径与空间平滑',
        ['random_bits','mod_qpsk','tx_array','array_channel','array_interference','rx_music','rx_music_mvdr','demod_qpsk','sink'],
        {0:{'count':2048},2:{'training':256},3:{'branches':8,'arrival':'12,42','departure':'0,0','gains':'1,0.35j','snr_db':28},4:{'angle':-30},5:{'sources':3,'subarray':5}})
    for index,name in enumerate('ABC'):
        out['tdl_'+name.lower()]=entry('标准信道 · TDL-'+name+' / OFDM 导频接收',
            ['random_bits','mod_qpsk','tx_ofdm','tdl_channel','complex_awgn','rx_ofdm_tracking','demod_qpsk','sink'],
            {0:{'count':2048},2:{'cp':32,'active_count':48,'pilot_interval':4},3:{'profile':index,'delay_spread_ns':3000,'doppler_hz':2},4:{'snr_db':30},5:{'method':0,'tracking_gain':.8}})
    return out


def build_stage(kind,q,domain,count,features):
    if kind=='tx_mlse_frame':
        scheme=features['modulator']['kind'][4:]
        if domain!='复符号' or scheme not in ('bpsk','qpsk') or features.get('wireless') or any(k in features for k in ('tx_frame','tx_rrc','tx_ofdm','tx_pilots')):
            raise ValueError('MLSE 训练帧直接连接 BPSK / QPSK 映射器。')
        features['wireless']={'tx':kind,'input_count':count,'params':q,'rate_factor':1}
        count+=q['training']+2
    elif kind=='rx_mlse':
        w=features.get('wireless',{})
        if domain!='复符号' or w.get('tx')!='tx_mlse_frame' or w.get('rx'):raise ValueError('MLSE 接收器连接 MLSE 公共训练帧对应的复符号信道。')
        count=w['input_count'];w['rx']=kind
    elif kind in ('rx_music','rx_music_mvdr'):
        w=features.get('wireless',{});channel=w.get('array_channel',{})
        if domain!='多天线符号' or w.get('tx')!='tx_array' or not channel:raise ValueError('MUSIC 接在均匀线阵训练帧与阵列角度信道之后。')
        if kind=='rx_music':
            aperture=q['subarray'] or channel['branches']
            if not q['sources']<aperture<=channel['branches']:raise ValueError('平滑子阵长度须大于信号源数，并位于接收阵元数以内。')
            if channel['spacing']>.5:raise ValueError('MUSIC 全角扫描使用不超过半波长的阵元间距。')
        else:
            if 'rx_music' not in features:raise ValueError('自动 MVDR 前先连接 MUSIC 到达角估计。')
            count=w['input_count'];domain='复符号';w['rx']=kind
    else:
        if domain not in ('复符号','复波形','复采样波形','OFDM 波形'):raise ValueError('TDL 信道连接单路复符号、复基带或 OFDM 波形。')
        fs=features['symbol_rate']*features.get('tx_rrc',{}).get('params',{}).get('sps',features.get('tx_ofdm',{}).get('params',{}).get('nfft',1))
        # SC-FDMA supplies its sampling-rate factor through the extension state.
        fs*=features.get('wireless',{}).get('rate_factor',1)
        count+=tdl_parameters(q,fs)['tail_samples']
    features[kind]={'params':q,'count':count}
    return domain,count


def mlse_frame(symbols,scheme,training):
    points=dsp.constellation(scheme)[1]
    pilot=points[np.random.default_rng(410021).integers(0,len(points),training)]
    tail=np.repeat(points[0],2)
    return np.r_[pilot,symbols,tail],{'pilot':pilot,'tail':tail,'count':len(symbols),'scheme':scheme}


def estimate_fir(pilot,received,taps):
    indices=np.arange(taps-1,len(pilot))
    design=np.asarray(pilot)[indices[:,None]-np.arange(taps)]
    observed=np.asarray(received)[indices]
    h=np.linalg.lstsq(design,observed,rcond=None)[0]
    variance=float(np.sum(abs(observed-design@h)**2)/(len(indices)-taps))
    return h,variance


def viterbi_sequence(received,h,points,history,tail):
    """Exact full-frame finite-memory MLSE, initialized and terminated publicly."""
    m=len(points);memory=len(h)-1;states=np.array(list(itertools.product(range(m),repeat=memory)))
    nstates=len(states);base=m**(memory-1)
    initial=np.argmin(abs(np.asarray(history)[-memory:][::-1,None]-points[None,:]),axis=1)
    initial_index=int(initial@ (m**np.arange(memory-1,-1,-1)))
    scores=np.full(nstates,np.inf);scores[initial_index]=0
    prediction=(points[states]@h[1:])[:,None]+h[0]*points[None,:]
    predecessors=(np.arange(nstates)%base)[:,None]*m+np.arange(m)[None,:]
    inputs=np.arange(nstates)//base
    back=np.empty((len(received),nstates),np.int16);trace=[];metric_offset=0.
    for i,value in enumerate(received):
        candidate=scores[predecessors]+abs(value-prediction[predecessors,inputs[:,None]])**2
        if i>=len(received)-len(tail):
            forced=int(np.argmin(abs(points-tail[i-(len(received)-len(tail))])))
            candidate[inputs!=forced]=np.inf
        best=candidate.argmin(axis=1);scores=candidate[np.arange(nstates),best]
        back[i]=predecessors[np.arange(nstates),best]
        lowest=float(np.min(scores));metric_offset+=lowest;scores-=lowest
        if i<64:trace.append([float(v) if np.isfinite(v) else None for v in scores])
    state=int(np.argmin(scores));indices=np.empty(len(received),int);path=np.empty(len(received),int)
    for i in range(len(received)-1,-1,-1):
        path[i]=state;indices[i]=inputs[state];state=int(back[i,state])
    return points[indices],{'state_count':nstates,'branch_count':nstates*m,'metric_evaluations':len(received)*nstates*m,
        'sequence_metric':metric_offset+float(np.min(scores)),'metric_history':trace,'predecessors':back[:64].tolist(),
        'survivor_states':path[:64].tolist(),'input_indices':indices[:64].tolist(),'state_symbols':states.tolist(),
        'initial_state':initial_index,'steps':len(received),'trace_steps':len(trace)}


def mlse_decode(received,public,taps):
    pilot=public['pilot'];n=public['count'];tail=public['tail'];y=np.asarray(received,complex)
    if len(y)<len(pilot)+n+len(tail):raise ValueError('MLSE 接收采样须覆盖公开训练、数据和终止符号。')
    h,variance=estimate_fir(pilot,y,taps)
    decoded,trace=viterbi_sequence(y[len(pilot):len(pilot)+n+len(tail)],h,dsp.constellation(public['scheme'])[1],pilot,tail)
    return decoded[:n],{'channel_estimate':arrays(h),'estimated_noise_variance':variance,'training_symbols':len(pilot),
        'mlse':trace,'recovered_symbols':arrays(decoded[:n]),'hard_sequence_output':True}


def music_estimate(received,public,q):
    """Covariance eigenspace and public-pilot target identification; no channel CSI."""
    y=np.asarray(received,complex)[public['prefix']:];nr=y.shape[1];length=q['subarray'] or nr
    covariance=sum(y[:,i:i+length].T@y[:,i:i+length].conj()/len(y) for i in range(nr-length+1))/(nr-length+1)
    if q['forward_backward']:covariance=(covariance+covariance[::-1,::-1].conj())/2
    eigenvalues,eigenvectors=np.linalg.eigh(covariance);noise=eigenvectors[:,:length-q['sources']]
    angles=np.arange(-90,90+q['step_deg']/2,q['step_deg'])
    steering=np.array([array.steering(length,public['spacing'],angle) for angle in angles])
    spectrum=1/np.maximum(np.sum(abs(steering.conj()@noise)**2,axis=1),1e-15)
    candidates=np.flatnonzero((spectrum>=np.r_[-np.inf,spectrum[:-1]]) & (spectrum>=np.r_[spectrum[1:],-np.inf]))
    peaks=[]
    for index in candidates[np.argsort(spectrum[candidates])[::-1]]:
        if all(abs(angles[index]-angles[old])>=1 for old in peaks):peaks.append(int(index))
        if len(peaks)==q['sources']:break
    if len(peaks)!=q['sources']:raise ValueError('角谱峰数量不足，请调整源数、阵元或扫描步长。')
    pilot=public['pilot'];h,_=array.pilot_estimate(pilot,y[:len(pilot)])
    directions=angles[peaks];a=np.column_stack([array.steering(nr,public['spacing'],angle) for angle in directions])
    coefficients=np.linalg.lstsq(a,h[:,0],rcond=None)[0];target=int(np.argmax(abs(coefficients)))
    return {'music':{'angles':angles.tolist(),'spectrum_db':(10*np.log10(np.maximum(spectrum/spectrum.max(),1e-8))).tolist(),
        'estimated_angles':directions.tolist(),'target_angle':float(directions[target]),'target_index':target,
        'pilot_coefficients':arrays(coefficients),'eigenvalues':eigenvalues.tolist(),'subarray_length':length,
        'snapshots':len(y),'source_count':q['sources'],'spacing':public['spacing']},'covariance':arrays(covariance)}


def tdl_parameters(q,fs):
    name='ABC'[q['profile']];delays,powers_db=TDL_PROFILES[name];powers=10**(np.array(powers_db)/10);powers/=powers.sum()
    delays_ns=np.array(delays)*q['delay_spread_ns'];samples=delays_ns*1e-9*fs
    if samples.max()>2048:raise ValueError('TDL 最大物理时延须在 2048 个采样点以内，请调整采样率或时延扩展。')
    if q['doppler_hz']>=fs/2:raise ValueError('最大多普勒须低于接收采样率的一半。')
    mean=float(delays_ns@powers);rms=float(np.sqrt((delays_ns-mean)**2@powers))
    return {'profile':'TDL-'+name,'delays_ns':delays_ns,'delays_samples':samples,'powers':powers,
        'powers_db':np.array(powers_db),'mean_delay_ns':mean,'rms_delay_ns':rms,'tail_samples':int(np.floor(samples.max()))+16}


def fractional_kernel(delay):
    integer=int(np.floor(delay));fraction=delay-integer
    taps=np.sinc(np.arange(-8,9)-fraction)*np.kaiser(17,6)
    taps/=taps.sum()
    return np.pad(taps,(integer,0))


def tdl_process(data,q,fs,rng,memory=None):
    """Length-preserving causal stream. Every call advances phases and FIR history."""
    parameters=tdl_parameters(q,fs);paths=len(parameters['powers']);tail=parameters['tail_samples']
    if memory is None:memory=runtime.state('tdl',lambda:{})
    if not memory:
        memory.update(offset=0,tail=np.zeros(tail,complex),phases=rng.uniform(-np.pi,np.pi,(paths,32)),
                      angles=rng.uniform(-np.pi,np.pi,(paths,32)),static=(rng.normal(size=paths)+1j*rng.normal(size=paths))/math.sqrt(2))
    extended=np.r_[memory['tail'],np.asarray(data,complex)];output=np.zeros(len(data),complex)
    times=(memory['offset']+np.arange(len(data)))/fs;shown=np.unique(np.linspace(0,max(0,len(data)-1),min(128,len(data))).astype(int))
    traces=[];measured=[]
    for i,(delay,power) in enumerate(zip(parameters['delays_samples'],parameters['powers'])):
        filtered=np.convolve(extended,fractional_kernel(delay))[tail:tail+len(data)]
        if q['doppler_hz']==0:fading=np.full(len(data),memory['static'][i],complex)
        else:
            fading=sum(np.exp(1j*(phase+2*np.pi*q['doppler_hz']*np.cos(angle)*times)) for phase,angle in zip(memory['phases'][i],memory['angles'][i]))/math.sqrt(32)
        gains=math.sqrt(power)*fading;output+=filtered*gains;traces.append(gains[shown]);measured.append(float(np.mean(abs(gains)**2)))
    memory['tail']=extended[-tail:].copy();memory['offset']+=len(data)
    details={k:(v.tolist() if isinstance(v,np.ndarray) else v) for k,v in parameters.items()}
    details.update(interpolation='17 点 Kaiser 窗 sinc',filter_delay_samples=8,doppler_hz=q['doppler_hz'],
        sample_indices=(shown+memory['offset']-len(data)).tolist(),path_gains=arrays(np.array(traces).T),
        measured_path_power=measured,processed_samples=memory['offset'])
    return output,details


def run_stage(kind,data,q,state,rng,fs):
    if kind=='tx_mlse_frame':
        data,state['mlse_public']=mlse_frame(data,state['scheme'],q['training'])
        return data,{'training_symbols':q['training'],'termination_symbols':2},fs
    if kind=='rx_mlse':
        data,details=mlse_decode(data,state['mlse_public'],q['taps']);return data,details,fs
    if kind in ('rx_music','rx_music_mvdr'):
        s=state['spatial'];public={k:s[k] for k in ('pilot','prefix','count','spacing')}
        if kind=='rx_music':
            details=music_estimate(s['received'],public,q);state['music_observation']=details['music']
            return data,details,fs
        selected=state['music_observation'];params={'look_angle':selected['target_angle'],'loading':q['loading']}
        data,details=array.receive(s['received'],public,'rx_array_mvdr',params)
        details['music']=selected;state['soft_variance']=np.asarray(details['effective_noise_variance'])
        return data,details,fs
    tail=tdl_parameters(q,fs)['tail_samples']
    data,details=tdl_process(np.r_[data,np.zeros(tail,complex)],q,fs,rng)
    details['guard_samples']=tail
    return data,details,fs
