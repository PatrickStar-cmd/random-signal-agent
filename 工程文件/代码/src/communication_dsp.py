"""Complex waveform algorithms; receiver functions take no payload truth or CSI."""
import math
import numpy as np
from src import baseband
from src import communication_runtime as runtime


def constellation(scheme):
    from src import communications as c
    if scheme == 'ook': return np.array([[0],[1]],dtype=np.uint8), np.array([0,math.sqrt(2)],dtype=complex)
    labels,points=c.constellation({'dbpsk':'bpsk','dqpsk':'qpsk'}.get(scheme,scheme))
    if scheme=='dqpsk': points=np.exp(1j*np.array([0,np.pi/2,-np.pi/2,np.pi]))
    return labels,points


def map_bits(bits, scheme):
    labels, points=constellation(scheme); width=labels.shape[1]
    groups=np.pad(bits,(0,-len(bits)%width)).reshape(-1,width)
    indices=groups.dot(2**np.arange(width-1,-1,-1))
    if scheme in ('dbpsk','dqpsk'):
        increments=np.array([1,-1]) if scheme=='dbpsk' else np.exp(1j*np.array([0,np.pi/2,-np.pi/2,np.pi]))
        return np.r_[1+0j,np.cumprod(increments[indices])],indices
    return points[indices],indices


def decisions(symbols, scheme):
    labels,points=constellation(scheme)
    if scheme in ('dbpsk','dqpsk'):
        symbols=symbols[1:]*symbols[:-1].conj()
        points=np.array([1,-1]) if scheme=='dbpsk' else np.exp(1j*np.array([0,np.pi/2,-np.pi/2,np.pi]))
    if scheme=='ook': indices=(abs(symbols)>math.sqrt(2)/2).astype(int)
    else: indices=np.argmin(abs(symbols[:,None]-points[None,:])**2,axis=1)
    return labels[indices].ravel(),indices


def soft_demod(symbols, scheme, noise):
    labels,points=constellation(scheme)
    distance=abs(symbols[:,None]-points)**2
    return np.column_stack([(np.min(distance[:,labels[:,b]==1],axis=1)-np.min(distance[:,labels[:,b]==0],axis=1))/noise for b in range(labels.shape[1])]).ravel()


def frequency_modulate(bits, scheme, q):
    sps=q['sps']; levels=2*bits.astype(float)-1
    if scheme=='fsk2':
        t=np.arange(sps)/sps
        return np.exp(1j*np.pi*levels[:,None]*t).ravel()
    frequency=np.repeat(levels,sps)
    if scheme=='gmsk':
        # Gaussian filter: power response is -3 dB at f=B, BT=B*T.
        t=np.arange(-2*sps,2*sps+1)/sps
        h=np.exp(-2*(np.pi*q['bt']*t)**2/np.log(2)); h/=h.sum()
        frequency=np.convolve(np.pad(frequency,(2*sps,2*sps),mode='edge'),h,mode='valid')
    return np.exp(1j*np.r_[0,np.cumsum(frequency)*np.pi/(2*sps)])


def frequency_demodulate(wave, scheme, q, coherent=False):
    sps=q['sps']
    if scheme=='fsk2':
        rows=wave.reshape(-1,sps); templates=np.exp(1j*np.pi*np.array([-1,1])[:,None]*np.arange(sps)/sps)
        correlation=rows@templates.conj().T
        indices=np.argmax(correlation.real if coherent else abs(correlation)**2,axis=1)
        return indices.astype(np.uint8)
    increments=np.angle(wave[1:]*wave[:-1].conj()).reshape(-1,sps)
    return (increments.sum(axis=1)>0).astype(np.uint8)


def rrc(q):
    h=baseband.pulse({**q,'pulse':5})
    return h/np.linalg.norm(h)


def public_preamble(length, scheme):
    # Public fixed format, independent of source seed, payload and channel.
    _,points=constellation(scheme)
    return np.random.default_rng(43017).choice(points,length)


