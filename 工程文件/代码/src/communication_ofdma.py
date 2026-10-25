"""Downlink OFDMA with independently queued source users and actual FFT receivers."""
import math
import numpy as np
from src import communication_dsp as dsp
from src.communication_spatial import arrays

TX={'tx_ofdma'};CHANNEL={'ofdma_channel'};RX={'rx_ofdma'};KINDS=TX|CHANNEL|RX


def register(block,number,field,blocks):
    block('tx_ofdma','OFDMA 多用户资源调度','tx_converter','将各独立信源作为用户，按到达时刻排队、分配子载波和功率，并形成实际 OFDM 波形。',
          nfft=field('FFT / 可分配子载波',32,'select',choices=[16,32,64,128]),cp=number('循环前缀 / 样本',8,1,64,True),
          scheduler=field('调度策略',2,'select',choices=[0,1,2,3],choice_labels={0:'固定频带分配',1:'轮询',2:'加权公平',3:'最长队列优先'}),
          weights=field('各用户资源权重','1,2,1',max_length=80),powers=field('各用户每载波功率','1,1,1',max_length=80),
          packet_symbols=number('每包符号数',16,1,256,True),arrival_gap=number('同用户包到达间隔 / OFDM 时隙',2,0,64,True))
    block('ofdma_channel','OFDMA 独立用户信道','channel','同一下行发射波形分别经过各用户复信道和独立噪声。',
          gains=field('各用户复增益','1,0.7+0.2j,0.4-0.1j',max_length=160),snrs=field('各用户发送信噪比 / dB','28,24,22',max_length=80),
          noise=field('加入独立白噪声',True,'boolean'))
    block('rx_ofdma','OFDMA 分用户恢复','rx_converter','各用户从公共训练估计信道、FFT 解复用自身资源，并统计实际 BER、吞吐、排队时延及公平性。')


def presets(preset):
    out={}
    for key,label,policy in [('ofdma_fair','多用户 · OFDMA 加权公平',2),('ofdma_round_robin','多用户 · OFDMA 轮询',1),('ofdma_queue','多用户 · OFDMA 最长队列',3)]:
        out[key]={'label':label,'program':preset(['random_bits','pn_bits','bit_pattern','mod_qpsk','tx_ofdma','ofdma_channel','rx_ofdma','demod_qpsk','sink'],
            {0:{'count':256},1:{'count':384},2:{'pattern':'10110010'*32},4:{'scheduler':policy}})}
    return out


def numbers(text,count,complex_values=False):
    values=np.array([(complex(x.strip().replace('i','j')) if complex_values else float(x.strip())) for x in text.split(',')])
    if len(values)!=count or not np.all(np.isfinite(values)):raise ValueError(f'参数须为 {count} 个有限数值，与独立信源用户一一对应。')
    return values


