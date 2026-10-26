"""Pilot-only LMMSE/Kalman channel estimation and calibrated soft MIMO detection."""
import math
import numpy as np
from src import communication_dsp as dsp
from src.communication_spatial import arrays

TX = set()
CHANNEL = set()
RX = {'rx_mimo_lmmse', 'rx_mimo_kalman', 'rx_mimo_soft'}
KINDS = RX


def register(block, number, field, blocks):
    common = dict(prior_power=number('信道先验功率', 1, .001, 100),
                  correlation=number('发射维先验相关系数', 0, 0, .99))
    tracking = dict(rho=number('每时隙状态相关系数', .999, .8, 1),
                    process_noise=number('每时隙过程噪声', .0002, 0, .5))
    block('rx_mimo_lmmse', '🔍 LMMSE 信道估计检测', 'rx_converter',
          '以公开导频和噪声估计形成贝叶斯线性信道估计，再作增益校准 MMSE 检测；支持静态、周期导频和 MIMO-OFDM。', **common)
    block('rx_mimo_kalman', '🧭 Kalman 复信道跟踪', 'rx_converter',
          '逐时隙预测复信道，在公开导频到达时更新状态和协方差，以因果估计检测数据。', **common, **tracking)
    block('rx_mimo_soft', '🫧 MIMO 软输出检测', 'rx_converter',
          '按空间流补偿 MMSE 增益，计算残余流间干扰及有效噪声；后接软解调和 LDPC / 软 Viterbi。',
          estimator=field('信道估计', 1, 'select', choices=[0, 1, 2],
                          choice_labels={0:'LS', 1:'LMMSE', 2:'Kalman（周期导频）'}), **common, **tracking)


def presets(preset):
    def entry(label, kinds, changes=None): return {'label':label, 'program':preset(kinds, changes)}
    return {
        'receiver_lmmse':entry('接收估计 · LMMSE / MIMO', ['random_bits','mod_qpsk','tx_mimo','spatial_channel','rx_mimo_lmmse','demod_qpsk','sink'], {3:{'snr_db':10}}),
        'receiver_kalman':entry('接收估计 · Kalman 因果跟踪', ['random_bits','mod_qpsk','tx_mimo_tracking','spatial_dynamic','rx_mimo_kalman','demod_qpsk','sink'], {0:{'count':2048},3:{'velocity_kmh':1,'snr_db':24}}),
        'receiver_soft_ldpc':entry('软检测 · MIMO / LDPC', ['random_bits','ldpc_encode','mod_qpsk','tx_mimo','spatial_channel','rx_mimo_soft','soft_qpsk','ldpc_decode','sink'], {4:{'snr_db':14}}),
        'receiver_soft_viterbi':entry('软检测 · MIMO-OFDM / 软 Viterbi', ['random_bits','conv_encode','mod_qpsk','tx_mimo_ofdm','spatial_multipath','rx_mimo_soft','soft_qpsk','conv_soft_decode','sink'], {4:{'snr_db':24}}),
        'receiver_ofdm_lmmse':entry('接收估计 · MIMO-OFDM / LMMSE', ['random_bits','mod_qpsk','tx_mimo_ofdm','spatial_multipath','rx_mimo_lmmse','demod_qpsk','sink'], {3:{'snr_db':18}}),
        'receiver_kalman_soft':entry('软检测 · Kalman / MIMO / LDPC', ['random_bits','ldpc_encode','mod_qpsk','tx_mimo_tracking','spatial_dynamic','rx_mimo_soft','soft_qpsk','ldpc_decode','sink'], {4:{'velocity_kmh':.5,'snr_db':24},5:{'estimator':2}}),
    }


def build_stage(kind, q, domain, count, features):
    w = features.setdefault('wireless', {})
    if domain != '多天线符号' or w.get('tx') not in {'tx_mimo','tx_mimo_tracking','tx_mimo_ofdm'} or 'spatial_channel' not in w:
        raise ValueError('信道估计接收器连接 MIMO 发送结构及对应空间信道。')
    if (kind == 'rx_mimo_kalman' or q.get('estimator') == 2) and w['tx'] != 'tx_mimo_tracking':
        raise ValueError('Kalman 跟踪连接周期正交导频 MIMO。')
    w['rx'] = kind
    features[kind] = {'params':q, 'count':w['input_count']}
    return '复符号', w['input_count']


def pilot_estimate(pilot, received, method='ls', prior_power=1., correlation=0.):
    """P H.T = Y; estimate noise from LS residual, independent of payload/true H."""
    p = np.asarray(pilot, complex); y = np.asarray(received, complex)
    if len(p) <= p.shape[1] or np.linalg.matrix_rank(p) < p.shape[1]:
        raise ValueError('公开导频须满列秩且时隙数大于发送天线数。')
    ls = np.linalg.lstsq(p, y, rcond=None)[0]
    variance = float(np.sum(abs(y-p@ls)**2)/((len(p)-p.shape[1])*y.shape[1]))
    if method == 'lmmse':
        n = p.shape[1]; prior = prior_power * correlation**abs(np.arange(n)[:,None]-np.arange(n))
        ls = np.linalg.solve(p.conj().T@p + variance*np.linalg.inv(prior), p.conj().T@y)
    return ls.T, variance


def calibrated_mmse(y, h, variance):
    """Unit-energy streams y = H x / sqrt(Nt) + n, with per-stream post-filter noise."""
    a = np.asarray(h, complex)/math.sqrt(h.shape[1]); y = np.atleast_2d(y)
    noise = max(float(variance), 1e-15)
    weights = np.linalg.solve(a.conj().T@a+noise*np.eye(a.shape[1]), a.conj().T)
    response = weights@a; gain = np.diag(response)
    if np.any(abs(gain) < 1e-12): raise ValueError('公开导频估计的空间流增益过低。')
    residual = np.maximum(0, np.sum(abs(response)**2,axis=1)-abs(gain)**2)
    effective = (noise*np.sum(abs(weights)**2,axis=1)+residual)/abs(gain)**2
    return (y@weights.T)/gain, effective, weights


