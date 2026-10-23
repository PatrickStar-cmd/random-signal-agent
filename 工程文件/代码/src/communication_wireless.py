"""DSSS acquisition/RAKE and pilot-estimated spatial diversity/multiplexing.

Arrays use (time, antenna). Spatial receivers use public pilots only; complete
transmit and receive antenna arrays are retained in the JSON experiment result.
"""
import math
import numpy as np

TX = {'tx_dsss', 'tx_simo', 'tx_alamouti', 'tx_mimo'}
CHANNEL = {'dsss_multipath', 'spatial_channel'}
RX = {'rx_code_acquire', 'rx_despread', 'rx_rake', 'rx_selection', 'rx_mrc',
      'rx_alamouti', 'rx_mimo_zf', 'rx_mimo_mmse'}
KINDS = TX | CHANNEL | RX
SPATIAL_TX = {'tx_simo', 'tx_alamouti', 'tx_mimo'}
SPATIAL_RX = {'rx_selection', 'rx_mrc', 'rx_alamouti', 'rx_mimo_zf', 'rx_mimo_mmse'}


def register(block, number, field, blocks):
    block('tx_dsss', 'DSSS 直接序列扩频', 'tx_converter',
          '使用 m 序列扩频并插入公共训练前导；每个数据符号的总能量保持为 1。',
          degree=field('PN 阶数 / 扩频倍率', 5, 'select', choices=[5, 6, 7],
                       choice_labels={5:'5 / 31', 6:'6 / 63', 7:'7 / 127'}),
          initial=number('PN 初始状态', 1, 1, 127, True),
          phase=number('发送码相位 / 码片', 0, 0, 126, True),
          training=field('公共训练符号数', 16, 'select', choices=[16, 32, 64]))
    block('dsss_multipath', '码片延迟与多径', 'channel',
          '按码片延迟叠加复增益路径，观察码捕获和 RAKE 合并。',
          delay=number('整帧延迟 / 码片', 9, 0, 256, True),
          delays=field('路径相对延迟 / 码片', '0,7,18', max_length=80),
          gains=field('路径复增益', '0.3,1,0.5+0.3j', max_length=160))
    block('rx_code_acquire', '扩频码相位捕获', 'rx_converter',
          '扫描本地 PN 码相位和帧延迟，以公共训练前导相关峰定位。',
          search=number('最大搜索延迟 / 码片', 128, 0, 512, True),
          threshold=number('归一化捕获阈值', .15, .01, .99))
    block('rx_despread', 'DSSS 相关解扩', 'rx_converter',
          '按捕获码相位做相关积分，使用训练前导估计复增益并恢复符号。')
    block('rx_rake', 'RAKE 多径合并', 'rx_converter',
          '训练序列最小二乘估计路径，选择最强指支路并按复增益做最大比合并。',
          fingers=number('RAKE 指数', 3, 1, 8, True),
          span=number('相关峰两侧搜索 / 码片', 32, 1, 64, True))
    for kind, label, description in [
        ('tx_simo', 'SIMO 分集训练帧', '单天线发送公共训练和数据，接收端使用多支路分集。'),
        ('tx_alamouti', 'Alamouti 2×1 编码', '两时隙正交空时编码，发送总功率归一化并插入正交训练。'),
        ('tx_mimo', '2×2 MIMO 空间复用', '每个时隙并行发送两个符号，发送总功率归一化并插入正交训练。')]:
        block(kind, label, 'tx_converter', description,
              training=field('训练时隙数', 32, 'select', choices=[16, 32, 64, 128]))
    block('spatial_channel', '多天线衰落与噪声', 'channel',
          '对每对收发天线应用复增益；各接收天线叠加独立复高斯噪声，整帧内增益恒定。',
          model=field('信道模型', 0, 'select', choices=[0,1], choice_labels={0:'指定复增益',1:'独立块 Rayleigh 衰落'}),
          branches=field('SIMO 接收支路数', 2, 'select', choices=[2,4]),
          gains=field('增益矩阵（按接收行排列）', '1,0.7+0.4j,0.2-0.1j,0.9', max_length=200),
          noise=field('加入独立白噪声', True, 'boolean'),
          snr_db=number('发送总功率 / 噪声功率 / dB', 14, -10, 60))
    for kind, label, description in [
        ('rx_selection', '选择合并 SC', '从公共训练估计各支路增益，选择估计信噪比最高的接收天线。'),
        ('rx_mrc', '最大比合并 MRC', '从公共训练估计各支路增益，以共轭增益加权并按总增益归一化。'),
        ('rx_alamouti', 'Alamouti 合并', '使用正交训练估计两个发射通道，按两时隙空时关系恢复数据。'),
        ('rx_mimo_zf', '2×2 MIMO ZF 检测', '用正交训练最小二乘估计信道矩阵，迫零逆矩阵分离空间流。'),
        ('rx_mimo_mmse', '2×2 MIMO MMSE 检测', '训练残差估计噪声方差，线性 MMSE 检测抑制病态信道的噪声增强。')]:
        block(kind, label, 'rx_converter', description)


