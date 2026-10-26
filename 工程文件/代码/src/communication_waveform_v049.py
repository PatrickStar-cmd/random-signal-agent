"""DFT-s-OFDM, measured-loopback DPD and public-marker burst synchronization."""
import math
import numpy as np
from src import communication_dsp as dsp, communication_runtime as runtime, communication_rf as rf

TX={'tx_dft_spread','tx_scfdma','tx_pa_probe','tx_dpd_fit','tx_dpd','tx_memory_pa','tx_burst_preamble'}
CHANNEL={'burst_clock'}
RX={'rx_scfdma','rx_dft_despread','rx_burst_sync'}
KINDS=TX|CHANNEL|RX


def register(block,number,field,blocks):
    block('tx_dft_spread','DFT 扩展','tx_converter','将每组调制符号作单位能量 DFT，发送端末组补零。',
          size=field('DFT 分组点数',16,'select',choices=[8,16,32,64]))
    block('tx_scfdma','SC-FDMA 子载波映射与 IFFT','tx_converter','连续或交织映射子载波，添加两组公开训练 OFDM 符号和循环前缀。',
          nfft=field('FFT 点数',64,'select',choices=[32,64,128,256]),
          cp=number('循环前缀 / 样本',16,1,64,True),
          size=field('分配子载波数',16,'select',choices=[8,16,32,64]),
          mapping=field('子载波映射',0,'select',choices=[0,1],choice_labels={0:'连续 LFDMA',1:'交织 IFDMA'}))
    block('rx_scfdma','SC-FDMA FFT 均衡与解映射','rx_converter','用重复公开训练估计频域信道，逐子载波均衡后取出分配载波。',
          regularization=number('均衡正则项',.00001,0,1))
    block('rx_dft_despread','IDFT 解扩','rx_converter','执行配对 IDFT，恢复发送符号并移除末组填充。')
    pa=dict(cubic=number('三阶系数',-.08,-.3,0),quintic=number('五阶系数',.003,0,.03),
            memory=number('延迟支路系数',.06,0,.3),depth=field('记忆深度',3,'select',choices=[1,2,3,5]),
            backoff_db=number('输入回退 / dB',3,0,12))
    block('tx_pa_probe','功放回环训练采集','tx_converter','使用公开训练序列驱动所配功放，采集实际输入与输出，提供给逆模型拟合。',
          **pa,count=field('训练样本数',4096,'select',choices=[1024,2048,4096,8192]))
    block('tx_dpd_fit','DPD 逆模型系数估计','tx_converter','通过回环输出与原始输入建立记忆多项式最小二乘逆模型。',
          order=field('多项式最高奇数阶',5,'select',choices=[3,5,7]),
          depth=field('逆模型记忆深度',3,'select',choices=[1,2,3,5]),ridge=number('岭回归系数',.000001,0,.1))
    block('tx_dpd','数字预失真器','tx_converter','将已拟合系数应用于发送波形；保留跨帧记忆，并输出系数供工程分析。')
    block('tx_memory_pa','记忆多项式功放','tx_converter','一、三、五阶复包络多项式叠加延迟支路，保留跨帧历史样本。',**pa)
    preamble=dict(method=field('前导类型',0,'select',choices=[0,1],choice_labels={0:'Schmidl–Cox 重复前导',1:'Zadoff–Chu 重复前导'}),
                  length=field('前导半长 / 样本',64,'select',choices=[32,64,128]))
    block('tx_burst_preamble','OFDM 突发同步前导','tx_converter','在波形首尾插入公开重复前导；首端捕获帧与频偏，首尾间隔用于估计采样时钟。',**preamble)
    block('burst_clock','突发延迟与采样频偏','channel','对波形施加整帧延迟、采样时钟 ppm 偏差及载波频偏。',
          delay=number('帧延迟 / 样本',27,0,1024,True),ppm=number('采样频偏 / ppm',350,-2000,2000),
          hz=number('载波频偏 / Hz',37,-10000,10000))
    block('rx_burst_sync','突发捕获与采样时钟恢复','rx_converter','重复前导相关捕获、频偏估计，首尾公开标记联合拟合采样时钟并重采样恢复波形。',
          **preamble,search=number('起始搜索窗口 / 样本',512,8,4096,True),
          max_ppm=number('采样频偏搜索范围 / ppm',1000,1,3000),
          payload_samples=number('录波有效波形长度（0 自动配对）',0,0,262144,True))