def complex_taps(q):
    try: taps=np.array([complex(v.strip()) for v in q['taps'].split(',')])
    except ValueError as exc: raise ValueError('多径抽头须为逗号分隔的实数或复数。') from exc
    if not 1<=len(taps)<=17 or not np.all(np.isfinite(taps)) or np.max(abs(taps))>8 or np.linalg.norm(taps)<1e-10:
        raise ValueError('多径需要 1–17 个有限抽头，幅值不超过 8，且不能全为零。')
    h=np.zeros((len(taps)-1)*q['spacing']+1,dtype=complex); h[::q['spacing']]=taps
    return h


def interp(wave, positions):
    x=np.arange(len(wave))
    return np.interp(positions,x,wave.real,left=0,right=0)+1j*np.interp(positions,x,wave.imag,left=0,right=0)


def fading(count, sample_rate, doppler, rng, k_db=None,state_key='fading'):
    def initial():
        value={'offset':0}
        if doppler==0: value['scatter']=(rng.normal()+1j*rng.normal())/math.sqrt(2)
        else: value.update(phases=rng.uniform(-np.pi,np.pi,32),angles=rng.uniform(-np.pi,np.pi,32))
        if k_db is not None: value['los_phase']=rng.uniform(-np.pi,np.pi)
        return value
    memory=runtime.state(state_key,initial);offset=memory['offset'];memory['offset']+=count
    if doppler==0:
        scatter=np.full(count,memory['scatter'])
    else:
        t=(offset+np.arange(count))/sample_rate; phases=memory['phases']; angles=memory['angles']
        scatter=np.zeros(count,dtype=complex)
        for phase,angle in zip(phases,angles): scatter+=np.exp(1j*(phase+2*np.pi*doppler*np.cos(angle)*t))/math.sqrt(32)
    if k_db is None: return scatter
    k=10**(k_db/10); phase=memory['los_phase']
    los=np.exp(1j*(phase+2*np.pi*doppler*(offset+np.arange(count))/sample_rate))
    return math.sqrt(1/(k+1))*scatter+math.sqrt(k/(k+1))*los


def coarse_frequency(wave, fs, scheme):
    order=2 if scheme=='bpsk' else 4
    nfft=1<<int(np.ceil(np.log2(max(64,len(wave)*4))))
    transformed=wave**order
    spectrum=abs(np.fft.fft(transformed*np.hanning(len(wave)),nfft))**2
    peak=int(np.argmax(spectrum)); left,center,right=np.log(np.maximum(spectrum[[(peak-1)%nfft,peak,(peak+1)%nfft]],1e-30))
    correction=.5*(left-right)/(left-2*center+right) if abs(left-2*center+right)>1e-12 else 0
    frequency=((peak+correction+nfft/2)%nfft-nfft/2)*fs/nfft/order
    corrected=wave*np.exp(-2j*np.pi*frequency*np.arange(len(wave))/fs)
    return corrected,{'estimated_hz':float(frequency),'power_order':order}