def presets(preset):
    def entry(label, kinds, changes=None):
        return {'label':label, 'program':preset(kinds, changes)}
    return {
        'dsss_interference':entry('扩频 · 码捕获与抗窄带干扰',
            ['random_bits','mod_bpsk','tx_dsss','narrowband','ideal','rx_code_acquire','rx_despread','demod_bpsk','sink'],
            {2:{'phase':11,'training':32},3:{'amplitude':1.5,'hz':31},5:{'threshold':.05}}),
        'dsss_rake':entry('扩频 · RAKE 多径合并',
            ['random_bits','mod_qpsk','tx_dsss','dsss_multipath','complex_awgn','rx_code_acquire','rx_rake','demod_qpsk','sink'],
            {2:{'phase':9},4:{'snr_db':16}}),
        'diversity_selection':entry('分集 · SIMO 选择合并',
            ['random_bits','mod_qpsk','tx_simo','spatial_channel','rx_selection','demod_qpsk','sink']),
        'diversity_mrc':entry('分集 · SIMO 最大比合并',
            ['random_bits','mod_qpsk','tx_simo','spatial_channel','rx_mrc','demod_qpsk','sink']),
        'diversity_alamouti':entry('分集 · Alamouti 2×1',
            ['random_bits','mod_qpsk','tx_alamouti','spatial_channel','rx_alamouti','demod_qpsk','sink']),
        'mimo_zf':entry('多天线 · 2×2 MIMO ZF',
            ['random_bits','mod_qam16','tx_mimo','spatial_channel','rx_mimo_zf','demod_qam16','sink'],{3:{'snr_db':26}}),
        'mimo_mmse':entry('多天线 · 2×2 MIMO MMSE',
            ['random_bits','mod_qam16','tx_mimo','spatial_channel','rx_mimo_mmse','demod_qam16','sink'],{3:{'snr_db':26}}),
    }


def _complex_values(text):
    values=np.array([complex(v.strip().replace('i','j')) for v in text.replace(';',',').split(',')], complex)
    if not np.all(np.isfinite(values)): raise ValueError('复增益须为有限数值。')
    return values


def paths(q):
    delays=np.array([int(v.strip()) for v in q['delays'].split(',')])
    gains=_complex_values(q['gains'])
    if len(delays)!=len(gains) or not 1<=len(delays)<=8: raise ValueError('路径延迟与增益须一一对应，路径数为 1–8。')
    if np.any(delays<0) or np.any(delays>256) or len(set(delays))!=len(delays): raise ValueError('路径延迟须为互异的 0–256 整数。')
    if np.linalg.norm(gains)==0: raise ValueError('至少一个路径增益须大于零。')
    return delays+q['delay'], gains


def pn_code(degree, initial):
    if degree not in (5,6,7) or not 0<initial<2**degree: raise ValueError('扩频 PN 初态须为 1 至 2ⁿ−1，阶数为 5、6、7。')
    bits=[]; seed=initial; tap=2 if degree==5 else 1
    for _ in range(2**degree-1):
        bits.append(2*(seed&1)-1)
        seed=(seed>>1)|(((seed^(seed>>tap))&1)<<(degree-1))
    return np.asarray(bits,float)


