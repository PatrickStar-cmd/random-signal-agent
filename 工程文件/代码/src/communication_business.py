"""Business payloads and inspectable source/channel coding algorithms."""
import base64
import hashlib
import heapq
import io
import itertools
import math
import wave
from functools import lru_cache

import numpy as np
from PIL import Image

SOURCES = {'audio_source', 'image_source', 'file_source', 'discrete_source'}
PAIRS = {'huffman_decode': 'huffman_encode', 'adpcm_decode': 'adpcm_encode',
         'bch_decode': 'bch_encode', 'rs_decode': 'rs_encode', 'packet_decode':'packet_encode'}
KINDS = SOURCES | set(PAIRS) | set(PAIRS.values())


def register(block, number, field, blocks):
    payload = lambda: field('上传数据 / Base64（builtin 使用示例）', 'builtin', max_length=50000)
    block('audio_source', '音频信源 🎙️', 'source', '单声道 PCM16 音频；使用工程采样率与样本数，可上传或播放内置双音。', data=payload(), filename=field('文件名', 'ocean.wav', max_length=160))
    block('image_source', '灰度图像信源 🖼️', 'source', '每像素 8 位，按行传送灰度图；内置海洋波纹图案。', data=payload(), filename=field('文件名', 'ocean.png', max_length=160), width=number('宽度 / 像素', 16, 1, 64, True), height=number('高度 / 像素', 16, 1, 64, True))
    block('file_source', '文件信源 📄', 'source', '传输文件字节，信宿重建文件并比较 SHA256。', data=payload(), filename=field('文件名', 'ocean.txt', max_length=160))
    block('discrete_source', '离散概率信源 🎲', 'source', '按指定概率生成字节符号，每个符号以 8 位表示。', count=number('符号数', 512, 1, 4096, True), symbols=field('符号值 / 0–255', '0,1,2,3', max_length=1200), probabilities=field('对应概率', '0.7,0.15,0.1,0.05', max_length=4000))
    for prefix, label, description in [('huffman', 'Huffman', '字节符号的规范 Huffman 码；码长表和原始长度随帧传输。'), ('bch', 'BCH (15,7)', 'GF(16) 二元 BCH，生成多项式 x⁸+x⁷+x⁶+x⁴+1，每码字纠正 2 位错误。'), ('rs', 'Reed–Solomon (255,223)', 'GF(256) 系统码，32 个校验字节，每码字纠正 16 个错误字节；末组补零。')]:
        block(prefix+'_encode', label+' 编码', 'tx_converter', description)
        block(prefix+'_decode', label+' 译码', 'rx_converter', description)
    for suffix, cat, label in [('encode','tx_converter','编码'),('decode','rx_converter','译码')]:
        block('adpcm_'+suffix, 'IMA ADPCM '+label, cat, '4 位自适应差分量化；标准 89 级步长表，预测器与步长索引逐样本更新。', full_scale=number('量程 ±', 1, .1, 32))
        block('packet_'+suffix, '数据分包 📦' if suffix=='encode' else '数据重组 📦', cat, '固定包槽承载序号、字节长度、数据与 CRC16；接收侧校验并重组，丢失包显示为空数据。', packet_bytes=number('每包有效字节',32,1,256,True))


