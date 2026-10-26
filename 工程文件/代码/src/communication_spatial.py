"""Ordered SIC, correlated mobile MIMO, and pilot-estimated MIMO-OFDM.

Complex arrays are time x antenna; H is receive x transmit. Detectors consume
received public pilots and observations. Simulation truth is only for plots.
"""
import math
import numpy as np
from src import communication_dsp as dsp, communication_runtime as runtime

TX={'tx_mimo_tracking','tx_mimo_ofdm'}
CHANNEL={'spatial_dynamic','spatial_multipath'}
RX={'rx_mimo_zf_sic','rx_mimo_mmse_sic','rx_mimo_tracking','rx_mimo_ofdm'}
KINDS=TX|CHANNEL|RX


def arrays(a):
    a=np.asarray(a,complex)
    return {'i':a.real.tolist(),'q':a.imag.tolist(),'shape':list(a.shape)}


def register(block,number,field,blocks):
    for k,label in [('rx_mimo_zf_sic','2×2 MIMO ZF-SIC'),('rx_mimo_mmse_sic','2×2 MIMO MMSE-SIC')]:
        block(k,label,'rx_converter','训练估计信道，按检测可靠度排序，逐层判决、重构并消除干扰。')
    block('tx_mimo_tracking','MIMO 周期正交导频','tx_converter','两空间流之间周期插入正交导频，保留每个导频和数据的实际时隙。',
          interval=number('数据时隙间隔',8,2,128,True),training=field('每组导频时隙',4,'select',choices=[4,8,16]))
    block('spatial_dynamic','移动与空间相关 MIMO','channel','按载频和速度生成连续 Clarke/Jakes 多普勒衰落，并应用收发天线相关矩阵。',
          carrier_ghz=number('载频 / GHz',2.4,.1,100),velocity_kmh=number('移动速度 / km/h',3,0,350),
          tx_correlation=number('发射天线相关系数',.25,0,.99),rx_correlation=number('接收天线相关系数',.25,0,.99),
          noise=field('加入白噪声',True,'boolean'),snr_db=number('总发送功率 / 噪声功率 / dB',28,-10,80))
    choices={0:'ZF',1:'MMSE',2:'ZF-SIC',3:'MMSE-SIC'}
    block('rx_mimo_tracking','MIMO 导频跟踪检测','rx_converter','各组导频最小二乘估计矩阵，按时间插值后逐时隙检测。',
          detector=field('检测器',1,'select',choices=list(choices),choice_labels=choices))
    block('tx_mimo_ofdm','2×2 MIMO-OFDM 组帧','tx_converter','两条空间流分别 IFFT 和插入 CP，使用分天线正交训练 OFDM 符号。',
          nfft=field('FFT 点数',32,'select',choices=[16,32,64,128]),cp=number('循环前缀 / 样本',8,1,64,True))
    block('spatial_multipath','频率选择性 MIMO 多径','channel','每条时延路径包含独立的 2×2 复矩阵，逐天线卷积后叠加接收噪声。',
          delays=field('路径延迟 / 样本','0,3,7',max_length=80),powers_db=field('路径平均功率 / dB','0,-8,-14',max_length=100),
          gains=field('首径 2×2 复矩阵','1,0.3+0.2j,0.2-0.1j,1',max_length=160),
          noise=field('加入白噪声',True,'boolean'),snr_db=number('总发送功率 / 噪声功率 / dB',30,-10,80))
    block('rx_mimo_ofdm','MIMO-OFDM 矩阵估计检测','rx_converter','去 CP、FFT，以正交训练逐子载波估计 2×2 矩阵并分离空间流。',
          detector=field('逐子载波检测器',1,'select',choices=list(choices),choice_labels=choices))


def presets(preset):
    def entry(label,tx,ch,rx,scheme='qpsk',changes=None):
        return {'label':label,'program':preset(['random_bits','mod_'+scheme,tx,ch,rx,'demod_'+scheme,'sink'],changes)}
    return {
        'mimo_zf_sic':entry('多天线 · 排序 ZF-SIC','tx_mimo','spatial_channel','rx_mimo_zf_sic',changes={3:{'snr_db':22}}),
        'mimo_mmse_sic':entry('多天线 · 排序 MMSE-SIC','tx_mimo','spatial_channel','rx_mimo_mmse_sic',changes={3:{'snr_db':22}}),
        'mimo_mobile_tracking':entry('移动多天线 · 周期导频跟踪','tx_mimo_tracking','spatial_dynamic','rx_mimo_tracking'),
        'mimo_correlated_tracking':entry('移动多天线 · 空间相关与 SIC','tx_mimo_tracking','spatial_dynamic','rx_mimo_tracking',changes={3:{'tx_correlation':.7,'rx_correlation':.6,'snr_db':32},4:{'detector':3}}),
        'mimo_ofdm_zf':entry('宽带多天线 · MIMO-OFDM ZF','tx_mimo_ofdm','spatial_multipath','rx_mimo_ofdm',changes={4:{'detector':0}}),
        'mimo_ofdm_mmse':entry('宽带多天线 · MIMO-OFDM MMSE-SIC','tx_mimo_ofdm','spatial_multipath','rx_mimo_ofdm','qam16',{3:{'snr_db':38},4:{'detector':3}}),
    }