def build_stage(kind, q, domain, count, features):
    """Validate a stage; enclosing engine handles direction and channel count."""
    w=features.setdefault('wireless', {})
    if kind in TX:
        if domain!='复符号' or 'tx' in w: raise ValueError('无线发送处理需要一条复符号流，每条链路选择一种无线发送结构。')
        if any(k in features for k in ('tx_rrc','tx_frame','tx_ofdm','tx_pilots')): raise ValueError('无线发送积木自带训练，请直接连接数字映射器。')
        w.update(tx=kind, input_count=count, params=q)
        if kind=='tx_dsss':
            pn_code(q['degree'],q['initial']); length=2**q['degree']-1
            if q['phase']>=length: raise ValueError('发送码相位须小于扩频倍率。')
            count=(count+q['training'])*length; domain='扩频码片'; w['rate_factor']=length
        else:
            count=(count if kind=='tx_simo' else 2*math.ceil(count/2) if kind=='tx_alamouti' else math.ceil(count/2))+q['training']
            domain='多天线符号'; w['rate_factor']=1
    elif kind=='dsss_multipath':
        if domain!='扩频码片': raise ValueError('码片多径信道需要 DSSS 扩频输出。')
        delays,_=paths(q); count+=int(delays.max())
    elif kind=='spatial_channel':
        if domain!='多天线符号' or 'spatial_channel' in w: raise ValueError('多天线信道须连接空间发送积木，每条链路放置一次。')
        tx=w['tx']; nr=q['branches'] if tx=='tx_simo' else 1 if tx=='tx_alamouti' else 2
        nt=1 if tx=='tx_simo' else 2
        if q['model']==0 and len(_complex_values(q['gains']))<nr*nt: raise ValueError('指定增益数须覆盖每一对收发天线。')
        w['spatial_channel']=q
    elif kind=='rx_code_acquire':
        if domain!='扩频码片' or w.get('acquired'): raise ValueError('码捕获放在扩频信道之后，每条链路放置一次。')
        w['acquired']=True
    elif kind in ('rx_despread','rx_rake'):
        if domain!='扩频码片' or not w.get('acquired'): raise ValueError('请先放置扩频码相位捕获。')
        domain='复符号'; count=w['input_count']; w['rx']=kind
    elif kind in SPATIAL_RX:
        expected={'rx_selection':'tx_simo','rx_mrc':'tx_simo','rx_alamouti':'tx_alamouti','rx_mimo_zf':'tx_mimo','rx_mimo_mmse':'tx_mimo'}[kind]
        if domain!='多天线符号' or w.get('tx')!=expected or 'spatial_channel' not in w: raise ValueError('空间接收算法须与发送结构及多天线信道配对。')
        domain='复符号'; count=w['input_count']; w['rx']=kind
    features[kind]={'params':q,'count':count}
    return domain,count


def validate_receiver(features):
    w=features.get('wireless')
    if w and not w.get('rx'): raise ValueError('请补充与无线发送结构配对的接收合并或解扩积木。')


def arrays(x):
    a=np.asarray(x,complex)
    return {'i':a.real.tolist(), 'q':a.imag.tolist(), 'shape':list(a.shape)}


def _training(length):
    return 2*np.random.default_rng(7547).integers(0,2,length)-1.


def spread(symbols, q):
    code=pn_code(q['degree'],q['initial'])
    chip_code=np.roll(code,q['phase'])/math.sqrt(len(code))
    pilot=_training(q['training']).astype(complex)
    signal=(np.r_[pilot,symbols][:,None]*chip_code).ravel()
    state={'code':code, 'pilot':pilot, 'count':len(symbols)}
    return signal,state


def acquire(signal, state, q):
    x=np.asarray(signal,complex); code=state['code']; pilot=state['pilot']; length=len(code); size=len(pilot)*length
    last=min(q['search'],len(x)-size)
    if last<0: raise ValueError('接收码片不足一个训练前导。')
    window=x[:size+last]; energies=np.convolve(abs(window)**2,np.ones(size),mode='valid')
    best=(-1,0,0,0j); phase_scores=[]; phase_profiles=[]
    for phase in range(length):
        template=(pilot[:,None]*np.roll(code,phase)[None,:]/math.sqrt(length)).ravel()
        correlation=np.correlate(window,template,mode='valid')
        score=abs(correlation)/np.sqrt(np.maximum(energies*len(pilot),1e-30))
        offset=int(np.argmax(score)); phase_scores.append(float(score[offset])); phase_profiles.append(score)
        if score[offset]>best[0]: best=(float(score[offset]),offset,phase,correlation[offset]/len(pilot))
    peak,offset,phase,gain=best
    if peak<q['threshold']: raise ValueError(f'码捕获相关峰 {peak:.3f} 低于阈值，请调整训练长度、搜索范围或信道。')
    state.update(offset=offset, phase=phase, gain=gain)
    return {'code_phase':phase,'delay_chips':offset,'correlation_peak':peak,
            'phase_scores':phase_scores,'delay_scores':phase_profiles[phase].tolist(),
            'processing_gain_db':10*math.log10(length),'spreading_factor':length}


