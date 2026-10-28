"""SISO monostatic OFDM sensing and communication on the same measured frame.

Range/Doppler processing follows OFDM channel-ratio processing. The sensing
receiver has its own transmitted grid as a local reference; the communications
equalizer uses only the public training symbols.
"""
import math
import numpy as np
from src import communication_runtime as runtime

C=299792458.
TX={'tx_isac_ofdm'}
CHANNEL={'isac_echo'}
RX={'rx_isac_ofdm'}
KINDS=TX|CHANNEL|RX


def register(block,number,field,blocks):
    block('tx_isac_ofdm','📡 OFDM 通感组帧','tx_converter','全子载波 QPSK OFDM，两个公共训练符号；本机雷达保存发送网格作为回波参考。',
          nfft=field('FFT 点数',64,'select',choices=[32,64,128]),cp=number('循环前缀点数',16,4,64,True))
    block('isac_echo','🛰️ 单目标延迟与多普勒','channel','直达通信路径叠加单目标往返回波，距离决定分数延迟，径向速度决定多普勒。',
          range_m=number('目标距离 / m',625,1,100000),velocity_mps=number('径向速度 / m/s',37.5,-1000,1000),
          carrier_ghz=number('射频载频 / GHz',3,.1,100),amplitude=number('回波幅度',.25,0,2),direct=number('直达路径幅度',1,0,2))
    block('rx_isac_ofdm','🔭 OFDM 通信与测距测速','rx_converter','公共训练均衡恢复通信符号；本机发送参考形成实测距离—速度谱，屏蔽零距离直达单元后检测峰值。',
          carrier_ghz=number('已知射频载频 / GHz',3,.1,100),threshold_db=number('峰值高于背景 / dB',10,3,60))


def presets(preset):
    p=preset(['random_bits','mod_qpsk','tx_isac_ofdm','isac_echo','complex_awgn','rx_isac_ofdm','demod_qpsk','sink'],
             {0:{'count':4096},4:{'snr_db':30}})
    p['symbol_rate']=15000
    return {'ofdm_isac':{'label':'通感 · OFDM 单目标测距测速','program':p}}


def build_stage(kind,q,domain,count,features):
    if kind=='tx_isac_ofdm':
        if domain!='复符号' or features['modulator']['kind']!='mod_qpsk' or features.get('wireless') or any(k in features for k in ('tx_ofdm','tx_rrc','tx_frame','tx_pilots')):
            raise ValueError('通感组帧直接连接 QPSK 映射器。')
        if q['cp']>=q['nfft']: raise ValueError('通感 CP 长度须小于 FFT 点数。')
        if math.ceil(count/q['nfft'])<8: raise ValueError('测距测速至少使用 8 个数据 OFDM 符号。')
        features['wireless']={'tx':kind,'input_count':count,'params':q,'rate_factor':q['nfft']}
        count=(math.ceil(count/q['nfft'])+2)*(q['nfft']+q['cp']);domain='OFDM 波形'
    elif kind=='isac_echo':
        w=features.get('wireless',{})
        if domain!='OFDM 波形' or w.get('tx')!='tx_isac_ofdm':raise ValueError('目标回波连接通感 OFDM 波形。')
        fs=features['symbol_rate']*w['params']['nfft']
        if 2*q['range_m']/C*fs+4>=w['params']['cp']:raise ValueError('目标往返延迟及插值余量须落在 CP 内，请增大 CP 或减小距离。')
        if abs(2*q['velocity_mps']/(C/(q['carrier_ghz']*1e9)))>=fs/(2*(w['params']['nfft']+w['params']['cp'])):raise ValueError('目标速度须位于慢时间无模糊速度区间。')
    else:
        w=features.get('wireless',{})
        if domain!='OFDM 波形' or w.get('tx')!='tx_isac_ofdm':raise ValueError('通感接收器需要通感 OFDM 组帧。')
        count=w['input_count'];domain='复符号';w['rx']=kind
        if 'isac_echo' in features and q['carrier_ghz']!=features['isac_echo']['params']['carrier_ghz']:raise ValueError('接收射频载频须与发射回波载频一致。')
    features[kind]={'params':q,'count':count}
    return domain,count


