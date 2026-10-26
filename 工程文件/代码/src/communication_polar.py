"""Polar F^(tensor n), BEC reliability construction and CRC-aided SCL.

LLR convention is log P(0)/P(1). K includes a per-codeword CRC-16. Frozen
indices are computed from the public design erasure probability, independently
of payload and channel realization. Natural-order recursion matches transform.
"""
from functools import lru_cache
import math
import time
import numpy as np

PAIRS = {'polar_decode': 'polar_encode'}


def register(block, number, field, blocks):
    common = dict(n=field('母码长度 N', 128, 'select', choices=[64, 128, 256]),
                  rate=field('信息位与 CRC 占比 K/N', 2, 'select', choices=[1, 2, 3],
                             choice_labels={1:'1/4', 2:'1/2', 3:'3/4'}),
                  design=number('BEC 构造设计参数', .5, .05, .95))
    block('polar_encode', 'Polar 编码', 'tx_converter',
          '每码字添加 CRC-16，以 BEC 可靠度选择信息位并执行蝶形极化变换。', **common)
    block('polar_decode', 'Polar SC / CRC-SCL 译码', 'rx_converter',
          '按 LLR 递归计算路径，SC 保留一条路径，CRC-SCL 从候选列表中选择通过 CRC 的路径。',
          **common, method=field('译码方式', 1, 'select', choices=[0, 1], choice_labels={0:'SC', 1:'CRC-SCL'}),
          list_size=field('列表宽度 L', 8, 'select', choices=[2, 4, 8, 16]))


def presets(preset):
    kinds=['random_bits','polar_encode','mod_bpsk','awgn','soft_bpsk','polar_decode','sink']
    return {'polar_sc':{'label':'现代编码 · Polar SC', 'program':preset(kinds,{3:{'esn0_db':5},5:{'method':0}})},
            'polar_scl':{'label':'现代编码 · Polar CRC-SCL', 'program':preset(kinds,{3:{'esn0_db':5}})}}


def dimensions(q):
    n=int(q['n']); k=n*int(q['rate'])//4
    if n not in (64,128,256) or q['rate'] not in (1,2,3) or k<=16:
        raise ValueError('Polar 信息位置数 K 需要大于 CRC 的 16 位；N=64 时选择 1/2 或 3/4。')
    return n,k,k-16


@lru_cache(maxsize=24)
def information(n,k,design):
    z=np.array([design],float)
    while len(z)<n: z=np.column_stack((2*z-z*z,z*z)).ravel()
    return np.sort(np.argsort(z,kind='stable')[:k])


def transform(bits):
    x=np.asarray(bits,np.uint8).copy(); step=1
    while step<len(x):
        for start in range(0,len(x),2*step): x[start:start+step]^=x[start+step:start+2*step]
        step*=2
    return x


def crc16(bits):
    value=65535
    for bit in bits:
        feedback=((value>>15)&1)^int(bit); value=(value<<1)&65535
        if feedback: value^=0x1021
    return ((value>>np.arange(15,-1,-1))&1).astype(np.uint8)


def encoded_count(kind,count,q):
    n,_,payload=dimensions(q); return math.ceil(count/payload)*n


def encode(kind,data,q):
    n,k,payload=dimensions(q); locations=information(n,k,float(q['design']))
    words=np.pad(np.asarray(data,np.uint8),(0,-len(data)%payload)).reshape(-1,payload); output=[]
    for word in words:
        u=np.zeros(n,np.uint8); u[locations]=np.r_[word,crc16(word)]; output.append(transform(u))
    return np.concatenate(output)


def _bit_llr(alpha, prefix, index):
    if len(alpha)==1: return float(alpha[0])
    half=len(alpha)//2; a,b=alpha[:half],alpha[half:]
    if index<half:
        # Stable exact box-plus (not a hard-sign approximation).
        values=np.logaddexp(0,a+b)-np.logaddexp(a,b)
        return _bit_llr(values,prefix,index)
    partial=transform(prefix[:half])
    return _bit_llr(b+(1-2*partial.astype(float))*a,prefix[half:],index-half)


def decode_word(llr,locations,list_size):
    info=set(map(int,locations)); paths=[(0.,np.empty(0,np.uint8))]; history=[]
    for index in range(len(llr)):
        candidates=[]
        for metric,prefix in paths:
            value=_bit_llr(llr,prefix,index)
            for bit in ((0,1) if index in info else (0,)):
                cost=metric+float(np.logaddexp(0,-(1-2*bit)*value))
                candidates.append((cost,np.r_[prefix,np.uint8(bit)]))
        paths=sorted(candidates,key=lambda v:v[0])[:list_size]
        if index<64: history.append({'bit':index,'frozen':index not in info,'path_metrics':[v[0] for v in paths]})
    candidates=[]
    for cost,path in paths:
        bits=path[locations]; passed=bool(np.array_equal(crc16(bits[:-16]),bits[-16:])); candidates.append((passed,cost,bits[:-16]))
    selected=next((v for v in candidates if v[0]),candidates[0])
    return selected[2],{'crc_pass':selected[0],'path_metric':selected[1],'survivors':len(paths),'history':history}


def decode(kind,data,q):
    started=time.perf_counter(); n,k,payload=dimensions(q); llr=np.asarray(data,float)
    if len(llr)%n: raise ValueError('Polar 软信息长度需要为母码长度的整数倍。')
    locations=information(n,k,float(q['design'])); size=1 if q['method']==0 else q['list_size']; output=[]; rows=[]
    for word in np.clip(llr,-120,120).reshape(-1,n):
        decoded,detail=decode_word(word,locations,size); output.append(decoded); rows.append(detail)
    return np.concatenate(output),{'crc_pass':all(v['crc_pass'] for v in rows),'failed_codewords':sum(not v['crc_pass'] for v in rows),
        'codewords':len(rows),'n':n,'k':k,'payload_bits':payload,'list_size':size,'seconds':time.perf_counter()-started,
        'information_positions':locations.tolist(),'learning':{'kind':'polar','history':rows[0]['history'],
        'crc_pass':[v['crc_pass'] for v in rows],'path_metrics':[v['path_metric'] for v in rows]}}
