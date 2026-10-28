"""Self-describing, CRC-protected single-carrier frames and streaming capture.

Frame format is public: 127-symbol BPSK PN, 292-symbol convolutionally coded
BPSK header, MCS-selected payload/CRC. Receiver decisions use observed samples
and decoded headers; transmitter bookkeeping is used only for TX plots.
"""
import base64
import math
import struct
import numpy as np
from src import communication_codecs as codec, communication_dsp as dsp

TX={'tx_self_frame'}; CHANNEL={'frame_stream_channel'}; RX={'rx_self_frame'}; KINDS=TX|CHANNEL|RX
PREAMBLE=(1-2*np.random.default_rng(410).integers(0,2,127)).astype(complex)
HEADER_SYMBOLS=292
MCS={0:('bpsk',False),1:('qpsk',False),2:('bpsk',True),3:('qpsk',True)}
MCS_NAMES={0:'BPSK',1:'QPSK',2:'BPSK · 卷积 1/2',3:'QPSK · 卷积 1/2'}


def register(block,number,field,blocks):
    block('tx_self_frame','自描述物理帧与连续分包','tx_converter',
          '公开前导捕获；BPSK 卷积保护帧头实际传输长度、MCS、包序号与业务偏移；逐包 CRC16。',
          packet_bytes=number('每包载荷 / 字节',32,1,256,True),
          mcs=field('载荷 MCS',1,'select',choices=[0,1,2,3,4],choice_labels={**MCS_NAMES,4:'四种 MCS 逐包轮换'}),
          gap=number('包间隔 / 样本',32,0,2048,True))
    block('frame_stream_channel','连续流间隔、噪声与截断','channel',
          '为连续实际波形添加前置噪声、AWGN、复增益，并按样本位置截去一段来验证重捕获。',
          snr_db=number('有效符号 Es/N₀ / dB',18,-10,60),
          leading=number('前置噪声 / 样本',83,0,4096,True),
          gain=number('接收幅度',.8,.05,3),phase_deg=number('接收相位 / °',24,-180,180),
          cut_start=number('截断起始 / 发送样本',0,0,1048576,True),
          cut_samples=number('移除样本数',0,0,65536,True))
    block('rx_self_frame','连续物理帧捕获与业务重组','rx_converter',
          '从录波相关捕获、软解保护帧头，再按实际解出的 MCS 与长度接收载荷；CRC 筛选并按偏移重组。',
          threshold=number('归一化前导捕获阈值',.62,.25,.95))


def presets(preset):
    kinds=['random_bits','mod_bpsk','tx_self_frame','frame_stream_channel','rx_self_frame','demod_bpsk','sink']
    return {'self_describing_frames':{'label':'物理分包 · 自描述连续收发','program':preset(kinds,{0:{'count':2048},2:{'mcs':4}})},
            'frame_reacquisition':{'label':'连续录波 · 截断后重捕获','program':preset(kinds,{0:{'count':2048},2:{'mcs':4},3:{'cut_start':520,'cut_samples':83}})}}


def payload_symbols(bit_count,mcs):
    scheme,coded=MCS[mcs]; count=bit_count+16
    if coded: count=2*(count+2)
    return math.ceil(count/(1 if scheme=='bpsk' else 2))


def stream_size(bit_count,q):
    size=int(q['packet_bytes'])*8; total=0; packets=math.ceil(bit_count/size)
    for seq,start in enumerate(range(0,bit_count,size)):
        mcs=seq%4 if q['mcs']==4 else q['mcs']
        total+=len(PREAMBLE)+HEADER_SYMBOLS+payload_symbols(min(size,bit_count-start),mcs)
    return total+max(0,packets-1)*int(q['gap'])


def build_stage(kind,q,domain,count,features):
    before=count; state=features.setdefault('framing_v0410',{})
    if kind=='tx_self_frame':
        if domain!='复符号' or 'tx_self_frame' in state: raise ValueError('自描述物理帧连接 BPSK 比特载体，每条链路放置一次。')
        count=stream_size(count,q); domain='复采样波形'; state['tx_self_frame']={'input_count':before,'params':q}
        features.setdefault('wireless',{}).update(tx=kind,rate_factor=1)
    elif kind=='frame_stream_channel':
        if domain!='复采样波形': raise ValueError('连续流信道连接自描述发送波形。')
        count+=q['leading']-min(q['cut_samples'],max(0,count-q['cut_start']))
    elif kind=='rx_self_frame':
        if domain!='复采样波形': raise ValueError('连续帧接收连接复采样录波或自描述物理帧。')
        count=state.get('tx_self_frame',{}).get('input_count',count); domain='复符号'
        features.setdefault('wireless',{}).update(rx=kind)
    features[kind]={'params':q,'input_count':before,'count':count}
    return domain,count