def transmit(symbols,q):
    n=q['nfft'];rows=math.ceil(len(symbols)/n)
    pilot=(2*np.random.default_rng(410032).integers(0,2,(2,n))-1).astype(complex)
    payload=np.pad(symbols,(0,rows*n-len(symbols)),constant_values=1).reshape(rows,n)
    grid=np.vstack((pilot,payload));wave=np.fft.ifft(grid,axis=1)*math.sqrt(n)
    wave=np.concatenate((wave[:,-q['cp']:],wave),axis=1).ravel()
    return wave,{'grid':grid,'pilot':pilot,'count':len(symbols),'params':q}


def echo(wave,q,fs):
    delay=2*q['range_m']/C*fs
    # Causal windowed-sinc fractional delay, with the integer part kept exact.
    whole=int(math.floor(delay));frac=delay-whole
    indices=np.arange(-4,5);h=np.sinc(indices-frac)*np.kaiser(9,6);h/=sum(h)
    extended=np.convolve(wave,h)
    positions=np.arange(len(wave))+4-whole
    delayed=np.zeros(len(wave),complex);valid=(positions>=0)&(positions<len(extended));delayed[valid]=extended[positions[valid]]
    wavelength=C/(q['carrier_ghz']*1e9);fd=2*q['velocity_mps']/wavelength
    state=runtime.state('isac_echo',lambda:{'phase':0.})
    phase=state['phase']+2*np.pi*fd*np.arange(len(wave))/fs;state['phase']=float((state['phase']+2*np.pi*fd*len(wave)/fs)%(2*np.pi))
    return q['direct']*wave+q['amplitude']*delayed*np.exp(1j*phase),{'delay_samples':delay,'doppler_hz':fd,'range_m':q['range_m'],'velocity_mps':q['velocity_mps']}


def receive(wave,reference,q,fs):
    n=reference['params']['nfft'];cp=reference['params']['cp'];rows=len(reference['grid'])
    if len(wave)<rows*(n+cp):raise ValueError('通感帧长度不足。')
    grid=np.fft.fft(np.asarray(wave[:rows*(n+cp)]).reshape(rows,n+cp)[:,cp:],axis=1)/math.sqrt(n)
    estimate=np.mean(grid[:2]/reference['pilot'],axis=0)
    equalized=grid[2:]*np.conj(estimate)/(abs(estimate)**2+1e-8)
    ratio=grid[2:]/reference['grid'][2:]
    slow=len(ratio);window=np.hanning(slow)
    delay_response=np.fft.ifft(ratio,axis=1)
    spectrum=np.fft.fftshift(np.fft.fft(delay_response*window[:,None],axis=0),axes=0)
    power=abs(spectrum[:,:cp])**2/max(sum(window)**2,1e-12)
    ranges=np.arange(cp)*C/(2*fs);wavelength=C/(q['carrier_ghz']*1e9)
    speeds=np.fft.fftshift(np.fft.fftfreq(slow,(n+cp)/fs))*wavelength/2
    searchable=power.copy();searchable[:,0]=0
    row,col=np.unravel_index(np.argmax(searchable),searchable.shape)
    background=float(np.median(power[:,1:]));peak=float(searchable[row,col]);contrast=10*math.log10(max(peak,1e-20)/max(background,1e-20))
    detected=bool(peak>1e-12 and contrast>=q['threshold_db'])
    sensing={'range_m':float(ranges[col]),'velocity_mps':float(speeds[row]),'detected':detected,'peak_background_db':contrast,
             'range_resolution_m':C/(2*fs),'velocity_resolution_mps':wavelength*fs/(2*slow*(n+cp)),
             'range_axis_m':ranges.tolist(),'velocity_axis_mps':speeds.tolist(),'power_db':(10*np.log10(np.maximum(power,1e-20))).tolist(),
             'reference':'local_transmit_grid','data_ofdm_symbols':slow,'direct_cell_excluded':0}
    return equalized.ravel()[:reference['count']],{'sensing':sensing,'channel_i':estimate.real.tolist(),'channel_q':estimate.imag.tolist(),
        'trace':{'channel_magnitude':abs(estimate).tolist(),'range_profile':np.max(power,axis=0).tolist(),'doppler_profile':np.max(searchable,axis=1).tolist()}}


def run_stage(kind,data,q,state,rng,fs):
    if kind=='tx_isac_ofdm':
        result,reference=transmit(data,q);state['isac_v0410']=reference
        return result,{'ofdm_symbols':len(reference['grid']),'local_reference':True},fs*q['nfft']
    if kind=='isac_echo':
        result,details=echo(data,q,fs);return result,details,fs
    reference=state['isac_v0410'];result,details=receive(data,reference,q,fs)
    return result,details,fs/reference['params']['nfft']
