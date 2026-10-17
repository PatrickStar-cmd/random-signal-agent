"""Receiver estimation, resampling, FSE and realistic packet impairments."""
import math
import numpy as np
from src import communication_runtime as runtime, communication_dsp as dsp


def agc(data,q):
    memory=runtime.state('agc',lambda:{'log_gain':0.});gain=memory['log_gain'];out=np.empty_like(data);trace=[]
    target=q['target']**2
    for i,x in enumerate(data):
        y=x*np.exp(gain);out[i]=y
        if abs(x)>1e-12: gain=float(np.clip(gain+q['step']*(target-abs(y)**2)/max(target,abs(y)**2),-9.2,9.2))
        if i%16==0: trace.append(float(np.exp(gain)))
    memory['log_gain']=gain
    return out,{'gain':float(np.exp(gain)),'gain_trace':trace,'output_power':float(np.mean(abs(out)**2))}


def noise_estimate(symbols,points,training=None):
    if training is not None and len(training):
        count=min(len(training),len(symbols));x=training[:count];y=symbols[:count];h=np.vdot(x,y)/max(float(np.vdot(x,x).real),1e-20)
        residual=y-h*x;degrees=max(1,count-1)
        variance=float(np.vdot(residual,residual).real/degrees);method='公共前导 LS 残差'
    else:
        nearest=points[np.argmin(abs(symbols[:,None]-points)**2,axis=1)]
        variance=float(np.mean(abs(symbols-nearest)**2));method='判决残差'
    return max(variance,1e-8),{'variance':max(variance,1e-8),'method':method}


def resample(data,up,down):
    """Windowed-sinc fractional interpolation with anti-alias cutoff."""
    ratio=up/down;count=math.ceil(len(data)*ratio);result=np.empty(count,dtype=complex);radius=16;cutoff=min(1.,ratio)
    for start in range(0,count,2048):
        positions=np.arange(start,min(count,start+2048))/ratio;center=np.floor(positions).astype(int)
        indices=center[:,None]+np.arange(-radius+1,radius+1);distance=positions[:,None]-indices
        kernel=cutoff*np.sinc(cutoff*distance)*np.where(abs(distance)<radius,.5+.5*np.cos(np.pi*distance/radius),0)
        kernel/=np.maximum(kernel.sum(axis=1,keepdims=True),1e-12)
        valid=(indices>=0)&(indices<len(data));samples=data[np.clip(indices,0,len(data)-1)]*valid
        result[start:start+len(positions)]=np.sum(samples*kernel,axis=1)
    return result


def fse(wave,sps,training,count,points,q):
    # Acquisition uses public training, never payload truth or configured CSI.
    phases=np.linspace(0,sps,max(4,int(math.ceil(sps))),endpoint=False);best=None
    for phase in phases:
        samples=dsp.interp(wave,phase+np.arange(int(len(wave)/sps))*sps)
        _,info=dsp.frame_sync(samples,training,count,.05)
        if best is None or info['peak']>best[0]: best=(info['peak'],phase,info)
    _,phase,info=best;start=phase+info['start_symbol']*sps
    gain=complex(info['gain_i'],info['gain_q']);half=q['half_taps'];nt=2*half+1
    memory=runtime.state('fse',lambda:{'weights':np.eye(1,nt,half,dtype=complex).ravel()});weights=memory['weights']
    output=np.empty(count,dtype=complex);errors=[];trace=[]
    for i in range(count):
        positions=start+i*sps+np.arange(half,-half-1,-1)*sps/2
        x=dsp.interp(wave,positions)/(gain if abs(gain)>1e-8 else 1)
        y=np.vdot(weights,x);desired=training[i] if i<len(training) else points[np.argmin(abs(y-points))]
        error=desired-y;weights+=q['step']*x*error.conjugate()/(1e-8+np.vdot(x,x).real)
        output[i]=y;errors.append(float(abs(error)**2))
        if (i+1)%32==0: trace.append({'symbol':i+1,'mse':float(np.mean(errors[-32:]))})
    if count%32: trace.append({'symbol':count,'mse':float(np.mean(errors[-(count%32):]))})
    return output,{'method':'分数间隔线性均衡','algorithm':'NLMS / T/2','error_trace':trace,'updates':count,'training_symbols':len(training),'tap_spacing':.5,'acquisition':info,'weights_i':weights.real.tolist(),'weights_q':weights.imag.tolist()}


def ofdm_frequency(wave,q,fs,search):
    n,cp=q['nfft'],q['cp'];period=n+cp
    products=wave[n:]*wave[:-n].conj();integral=np.r_[0,np.cumsum(products)]
    best=0j
    for offset in range(period):
        starts=np.arange(offset,len(products)-cp+1,period)
        value=np.sum(integral[starts+cp]-integral[starts])
        if abs(value)>abs(best): best=value
    fractional=float(np.angle(best)*fs/(2*np.pi*n));corrected=wave*np.exp(-2j*np.pi*fractional*np.arange(len(wave))/fs)
    scores=[];starts=[]
    for integer in range(-search,search+1):
        trial=corrected*np.exp(-2j*np.pi*integer*np.arange(len(wave))/n)
        start,score=ofdm_acquire(trial,q);scores.append(score);starts.append(start)
    integer=int(np.argmax(scores))-search;frequency=fractional+integer*fs/n
    return wave*np.exp(-2j*np.pi*frequency*np.arange(len(wave))/fs),{'estimated_hz':frequency,'fractional_hz':fractional,'integer_subcarriers':integer,'cp_correlation':float(abs(best)),'start_sample':starts[integer+search]}