def parse_paths(q):
    delays=np.array([int(x.strip()) for x in q['delays'].split(',')])
    powers=np.array([float(x.strip()) for x in q['powers_db'].split(',')])
    h=np.array([complex(x.strip().replace('i','j')) for x in q['gains'].split(',')])
    if not 1<=len(delays)<=8 or len(delays)!=len(powers) or len(set(delays))!=len(delays) or np.min(delays)!=0 or np.max(delays)>64:
        raise ValueError('多径延迟从 0 开始，包含 1–8 个互异的 0–64 整数，并与路径功率一一对应。')
    if not np.all(np.isfinite(powers)) or np.any(abs(powers)>100) or len(h)!=4 or not np.all(np.isfinite(h)) or np.linalg.norm(h)==0:
        raise ValueError('路径功率须为 −100 至 100 dB，首径须包含四个有限复增益和非零总功率。')
    return delays,10**(powers/10),h.reshape(2,2)


def build_stage(kind,q,domain,count,features):
    w=features.setdefault('wireless',{})
    if kind in TX:
        if domain!='复符号' or 'tx' in w or any(k in features for k in ('tx_rrc','tx_frame','tx_ofdm','tx_pilots')):
            raise ValueError('MIMO 发送结构直接连接数字映射器，每条链路选择一个组帧积木。')
        if features['modulator']['kind'][4:] not in {'bpsk','qpsk','psk8','qam16','qam64','qam256'}: raise ValueError('MIMO 检测使用 PSK / QAM 星座。')
        w.update(tx=kind,input_count=count,params=q,rate_factor=1)
        if kind=='tx_mimo_tracking':
            slots=math.ceil(count/2);count=slots+(math.ceil(slots/q['interval'])+1)*q['training']
        else:
            if q['cp']>=q['nfft']: raise ValueError('循环前缀长度须小于 FFT 点数。')
            count=(math.ceil(count/(2*q['nfft']))+4)*(q['nfft']+q['cp']);w['rate_factor']=q['nfft']
        domain='多天线符号'
    elif kind in CHANNEL:
        expected='tx_mimo_tracking' if kind=='spatial_dynamic' else 'tx_mimo_ofdm'
        if domain!='多天线符号' or w.get('tx')!=expected or w.get('spatial_channel'): raise ValueError('请将该信道与对应的 MIMO 组帧积木连接。')
        if kind=='spatial_multipath':
            delays,_,_=parse_paths(q)
            if max(delays)>w['params']['cp']: raise ValueError('MIMO-OFDM 循环前缀须覆盖最大路径延迟。')
            count+=int(max(delays))
        elif q['velocity_kmh']/3.6*q['carrier_ghz']*1e9/299792458>=features.get('symbol_rate',1000)/2:
            raise ValueError('最大多普勒频移须小于符号采样率的一半。')
        w['spatial_channel']=q
    else:
        expected={'rx_mimo_zf_sic':'tx_mimo','rx_mimo_mmse_sic':'tx_mimo','rx_mimo_tracking':'tx_mimo_tracking','rx_mimo_ofdm':'tx_mimo_ofdm'}[kind]
        if domain!='多天线符号' or w.get('tx')!=expected or not w.get('spatial_channel'): raise ValueError('接收检测器须与发送结构及多天线信道配对。')
        if features['modulator']['kind'][4:] not in {'bpsk','qpsk','psk8','qam16','qam64','qam256'}: raise ValueError('MIMO 检测使用 PSK / QAM 星座。')
        w['rx']=kind;domain='复符号';count=w['input_count']
    features[kind]={'params':q,'count':count}
    return domain,count