def schedule(lengths,q):
    """Return a resource owner and original-symbol-index for every resource cell."""
    users=len(lengths);n=q['nfft'];weights=numbers(q['weights'],users);powers=numbers(q['powers'],users)
    if np.any(weights<=0) or np.any(weights>100) or np.any(powers<=0) or np.any(powers>100):raise ValueError('资源权重和每载波功率须在 0 至 100 之间。')
    starts=np.r_[0,np.cumsum(lengths)];served=np.zeros(users,int);rows=[];owners=[];queue=[];turn=0
    fixed=np.minimum(np.searchsorted(np.cumsum(weights)/sum(weights),(np.arange(n)+.5)/n),users-1)
    if q['scheduler']==0 and len(set(fixed))!=users:raise ValueError('固定频带分配须为每个用户保留至少一个子载波，请调整资源权重。')
    frame=0
    while np.any(served<lengths):
        if frame>=2048:raise ValueError('OFDMA 调度超过 2048 个时隙，请缩短到达间隔或减少数据。')
        arrived=np.array(lengths) if not q['arrival_gap'] else np.minimum(lengths,(frame//q['arrival_gap']+1)*q['packet_symbols'])
        pending=arrived-served;queue.append(pending.copy());row=np.full(n,-1,int);owner=np.full(n,-1,int)
        for carrier in range(n):
            active=np.flatnonzero(pending>0)
            if len(active)==0:break
            if q['scheduler']==0:
                user=int(fixed[carrier])
                if pending[user]==0:continue
            elif q['scheduler']==1:
                user=int(next((turn+i)%users for i in range(users) if pending[(turn+i)%users]>0));turn=(user+1)%users
            elif q['scheduler']==2:user=int(active[np.argmin(served[active]/weights[active])])
            else:user=int(active[np.argmax(pending[active])])
            row[carrier]=starts[user]+served[user];owner[carrier]=user;served[user]+=1;pending[user]-=1
        rows.append(row);owners.append(owner);frame+=1
    return np.array(rows),np.array(owners),np.array(queue),powers


def build_stage(kind,q,domain,count,features):
    w=features.setdefault('wireless',{})
    if kind=='tx_ofdma':
        if domain!='复符号' or 'tx' in w or any(k in features for k in ('tx_rrc','tx_frame','tx_ofdm','tx_pilots')):raise ValueError('OFDMA 组帧直接连接独立信源的数字映射。')
        sources=features['source_counts'];scheme=features['modulator']['kind'][4:]
        if not 2<=len(sources)<=4 or scheme not in {'bpsk','qpsk','psk8','qam16','qam64','qam256'}:raise ValueError('OFDMA 使用 2–4 个独立数字信源，并连接 PSK / QAM 映射。')
        width=dsp.constellation(scheme)[0].shape[1]
        if any(size%width for size in sources) or sum(sources)!=features['coded_count'] or features.get('encoding_kinds'):raise ValueError('每个用户比特数须整除星座位宽，用户信源直接连接映射器以保留独立边界。')
        if q['cp']>=q['nfft']:raise ValueError('循环前缀长度须小于 FFT 点数。')
        lengths=np.array(sources)//width;rows,_,_,_=schedule(lengths,q)
        w.update(tx=kind,input_count=count,params=q,rate_factor=q['nfft'],users=len(sources));count=(len(rows)+1)*(q['nfft']+q['cp']);domain='多用户波形'
    elif kind=='ofdma_channel':
        if domain!='多用户波形' or w.get('channel'):raise ValueError('OFDMA 用户信道连接多用户组帧，每条链路放置一次。')
        gains=numbers(q['gains'],w['users'],True);snrs=numbers(q['snrs'],w['users'])
        if np.any(abs(gains)<1e-6) or np.any(abs(snrs)>100):raise ValueError('用户增益幅度须大于 10⁻⁶，SNR 为 −100 至 100 dB。')
        w['channel']=kind
    else:
        if domain!='多用户波形' or w.get('channel')!='ofdma_channel':raise ValueError('OFDMA 接收需要配对组帧和用户信道。')
        domain='复符号';count=w['input_count'];w['rx']=kind
    features[kind]={'params':q,'count':count}
    return domain,count


def encode(symbols,q,state,fs):
    width=dsp.constellation(state['scheme'])[0].shape[1];lengths=np.array(state['source_counts'])//width
    rows,owners,queues,powers=schedule(lengths,q);grid=np.zeros(rows.shape,complex);used=owners>=0
    grid[used]=symbols[rows[used]]*np.sqrt(powers[owners[used]])
    grid=np.vstack([np.ones(q['nfft'],complex),grid]);wave=np.fft.ifft(grid,axis=1,norm='ortho')
    tx=np.concatenate([wave[:,-q['cp']:],wave],axis=1).ravel()
    resource_power=np.zeros(rows.shape);resource_power[used]=powers[owners[used]]
    resource={'owners':owners.tolist(),'power':resource_power.tolist(),'subcarriers':np.fft.fftfreq(q['nfft'],d=1/q['nfft']).astype(int).tolist(),
              'frame_seconds':(q['nfft']+q['cp'])/(fs*q['nfft']),'scheduler':q['scheduler']}
    state['ofdma']={'tx':tx,'reference':symbols.copy(),'rows':rows,'owners':owners,'queues':queues,'powers':powers,'lengths':lengths,'params':q,'resources':resource,'width':width}
    return tx,{'full_tx':arrays(tx[:,None]),'grid':arrays(grid),'resources':resource,'user_source_bits':state['source_counts']}


def channel(s,q,rng):
    users=len(s['lengths']);gains=numbers(q['gains'],users,True);snrs=numbers(q['snrs'],users)
    y=s['tx'][:,None]*gains[None,:];variances=np.mean(abs(s['tx'])**2)*10**(-snrs/10) if q['noise'] else np.zeros(users)
    y+=np.sqrt(variances[None,:]/2)*(rng.normal(size=y.shape)+1j*rng.normal(size=y.shape))
    s['received']=y
    return y,{'full_rx':arrays(y),'user_gains':arrays(gains),'noise_variances':variances.tolist(),'users':users}


def decode(s,scheme):
    q=s['params'];n=q['nfft'];cp=q['cp'];users=len(s['lengths']);frames=len(s['rows'])+1
    grid=np.fft.fft(s['received'].reshape(frames,n+cp,users)[:,cp:],axis=1,norm='ortho');h=grid[0]
    if np.any(abs(h)<1e-12):raise ValueError('用户训练增益过低，请调整信道或训练信噪比。')
    out=np.zeros(len(s['reference']),complex);user_results=[];duration=frames*s['resources']['frame_seconds'];offset=0;delivered=[]
    for user,size in enumerate(s['lengths']):
        size=int(size)
        selected=s['owners']==user;time,carrier=np.where(selected);indices=s['rows'][selected]
        out[indices]=grid[time+1,carrier,user]/h[carrier,user]/math.sqrt(s['powers'][user])
        recovered,_=dsp.decisions(out[offset:offset+size],scheme);reference,_=dsp.decisions(s['reference'][offset:offset+size],scheme)
        errors=recovered!=reference;packets=[];delays=[];sent=0;times=np.zeros(size,int);times[indices-offset]=time
        for start in range(0,size,q['packet_symbols']):
            end=min(size,start+q['packet_symbols']);packet_errors=int(errors[start*s['width']:end*s['width']].sum());ok=packet_errors==0
            if ok:sent+=(end-start)*s['width']
            arrival=(start//q['packet_symbols'])*q['arrival_gap'];finish=int(times[start:end].max())+1
            delay=(finish-arrival)*s['resources']['frame_seconds'];delays.append(delay)
            packets.append({'symbols':end-start,'bit_errors':packet_errors,'delivered':ok,'arrival_slot':arrival,'completion_slot':finish,'delay_seconds':delay})
        result={'id':user,'source_bits':int(size*s['width']),'bit_errors':int(errors.sum()),'ber':float(errors.mean()),'delivered_bits':sent,
                'throughput_bps':sent/duration,'mean_delay_seconds':float(np.mean(delays)),'queue_history':(s['queues'][:,user]*s['width']).tolist(),
                'allocated_cells':int(selected.sum()),'power':float(s['powers'][user]),'packets':packets}
        user_results.append(result);delivered.append(sent/duration);offset+=size
    rates=np.array(delivered);fairness=float(rates.sum()**2/(users*np.sum(rates**2))) if np.any(rates) else 0.
    return out,{'recovered_symbols':arrays(out),'grid':arrays(grid),'channel_estimate':arrays(h),'resources':s['resources'],
                'users':user_results,'fairness':fairness,'duration_seconds':duration,'total_throughput_bps':sum(delivered)}


def run_stage(kind,data,q,state,rng,fs):
    if kind=='tx_ofdma':data,details=encode(data,q,state,fs);return data,details,fs*q['nfft']
    s=state['ofdma']
    if kind=='ofdma_channel':y,details=channel(s,q,rng);return y[:,0],details,fs
    data,details=decode(s,state['scheme']);return data,details,fs/s['params']['nfft']