def despread_at(signal, state, offset):
    length=len(state['code']); count=len(state['pilot'])+state['count']
    segment=np.asarray(signal,complex)[offset:offset+count*length]
    segment=np.pad(segment,(0,count*length-len(segment)))
    code=np.roll(state['code'],state['phase'])/math.sqrt(length)
    return segment.reshape(count,length)@code


def rake(signal, state, q):
    x=np.asarray(signal,complex); length=len(state['code']); pilot=state['pilot']
    template=(pilot[:,None]*np.roll(state['code'],state['phase'])/math.sqrt(length)).ravel()
    delays=np.arange(max(0,state['offset']-q['span']),state['offset']+q['span']+1)
    # Rows end before the earliest possible payload arrival; no payload symbols
    # or simulated path coefficients participate in channel estimation.
    rows=min(len(x),len(template)+int(delays[0])); index=np.arange(rows)[:,None]-delays
    matrix=np.where((index>=0)&(index<len(template)),template[np.clip(index,0,len(template)-1)],0)
    h=np.linalg.lstsq(matrix,x[:rows],rcond=None)[0]; profile=abs(h).tolist()
    picked=np.argsort(abs(h))[-q['fingers']:]; picked=picked[np.argsort(delays[picked])]
    h=np.linalg.lstsq(matrix[:,picked],x[:rows],rcond=None)[0]
    selected=delays[picked]
    fingers=np.stack([despread_at(x,state,int(d)) for d in selected],axis=1)
    power=float(np.sum(abs(h)**2))
    if power<1e-15: raise ValueError('RAKE 训练路径功率过低。')
    combined=fingers@h.conj()/power
    # Finite codes have nonzero shifted correlations; calibrate their coherent
    # contribution using the same public pilot after finger combination.
    gain=np.vdot(pilot,combined[:len(pilot)])/len(pilot)
    if abs(gain)<1e-10: raise ValueError('RAKE 合并训练增益过低。')
    combined/=gain
    details={'finger_delays':selected.tolist(),'finger_gains':arrays(h),'finger_symbols':arrays(fingers),
             'estimated_delays':delays.tolist(),'delay_profile':profile,
             'combined_gain_power':power,'calibration_gain':arrays([gain]),'training_mse':float(np.mean(abs(matrix[:,picked]@h-x[:rows])**2))}
    return combined[len(pilot):],details


def spatial_encode(symbols, kind, q):
    symbols=np.asarray(symbols,complex); original=len(symbols); nt=1 if kind=='tx_simo' else 2
    pilot=np.column_stack([np.ones(q['training']),(-1.)**np.arange(q['training'])])[:,:nt]/math.sqrt(nt)
    if kind=='tx_simo': payload=symbols[:,None]
    else:
        paired=np.pad(symbols,(0,-len(symbols)%2)).reshape(-1,2)
        if kind=='tx_mimo': payload=paired/math.sqrt(2)
        else:
            payload=np.empty((2*len(paired),2),complex)
            payload[::2]=paired/math.sqrt(2)
            payload[1::2]=np.column_stack([-paired[:,1].conj(),paired[:,0].conj()])/math.sqrt(2)
    return np.vstack([pilot,payload]),{'mode':kind,'pilot':pilot,'count':original}


def spatial_channel(tx, mode, q, rng):
    nt=tx.shape[1]; nr=q['branches'] if mode=='tx_simo' else 1 if mode=='tx_alamouti' else 2
    h=((rng.normal(size=(nr,nt))+1j*rng.normal(size=(nr,nt)))/math.sqrt(2)
       if q['model']==1 else _complex_values(q['gains'])[:nr*nt].reshape(nr,nt))
    received=tx@h.T
    variance=float(np.mean(np.sum(abs(tx)**2,axis=1)))*10**(-q['snr_db']/10) if q['noise'] else 0.
    received+=math.sqrt(variance/2)*(rng.normal(size=received.shape)+1j*rng.normal(size=received.shape))
    return received,{'channel_matrix':arrays(h),'noise_variance':variance,'tx_antennas':nt,'rx_antennas':nr}