def presets(preset):
    base=['random_bits','mod_qpsk','tx_dft_spread','tx_scfdma','complex_awgn','rx_scfdma','rx_dft_despread','demod_qpsk','sink']
    pa=['random_bits','mod_qam16','tx_dft_spread','tx_scfdma','tx_pa_probe','tx_dpd_fit','tx_dpd','tx_memory_pa','complex_awgn','rx_scfdma','rx_dft_despread','demod_qam16','sink']
    sync=['random_bits','mod_qpsk','tx_ofdm','tx_burst_preamble','burst_clock','complex_awgn','rx_burst_sync','rx_ofdm','demod_qpsk','sink']
    return {
        'scfdma_localized':{'label':'新波形 · DFT-s-OFDM 连续映射','program':preset(base,{4:{'snr_db':30}})},
        'scfdma_interleaved':{'label':'新波形 · SC-FDMA 交织映射','program':preset(base,{3:{'mapping':1},4:{'snr_db':30}})},
        'ofdm_unspread_reference':{'label':'波形对照 · 相同资源的 OFDM','program':preset(['random_bits','mod_qpsk','tx_scfdma','complex_awgn','rx_scfdma','demod_qpsk','sink'],{3:{'snr_db':30}})},
        'memory_pa_dpd':{'label':'射频 · 回环训练与数字预失真','program':preset(pa,{8:{'snr_db':40}})},
        'memory_pa_reference':{'label':'射频对照 · 记忆功放输出','program':preset(['random_bits','mod_qam16','tx_dft_spread','tx_scfdma','tx_memory_pa','complex_awgn','rx_scfdma','rx_dft_despread','demod_qam16','sink'],{5:{'snr_db':40}})},
        'burst_schmidl_cox':{'label':'同步 · Schmidl–Cox 与采样时钟','program':preset(sync,{0:{'count':2048},2:{'active_count':48},5:{'snr_db':35}})},
        'burst_zadoff_chu':{'label':'同步 · Zadoff–Chu 与采样时钟','program':preset(sync,{0:{'count':2048},2:{'active_count':48},3:{'method':1},5:{'snr_db':35},6:{'method':1}})},
    }