def kalman_channels(received, pilot, pilot_slots, data_slots, q, variance):
    """Complex AR(1) state filter, updating only at the observed public pilot slots."""
    nt = pilot.shape[1]; nr = received.shape[1]
    h = np.zeros((nr, nt),complex)
    covariance = q['prior_power']*q['correlation']**abs(np.arange(nt)[:,None]-np.arange(nt))
    measurements = {int(slot):pilot[j] for group in pilot_slots for j,slot in enumerate(group)}
    wanted = set(data_slots); estimates=[]; uncertainty=[]; innovations=[]
    for slot in range(max(data_slots)+1):
        h *= q['rho']; covariance = q['rho']**2*covariance+q['process_noise']*np.eye(nt)
        if slot in measurements:
            x=measurements[slot]; residual=received[slot]-h@x
            gain=covariance@x.conj()/(float((x@covariance@x.conj()).real)+max(variance,1e-15))
            h += residual[:,None]*gain[None,:]
            covariance -= np.outer(gain,x@covariance)
            covariance=(covariance+covariance.conj().T)/2
            innovations.append(float(np.mean(abs(residual)**2)))
        if slot in wanted:
            estimates.append(h.copy()); uncertainty.append(float(np.trace(covariance).real))
    return np.array(estimates), {'covariance_trace':uncertainty, 'innovation_power':innovations}


def decode(received, public, kind, q, scheme):
    """public contains training, length, layout; the decoder never reads tx or true CSI."""
    mode=public['mode']; method='kalman' if kind=='rx_mimo_kalman' else ('ls','lmmse','kalman')[q.get('estimator',1)]
    prior=q['prior_power']; corr=q['correlation']; tracking={}; details={}
    if mode=='tx_mimo_ofdm':
        n=public['params']['nfft']; cp=public['params']['cp']; frames=public['frames']+4
        grid=np.fft.fft(received[:frames*(n+cp)].reshape(frames,n+cp,2)[:,cp:],axis=1,norm='ortho')
        estimates=[]; variances=[]
        for carrier in range(n):
            h,noise=pilot_estimate(public['pilot'][:,carrier],grid[:4,carrier],method,prior,corr)
            estimates.append(h);variances.append(noise)
        estimates=np.array(estimates);variance=float(np.mean(variances))
        values=np.zeros((public['frames'],n,2),complex); noises=np.zeros(values.shape,float)
        for carrier in range(n):
            values[:,carrier],post,_=calibrated_mmse(grid[4:,carrier],estimates[carrier],variance)
            noises[:,carrier]=post
        details.update(grid=arrays(grid),subcarriers=np.fft.fftfreq(n,d=1/n).astype(int).tolist(),
                       condition_numbers=[float(np.linalg.cond(h)) for h in estimates])
    elif mode=='tx_mimo_tracking':
        groups=public['pilot_slots']; slots=public['data_slots']; pilot=public['pilot']; hs=[];variances=[]
        for group in groups:
            h,noise=pilot_estimate(pilot,received[group],method if method!='kalman' else 'ls',prior,corr)
            hs.append(h);variances.append(noise)
        variance=float(variances[0] if method=='kalman' else np.mean(variances));hs=np.array(hs);centers=np.mean(groups,axis=1)
        if method=='kalman': estimates,tracking=kalman_channels(received,pilot,groups,slots,q,variance)
        else:
            estimates=np.empty((len(slots),2,2),complex)
            for r in range(2):
                for t in range(2): estimates[:,r,t]=np.interp(slots,centers,hs[:,r,t].real)+1j*np.interp(slots,centers,hs[:,r,t].imag)
        values=[];noises=[]
        for sample,h in zip(received[slots],estimates):
            value,post,_=calibrated_mmse(sample,h,variance);values.append(value[0]);noises.append(post)
        tracking.update(pilot_slots=groups,data_slots=slots,estimated=arrays(hs),condition_numbers=[float(np.linalg.cond(h)) for h in estimates])
        details['tracking']=tracking
    else:
        pilot=public['pilot']; estimates,variance=pilot_estimate(pilot,received[:len(pilot)],method,prior,corr)
        values,post,weights=calibrated_mmse(received[len(pilot):],estimates,variance)
        noises=np.broadcast_to(post,values.shape)
        details.update(detector_weights=arrays(weights),singular_values=np.linalg.svd(estimates,compute_uv=False).tolist())
    out=np.asarray(values).ravel()[:public['count']];post=np.asarray(noises).ravel()[:public['count']]
    llr=dsp.soft_demod(out,scheme,post)
    details.update(channel_estimate=arrays(estimates),estimated_noise_variance=variance,estimator=method.upper(),
                   effective_noise_variance=post.tolist(),llr=llr.tolist(),recovered_symbols=arrays(out),
                   stream_symbols=arrays(np.pad(out,(0,-len(out)%2)).reshape(-1,2)),
                   stream_counts=[math.ceil(len(out)/2),len(out)//2])
    return out,details


def run_stage(kind,data,q,state,rng,fs):
    s=state['spatial']; public={k:s[k] for k in ('mode','count','pilot','pilot_slots','data_slots','params','frames') if k in s}
    out,details=decode(s['received'],public,kind,q,state['scheme'])
    state['soft_variance']=np.array(details['effective_noise_variance'])
    if s['mode']=='tx_mimo_ofdm': fs/=s['params']['nfft']
    return out,details,fs