def timing_recover(wave, sps, bandwidth=.005, manual=False, offset=0):
    if float(sps).is_integer():
        sps=int(sps);phase=float(offset*sps%sps) if manual else float(np.argmax([np.mean(abs(wave[p::sps])**2) for p in range(sps)]))
    else:
        candidates=np.linspace(0,sps,max(4,int(math.ceil(sps))),endpoint=False)
        phase=float(offset*sps%sps) if manual else float(candidates[np.argmax([np.mean(abs(interp(wave,p+np.arange(int(len(wave)/sps))*sps))**2) for p in candidates])])
    memory=runtime.state('timing',lambda:{'period':float(sps),'phase':phase})
    if not manual: phase=memory['phase']
    # Use scalar interpolation in the loop; complexity is linear in sample count.
    def sample(t):
        i=int(t); f=t-i
        return wave[i]*(1-f)+wave[i+1]*f if 0<=i<len(wave)-1 else 0j
    position=phase+sps; period=memory['period']; output=[sample(phase)]; phases=[phase/sps]; errors=[]
    power=max(float(np.mean(abs(wave)**2)),1e-12)
    while position<len(wave)-sps:
        early=output[-1]; middle=sample(position-period/2); current=sample(position)
        error=float(np.clip(np.real((early-current)*middle.conjugate())/power,-2,2))
        if not manual:
            period=float(np.clip(period+bandwidth**2*error,sps*.995,sps*1.005))
        output.append(current); phases.append((position-len(phases)*sps)/sps); errors.append(error)
        position+=period+(0 if manual else 2*bandwidth*error)
    stride=max(1,len(phases)//512)
    memory.update(period=period,phase=float((position-len(wave))%sps))
    return np.array(output),{'method':'手动相位' if manual else 'Gardner PI','phases':phases[::stride],'phase_step':stride,'frequency_ppm':(period/sps-1)*1e6,'error':errors[::stride]}


def carrier_recover(symbols, scheme, bandwidth):
    memory=runtime.state('carrier',lambda:{'phase':0.,'frequency':0.})
    _,points=constellation(scheme);phase=memory['phase'];frequency=memory['frequency'];output=np.zeros_like(symbols); trace=[]
    # Normalize for phase detector only; output retains measured amplitude.
    rms=max(float(np.sqrt(np.mean(abs(symbols)**2))),1e-12)
    for i,x in enumerate(symbols):
        value=x*np.exp(-1j*phase); normalized=value/rms
        target=points[np.argmin(abs(normalized-points))]
        error=float(np.clip(np.angle(normalized*target.conjugate()),-.5,.5)) if abs(value)>1e-8 else 0.
        frequency+=bandwidth**2*error; phase+=frequency+2*bandwidth*error
        output[i]=value
        if i%16==0: trace.append(float(phase))
    memory.update(phase=float(phase%(2*np.pi)),frequency=float(frequency))
    return output,{'phase_trace':trace,'residual_cycles_per_symbol':float(frequency/(2*np.pi))}


def frame_sync(symbols, preamble, count, threshold):
    if len(symbols)<len(preamble): raise ValueError('接收样本不足以检测前导。')
    correlation=np.correlate(symbols,preamble,mode='valid')
    energy=np.convolve(abs(symbols)**2,np.ones(len(preamble)),mode='valid')
    score=abs(correlation)/np.sqrt(np.maximum(energy*np.sum(abs(preamble)**2),1e-24))
    start=int(np.argmax(score)); detected=bool(score[start]>=threshold)
    # Keep failures observable in BER/FER instead of aborting a Monte Carlo run.
    frame=np.pad(symbols[start:start+count],(0,max(0,count-(len(symbols)-start))))
    known=frame[:len(preamble)]
    gain=np.vdot(preamble,known)/np.vdot(preamble,preamble)
    if abs(gain)>1e-8: frame=frame/gain
    step=max(1,len(score)//512)
    return frame,{'detected':detected,'start_symbol':start,'peak':float(score[start]),'gain_i':float(gain.real),'gain_q':float(gain.imag),'correlation':score[::step].tolist(),'correlation_step':step}


def equalize(symbols, points, q, training=None, cma=False):
    half=q['half_taps']; nt=2*half+1; nf=q.get('feedback_taps',0) if q.get('dfe',False) else 0
    memory=runtime.state('equalizer',lambda:{'weights':np.eye(1,nt+nf,half,dtype=complex).ravel(),'feedback':np.zeros(nf,dtype=complex),'covariance':np.eye(nt+nf,dtype=complex)*100})
    weights=memory['weights'];feedback=memory['feedback'];covariance=memory['covariance']
    padded=np.pad(symbols,(half,half));output=np.zeros_like(symbols)
    errors=[]; trace=[]; target_modulus=float(np.mean(abs(points)**4)/np.mean(abs(points)**2))
    for i in range(len(symbols)):
        x=np.r_[padded[i:i+nt][::-1],feedback]
        y=np.vdot(weights,x); decision=points[np.argmin(abs(y-points))]
        desired=training[i] if training is not None and i<len(training) else decision
        error=y*(target_modulus-abs(y)**2) if cma else desired-y
        norm=1e-8+float(np.vdot(x,x).real)
        if not cma and q['algorithm']==2:
            px=covariance@x; gain=px/(q['forgetting']+np.vdot(x,px))
            weights+=gain*error.conjugate()
            covariance=(covariance-np.outer(gain,x.conj()@covariance))/q['forgetting']
        else:
            denominator=norm if cma or q['algorithm']==1 else 1
            weights+=q['step_size']*x*error.conjugate()/denominator
        if not np.all(np.isfinite(weights)) or np.linalg.norm(weights)>100:
            raise ValueError('均衡器未收敛，请减小步长或增加训练前导。')
        if nf: feedback=np.r_[desired,feedback[:-1]]
        output[i]=y; errors.append(float((target_modulus-abs(y)**2)**2 if cma else abs(error)**2))
        if (i+1)%32==0: trace.append({'symbol':i+1,'mse':float(np.mean(errors[-32:]))})
    if len(symbols)%32: trace.append({'symbol':len(symbols),'mse':float(np.mean(errors[-(len(symbols)%32):]))})
    memory.update(weights=weights,feedback=feedback,covariance=covariance)
    return output,{'method':'CMA' if cma else '自适应 DFE' if nf else '自适应线性','algorithm':'CMA' if cma else ['LMS','NLMS','RLS'][q['algorithm']], 'error_trace':trace,'updates':len(symbols),'training_symbols':0 if training is None else len(training),'weights_i':weights.real.tolist(),'weights_q':weights.imag.tolist()}


def insert_pilots(symbols, interval):
    chunks=[np.r_[1+0j,symbols[i:i+interval]] for i in range(0,len(symbols),interval)]
    return np.concatenate(chunks)


def estimate_pilots(symbols, interval, count, floor):
    locations=np.arange(0,len(symbols),interval+1); estimates=symbols[locations]
    h=interp(estimates,np.interp(np.arange(len(symbols)),locations,np.arange(len(locations))))
    corrected=symbols*h.conj()/(abs(h)**2+floor)
    mask=np.ones(len(symbols),dtype=bool); mask[locations]=False
    return corrected[mask][:count],{'pilot_positions':locations.tolist(),'gain_i':estimates.real.tolist(),'gain_q':estimates.imag.tolist()}


def ofdm_indices(nfft):
    active=np.arange(1,nfft); pilots=active[active%4==1]; data=active[active%4!=1]
    return active,pilots,data


def ofdm_modulate(symbols, q):
    n,cp=q['nfft'],q['cp']; active,pilots,data=ofdm_indices(n)
    rows=math.ceil(len(symbols)/len(data)); grid=np.zeros((rows+1,n),dtype=complex)
    # Public BPSK training avoids the all-ones time-domain impulse.
    grid[0,active]=np.random.default_rng(43064).choice([-1,1],len(active))
    grid[1:,pilots]=1; grid[1:,data]=np.pad(symbols,(0,rows*len(data)-len(symbols))).reshape(rows,-1)
    time=np.fft.ifft(grid,axis=1)*math.sqrt(n)
    wave=np.concatenate((time[:,-cp:],time),axis=1).ravel()
    return wave,{'nfft':n,'cp':cp,'data_carriers':data.tolist(),'pilot_carriers':pilots.tolist(),'symbols':rows,'papr_db':float(10*np.log10(np.max(abs(wave)**2)/np.mean(abs(wave)**2)))}


def ofdm_demodulate(wave, q, receive, count):
    n,cp=q['nfft'],q['cp']; active,pilots,data=ofdm_indices(n)
    training,_=ofdm_modulate(np.zeros(1,dtype=complex),q); training=training[:n+cp]
    corr=abs(np.correlate(wave,training,mode='valid'))
    start=int(np.argmax(corr)); rows=1+math.ceil(count/len(data)); length=rows*(n+cp)
    packet=wave[start:start+length]; packet=np.pad(packet,(0,length-len(packet)))
    grid=np.fft.fft(packet.reshape(rows,n+cp)[:,cp:],axis=1)/math.sqrt(n)
    known=np.random.default_rng(43064).choice([-1,1],len(active)); h=np.ones(n,dtype=complex); h[active]=grid[0,active]/known
    output=grid[1:].copy()
    if receive['equalize']:
        output*=h.conj()/(abs(h)**2+receive['regularization'])
        phases=np.angle(np.sum(output[:,pilots],axis=1)); output*=np.exp(-1j*phases[:,None])
    return output[:,data].ravel()[:count],{'start_sample':start,'channel_i':h.real.tolist(),'channel_q':h.imag.tolist(),'grid_i':output[:16].real.tolist(),'grid_q':output[:16].imag.tolist()}