def presets(preset):
    result = {}
    def add(key,label,kinds,changes=None,settings=None):
        p=preset(kinds,changes); p.update(settings or {}); result[key]={'label':label,'program':p}
    add('business_audio','业务 · 音频 / ADPCM',['audio_source','adpcm_encode','mod_qpsk','awgn','demod_qpsk','adpcm_decode','sink'],{3:{'esn0_db':30}}, {'sample_rate':8000,'sample_count':1024})
    add('business_image','业务 · 图像 / RS 纠错',['image_source','rs_encode','mod_qpsk','awgn','demod_qpsk','rs_decode','sink'],{3:{'esn0_db':14}})
    add('business_file','业务 · 文件 / CRC / BCH',['file_source','crc_append','bch_encode','mod_bpsk','awgn','demod_bpsk','bch_decode','crc_check','sink'],{4:{'esn0_db':12}})
    add('business_huffman','信源编码 · 概率 / Huffman 编码树',['discrete_source','huffman_encode','mod_qpsk','ideal','demod_qpsk','huffman_decode','sink'])
    add('business_bch','纠错 · BCH 双错纠正',['random_bits','bch_encode','mod_bpsk','awgn','demod_bpsk','bch_decode','sink'],{3:{'esn0_db':5}})
    add('business_rs_burst','纠错 · RS / 交织 / 突发噪声',['image_source','rs_encode','interleave','mod_bpsk','burst_noise','demod_bpsk','deinterleave','rs_decode','sink'],{4:{'good_to_bad':.002,'bad_to_good':.2,'good_snr':30,'bad_snr':0}})
    add('business_packets','业务 · 文件分包 / BCH / 重组',['file_source','packet_encode','bch_encode','mod_qpsk','awgn','demod_qpsk','bch_decode','packet_decode','sink'],{4:{'esn0_db':14}})
    return result


def byte_bits(data):
    return np.unpackbits(np.frombuffer(bytes(data),dtype=np.uint8))


def raw_payload(q):
    try: return base64.b64decode(q['data'], validate=True)
    except (ValueError,base64.binascii.Error) as exc: raise ValueError('上传数据须为有效 Base64。') from exc


def generate(kind, q, p, rng):
    if kind=='audio_source':
        if q['data']=='builtin':
            t=np.arange(p['sample_count'])/p['sample_rate']; f=min(440,p['sample_rate']/12)
            return .55*np.sin(2*np.pi*f*t)+.22*np.sin(2*np.pi*f*1.5*t)
        raw=raw_payload(q)
        if len(raw)%2 or len(raw)//2!=p['sample_count']: raise ValueError('音频 PCM16 样本数须与工程样本数一致。')
        return np.frombuffer(raw,dtype='<i2').astype(float)/32768
    if kind=='image_source':
        if q['data']=='builtin':
            y,x=np.indices((q['height'],q['width'])); values=np.rint(128+85*np.sin(x*.45+y*.6)+35*np.cos(x*.7-y*.3)).clip(0,255).astype(np.uint8)
            return byte_bits(values.tobytes())
        raw=raw_payload(q)
        if len(raw)!=q['width']*q['height']: raise ValueError('灰度数据长度须等于图像宽度乘高度。')
        return byte_bits(raw)
    if kind=='file_source':
        raw='海洋通信实验室：每一个字节都连接一段旅程。\nOcean communication laboratory.\n'.encode() if q['data']=='builtin' else raw_payload(q)
        if not raw: raise ValueError('文件需要至少一个字节。')
        return byte_bits(raw)
    if kind=='discrete_source':
        try: values=np.array([int(v.strip()) for v in q['symbols'].split(',')]); probs=np.array([float(v.strip()) for v in q['probabilities'].split(',')])
        except ValueError as exc: raise ValueError('请按逗号分隔填写符号和概率。') from exc
        if not 1<=len(values)<=256 or len(values)!=len(probs) or len(set(values.tolist()))!=len(values) or np.any((values<0)|(values>255)) or not np.isfinite(probs).all() or np.any(probs<=0) or not np.isclose(probs.sum(),1): raise ValueError('符号须互异且在 0–255，概率须为正且总和为 1。')
        return byte_bits(rng.choice(values,size=q['count'],p=probs).astype(np.uint8).tobytes())
    raise ValueError('未知业务信源。')


def source_count(kind,q,p):
    return len(generate(kind,q,p,np.random.default_rng(0)))