def detect(y,h,variance,scheme,method,valid=None):
    """Detect normalized streams in y = H s / sqrt(Nt) + n."""
    y=np.atleast_2d(y);nt=h.shape[1];scaled=h/math.sqrt(nt)
    # Public frame length marks zero-padding cells. Cancel only active streams;
    # slicing a known padding zero onto QAM would inject a false final symbol.
    if valid is not None and not np.all(valid):
        valid=np.asarray(valid,bool);out=np.zeros((len(y),nt),complex);traces={}
        for pattern in np.unique(valid,axis=0):
            rows=np.flatnonzero(np.all(valid==pattern,axis=1));columns=np.flatnonzero(pattern)
            if not len(columns):continue
            values,trace=detect(y[rows],h[:,columns]*math.sqrt(len(columns)/nt),variance,scheme,method)
            out[np.ix_(rows,columns)]=values
            for row,order,power in zip(rows,trace['orders'],trace['residual_power']):
                if row<64:traces[int(row)]=([int(columns[col]) for col in order],power)
        indices=sorted(traces);_,points=dsp.constellation(scheme)
        hard=points[np.argmin(abs(out[:64,:,None]-points)**2,axis=2)];hard[~valid[:64]]=0
        return out,{'orders':[traces[row][0] for row in indices],'residual_power':[traces[row][1] for row in indices],
                    'sample_indices':indices,'decisions':arrays(hard)}
    singular=np.linalg.svd(h,compute_uv=False)
    if method in (0,2) and singular[-1]<1e-10: raise ValueError('ZF 检测需要满列秩信道矩阵。')
    if method>=2 and np.any(np.linalg.norm(h,axis=0)<1e-12): raise ValueError('SIC 检测需要每条空间流具有有效的接收训练增益。')
    trace={'orders':[],'residual_power':[],'decisions':None}
    if method<2:
        weights=np.linalg.pinv(scaled) if method==0 else np.linalg.solve(scaled.conj().T@scaled+max(variance,1e-15)*np.eye(nt),scaled.conj().T)
        return y@weights.T,trace
    _,points=dsp.constellation(scheme);active=list(range(nt));residual=y.copy();out=np.zeros((len(y),nt),complex);decisions=np.zeros_like(out)
    order=[];powers=[]
    while active:
        a=scaled[:,active];alpha=max(variance,1e-15) if method==3 else 0.
        weights=np.linalg.solve(a.conj().T@a+alpha*np.eye(len(active)),a.conj().T)
        response=weights@a
        metric=abs(np.diag(response))**2/(np.sum(abs(response)**2,axis=1)-abs(np.diag(response))**2+max(variance,1e-15)*np.sum(abs(weights)**2,axis=1)+1e-30)
        chosen=int(np.argmax(metric));stream=active.pop(chosen)
        soft=residual@weights[chosen]/response[chosen,chosen]
        decided=points[np.argmin(abs(soft[:,None]-points)**2,axis=1)]
        out[:,stream]=soft
        decisions[:,stream]=decided
        residual-=decided[:,None]*scaled[:,stream][None,:]
        order.append(stream);powers.append(np.mean(abs(residual)**2,axis=1))
    trace={'orders':[order]*min(len(y),64),'residual_power':np.array(powers).T[:64].tolist(),'decisions':arrays(decisions[:64])}
    return out,trace


def tracking_encode(symbols,q):
    paired=np.pad(symbols,(0,-len(symbols)%2)).reshape(-1,2)/math.sqrt(2)
    pilot=np.column_stack([np.ones(q['training']),(-1.)**np.arange(q['training'])])/math.sqrt(2)
    chunks=[];positions=[];data_slots=[];offset=0
    for start in range(0,len(paired),q['interval']):
        positions.append(list(range(offset,offset+len(pilot))));chunks.append(pilot);offset+=len(pilot)
        segment=paired[start:start+q['interval']];data_slots.extend(range(offset,offset+len(segment)));chunks.append(segment);offset+=len(segment)
    positions.append(list(range(offset,offset+len(pilot))));chunks.append(pilot)
    tx=np.vstack(chunks)
    return tx,{'mode':'tx_mimo_tracking','count':len(symbols),'pilot':pilot,'pilot_slots':positions,'data_slots':data_slots}


