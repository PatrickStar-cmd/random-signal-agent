"""RF models and full-array experiment measurements (complex baseband)."""
import math
import numpy as np
from src import communication_runtime as runtime

SCHEMES = ('bpsk', 'qpsk', 'psk8', 'qam16', 'qam64', 'qam256')
TX = {'tx_pa', 'tx_clip_filter'}
CHANNEL = {'iq_imbalance', 'dc_offset', 'adc', 'narrowband'}
RX = {'rx_iq', 'rx_dc', 'rx_notch'}


def constellation(scheme):
    width = {'psk8': 3, 'qam64': 6, 'qam256': 8}[scheme]
    words = np.arange(2**width)
    labels = ((words[:, None] >> np.arange(width-1, -1, -1)) & 1).astype(np.uint8)
    def ungray(v):
        out = v.copy(); shift = v >> 1
        while np.any(shift): out ^= shift; shift >>= 1
        return out
    if scheme == 'psk8': points = np.exp(2j*np.pi*ungray(words)/8)
    else:
        side = 2**(width//2)
        points = (2*ungray(words//side)-side+1 + 1j*(2*ungray(words%side)-side+1))/math.sqrt(2*(side**2-1)/3)
    return labels, points


def process(kind, x, q, fs, ofdm=None, training=None):
    x = np.asarray(x, dtype=complex); details = {}
    if kind == 'iq_imbalance':
        gain = 10**(q['gain_db']/20); phase = np.deg2rad(q['phase_deg'])
        y = x.real + 1j*gain*(x.imag*np.cos(phase)+x.real*np.sin(phase))
    elif kind == 'dc_offset': y = x + complex(q['i'], q['q'])
    elif kind == 'rx_dc':
        if q['method'] == 0:
            mean = x.mean(); y = x-mean; details = {'offset_i':float(mean.real),'offset_q':float(mean.imag)}
        else:
            memory = runtime.state('dc', lambda:{'x':0j,'y':0j}); y = np.empty_like(x)
            for i, sample in enumerate(x):
                memory['y'] = sample-memory['x']+q['pole']*memory['y']; memory['x'] = sample; y[i] = memory['y']
    elif kind == 'rx_iq':
        count = min(len(training),len(x)); t = training[:count]
        matrix = np.column_stack((t,t.conj()))
        a,b = np.linalg.lstsq(matrix,x[:count],rcond=None)[0]; determinant = abs(a)**2-abs(b)**2
        if np.linalg.matrix_rank(matrix)<2 or abs(determinant)<1e-8: raise ValueError('I/Q 校正需要非退化的复数训练星座。')
        y = (a.conjugate()*x-b*x.conj())/determinant
        details = {'direct_i':float(a.real),'direct_q':float(a.imag),'image_i':float(b.real),'image_q':float(b.imag)}
    elif kind == 'adc':
        scale=q['full_scale']; levels=2**q['bits']-1
        def quantize(v): return np.rint((np.clip(v,-scale,scale)+scale)*levels/(2*scale))*2*scale/levels-scale
        y=quantize(x.real)+1j*quantize(x.imag)
        details={'clipped_samples':int(np.count_nonzero((abs(x.real)>scale)|(abs(x.imag)>scale))),'step':2*scale/levels}
    elif kind == 'tx_pa':
        z=x*10**(-q['backoff_db']/20); amplitude=abs(z)/q['saturation']
        if q['model']==0:
            magnitude=q['saturation']*amplitude/(1+amplitude**(2*q['smoothness']))**(1/(2*q['smoothness'])); phase=np.angle(z)
        else:
            magnitude=q['saturation']*amplitude/(1+amplitude**2)
            phase=np.angle(z)+np.deg2rad(q['phase_deg'])*amplitude**2/(1+amplitude**2)
        y=magnitude*np.exp(1j*phase)
    elif kind == 'narrowband':
        memory=runtime.state('tone',lambda:{'phase':0.})
        phase=memory['phase']+2*np.pi*q['hz']*np.arange(len(x))/fs
        memory['phase']=float((memory['phase']+2*np.pi*q['hz']*len(x)/fs)%(2*np.pi))
        y=x+q['amplitude']*np.exp(1j*phase)
    elif kind == 'rx_notch':
        memory=runtime.state('notch',lambda:{'x':0j,'y':0j}); y=np.empty_like(x)
        zero=np.exp(2j*np.pi*q['hz']/fs); pole=q['pole']*zero
        for i,sample in enumerate(x):
            value=sample-zero*memory['x']+pole*memory['y']; memory.update(x=sample,y=value); y[i]=value
    elif kind == 'tx_clip_filter':
        from src.communication_dsp import ofdm_indices
        n,cp=ofdm['nfft'],ofdm['cp']; active,_,_=ofdm_indices(n,ofdm)
        # Interpolate each useful OFDM symbol 4x before clipping; project back
        # onto allocated carriers, then regenerate its cyclic prefix.
        rows=x.reshape(-1,n+cp)[:,cp:]; bins=np.fft.fft(rows,axis=1)
        large=np.zeros((len(rows),4*n),complex); signed=np.where(active<=n//2,active,active-n)
        large[:,signed%(4*n)]=bins[:,active]*4
        y4=np.fft.ifft(large,axis=1); threshold=np.sqrt(np.mean(abs(y4)**2,axis=1,keepdims=True))*10**(q['threshold_db']/20)
        mask=np.zeros(4*n,bool);mask[signed%(4*n)]=True
        for _ in range(q['iterations']):
            y4*=np.minimum(1,threshold/np.maximum(abs(y4),1e-15))
            spectrum=np.fft.fft(y4,axis=1);spectrum[:,~mask]=0;y4=np.fft.ifft(spectrum,axis=1)
        rows=y4[:,::4];y=np.concatenate((rows[:,-cp:],rows),axis=1).ravel()
        details={'oversampling':4,'threshold_db':q['threshold_db']}
    else: raise ValueError('未知射频处理。')
    return y,details


def measure(x, fs):
    """Two-sided Welch density, Hann/50% overlap, full frame coverage."""
    x=np.asarray(x,complex); size=min(1024,len(x)); window=np.hanning(size) if size>2 else np.ones(size)
    starts=list(range(0,max(1,len(x)-size+1),max(1,size//2)))
    if starts[-1]!=len(x)-size: starts.append(len(x)-size)
    density=np.zeros(size)
    for start in starts: density+=abs(np.fft.fft(x[start:start+size]*window))**2
    density=np.fft.fftshift(density/(len(starts)*fs*np.sum(window**2)))
    frequency=np.fft.fftshift(np.fft.fftfreq(size,1/fs)); mass=density.sum(); cumulative=np.cumsum(density)/max(mass,1e-30)
    lo=min(size-1,int(np.searchsorted(cumulative,.005)));hi=min(size-1,int(np.searchsorted(cumulative,.995)))
    power=abs(x)**2;mean=float(power.mean());relative=power/max(mean,1e-30);thresholds=np.linspace(0,15,61)
    return {'sample_rate':fs,'count':len(x),'power':mean,'papr_db':float(10*np.log10(max(1,float(relative.max())))),
        'occupied_bandwidth_hz':float(frequency[hi]-frequency[lo]+fs/size) if mass>0 else 0.,
        'frequency_hz':frequency.tolist(),'density':density.tolist(),'density_db':(10*np.log10(np.maximum(density,1e-30))).tolist(),
        'ccdf_db':thresholds.tolist(),'ccdf':[(float(np.mean(relative>10**(v/10)))) for v in thresholds],
        'method':'Welch · Hann · 50% overlap','segments':len(starts)}


def analyze(tx, channel, reference, received, fs, bit_count, ofdm=None, stages=None):
    sending=measure(tx,fs); receiving=measure(channel,fs)
    duration=len(tx)/fs; result={'tx':sending,'channel':receiving,'stages':stages or [],'duration_seconds':duration,
        'net_bit_rate':bit_count/duration if bit_count is not None else None,'spectral_efficiency':bit_count/duration/max(sending['occupied_bandwidth_hz'],1e-30) if bit_count is not None else None,
        'efficiency_bandwidth':'发送端 99% 占用带宽','evm_trace':[]}
    for start in range(0,len(reference),128):
        ref=reference[start:start+128];rx=received[start:start+128]
        result['evm_trace'].append({'symbol':start+len(ref),'evm_percent':float(100*np.linalg.norm(rx-ref)/max(np.linalg.norm(ref),1e-15))})
    if ofdm:
        carriers=ofdm['data_carriers']; count=len(carriers); values=[]
        error=abs(received-reference)**2; energy=abs(reference)**2
        for i in range(count):
            e=energy[i::count];values.append(float(100*np.sqrt(error[i::count].sum()/max(e.sum(),1e-30))) if len(e) else None)
        result['ofdm_evm']={'carriers':carriers,'percent':values}
    return result


def theory_ber(scheme, esn0_db):
    es=10**(esn0_db/10)
    if scheme in ('bpsk','qpsk'): return .5*math.erfc(math.sqrt(es/(2 if scheme=='qpsk' else 1)))
    if scheme=='psk8': return math.erfc(math.sqrt(es)*math.sin(math.pi/8))/3
    order={'qam16':16,'qam64':64,'qam256':256}[scheme]
    return 2*(1-1/math.sqrt(order))/math.log2(order)*math.erfc(math.sqrt(3*es/(2*(order-1))))
