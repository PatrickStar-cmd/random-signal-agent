"""Parallel concatenated (13,15) octal RSC codes and exact log-domain BCJR.

LLRs are log P(0)/P(1). Each constituent is independently terminated with
three tail inputs. The wire contains K systematic/parity1/parity2 triples,
then the two six-bit systematic/parity tail sections.
"""
from functools import lru_cache
import math
import numpy as np

PAIRS = {'turbo_decode': 'turbo_encode'}


def register(block, number, field, blocks):
    common = dict(block_size=field('每码字信息位 K', 128, 'select', choices=[32,64,128,256,512]),
                  interleaver_seed=number('公开交织种子', 17, 0, 65535, True))
    block('turbo_encode', 'Turbo 并行级联编码', 'tx_converter',
          '两个 (13,15)₈ 递归系统卷积编码器由公开交织器连接，各自添加三位终止输入。', **common)
    block('turbo_decode', 'Turbo BCJR 迭代译码', 'rx_converter',
          '两个软输入软输出 BCJR 译码器交换外信息，显示各轮先验、外信息与后验。', **common,
          iterations=number('迭代轮数', 6, 1, 12, True),
          algorithm=field('路径求和', 0, 'select', choices=[0,1], choice_labels={0:'Log-MAP',1:'Max-log-MAP'}))


def presets(preset):
    kinds=['random_bits','turbo_encode','mod_bpsk','awgn','soft_bpsk','turbo_decode','sink']
    return {'turbo_logmap': {'label':'迭代编码 · Turbo Log-MAP', 'program':preset(kinds,{3:{'esn0_db':0}})},
            'turbo_maxlog': {'label':'迭代编码 · Turbo Max-log-MAP', 'program':preset(kinds,{3:{'esn0_db':0},5:{'algorithm':1}})}}


@lru_cache(maxsize=32)
def interleaver(size, seed):
    return np.random.default_rng(seed).permutation(size)


def trellis():
    states=np.arange(8); a=(states>>2)&1; b=(states>>1)&1; c=states&1
    inputs=np.array([0,1]); feedback=inputs[None,:]^b[:,None]^c[:,None]
    following=(feedback<<2)|(a[:,None]<<1)|b[:,None]
    parity=feedback^a[:,None]^c[:,None]
    return following,parity


NEXT,PARITY=trellis()


def rsc(bits):
    state=0; systematic=[]; parity=[]
    for bit in np.asarray(bits,np.uint8):
        systematic.append(int(bit)); parity.append(int(PARITY[state,bit])); state=int(NEXT[state,bit])
    for _ in range(3):
        bit=((state>>1)&1)^(state&1)
        systematic.append(bit); parity.append(int(PARITY[state,bit])); state=int(NEXT[state,bit])
    assert state==0
    return np.asarray(systematic,np.uint8),np.asarray(parity,np.uint8)


def encoded_count(kind,count,q):
    k=int(q['block_size']); return math.ceil(count/k)*(3*k+12)


def encode(kind,data,q):
    k=int(q['block_size']); permutation=interleaver(k,int(q['interleaver_seed']))
    words=np.pad(np.asarray(data,np.uint8),(0,-len(data)%k)).reshape(-1,k); output=[]
    for word in words:
        s1,p1=rsc(word); s2,p2=rsc(word[permutation])
        output.append(np.r_[np.column_stack((word,p1[:k],p2[:k])).ravel(),
                            np.column_stack((s1[k:],p1[k:])).ravel(),np.column_stack((s2[k:],p2[k:])).ravel()])
    return np.concatenate(output)


def bcjr(systematic,parity,prior,algorithm=0):
    """Known zero initial/final states; normalized forward/backward recursion."""
    systematic=np.asarray(systematic,float); parity=np.asarray(parity,float); prior=np.asarray(prior,float)
    n=len(systematic); alpha=np.full((n+1,8),-np.inf); beta=np.full((n+1,8),-np.inf)
    alpha[0,0]=0.; beta[-1,0]=0.
    gamma=.5*((systematic+prior)[:,None,None]*(1-2*np.array([0.,1.]))[None,None,:]
               +parity[:,None,None]*(1-2*PARITY.astype(float))[None,:,:])
    reduce=np.max if algorithm else np.logaddexp.reduce
    # Every state has two predecessors. Indexing these once keeps each step small.
    predecessor=np.empty((8,2),int); input_bit=np.empty((8,2),int)
    for dest in range(8): predecessor[dest],input_bit[dest]=np.where(NEXT==dest)
    for t in range(n):
        values=alpha[t,predecessor]+gamma[t,predecessor,input_bit]
        alpha[t+1]=reduce(values,axis=1); alpha[t+1]-=np.max(alpha[t+1])
    for t in range(n-1,-1,-1):
        beta[t]=reduce(gamma[t]+beta[t+1,NEXT],axis=1); beta[t]-=np.max(beta[t])
    paths=alpha[:-1,:,None]+gamma+beta[1:,NEXT]
    return reduce(paths[:,:,0],axis=1)-reduce(paths[:,:,1],axis=1)


def decode_word(wire,q):
    k=int(q['block_size']); permutation=interleaver(k,int(q['interleaver_seed'])); inverse=np.argsort(permutation)
    triples=wire[:3*k].reshape(k,3); tail1=wire[3*k:3*k+6].reshape(3,2); tail2=wire[3*k+6:].reshape(3,2)
    s1=np.r_[triples[:,0],tail1[:,0]]; p1=np.r_[triples[:,1],tail1[:,1]]
    s2=np.r_[triples[permutation,0],tail2[:,0]]; p2=np.r_[triples[:,2],tail2[:,1]]
    prior1=np.zeros(k); history=[]; previous=(triples[:,0]<0)
    for iteration in range(int(q['iterations'])):
        post1=bcjr(s1,p1,np.r_[prior1,np.zeros(3)],q['algorithm'])[:k]
        ext1=np.clip(post1-triples[:,0]-prior1,-60,60); prior2=ext1[permutation]
        post2=bcjr(s2,p2,np.r_[prior2,np.zeros(3)],q['algorithm'])[:k]
        ext2=np.clip(post2-triples[permutation,0]-prior2,-60,60)
        posterior=post2[inverse]; hard=posterior<0
        history.append({'iteration':iteration+1,'changed_bits':int(np.count_nonzero(hard!=previous)),
                        'mean_abs_posterior':float(np.mean(abs(posterior))),
                        'prior':prior1[:64].tolist(),'extrinsic':ext1[:64].tolist(),
                        'second_extrinsic':ext2[inverse][:64].tolist(),'posterior':posterior[:64].tolist()})
        prior1=ext2[inverse]; previous=hard
    return hard.astype(np.uint8),history


def decode(kind,data,q):
    k=int(q['block_size']); width=3*k+12; values=np.asarray(data,float)
    if len(values)%width: raise ValueError('Turbo 软信息长度需要覆盖完整码字与终止尾位。')
    output=[]; traces=[]
    for word in values.reshape(-1,width):
        decoded,history=decode_word(word,q); output.append(decoded); traces.append(history)
    return np.concatenate(output),{'codewords':len(output),'block_size':k,'iterations':q['iterations'],
        'algorithm':'Max-log-MAP' if q['algorithm'] else 'Log-MAP','effective_rate':k/width,
        'learning':{'kind':'turbo','history':traces[0],'codewords':len(output),
                    'interleaver':interleaver(k,int(q['interleaver_seed'])).tolist(),
                    'all_mean_abs_posterior':[[r['mean_abs_posterior'] for r in h] for h in traces]}}