def dynamic_channel(tx,q,rng,fs):
    fd=q['velocity_kmh']/3.6*q['carrier_ghz']*1e9/299792458
    memory=runtime.state('mobile_mimo',lambda:{'offset':0,'phase':rng.uniform(0,2*np.pi,(2,2,32)),
                          'angles':rng.uniform(0,2*np.pi,(2,2,32))})
    times=(memory['offset']+np.arange(len(tx)))/fs;memory['offset']+=len(tx)
    independent=np.empty((len(tx),2,2),complex)
    for r in range(2):
        for t in range(2):
            independent[:,r,t]=np.exp(1j*(memory['phase'][r,t][None,:]+2*np.pi*fd*times[:,None]*np.cos(memory['angles'][r,t])[None,:])).sum(axis=1)/math.sqrt(32)
    lr=np.linalg.cholesky([[1,q['rx_correlation']],[q['rx_correlation'],1]])
    lt=np.linalg.cholesky([[1,q['tx_correlation']],[q['tx_correlation'],1]])
    h=np.einsum('ab,tbc,dc->tad',lr,independent,lt)
    y=np.einsum('trc,tc->tr',h,tx)
    variance=float(np.mean(np.sum(abs(tx)**2,axis=1)))*10**(-q['snr_db']/10) if q['noise'] else 0.
    y+=math.sqrt(variance/2)*(rng.normal(size=y.shape)+1j*rng.normal(size=y.shape))
    return y,{'channel_trace':arrays(h),'time_seconds':times.tolist(),'doppler_hz':fd,'noise_variance':variance,
              'tx_antennas':2,'rx_antennas':2,'tx_correlation':q['tx_correlation'],'rx_correlation':q['rx_correlation']}


def tracking_decode(y,s,q,scheme):
    pilot=s['pilot'];groups=np.array(s['pilot_slots']);slots=np.array(s['data_slots']);estimates=[];residual=[]
    for group in groups:
        ht=np.linalg.lstsq(pilot,y[group],rcond=None)[0];estimates.append(ht.T);residual.extend((y[group]-pilot@ht).ravel())
    estimates=np.array(estimates);variance=float(np.sum(abs(np.array(residual))**2)/(len(groups)*(len(pilot)-2)*2))
    centers=groups.mean(axis=1);h=np.empty((len(slots),2,2),complex)
    for r in range(2):
        for t in range(2):h[:,r,t]=np.interp(slots,centers,estimates[:,r,t].real)+1j*np.interp(slots,centers,estimates[:,r,t].imag)
    out=[];conditions=[];orders=[];powers=[]
    for index,(sample,matrix) in enumerate(zip(y[slots],h)):
        values,trace=detect(sample,matrix,variance,scheme,q['detector'],np.array([[index*2<s['count'],index*2+1<s['count']]]));out.extend(values.ravel());conditions.append(float(np.linalg.cond(matrix)))
        if len(orders)<64 and trace['orders']:orders.extend(trace['orders']);powers.extend(trace['residual_power'])
    return np.array(out)[:s['count']],{'channel_estimate':arrays(h),'estimated_noise_variance':variance,
        'tracking':{'pilot_slots':groups.tolist(),'estimated':arrays(estimates),'data_slots':slots.tolist(),'condition_numbers':conditions},
        'sic':{'orders':orders,'residual_power':powers},'pilot_reference':arrays(pilot),'pilot_received':arrays(y[groups])}


def ofdm_encode(symbols,q):
    n=q['nfft'];frames=math.ceil(len(symbols)/(2*n));payload=np.pad(symbols,(0,frames*n*2-len(symbols))).reshape(frames,n,2)/math.sqrt(2)
    pilots=np.zeros((4,n,2),complex);pilots[::2,:,0]=1/math.sqrt(2);pilots[1::2,:,1]=1/math.sqrt(2)
    grid=np.concatenate([pilots,payload]);wave=np.fft.ifft(grid,axis=1,norm='ortho');tx=np.concatenate([wave[:,-q['cp']:],wave],axis=1).reshape(-1,2)
    return tx,{'mode':'tx_mimo_ofdm','count':len(symbols),'params':q,'frames':frames,'grid':grid,'pilot':pilots}


def multipath_channel(tx,q,rng):
    delays,powers,base=parse_paths(q);matrices=(rng.normal(size=(len(delays),2,2))+1j*rng.normal(size=(len(delays),2,2)))/math.sqrt(2)
    matrices[0]=base;matrices*=np.sqrt(powers/powers.sum())[:,None,None]
    y=np.zeros((len(tx)+int(max(delays)),2),complex)
    for delay,matrix in zip(delays,matrices):y[delay:delay+len(tx)]+=tx@matrix.T
    variance=float(np.mean(np.sum(abs(tx)**2,axis=1)))*10**(-q['snr_db']/10) if q['noise'] else 0.
    y+=math.sqrt(variance/2)*(rng.normal(size=y.shape)+1j*rng.normal(size=y.shape))
    return y,{'path_delays':delays.tolist(),'path_matrices':arrays(matrices),'noise_variance':variance,'tx_antennas':2,'rx_antennas':2}