def encode_stream(bits,q):
    from src import communications as c
    bits=np.asarray(bits,np.uint8); size=int(q.get('packet_bytes',32))*8; chunks=[]; frames=[]; position=0
    if len(bits)>1048576: raise ValueError('一组自描述业务最多传输 1048576 位。')
    if math.ceil(len(bits)/size)>65536: raise ValueError('一组业务最多 65536 包，请增加每包载荷长度。')
    for sequence,start in enumerate(range(0,len(bits),size)):
        payload=bits[start:start+size]; mcs=sequence%4 if q.get('mcs',1)==4 else int(q.get('mcs',1))
        header=struct.pack('>HBBHHII',0x4f43,1,mcs,len(payload),sequence,start,len(bits))
        header_bits=np.unpackbits(np.frombuffer(header,dtype=np.uint8))
        protected=c.conv_encode(np.r_[header_bits,codec.crc(header_bits,16)])
        header_wave=(1-2*protected.astype(float)).astype(complex)
        content=np.r_[payload,codec.crc(payload,16)]; scheme,coded=MCS[mcs]
        payload_wave,_=c.modulate(c.conv_encode(content) if coded else content,scheme)
        wave=np.r_[PREAMBLE,header_wave,payload_wave]; chunks.append(wave)
        frames.append({'sequence':sequence,'start_sample':position,'end_sample':position+len(wave),
                       'payload_bits':len(payload),'offset_bits':start,'total_bits':len(bits),'mcs':mcs,'mcs_name':MCS_NAMES[mcs]})
        position+=len(wave)
        if start+size<len(bits): chunks.append(np.zeros(int(q.get('gap',32)),complex)); position+=int(q.get('gap',32))
    return np.concatenate(chunks),{'kind':'self_frame_tx','frames':frames,'total_bits':len(bits),'samples':position,
                                   'header_bits':144,'header_symbols':HEADER_SYMBOLS,'preamble_symbols':len(PREAMBLE)}


def read_header(samples,gain,variance):
    llr=4*(samples/gain).real/max(variance,1e-9)
    bits=codec.soft_viterbi(llr)
    if len(bits)!=144 or not np.array_equal(codec.crc(bits[:-16],16),bits[-16:]): return None
    magic,version,mcs,length,sequence,offset,total=struct.unpack('>HBBHHII',np.packbits(bits[:-16]).tobytes())
    if magic!=0x4f43 or version!=1 or mcs not in MCS or not 0<length<=2048 or not length<=total<=1048576 or offset+length>total: return None
    return {'version':version,'mcs':mcs,'mcs_name':MCS_NAMES[mcs],'payload_bits':length,
            'sequence':sequence,'offset_bits':offset,'total_bits':total}


