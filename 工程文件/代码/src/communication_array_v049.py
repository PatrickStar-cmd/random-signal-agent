"""ULA propagation, measured reciprocal sounding, precoding and spatial rejection."""
import math
import numpy as np
from src.communication_spatial import arrays
from src.communication_receiver_v049 import pilot_estimate, calibrated_mmse

TX={'tx_array','tx_mrt','tx_svd'}
CHANNEL={'array_channel','array_interference'}
RX={'rx_array_conventional','rx_array_mvdr','rx_array_svd'}
KINDS=TX|CHANNEL|RX


def register(block,number,field,blocks):
    for kind,label,description in [
        ('tx_array','📡 均匀线阵训练帧','单路符号与公共训练；由阵列信道生成各接收阵元的相位差。'),
        ('tx_mrt','🧭 MRT 发射波束成形','反向正交导频实测信道，按估计信道共轭设置单流发射权重；总发送功率归一化。'),
        ('tx_svd','🛰️ SVD 双流预编码','反向正交导频实测矩阵，以右奇异向量发送两路数据，正向导频供接收估计有效信道。')]:
        params={'training':field('公开训练时隙',128,'select',choices=[32,64,128,256])}
        if kind!='tx_array':params['antennas']=field('发送天线数',4,'select',choices=[2,4,8])
        block(kind,label,'tx_converter',description,**params)
    block('array_channel','🌐 阵列角度多径信道','channel','按到达角、离开角和阵元间距形成每条路径的阵列响应，叠加路径并加入独立接收噪声。',
          branches=field('接收天线数',4,'select',choices=[1,2,4,8]),spacing=number('阵元间距 / 波长',.5,.1,1),
          arrival=field('各路径到达角 / °','10',max_length=120),departure=field('各路径离开角 / °','20',max_length=120),
          gains=field('各路径复增益','1',max_length=200),noise=field('加入白噪声',True,'boolean'),snr_db=number('发送总功率 / 每阵元噪声 / dB',15,-10,80))
    block('array_interference','🎯 定向空间干扰','channel','从指定方向叠加独立 QPSK 干扰，各阵元按真实空间相位接收同一干扰波形。',
          angle=number('干扰到达角 / °',-35,-90,90),amplitude=number('每阵元干扰 RMS',3,0,20))
    for kind,label in [('rx_array_conventional','🧭 常规波束合并'),('rx_array_mvdr','🎯 MVDR 自适应零陷')]:
        params={'look_angle':number('目标观察角 / °',10,-90,90)}
        if kind=='rx_array_mvdr':params['loading']=number('协方差对角加载 / 平均功率',.001,.000001,1)
        block(kind,label,'rx_converter','使用目标方向矢量形成权重；公共训练校准输出增益。'+('训练残差估计干扰噪声协方差，在目标方向保持单位响应。' if kind.endswith('mvdr') else ''),**params)
    block('rx_array_svd','🛰️ 预编码双流接收','rx_converter','仅由正向公共导频估计有效信道，以增益校准 MMSE 检测恢复空间流，并输出每流有效噪声。')


def presets(preset):
    def entry(label,kinds,changes=None):return {'label':label,'program':preset(kinds,changes)}
    return {
        'array_conventional':entry('阵列 · 常规波束与方向干扰',['random_bits','mod_qpsk','tx_array','array_channel','array_interference','rx_array_conventional','demod_qpsk','sink']),
        'array_mvdr':entry('阵列 · MVDR 自适应零陷',['random_bits','mod_qpsk','tx_array','array_channel','array_interference','rx_array_mvdr','demod_qpsk','sink']),
        'array_mrt':entry('预编码 · 公共导频 / MRT',['random_bits','mod_qpsk','tx_mrt','array_channel','rx_array_conventional','demod_qpsk','sink'],{3:{'branches':1},4:{'look_angle':10}}),
        'array_svd':entry('预编码 · 公共导频 / SVD 双流',['random_bits','mod_qam16','tx_svd','array_channel','rx_array_svd','demod_qam16','sink'],{3:{'arrival':'10,-35','departure':'20,50','gains':'1,0.6+0.2j','snr_db':25}}),
    }


def steering(count,spacing,angle):
    return np.exp(2j*np.pi*spacing*np.arange(count)*np.sin(np.deg2rad(angle)))