def media_result(p, source, received):
    sources=[b for b in p['blocks'] if b['kind'] in SOURCES]
    if not sources or sources[0]['kind']=='discrete_source': return None
    b=sources[0];q=b['params']; kind=b['kind'].split('_')[0]
    def b64(raw): return base64.b64encode(raw).decode('ascii')
    if kind=='audio':
        def wav(x):
            buffer=io.BytesIO()
            with wave.open(buffer,'wb') as stream:
                stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(round(p['sample_rate']));stream.writeframes(np.rint(np.clip(x,-1,32767/32768)*32768).astype('<i2').tobytes())
            return buffer.getvalue()
        mse=float(np.mean((source-received)**2)); power=float(np.mean(source**2))
        return {'kind':kind,'mime':'audio/wav','filename':q['filename'],'sample_rate':p['sample_rate'],'original_base64':b64(wav(source)),'received_base64':b64(wav(received)), 'metrics':{'rmse':math.sqrt(mse),'snr_db':float(10*np.log10(power/mse)) if mse and power else None,'duration_seconds':len(source)/p['sample_rate']}}
    original=np.packbits(source).tobytes(); output=np.packbits(received).tobytes()
    metrics={'bytes':len(original),'identical':original==output,'original_sha256':hashlib.sha256(original).hexdigest(),'received_sha256':hashlib.sha256(output).hexdigest()}
    result={'kind':kind,'mime':'application/octet-stream','filename':q['filename'],'original_base64':b64(original),'received_base64':b64(output),'metrics':metrics}
    if kind=='image':
        def png(raw):
            buffer=io.BytesIO();Image.frombytes('L',(q['width'],q['height']),raw).save(buffer,format='PNG');return buffer.getvalue()
        mse=float(np.mean((np.frombuffer(original,dtype=np.uint8).astype(float)-np.frombuffer(output,dtype=np.uint8))**2))
        result.update(mime='image/png',width=q['width'],height=q['height'],original_base64=b64(png(original)),received_base64=b64(png(output)))
        metrics.update(mse=mse,psnr_db=float(10*np.log10(255**2/mse)) if mse else None)
    return result


def huffman_dictionary(values):
    counts=np.bincount(values,minlength=256); heap=[]; serial=itertools.count(); nodes=[]
    for symbol in np.flatnonzero(counts):
        node={'id':len(nodes),'symbol':int(symbol),'weight':int(counts[symbol])};nodes.append(node);heapq.heappush(heap,(int(counts[symbol]),next(serial),node['id']))
    while len(heap)>1:
        a=heapq.heappop(heap);b=heapq.heappop(heap);node={'id':len(nodes),'left':a[2],'right':b[2],'weight':a[0]+b[0]};nodes.append(node);heapq.heappush(heap,(node['weight'],next(serial),node['id']))
    lengths={}
    def walk(index,depth):
        node=nodes[index]
        if 'symbol' in node: lengths[node['symbol']]=max(1,depth)
        else: walk(node['left'],depth+1);walk(node['right'],depth+1)
    walk(heap[0][2],0)
    return canonical_codes(lengths),nodes,counts


def canonical_codes(lengths):
    code=0;previous=0;codes={}
    for symbol,length in sorted(lengths.items(),key=lambda item:(item[1],item[0])):
        code <<= length-previous
        if length<1 or length>255 or code >= (1<<length): raise ValueError('Huffman 码长表无效。')
        codes[symbol]=format(code,f'0{length}b');code+=1;previous=length
    return codes