def ofdm_acquire(wave,q):
    n,cp=q['nfft'],q['cp'];known_wave,_=dsp.ofdm_modulate(np.zeros(1,dtype=complex),q);known_wave=known_wave[:n+cp]
    correlation=abs(np.correlate(wave,known_wave,mode='valid'))
    energy=np.convolve(abs(wave)**2,np.ones(n+cp),mode='valid')
    normalized=correlation/np.sqrt(np.maximum(energy*np.sum(abs(known_wave)**2),1e-24))
    candidates=np.argpartition(normalized,-min(32,len(normalized)))[-min(32,len(normalized)):]
    active,_,_=dsp.ofdm_indices(n);known=np.random.default_rng(43064).choice([-1,1],len(active));best=(-1.,0)
    for start in candidates:
        received=np.fft.fft(wave[start+cp:start+cp+n])/math.sqrt(n)
        response=np.zeros(n,dtype=complex);response[active]=received[active]/known
        impulse=abs(np.fft.ifft(response))**2
        concentration=float(np.max(np.convolve(np.r_[impulse,impulse[:cp]],np.ones(cp),mode='valid'))/max(impulse.sum(),1e-24))
        score=concentration+.01*normalized[start]
        if score>best[0]: best=(score,int(start))
    return best[1],best[0]


def ofdm_tracking(wave,q,receive,count):
    n,cp=q['nfft'],q['cp'];active,pilots,data=dsp.ofdm_indices(n)
    start,_=ofdm_acquire(wave,q);rows=1+math.ceil(count/len(data));length=rows*(n+cp)
    packet=np.pad(wave[start:start+length],(0,max(0,length-len(wave[start:start+length]))))
    grid=np.fft.fft(packet.reshape(rows,n+cp)[:,cp:],axis=1)/math.sqrt(n)
    known=np.random.default_rng(43064).choice([-1,1],len(active));h=np.ones(n,dtype=complex);h[active]=grid[0,active]/known
    length_h=min(cp,len(pilots));matrix=np.exp(-2j*np.pi*pilots[:,None]*np.arange(length_h)/n);inverse=np.linalg.pinv(matrix)
    output=grid[1:].copy();history=[]
    for i in range(rows-1):
        measured=grid[i+1,pilots]
        if receive['method']==0: estimated=np.interp(np.arange(n),pilots,measured.real)+1j*np.interp(np.arange(n),pilots,measured.imag)
        else: estimated=np.fft.fft(inverse@measured,n)
        h=(1-receive['tracking_gain'])*h+receive['tracking_gain']*estimated
        output[i]*=h.conj()/(abs(h)**2+receive['regularization']);history.append(h.copy())
    return output[:,data].ravel()[:count],{'start_sample':start,'channel_i':h.real.tolist(),'channel_q':h.imag.tolist(),'grid_i':output[:16].real.tolist(),'grid_q':output[:16].imag.tolist(),
        'tracking':'DFT 导频 LS' if receive['method'] else '线性插值导频 LS','tracking_gain':receive['tracking_gain'],'channel_history_i':[v.real.tolist() for v in history[:16]],'channel_history_q':[v.imag.tolist() for v in history[:16]]}


def parse_paths(q):
    try:
        delays=[int(v.strip()) for v in q['delays'].split(',')];powers=np.array([float(v.strip()) for v in q['powers_db'].split(',')])
    except ValueError as exc: raise ValueError('路径延迟须为整数，功率须为 dB 数值。') from exc
    if not 1<=len(delays)<=8 or len(delays)!=len(powers) or min(delays)<0 or max(delays)>128 or not np.all(np.isfinite(powers)) or min(powers)<-60 or max(powers)>30: raise ValueError('需要 1–8 条路径，延迟 0–128 点，功率 −60–30 dB，两个列表等长。')
    weights=10**(powers/10);return delays,np.sqrt(weights/weights.sum())


def time_multipath(data,q,fs,rng):
    delays,weights=parse_paths(q);maximum=max(delays)
    memory=runtime.state('multipath_history',lambda:{'tail':np.zeros(maximum,dtype=complex)})
    extended=np.r_[memory['tail'],data];output=np.zeros(len(data),dtype=complex)
    for i,(delay,weight) in enumerate(zip(delays,weights)):
        h=dsp.fading(len(data),fs,q['doppler'],rng,state_key='path-'+str(i))
        output+=weight*h*extended[maximum-delay:maximum-delay+len(data)]
    if maximum: memory['tail']=extended[-maximum:].copy()
    return output


def burst_noise(data,q,power,rng):
    memory=runtime.state('burst',lambda:{'bad':False});bad=memory['bad'];mask=np.zeros(len(data),dtype=bool)
    for i,value in enumerate(rng.random(len(data))):
        bad=(value>=q['bad_to_good']) if bad else (value<q['good_to_bad']);mask[i]=bad
    memory['bad']=bool(bad)
    variance=power*10**(-np.where(mask,q['bad_snr'],q['good_snr'])/10)
    noise=np.sqrt(variance/2)*(rng.normal(size=len(data))+1j*rng.normal(size=len(data)))
    return data+noise,{'bad_samples':int(mask.sum()),'bad_fraction':float(mask.mean()),'state_trace':mask[:512].astype(int).tolist()}