def geometry(q,nt):
    arrival=np.array([float(x) for x in q['arrival'].split(',')]);departure=np.array([float(x) for x in q['departure'].split(',')])
    gains=np.array([complex(x.strip().replace('i','j')) for x in q['gains'].split(',')])
    if not 1<=len(gains)<=8 or len(arrival)!=len(gains) or len(departure)!=len(gains):raise ValueError('每条路径填写一个到达角、离开角和复增益，路径数为 1–8。')
    if not np.isfinite(arrival).all() or not np.isfinite(departure).all() or not np.isfinite(gains).all() or np.any(abs(arrival)>90) or np.any(abs(departure)>90) or np.linalg.norm(gains)==0:
        raise ValueError('路径角度为 −90 至 90°，复增益有限且总功率大于零。')
    return sum(g*np.outer(steering(q['branches'],q['spacing'],a),steering(nt,q['spacing'],d).conj()) for a,d,g in zip(arrival,departure,gains))


def public_pilots(length,streams):
    return np.exp(2j*np.pi*np.arange(length)[:,None]*np.arange(streams)[None,:]/length)/math.sqrt(streams)


def sounding(channel,length,variance,rng):
    """Environment sends reverse public pilots; estimator sees only P and Y."""
    pilot=public_pilots(length,channel.shape[0]); received=pilot@channel
    received=received+math.sqrt(variance/2)*(rng.normal(size=received.shape)+1j*rng.normal(size=received.shape))
    reverse,noise=pilot_estimate(pilot,received)
    return reverse.T, {'reference':arrays(pilot),'received':arrays(received),'estimated_channel':arrays(reverse.T),'estimated_noise_variance':noise}


def pattern(weights,spacing,transmit=False):
    angles=np.linspace(-90,90,181);weights=np.asarray(weights)
    if weights.ndim==1:weights=weights[:,None]
    response=np.array([steering(len(weights),spacing,a).conj()@weights for a in angles])
    power=abs(response)**2
    power/=np.maximum(np.max(power,axis=0),1e-30)
    return {'angles':angles.tolist(),'db':(10*np.log10(np.maximum(power,1e-8))).T.tolist(),'transmit':transmit}


def build_stage(kind,q,domain,count,features):
    w=features.setdefault('wireless',{})
    if kind in TX:
        if domain!='复符号' or 'tx' in w or any(k in features for k in ('tx_rrc','tx_frame','tx_ofdm','tx_pilots')):raise ValueError('阵列发送结构直接连接数字映射器。')
        streams=2 if kind=='tx_svd' else 1; prefix=q['training'] if kind!='tx_array' else 0
        w.update(tx=kind,input_count=count,params=q,rate_factor=1,streams=streams,tx_antennas=q.get('antennas',1))
        count=prefix+q['training']+math.ceil(count/streams);domain='多天线符号'
    elif kind=='array_channel':
        if domain!='多天线符号' or w.get('tx') not in TX or w.get('array_channel'):raise ValueError('阵列角度信道接在阵列 / MRT / SVD 发送之后，每条链路放置一次。')
        h=geometry(q,w['tx_antennas'])
        if w['tx']=='tx_mrt' and q['branches']!=1:raise ValueError('MRT 单流示例使用一根接收天线。')
        if w['tx']=='tx_svd' and np.linalg.matrix_rank(h)<2:raise ValueError('SVD 双流需要两条独立空间路径和至少两根接收天线。')
        w['array_channel']=q
    elif kind=='array_interference':
        if domain!='多天线符号' or not w.get('array_channel'):raise ValueError('方向干扰放在阵列角度信道之后。')
    else:
        if domain!='多天线符号' or not w.get('array_channel'):raise ValueError('阵列接收器连接阵列角度信道。')
        if (kind=='rx_array_svd')!=(w['tx']=='tx_svd'):raise ValueError('SVD 双流使用预编码双流接收，其余阵列发送使用常规或 MVDR 合并。')
        w['rx']=kind;domain='复符号';count=w['input_count']
    features[kind]={'params':q,'count':count}
    return domain,count