def huffman_encode(bits, trace=False):
    values=np.packbits(bits);codes,nodes,counts=huffman_dictionary(values)
    header=bytearray(b'HF')+len(bits).to_bytes(4,'big')+len(codes).to_bytes(2,'big')
    for symbol,code in sorted(codes.items()): header.extend((symbol,len(code)))
    payload=''.join(codes[int(v)] for v in values)
    out=np.r_[byte_bits(header),np.fromiter((int(v) for v in payload),dtype=np.uint8)]
    probabilities=counts[counts>0]/len(values)
    tree=[{'id':0,'weight':len(values)}]
    for symbol,code in codes.items():
        current=0
        for bit in code:
            branch='left' if bit=='0' else 'right'
            if branch not in tree[current]: tree[current][branch]=len(tree);tree.append({'id':len(tree),'weight':0})
            current=tree[current][branch];tree[current]['weight']+=int(counts[symbol])
        tree[current]['symbol']=symbol
    info={'kind':'huffman','nodes':tree,'tree_root':0,'merge_nodes':nodes,'codes':[{'symbol':s,'code':code,'count':int(counts[s])} for s,code in codes.items()], 'entropy':float(-np.sum(probabilities*np.log2(probabilities))), 'average_length':len(payload)/len(values),'payload_bits':len(payload),'header_bits':len(header)*8,'input_bits':len(bits),'compression_ratio':len(bits)/len(out)}
    return (out,info) if trace else out


def huffman_decode(bits):
    raw=np.packbits(bits).tobytes()
    if len(raw)<8 or raw[:2]!=b'HF': raise ValueError('Huffman 帧头校验失败，请提高信噪比或增加信道编码。')
    size=int.from_bytes(raw[2:6],'big');count=int.from_bytes(raw[6:8],'big');offset=8+2*count
    if not 1<=size<=262144 or not 1<=count<=256 or offset>len(raw): raise ValueError('Huffman 帧长度无效。')
    lengths=dict(zip(raw[8:offset:2],raw[9:offset:2]))
    if len(lengths)!=count: raise ValueError('Huffman 码表包含重复符号。')
    codes=canonical_codes(lengths);lookup={code:symbol for symbol,code in codes.items()};word='';output=[]
    for bit in bits[offset*8:]:
        word+=str(int(bit))
        if word in lookup:
            output.append(lookup[word]);word=''
            if len(output)==math.ceil(size/8): break
        elif len(word)>max(lengths.values()): raise ValueError('Huffman 数据校验失败。')
    if len(output)!=math.ceil(size/8): raise ValueError('Huffman 数据长度不足。')
    return byte_bits(output)[:size]


IMA_STEPS=np.array([7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767])
IMA_INDEX=(-1,-1,-1,-1,2,4,6,8)


def adpcm(data,scale,inverse=False):
    from src.communication_codecs import bits_to_words,words_to_bits
    values=bits_to_words(data,4) if inverse else np.rint(np.clip(data/scale,-1,32767/32768)*32768).astype(int)
    predictor=0;index=0;output=[];trace=[]
    for value in values:
        step=int(IMA_STEPS[index]);code=int(value) if inverse else (8 if value<predictor else 0)
        if not inverse:
            remaining=abs(int(value)-predictor)
            for mask,threshold in ((4,step),(2,step>>1),(1,step>>2)):
                if remaining>=threshold: code|=mask;remaining-=threshold
        delta=(step>>3)+(step if code&4 else 0)+(step>>1 if code&2 else 0)+(step>>2 if code&1 else 0)
        predictor=int(np.clip(predictor+(-delta if code&8 else delta),-32768,32767));index=int(np.clip(index+IMA_INDEX[code&7],0,88))
        output.append(predictor/32768*scale if inverse else code)
        if len(trace)<128: trace.append({'predictor':predictor/32768*scale,'step':step/32768*scale,'index':index,'code':code})
    return (np.array(output) if inverse else words_to_bits(output,4)),{'kind':'adpcm','samples':trace}


def binary_remainder(value, generator=0x1d1):
    while value.bit_length()>=generator.bit_length(): value ^= generator << (value.bit_length()-generator.bit_length())
    return value


@lru_cache(maxsize=1)
def bch_error_table():
    table={0:0}
    for width in (1,2):
        for positions in itertools.combinations(range(15),width):
            error=sum(1<<i for i in positions);table[binary_remainder(error)]=error
    return table