def ofdm_decode(y,s,q,scheme):
    n=s['params']['nfft'];cp=s['params']['cp'];frames=s['frames']+4
    grid=np.fft.fft(y[:frames*(n+cp)].reshape(frames,n+cp,2)[:,cp:],axis=1,norm='ortho')
    h=np.stack([np.mean(grid[:4:2],axis=0),np.mean(grid[1:4:2],axis=0)],axis=2)*math.sqrt(2)
    prediction=np.einsum('krn,fkn->fkr',h,s['pilot']);residual=grid[:4]-prediction
    variance=float(np.sum(abs(residual)**2)/(n*2*2));decoded=np.zeros((s['frames'],n,2),complex);orders=[];powers=[];sample_indices=[]
    for carrier in range(n):
        valid=(np.arange(s['frames'])[:,None]*n*2+carrier*2+np.arange(2)[None,:])<s['count']
        decoded[:,carrier],trace=detect(grid[4:,carrier],h[carrier],variance,scheme,q['detector'],valid)
        if len(orders)<64:
            orders.extend(trace['orders']);powers.extend(trace['residual_power'])
            sample_indices.extend([row*n+carrier for row in trace.get('sample_indices',range(len(trace['orders'])))])
    return decoded.ravel()[:s['count']],{'channel_estimate':arrays(h),'estimated_noise_variance':variance,'grid':arrays(grid),
        'recovered_grid':arrays(decoded),'subcarriers':np.fft.fftfreq(n,d=1/n).astype(int).tolist(),
        'condition_numbers':[float(np.linalg.cond(matrix)) for matrix in h],
        'sic':{'orders':orders[:64],'residual_power':powers[:64],'sample_indices':sample_indices[:64]},'pilot_reference':arrays(s['pilot']),'pilot_received':arrays(grid[:4])}


def run_stage(kind,data,q,state,rng,fs):
    scheme=state['scheme']
    if kind in TX:
        tx,s=tracking_encode(data,q) if kind=='tx_mimo_tracking' else ofdm_encode(data,q)
        s['tx']=tx;state['spatial']=s
        details={'full_tx':arrays(tx),'tx_antennas':2,'time_slots':len(tx),'total_energy':float(np.sum(abs(tx)**2))}
        if kind=='tx_mimo_ofdm':details.update(grid=arrays(s['grid']),subcarriers=np.fft.fftfreq(q['nfft'],d=1/q['nfft']).astype(int).tolist());fs*=q['nfft']
        else:details['pilot_slots']=s['pilot_slots']
        return tx[:,0],details,fs
    s=state['spatial']
    if kind in CHANNEL:
        y,details=dynamic_channel(s['tx'],q,rng,fs) if kind=='spatial_dynamic' else multipath_channel(s['tx'],q,rng)
        s['received']=y;details['full_rx']=arrays(y)
        return y[:,0],details,fs
    if kind=='rx_mimo_tracking':out,details=tracking_decode(s['received'],s,q,scheme)
    elif kind=='rx_mimo_ofdm':out,details=ofdm_decode(s['received'],s,q,scheme);fs/=s['params']['nfft']
    else:
        pilot=s['pilot'];training=s['received'][:len(pilot)];h=np.linalg.lstsq(pilot,training,rcond=None)[0].T
        variance=float(np.sum(abs(training-pilot@h.T)**2)/((len(pilot)-2)*2))
        received=s['received'][len(pilot):];valid=np.arange(len(received)*2).reshape(-1,2)<s['count']
        values,trace=detect(received,h,variance,scheme,2 if kind=='rx_mimo_zf_sic' else 3,valid);out=values.ravel()[:s['count']]
        details={'channel_estimate':arrays(h),'estimated_noise_variance':variance,'sic':trace,'pilot_reference':arrays(pilot),'pilot_received':arrays(training),
                 'condition_number':float(np.linalg.cond(h)),'singular_values':np.linalg.svd(h,compute_uv=False).tolist()}
    details['recovered_symbols']=arrays(out)
    details['stream_symbols']=arrays(np.pad(out,(0,-len(out)%2)).reshape(-1,2))
    details['stream_counts']=[math.ceil(len(out)/2),len(out)//2]
    return out,details,fs