def carriers(q):
    n,m=q['nfft'],q['size']
    if m>n//2 or n%m or q['cp']>=n: raise ValueError('分配载波数需整除 FFT 点数且至多占一半；CP 小于 FFT 点数。')
    return np.arange(m)*(n//m if q['mapping'] else 1)+1


def build_stage(kind,q,domain,count,features):
    st=features.setdefault('waveform_v049',{}); before=count
    if kind in TX and domain not in ('复符号','复采样波形','OFDM 波形'):
        raise ValueError('波形发送积木连接复符号或发送波形。')
    if kind=='tx_dft_spread':
        if domain!='复符号' or kind in st: raise ValueError('DFT 扩展放在数字映射之后，每条链路放一次。')
        count=math.ceil(count/q['size'])*q['size']; st[kind]={'params':q,'input_count':before}
    elif kind=='tx_scfdma':
        if domain!='复符号' or 'tx_scfdma' in st or any(k in features for k in ('tx_ofdm','tx_rrc','tx_frame')): raise ValueError('SC-FDMA 映射直接接数字映射或 DFT 扩展。')
        carriers(q)
        if 'tx_dft_spread' in st and st['tx_dft_spread']['params']['size']!=q['size']: raise ValueError('DFT 扩展点数与分配载波数相同。')
        count=(2+math.ceil(count/q['size']))*(q['nfft']+q['cp']);domain='OFDM 波形';st[kind]={'params':q,'input_count':before}
        features.setdefault('wireless',{}).update(tx=kind,rate_factor=q['nfft'])
    elif kind=='tx_pa_probe': st[kind]={'params':q}
    elif kind=='tx_dpd_fit':
        if 'tx_pa_probe' not in st: raise ValueError('DPD 系数拟合前先放置功放回环训练采集。')
        st[kind]={'params':q}
    elif kind=='tx_dpd':
        if 'tx_dpd_fit' not in st: raise ValueError('预失真器需要已拟合的 DPD 系数。')
        st[kind]={'params':q}
    elif kind=='tx_memory_pa':
        if 'tx_dpd' in st:
            probe=st['tx_pa_probe']['params']
            if any(q[key]!=probe[key] for key in q): raise ValueError('应用 DPD 时，实际功放参数需要与回环采集功放一致。')
        st[kind]={'params':q}
    elif kind=='tx_burst_preamble':
        if domain!='OFDM 波形' or kind in st: raise ValueError('突发前导连接 OFDM 或 SC-FDMA 波形，每帧一组。')
        st[kind]={'params':q,'input_count':count};count+=4*q['length']
    elif kind=='burst_clock':
        if domain!='OFDM 波形' or 'tx_burst_preamble' not in st: raise ValueError('突发时钟信道连接带同步前导的 OFDM 波形。')
        count=math.ceil(count*(1+q['ppm']*1e-6))+q['delay']+2
    elif kind=='rx_burst_sync':
        if domain!='OFDM 波形' or 'tx_burst_preamble' not in st: raise ValueError('同步恢复需要配对的突发前导。')
        tx=st['tx_burst_preamble']
        if any(q[key]!=tx['params'][key] for key in ('method','length')): raise ValueError('收发同步前导类型和半长相同。')
        count=tx['input_count'];st[kind]={'params':q}
    elif kind=='rx_scfdma':
        if domain!='OFDM 波形' or 'tx_scfdma' not in st: raise ValueError('SC-FDMA 接收连接配对的发送波形。')
        if 'tx_burst_preamble' in st and 'rx_burst_sync' not in st: raise ValueError('先恢复突发同步，再做 SC-FDMA FFT。')
        count=st['tx_scfdma']['input_count'];domain='复符号';features['wireless']['rx']=kind;st[kind]={'params':q}
    elif kind=='rx_dft_despread':
        if domain!='复符号' or not {'tx_dft_spread','rx_scfdma'}<=st.keys(): raise ValueError('IDFT 解扩需要 DFT 扩展和 SC-FDMA 接收。')
        count=st['tx_dft_spread']['input_count'];st[kind]={'params':q}
    features[kind]={'params':q,'input_count':before,'count':count}
    return domain,count


def validate_receiver(features):
    st=features.get('waveform_v049',{})
    for tx,rx in [('tx_dft_spread','rx_dft_despread'),('tx_scfdma','rx_scfdma'),('tx_burst_preamble','rx_burst_sync')]:
        if tx in st and rx not in st: raise ValueError('补充配对接收积木：'+rx)


def spread(x,size,inverse=False):
    rows=np.pad(x,(0,-len(x)%size)).reshape(-1,size)
    return ((np.fft.ifft(rows,axis=1)*math.sqrt(size)) if inverse else (np.fft.fft(rows,axis=1)/math.sqrt(size))).ravel()


def scfdma_encode(symbols,q):
    n,cp,m=q['nfft'],q['cp'],q['size'];indices=carriers(q);rows=math.ceil(len(symbols)/m)
    grid=np.zeros((rows+2,n),complex);known=dsp.public_preamble(m,'qpsk')
    grid[:2,indices]=known;grid[2:,indices]=np.pad(symbols,(0,rows*m-len(symbols))).reshape(rows,m)
    wave=np.fft.ifft(grid,axis=1)*math.sqrt(n)
    return np.concatenate((wave[:,-cp:],wave),axis=1).ravel(),{'params':q,'count':len(symbols),'known':known}


def scfdma_decode(wave,state,q):
    settings=state['params'];n,cp,m=settings['nfft'],settings['cp'],settings['size'];idx=carriers(settings)
    template,_=scfdma_encode(np.zeros(m),settings);template=template[:2*(n+cp)]
    corr=abs(np.correlate(wave,template,mode='valid'));start=int(np.argmax(corr));rows=2+math.ceil(state['count']/m);length=rows*(n+cp)
    packet=np.pad(wave[start:start+length],(0,max(0,start+length-len(wave))))
    grid=np.fft.fft(packet.reshape(rows,n+cp)[:,cp:],axis=1)/math.sqrt(n)
    h=np.mean(grid[:2,idx],axis=0)/state['known'];noise=float(np.mean(abs(grid[0,idx]-grid[1,idx])**2)/2)
    data=grid[2:,idx]*h.conj()/(abs(h)**2+q['regularization'])
    return data.ravel()[:state['count']],{'carriers':idx.tolist(),'channel_i':h.real.tolist(),'channel_q':h.imag.tolist(),
        'start_sample':start,'noise_variance':noise,'grid_i':data[:32].real.tolist(),'grid_q':data[:32].imag.tolist()}


def basis(x,order,depth,history=None):
    x=np.asarray(x,complex);old=np.zeros(depth-1,complex) if history is None else np.asarray(history,complex)
    padded=np.r_[old,x];cols=[]
    for delay in range(depth):
        z=padded[depth-1-delay:depth-1-delay+len(x)]
        cols.extend(z*abs(z)**(p-1) for p in range(1,order+1,2))
    return np.column_stack(cols)


def pa_coefficients(q):
    coefficients=[]
    for delay in range(q['depth']):
        weight=1 if delay==0 else q['memory']*.5**(delay-1)
        coefficients.extend([weight,weight*q['cubic']*(1+.2j),weight*q['quintic']*(1+.1j)])
    return np.array(coefficients,complex)


def pa_model(x,q,history=None):
    return basis(x*10**(-q['backoff_db']/20),5,q['depth'],history)@pa_coefficients(q)


def train_dpd(inputs,outputs,order,depth,ridge):
    matrix=basis(outputs,order,depth);gram=matrix.conj().T@matrix
    regularizer=ridge*float(np.trace(gram).real)/len(gram)
    coefficients=np.linalg.solve(gram+np.eye(len(gram))*regularizer,matrix.conj().T@inputs)
    predicted=matrix@coefficients
    return coefficients,float(np.linalg.norm(predicted-inputs)/np.linalg.norm(inputs))


def preamble(q):
    n=q['length']
    if q['method']==0:
        rng=np.random.default_rng(49001);half=(rng.choice([-1,1],n)+1j*rng.choice([-1,1],n))/math.sqrt(2)
    else:
        # Even-length Zadoff-Chu, root 1 is coprime with all supported lengths.
        k=np.arange(n);half=np.exp(-1j*np.pi*k*k/n)
    return np.tile(half,2)


def burst_encode(x,q):
    marker=preamble(q);return np.r_[marker,x,marker],{'params':q,'count':len(x)}


def burst_impair(x,q,fs):
    scale=1+q['ppm']*1e-6;locations=(np.arange(math.ceil(len(x)*scale)+q['delay']+2)-q['delay'])/scale
    # Bandlimited interpolation preserves the OFDM spectrum under clock drift.
    y=interpolate(x,locations)
    return y*np.exp(2j*np.pi*q['hz']*np.arange(len(y))/fs)


def interpolate(x,t):
    """Windowed-sinc fractional sampling, exact at integer locations."""
    t=np.asarray(t,float)
    if len(t)>4096: return np.concatenate([interpolate(x,t[i:i+4096]) for i in range(0,len(t),4096)])
    base=np.floor(t).astype(int);offset=np.arange(-48,49)
    indices=base[:,None]+offset;distance=t[:,None]-indices
    weights=np.sinc(distance)*np.sinc(distance/49);valid=(indices>=0)&(indices<len(x))
    return np.sum(np.asarray(x)[np.clip(indices,0,len(x)-1)]*weights*valid,axis=1)/np.sum(weights,axis=1)


def synchronize(wave,q,fs,payload_count):
    """Estimate offset, CFO and clock scale from two public repeated markers.

    Only marker samples and configured nominal frame length enter the objective.
    Payload samples, channel delay, frequency and ppm truth are never consulted.
    """
    wave=np.asarray(wave,complex);marker=preamble(q);n=q['length'];separation=len(marker)+payload_count
    if payload_count<1 or len(wave)<2*len(marker)+payload_count-16: raise ValueError('同步需要有效波形长度与完整首尾前导。')
    minimum_frame=math.floor((4*n+payload_count)*(1-q['max_ppm']*1e-6))
    last=max(0,min(q['search'],len(wave)-minimum_frame));offsets=np.arange(last+1)
    pairs=wave[n:]*wave[:-n].conj();p=np.convolve(pairs,np.ones(n),mode='valid')[:last+1]
    energy=np.convolve(abs(wave[n:])**2,np.ones(n),mode='valid')[:last+1]
    metric=abs(p)**2/np.maximum(energy**2,1e-20)
    # Coarse joint timing/CFO: repeated-half metric identifies candidates;
    # public-template correlation resolves the plateau and cyclic ZC sidelobes.
    candidates=[]
    for start in offsets:
        freq=np.angle(p[start])/(2*np.pi*n)
        segment=wave[start:start+2*n]*np.exp(-2j*np.pi*freq*np.arange(2*n))
        score=abs(np.vdot(marker,segment))**2/max(float(np.vdot(segment,segment).real)*len(marker),1e-20)
        candidates.append((score,int(start),freq))
    _,coarse,freq=max(candidates)
    clean=wave*np.exp(-2j*np.pi*freq*np.arange(len(wave)))
    # Refine both timing positions and the phase accrued over the full frame.
    # Optimization uses only two small, public marker regions.
    nominal=np.r_[np.arange(2*n),separation+np.arange(2*n)]
    target=np.tile(marker,2);bound=q['max_ppm']*1e-6
    def residual(parameters,details=False,vector=False):
        delay,ppm,frequency=parameters;scale=1+ppm*1e-6;t=delay+scale*nominal
        observed=interpolate(wave,t)*np.exp(-2j*np.pi*frequency*t)
        # Fit separate marker gains: phase drift is estimated locally from
        # repetition, while the inter-marker gap estimates sampling scale.
        groups=observed.reshape(2,2*n);gains=groups@marker.conj()/np.vdot(marker,marker).real
        error=groups-gains[:,None]*marker
        score=float(np.sum(abs(error)**2)/max(np.sum(abs(groups)**2),1e-20))
        if vector:
            normalized=error.ravel()/math.sqrt(max(np.sum(abs(groups)**2),1e-20))
            return np.r_[normalized.real,normalized.imag]
        return (score,gains) if details else score
    # Locate trailing marker independently, then infer initial clock slope.
    tail_center=coarse+separation;tail_range=math.ceil(abs(separation)*bound)+5
    tail_candidates=np.arange(max(coarse+2*n,tail_center-tail_range),min(len(wave)-2*n,tail_center+tail_range)+1)
    tail_scores=[abs(np.vdot(marker,clean[t:t+2*n]))**2/max(np.sum(abs(clean[t:t+2*n])**2)*len(marker),1e-20) for t in tail_candidates]
    tail=int(tail_candidates[int(np.argmax(tail_scores))]);initial_ppm=float(np.clip((tail-coarse-separation)/separation*1e6,-q['max_ppm'],q['max_ppm']))
    # Scaling parameters keeps finite differences and optimizer steps balanced.
    def errors(v):return residual([coarse+v[0],v[1]*1000,freq+v[2]/n],vector=True)
    fitted=np.array([0,initial_ppm/1000,0]);lower=np.array([-2,-q['max_ppm']/1000,-.15]);upper=-lower
    # Small three-parameter Gauss-Newton fit, bounded and entirely NumPy.
    for _ in range(30):
        error=errors(fitted);epsilon=1e-4;columns=[]
        for axis in range(3):
            shift=np.zeros(3);shift[axis]=epsilon
            columns.append((errors(fitted+shift)-errors(fitted-shift))/(2*epsilon))
        jacobian=np.column_stack(columns)
        step=np.linalg.solve(jacobian.T@jacobian+np.eye(3)*1e-8,-jacobian.T@error)
        if np.linalg.norm(step)<1e-7:break
        score=float(error@error)
        for fraction in (1,.5,.25,.125,.0625,.03125):
            candidate=np.clip(fitted+fraction*step,lower,upper);candidate_error=errors(candidate)
            if float(candidate_error@candidate_error)<score:
                fitted=candidate;break
        else:break
    delay=coarse+fitted[0];ppm=fitted[1]*1000;frequency=freq+fitted[2]/n;scale=1+ppm*1e-6
    _,gains=residual([delay,ppm,frequency],True)
    frequency+=np.angle(gains[1]*gains[0].conjugate())/(2*np.pi*scale*separation)
    t=delay+scale*(2*n+np.arange(payload_count));received=interpolate(wave,t)*np.exp(-2j*np.pi*frequency*t)
    error,gains=residual([delay,ppm,frequency],True)
    return received,{'detected':bool(error<.5),'start_sample':float(delay),'frequency_hz':float(frequency*fs),'clock_ppm':float(ppm),
        'marker_error':error,'timing_metric':metric.tolist(),'offsets':offsets.tolist(),'correlation':[v[0] for v in candidates],
        'marker_positions':[float(delay),float(delay+scale*separation)],'payload_samples':payload_count,
        'method':'Schmidl–Cox' if q['method']==0 else 'Zadoff–Chu'}


def run_stage(kind,data,q,state,rng,fs):
    st=state.setdefault('waveform_v049',{});details={};data=np.asarray(data,complex)
    if kind=='tx_dft_spread':
        st['spread']={'count':len(data),'size':q['size']};data=spread(data,q['size']);details={'dft_size':q['size'],'padding':len(data)-st['spread']['count']}
    elif kind=='tx_scfdma':
        data,st['scfdma']=scfdma_encode(data,q);fs*=q['nfft'];details={'carriers':carriers(q).tolist(),'nfft':q['nfft'],'mapping':'IFDMA' if q['mapping'] else 'LFDMA'}
    elif kind=='rx_scfdma': data,details=scfdma_decode(data,st['scfdma'],q);fs/=st['scfdma']['params']['nfft']
    elif kind=='rx_dft_despread':data=spread(data,st['spread']['size'],True)[:st['spread']['count']];details={'idft_size':st['spread']['size']}
    elif kind=='tx_pa_probe':
        train_rng=np.random.default_rng(49002);x=(train_rng.normal(size=q['count'])+1j*train_rng.normal(size=q['count']))*.48
        y=pa_model(x,q);st['probe']={'input':x,'output':y};details={'training_samples':len(x),'input_amplitude':abs(x[:512]).tolist(),
            'output_amplitude':abs(y[:512]).tolist(),'output_phase_deg':np.rad2deg(np.angle(y[:512]/x[:512])).tolist()}
    elif kind=='tx_dpd_fit':
        probe=st['probe'];coeff,error=train_dpd(probe['input'],probe['output'],q['order'],q['depth'],q['ridge'])
        st['dpd']={'coefficients':coeff,'order':q['order'],'depth':q['depth']};details={'fit_error':error,'order':q['order'],'depth':q['depth'],
            'coefficients_i':coeff.real.tolist(),'coefficients_q':coeff.imag.tolist()}
    elif kind=='tx_dpd':
        model=st['dpd'];depth=model['depth'];memory=runtime.state('dpd_history',lambda:{'x':np.zeros(depth-1,complex)})
        original=data.copy();data=basis(data,model['order'],depth,memory['x'])@model['coefficients']
        if depth>1:memory['x']=np.r_[memory['x'],original][-depth+1:]
        details={'coefficients_i':model['coefficients'].real.tolist(),'coefficients_q':model['coefficients'].imag.tolist(),
            'input_amplitude':abs(original[:512]).tolist(),'output_amplitude':abs(data[:512]).tolist(),
            'before':rf.measure(original,fs),'after':rf.measure(data,fs)}
    elif kind=='tx_memory_pa':
        depth=q['depth'];memory=runtime.state('pa_history',lambda:{'x':np.zeros(depth-1,complex)});original=data.copy()
        data=pa_model(data,q,memory['x'])
        if depth>1:memory['x']=np.r_[memory['x'],original*10**(-q['backoff_db']/20)][-depth+1:]
        details={'input_amplitude':abs(original[:512]).tolist(),'output_amplitude':abs(data[:512]).tolist(),
            'output_phase_deg':np.rad2deg(np.angle(data[:512]/np.where(abs(original[:512])>1e-12,original[:512],1))).tolist(),
            'memory_depth':depth,'input_power':float(np.mean(abs(original)**2)),'output_power':float(np.mean(abs(data)**2)),
            'before':rf.measure(original,fs),'after':rf.measure(data,fs)}
    elif kind=='tx_burst_preamble':data,st['burst']=burst_encode(data,q);details={'marker_length':2*q['length'],'payload_samples':st['burst']['count']}
    elif kind=='burst_clock':data=burst_impair(data,q,fs);details={'applied_ppm':q['ppm'],'applied_hz':q['hz'],'applied_delay':q['delay']}
    elif kind=='rx_burst_sync':
        count=q['payload_samples'] or st.get('burst',{}).get('count',0);data,details=synchronize(data,q,fs,count)
    else: raise ValueError('未知波形处理积木。')
    return data,details,fs