def bch_encode(bits):
    from src.communication_codecs import bits_to_words,words_to_bits
    values=bits_to_words(np.pad(bits,(0,-len(bits)%7)),7)
    return words_to_bits([(int(v)<<8)^binary_remainder(int(v)<<8) for v in values],15)


def bch_decode(bits):
    from src.communication_codecs import bits_to_words,words_to_bits
    values=bits_to_words(bits,15);out=[];corrected=failed=0;trace=[]
    for value in values:
        value=int(value);syndrome=binary_remainder(value);error=bch_error_table().get(syndrome,0)
        failed+=int(syndrome not in bch_error_table());corrected+=error.bit_count();out.append((value^error)>>8)
        if len(trace)<32: trace.append({'syndrome':syndrome,'error_positions':[14-i for i in range(15) if error>>i&1]})
    return words_to_bits(out,7),{'corrected_bits':corrected,'failed_codewords':failed,'syndromes':trace}


# GF(256), primitive polynomial x^8+x^4+x^3+x^2+1, alpha=2.
GF_EXP=[0]*510;GF_LOG=[0]*256
_value=1
for _i in range(255):
    GF_EXP[_i]=_value;GF_LOG[_value]=_i;_value<<=1
    if _value&256: _value^=0x11d
GF_EXP[255:]=GF_EXP[:255]


def gf_mul(a,b): return GF_EXP[GF_LOG[a]+GF_LOG[b]] if a and b else 0
def gf_div(a,b):
    if not b: raise ValueError('RS 有限域除数为零。')
    return GF_EXP[(GF_LOG[a]-GF_LOG[b])%255] if a else 0
def gf_poly(values,x):
    result=0
    for value in values: result=gf_mul(result,x)^int(value)
    return result


@lru_cache(maxsize=1)
def rs_generator():
    poly=[1]
    for i in range(32):
        next_poly=[0]*(len(poly)+1)
        for j,value in enumerate(poly): next_poly[j]^=value;next_poly[j+1]^=gf_mul(value,GF_EXP[i])
        poly=next_poly
    return poly


def rs_encode(bits):
    values=np.packbits(bits);values=np.pad(values,(0,-len(values)%223)).reshape(-1,223);output=[];generator=rs_generator()
    for row in values:
        word=row.tolist()+[0]*32
        for i in range(223):
            coefficient=word[i]
            if coefficient:
                for j in range(1,33): word[i+j]^=gf_mul(generator[j],coefficient)
        output.extend(row.tolist()+word[-32:])
    return byte_bits(output)


def rs_correct(word):
    syndrome=[gf_poly(word,GF_EXP[i]) for i in range(32)]
    if not any(syndrome): return word,0,False
    # Berlekamp–Massey: ascending coefficients of the error locator.
    locator=[1]+[0]*32;previous=locator.copy();degree=0;gap=1;last=1
    for n in range(32):
        discrepancy=syndrome[n]
        for i in range(1,degree+1): discrepancy ^= gf_mul(locator[i],syndrome[n-i])
        if discrepancy==0: gap+=1;continue
        saved=locator.copy();factor=gf_div(discrepancy,last)
        for i in range(33-gap): locator[i+gap]^=gf_mul(factor,previous[i])
        if 2*degree<=n: degree=n+1-degree;previous=saved;last=discrepancy;gap=1
        else: gap+=1
    positions=[j for j in range(len(word)) if gf_poly(locator[:degree+1][::-1],GF_EXP[-(len(word)-1-j)%255])==0]
    if not 1<=degree<=16 or len(positions)!=degree: return word,0,True
    # Solve S_i=sum(e_j*alpha^(i*position_j)) in GF(256).
    matrix=[[GF_EXP[(i*(len(word)-1-j))%255] for j in positions]+[syndrome[i]] for i in range(degree)]
    for col in range(degree):
        pivot=next((r for r in range(col,degree) if matrix[r][col]),None)
        if pivot is None: return word,0,True
        matrix[col],matrix[pivot]=matrix[pivot],matrix[col];factor=matrix[col][col];matrix[col]=[gf_div(v,factor) for v in matrix[col]]
        for r in range(degree):
            if r!=col and matrix[r][col]:
                factor=matrix[r][col];matrix[r]=[a^gf_mul(factor,b) for a,b in zip(matrix[r],matrix[col])]
    corrected=word.copy()
    for j,row in zip(positions,matrix): corrected[j]^=row[-1]
    if any(gf_poly(corrected,GF_EXP[i]) for i in range(32)): return word,0,True
    return corrected,degree,False