def spatial_decode(received, state, kind):
    pilot=state['pilot']; training=received[:len(pilot)]; data=received[len(pilot):]
    # The receiver estimates H and noise exclusively from received public pilots.
    ht=np.linalg.lstsq(pilot,training,rcond=None)[0]; h=ht.T
    residual=training-pilot@ht
    variance=float(np.sum(abs(residual)**2)/((len(pilot)-pilot.shape[1])*received.shape[1]))
    details={'channel_estimate':arrays(h),'estimated_noise_variance':variance,'pilot_received':arrays(training),
             'pilot_reference':arrays(pilot),'branch_power':np.sum(abs(h)**2,axis=1).tolist()}
    if kind in ('rx_selection','rx_mrc'):
        gains=h[:,0]; power=abs(gains)**2
        if np.max(power)<1e-15: raise ValueError('接收训练增益过低。')
        if kind=='rx_selection':
            branch=int(np.argmax(power)); decoded=data[:,branch]/gains[branch]; details['selected_branch']=branch
        else: decoded=data@gains.conj()/power.sum()
        details['combined_gain_power']=float(power.max() if kind=='rx_selection' else power.sum())
    elif kind=='rx_alamouti':
        a,b=h[0]; first=data[::2,0]; second=data[1::2,0]; power=abs(a)**2+abs(b)**2
        if power<1e-15: raise ValueError('Alamouti 接收训练增益过低。')
        decoded=np.column_stack((a.conjugate()*first+b*second.conj(),b.conjugate()*first-a*second.conj())).ravel()*math.sqrt(2)/power
        details['combined_gain_power']=float(power)
    else:
        singular=np.linalg.svd(h,compute_uv=False)
        if kind=='rx_mimo_zf':
            if singular[-1]<1e-10: raise ValueError('ZF 需要满秩的信道矩阵，请调整增益或选用 MMSE。')
            weights=np.linalg.inv(h)
        else: weights=np.linalg.solve(h.conj().T@h+max(2*variance,1e-15)*np.eye(2),h.conj().T)
        decoded=(data@weights.T*math.sqrt(2)).ravel()
        details.update(singular_values=singular.tolist(),condition_number=float(singular[0]/max(singular[-1],1e-15)),detector_weights=arrays(weights))
    details['recovered_symbols']=arrays(decoded[:state['count']])
    return decoded[:state['count']],details


def run_stage(kind, data, q, state, rng, fs):
    """Return 1-D stage display, JSON details and current sample rate."""
    details={}
    if kind=='tx_dsss':
        data,dsss=spread(data,q); state['dsss']=dsss; fs*=len(dsss['code'])
        details={'spreading_factor':len(dsss['code']),'processing_gain_db':10*math.log10(len(dsss['code'])),
                 'code':dsss['code'].tolist(),'training_symbols':len(dsss['pilot'])}
    elif kind=='dsss_multipath':
        delays,gains=paths(q); taps=np.zeros(int(delays.max())+1,complex); taps[delays]=gains
        data=np.convolve(data,taps); details={'path_delays':delays.tolist(),'path_gains':arrays(gains)}
    elif kind=='rx_code_acquire': details=acquire(data,state['dsss'],q)
    elif kind=='rx_despread':
        d=state['dsss']; symbols=despread_at(data,d,d['offset']); pilot=d['pilot']
        gain=np.vdot(pilot,symbols[:len(pilot)])/len(pilot)
        if abs(gain)<1e-10: raise ValueError('解扩训练增益过低。')
        data=symbols[len(pilot):]/gain; fs/=len(d['code']); details={'estimated_gain':arrays([gain])}
    elif kind=='rx_rake':
        data,details=rake(data,state['dsss'],q); fs/=len(state['dsss']['code'])
    elif kind in SPATIAL_TX:
        tx,spatial=spatial_encode(data,kind,q); spatial['tx']=tx; state['spatial']=spatial
        data=tx[:,0]; details={'full_tx':arrays(tx),'tx_antennas':tx.shape[1],'training_slots':q['training'],
                              'total_energy':float(np.sum(abs(tx)**2)),'time_slots':len(tx)}
    elif kind=='spatial_channel':
        s=state['spatial']; received,details=spatial_channel(s['tx'],s['mode'],q,rng); s['received']=received
        details['full_rx']=arrays(received); data=received[:,0]
    elif kind in SPATIAL_RX:
        s=state['spatial']; data,details=spatial_decode(s['received'],s,kind)
    else: raise ValueError('未知无线处理积木。')
    return data,details,fs