def receive_stream(wave,q=None,state=None,final=True):
    """Decode a recording/chunks. Return (reassembled_bits, details, mutable_state).

    Only the correlation threshold is configured. Payload length and MCS are
    recovered from transmitted headers. Zero-filled holes have explicit
    coverage intervals; received_base64 contains accepted packets in order.
    """
    q=q or {}; threshold=float(q.get('threshold',.62))
    if state is None: state={'buffer':np.empty(0,complex),'base':0,'accepted':{},'frames':[],'total_bits':0,'header_failures':0}
    data=np.r_[state['buffer'],np.asarray(wave,complex)]; n=len(PREAMBLE); scan=0; consumed=0
    if len(data)>=n:
        correlation=np.correlate(data,PREAMBLE,mode='valid')
        power=np.convolve(abs(data)**2,np.ones(n),mode='valid')
        metric=abs(correlation)/np.sqrt(np.maximum(n*power,1e-20))
        candidates=np.flatnonzero(metric>=threshold)
        for start in candidates:
            start=int(start)
            if start<scan: continue
            head_end=start+n+HEADER_SYMBOLS
            if head_end>len(data):
                if not final: consumed=start; break
                scan=start+1; continue
            gain=correlation[start]/n
            variance=float(np.mean(abs(data[start:start+n]/gain-PREAMBLE)**2))
            header=read_header(data[start+n:head_end],gain,variance)
            if header is None:
                state['header_failures']+=1; scan=start+1; continue
            end=head_end+payload_symbols(header['payload_bits'],header['mcs'])
            if end>len(data) and not final: consumed=start; break
            state['total_bits']=max(state['total_bits'],header['total_bits'])
            event={**header,'start_sample':state['base']+start,'end_sample':state['base']+end,
                   'correlation':float(metric[start]),'noise_variance':variance,'header_crc_pass':True,
                   'gain_i':float(gain.real),'gain_q':float(gain.imag),'payload_crc_pass':False,'truncated':end>len(data)}
            if end<=len(data):
                scheme,coded=MCS[header['mcs']]; llr=dsp.soft_demod(data[head_end:end]/gain,scheme,max(variance,1e-9))
                bit_count=header['payload_bits']+16
                decoded=codec.soft_viterbi(llr[:2*(bit_count+2)]) if coded else (llr[:bit_count]<0).astype(np.uint8)
                passed=bool(np.array_equal(codec.crc(decoded[:-16],16),decoded[-16:])); event['payload_crc_pass']=passed
                if passed:
                    key=(header['total_bits'],header['offset_bits']); event['duplicate']=key in state['accepted']
                    state['accepted'].setdefault(key,decoded[:-16].copy()); scan=end
                else: scan=start+1
            else: scan=start+1
            state['frames'].append(event)
        else: consumed=max(scan,len(data)-n+1)
    elif final: consumed=len(data)
    if final: consumed=len(data)
    state['buffer']=data[consumed:].copy(); state['base']+=consumed
    total=state['total_bits']; restored=np.zeros(total,np.uint8); coverage=np.zeros(total,bool); accepted=[]; intervals=[]
    for (business_size,offset),bits in sorted(state['accepted'].items()):
        if business_size!=total: continue
        restored[offset:offset+len(bits)]=bits; coverage[offset:offset+len(bits)]=True; accepted.append(bits); intervals.append([offset,offset+len(bits)])
    delivered=np.concatenate(accepted) if accepted else np.empty(0,np.uint8)
    details={'kind':'self_frame_rx','frames':list(state['frames']),'detected':bool(state['frames']),
             'total_bits':total,'received_bits':int(coverage.sum()),'complete_payload':bool(total and coverage.all()),
             'accepted_packets':len(accepted),'failed_packets':sum(not r['payload_crc_pass'] for r in state['frames']),
             'header_failures':state['header_failures'],'coverage':intervals,'pending_samples':len(state['buffer']),
             'received_base64':base64.b64encode(np.packbits(delivered)).decode(),
             'reassembled_base64':base64.b64encode(np.packbits(restored)).decode(),
             'received_bit_count':len(delivered),'decoded_header_fields':['version','mcs','payload_bits','sequence','offset_bits','total_bits']}
    return restored,details,state


def run_stage(kind,data,q,state,rng,fs):
    x=np.asarray(data,complex)
    if kind=='tx_self_frame':
        if state.get('scheme','bpsk')!='bpsk': raise ValueError('自描述物理帧的外层比特载体选择 BPSK，载荷调制在物理帧积木内选择。')
        y,details=encode_stream((x.real<0).astype(np.uint8),q)
    elif kind=='frame_stream_channel':
        start=q['cut_start']; stop=min(len(x),start+q['cut_samples'])
        y=np.r_[x[:start],x[stop:]] if start<len(x) else x.copy()
        y=np.r_[np.zeros(q['leading'],complex),y]*q['gain']*np.exp(1j*np.deg2rad(q['phase_deg']))
        variance=q['gain']**2*10**(-q['snr_db']/10)
        y+=math.sqrt(variance/2)*(rng.normal(size=len(y))+1j*rng.normal(size=len(y)))
        details={'kind':'frame_stream_channel','noise_variance':variance,'leading_samples':q['leading'],
                 'removed_samples':max(0,stop-start),'output_samples':len(y)}
    else:
        bits,details,_=receive_stream(x,q); y=(1-2*bits.astype(float)).astype(complex)
    return y,details,fs