def encode(symbols,kind,q,channel_q,rng):
    streams=2 if kind=='tx_svd' else 1;nt=q.get('antennas',1);precoder=np.ones((nt,streams),complex)/math.sqrt(nt)
    prefix=0;details={}
    if kind!='tx_array':
        channel=geometry(channel_q,nt);variance=10**(-channel_q['snr_db']/10) if channel_q['noise'] else 0.
        estimate,observed=sounding(channel,q['training'],variance,rng)
        if kind=='tx_mrt':precoder=estimate[0].conj()[:,None]/np.linalg.norm(estimate[0])
        else:precoder=np.linalg.svd(estimate,full_matrices=False)[2].conj().T[:,:streams]
        prefix=q['training'];details.update(sounding=observed,precoder=arrays(precoder),beam_pattern=pattern(precoder,channel_q['spacing'],True))
    pilot=public_pilots(q['training'],streams);payload=np.pad(symbols,(0,-len(symbols)%streams)).reshape(-1,streams)/math.sqrt(streams)
    tx=np.vstack([np.zeros((prefix,nt),complex),np.vstack([pilot,payload])@precoder.T])
    s={'mode':kind,'pilot':pilot,'count':len(symbols),'prefix':prefix,'tx':tx,'streams':streams,'spacing':channel_q['spacing']}
    details.update(full_tx=arrays(tx),tx_antennas=nt,training_slots=q['training'],sounding_slots=prefix,
                   total_energy=float(np.sum(abs(tx)**2)),time_slots=len(tx))
    return tx,s,details


def receive(y,public,kind,q):
    prefix=public['prefix'];p=public['pilot'];y=y[prefix:];training=y[:len(p)];payload=y[len(p):]
    h,variance=pilot_estimate(p,training)
    details={'channel_estimate':arrays(h),'pilot_reference':arrays(p),'pilot_received':arrays(training),'estimated_noise_variance':variance}
    if kind=='rx_array_svd':
        values,noise,weights=calibrated_mmse(payload,h,variance);out=values.ravel()[:public['count']]
        details.update(effective_noise_variance=np.broadcast_to(noise,values.shape).ravel()[:len(out)].tolist(),
                       detector_weights=arrays(weights),stream_symbols=arrays(values),stream_counts=[math.ceil(len(out)/2),len(out)//2])
    else:
        a=steering(y.shape[1],public['spacing'],q['look_angle'])
        residual=training-p@h.T;covariance=residual.T@residual.conj()/len(residual)
        if kind=='rx_array_mvdr':
            load=q['loading']*max(float(np.trace(covariance).real/y.shape[1]),1e-12)
            inverse=np.linalg.solve(covariance+load*np.eye(len(a)),a);weights=inverse/np.vdot(a,inverse)
        else:weights=a/np.vdot(a,a)
        gain=np.vdot(weights,h[:,0])
        if abs(gain)<1e-10:raise ValueError('当前观察角度的公共训练响应过低。')
        out=(payload@weights.conj()/gain)[:public['count']]
        pre=float(np.mean(abs(residual)**2));post=float(np.mean(abs(residual@weights.conj()/gain)**2))
        details.update(beam_weights=arrays(weights),beam_pattern=pattern(weights,public['spacing']),
                       covariance=arrays(covariance),input_interference_noise=pre,output_interference_noise=post,
                       rejection_db=float(10*np.log10(max(pre,1e-20)/max(post,1e-20))),effective_noise_variance=[max(post,1e-15)]*len(out))
    details['recovered_symbols']=arrays(out)
    return out,details


def run_stage(kind,data,q,state,rng,fs):
    if kind in TX:
        channel_q=state['array_channel_params']
        tx,s,details=encode(data,kind,q,channel_q,rng);state['spatial']=s
        return tx[:,0],details,fs
    s=state['spatial']
    if kind=='array_channel':
        h=geometry(q,s['tx'].shape[1]);variance=10**(-q['snr_db']/10) if q['noise'] else 0.
        y=s['tx']@h.T+math.sqrt(variance/2)*(rng.normal(size=(len(s['tx']),q['branches']))+1j*rng.normal(size=(len(s['tx']),q['branches'])))
        s['received']=y
        return y[:,0],{'full_rx':arrays(y),'channel_matrix':arrays(h),'noise_variance':variance,'arrival_angles':[float(a) for a in q['arrival'].split(',')]},fs
    if kind=='array_interference':
        y=s['received'];a=steering(y.shape[1],s['spacing'],q['angle'])
        jammer=q['amplitude']*(2*rng.integers(0,2,len(y))-1+1j*(2*rng.integers(0,2,len(y))-1))/math.sqrt(2)
        y=y+jammer[:,None]*a[None,:];s['received']=y
        return y[:,0],{'full_rx':arrays(y),'interference_angle':q['angle'],'interference_power':q['amplitude']**2},fs
    public={k:s[k] for k in ('pilot','count','prefix','spacing')}
    out,details=receive(s['received'],public,kind,q);state['soft_variance']=np.array(details['effective_noise_variance'])
    return out,details,fs