def rs_decode(bits):
    rows=np.packbits(bits).reshape(-1,255);output=[];corrected=failed=0
    for row in rows:
        word,n,error=rs_correct(row.tolist());output.extend(word[:223]);corrected+=n;failed+=int(error)
    return byte_bits(output),{'corrected_bytes':corrected,'failed_codewords':failed}


def encoded_count(kind,count,q):
    if kind=='packet_encode': return math.ceil(count/8)*8+math.ceil(count/(q['packet_bytes']*8))*48
    if kind=='adpcm_encode': return count*4
    if kind=='bch_encode': return math.ceil(count/7)*15
    if kind=='rs_encode': return math.ceil(count/(223*8))*255*8
    raise ValueError('Huffman 长度需要实际编码数据。')


def encode(kind,data,q):
    if kind=='packet_encode':
        from src.communication_protocols import packetize
        return np.concatenate([p['wire'] for p in packetize(data,q['packet_bytes'])])
    if kind=='huffman_encode': return huffman_encode(data)
    if kind=='adpcm_encode': return adpcm(data,q['full_scale'])[0]
    if kind=='bch_encode': return bch_encode(data)
    if kind=='rs_encode': return rs_encode(data)
    raise ValueError('未知业务编码器。')


def preview_encode(kind,data,q):
    """Evaluate the deterministic transmitter prefix for variable-length Build."""
    from src import communication_codecs as codec, communications as c
    if kind in set(codec.PAIRS.values())-{'conv_encode'}: return codec.encode(kind,data,q)
    if kind=='pcm_encode': return codec.words_to_bits(np.rint((np.clip(data,-q['full_scale'],q['full_scale'])+q['full_scale'])/(2*q['full_scale'])*(2**q['bits']-1)),q['bits'])
    if kind=='repeat_encode': return np.repeat(data,q['factor'])
    if kind=='hamming_encode': return c.hamming_encode(data)
    if kind=='conv_encode': return c.conv_encode(data)
    if kind=='interleave': return np.pad(data,(0,-len(data)%q['columns'])).reshape(-1,q['columns']).T.ravel()
    return data


def decode(kind,data,q):
    if kind=='packet_decode':
        from src.communication_protocols import unpack_packet
        width=q['packet_bytes']*8+48;output=[];packets=[];lost=0
        for sequence,start in enumerate(range(0,len(data),width)):
            wire=data[start:start+width];parsed=unpack_packet(wire);size=len(wire)-48
            if size<=0 or size%8: raise ValueError('分包接收长度无效。')
            valid=parsed is not None and parsed[0]==sequence
            output.append(parsed[1] if valid else np.zeros(size,dtype=np.uint8));lost+=int(not valid)
            packets.append({'sequence':sequence,'bytes':size//8,'crc_pass':valid})
        return np.concatenate(output),{'packet_count':len(packets),'packet_loss':lost,'crc_pass':lost==0,'packets':packets}
    if kind=='huffman_decode': return huffman_decode(data),{}
    if kind=='adpcm_decode': return adpcm(data,q['full_scale'],True)
    if kind=='bch_decode': return bch_decode(data)
    if kind=='rs_decode': return rs_decode(data)
    raise ValueError('未知业务译码器。')
