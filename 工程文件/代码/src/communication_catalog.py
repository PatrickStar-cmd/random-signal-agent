"""v0.4.3 block definitions and runnable experiment presets."""

MODULATIONS = {'ook': 'OOK / 2ASK', 'fsk2': '2FSK', 'dbpsk': 'DBPSK', 'dqpsk': 'DQPSK', 'msk': 'MSK', 'gmsk': 'GMSK'}
KINDS = set()


def register(block, number, field, blocks):
    before = set(blocks)
    def select(label, default, labels):
        return field(label, default, 'select', choices=list(labels), choice_labels=labels)
    pn = dict(degree=select('LFSR 阶数', 7, {7: 'PRBS7', 9: 'PRBS9', 15: 'PRBS15'}), initial=number('非零初态', 1, 1, 32767, True))
    block('pn_bits', 'PN / m 序列', 'source', 'LFSR 生成 PRBS7、PRBS9 或 PRBS15，可观察周期与相关性。', count=number('比特数', 1024, 8, 8192, True), **pn)
    for tx, rx, label, description, params in [
        ('crc_append','crc_check','CRC','CRC-16/CCITT-FALSE 或 CRC-32/MPEG-2，按整帧附加与校验。', {'width':select('CRC 位数',16,{16:'CRC-16/CCITT-FALSE',32:'CRC-32/MPEG-2'})}),
        ('scramble','descramble','同步扰码','逐位异或公共 LFSR 序列，收发端使用同一初态。',pn),
        ('compand_encode','compand_decode','压扩 PCM','连续 A 律 / μ 律压扩后均匀量化。',{'law':select('压扩律',0,{0:'μ 律（μ=255）',1:'A 律（A=87.6）'}),'bits':number('量化位数',8,2,12,True),'full_scale':number('量程 ±',1,.1,32)}),
        ('dpcm_encode','dpcm_decode','DPCM','一阶重构反馈预测，对预测残差量化编码。',{'bits':number('残差量化位数',6,2,12,True),'full_scale':number('残差量程 ±',1,.01,32),'predictor':number('预测系数',1,0,1)}),
        ('delta_encode','delta_decode','增量调制','一位上升/下降指令与累加重构，比较斜率过载和颗粒噪声。',{'step':number('量化步长 Δ',.15,.001,4)}),
    ]:
        block(tx,label+' 编码','tx_converter',description,**params)
        block(rx,label+' 译码','rx_converter',description,**params)
    block('ldpc_encode','LDPC (128,64) 编码','tx_converter','教学 IRA 稀疏校验矩阵、码率 1/2，系统位加累加校验位。')
    block('ldpc_decode','LDPC 软译码','rx_converter','归一化最小和迭代，输出校验未通过码字数。输入为 LLR。',iterations=number('最大迭代次数',30,1,60,True),scale=number('最小和归一化系数',.8,.1,1))
    block('conv_soft_decode','软判决 Viterbi','rx_converter','使用 LLR 对 (7,5)₈ 卷积码作零尾完整帧软译码。')
    for scheme in ('bpsk','qpsk','qam16'):
        block('soft_'+scheme,scheme.upper()+' 软解调','demodulator','Max-log LLR：正数偏向 0，负数偏向 1；送软 Viterbi 或 LDPC。',noise_variance=number('复噪声方差 N₀',.1,.000001,100),compensate=field('已知增益 / 相位补偿',True,'boolean'),automatic_variance=field('使用接收噪声方差估计',False,'boolean'))
    for kind, label in MODULATIONS.items():
        waveform = kind in ('fsk2','msk','gmsk')
        params = {'sps':select('每码元采样点',8,{4:4,8:8,16:16,32:32})} if waveform else {}
        if kind == 'gmsk': params['bt'] = number('高斯带宽时间积 BT',.3,.2,1)
        block('mod_'+kind,label+' 调制','modulator','连续相位、调制指数 h=1/2。' if kind in ('msk','gmsk') else '正交双音频移键控。' if kind=='fsk2' else '差分相位编码，附带一个参考符号。' if kind.startswith('d') else '0 关断、1 开启，平均标称符号能量为 1。',**params)
        receive={'compensate':field('已知增益 / 相位补偿',True,'boolean')}
        if kind=='fsk2': receive['coherent']=field('相干相关检测（关闭为能量检测）',False,'boolean')
        block('demod_'+kind,label+' 解调','demodulator','相位差鉴频后逐码元积分判决。' if kind in ('msk','gmsk') else '双音相关 / 能量比较。' if kind=='fsk2' else '相邻符号差分相位判决。' if kind.startswith('d') else '幅度门限判决。',**receive)
    rrc={'sps':select('每码元采样点',8,{4:4,8:8,16:16}),'span':select('滤波器跨度 / 码元',8,{4:4,8:8,12:12,16:16}),'rolloff':number('RRC 滚降系数',.35,.05,1)}
    block('tx_rrc','复基带 RRC 成形','modulator','上采样与单位能量根升余弦 FIR，接在 PSK/QAM 映射之后。',**rrc)
    block('rx_matched','复基带匹配滤波','demodulator','匹配发送 RRC；输出仍为多采样点复波形。')
    block('rx_timing','复基带符号同步','demodulator','能量扫描初始采样相位，Gardner 复数误差与 PI 环跟踪。',bandwidth=number('定时环带宽',.005,.0001,.05),manual=field('使用手动相位',False,'boolean'),offset=number('手动相位 / T',0,-.49,.49))
    block('tx_frame','公共前导组帧','modulator','插入已知训练序列，接收端用相关峰定位帧起点。',length=select('前导长度 / 码元',256,{128:128,256:256,512:512,1024:1024}))
    block('rx_frame','相关帧同步','demodulator','搜索公共前导相关峰，消除 PSK 相位模糊，并估计复增益。',threshold=number('归一化相关门限',.45,.05,.99))
    block('rx_frequency','粗频偏估计','demodulator','PSK 二次 / 四次方法的 FFT 峰值估计，补偿未知载波频偏。')
    block('rx_carrier','Costas / PLL 载波恢复','demodulator','星座判决相位误差驱动二阶环，跟踪残余频偏和相位。',bandwidth=number('载波环带宽',.015,.0001,.1))
    block('rx_equalizer','复基带自适应均衡','demodulator','公共前导训练，支持 LMS / NLMS / RLS 及线性 / DFE 结构。',algorithm=select('算法',1,{0:'LMS',1:'NLMS',2:'RLS'}),dfe=field('判决反馈 DFE',False,'boolean'),half_taps=number('前向单侧抽头',3,1,8,True),feedback_taps=number('反馈抽头',4,1,12,True),step_size=number('步长 μ',.1,.00001,.5),forgetting=number('RLS 遗忘因子',.995,.95,1))
    block('rx_cma','CMA 盲均衡','demodulator','恒模代价自适应 FIR；无需训练，后接帧同步解决相位不确定性。',half_taps=number('单侧抽头',3,1,8,True),step_size=number('步长 μ',.005,.00001,.05))
    block('tx_pilots','周期导频插入','modulator','每组数据前插入一个已知 +1 导频，用于时变平坦衰落估计。',interval=number('导频间隔 / 数据码元',16,2,64,True))
    block('rx_pilots','LS 导频信道估计','demodulator','由导频估计复增益，在时间轴插值后补偿并移除导频。',floor=number('均衡正则下限',.0001,.000001,.1))
    block('tx_ofdm','OFDM / IFFT / 循环前缀','modulator','PSK/QAM 子载波映射、梳状导频、全导频训练符号、IFFT 与 CP。',nfft=select('FFT 点数',64,{32:32,64:64,128:128}),cp=number('循环前缀 / 采样点',16,1,32,True))
    block('rx_ofdm','OFDM / FFT / 频域均衡','demodulator','训练序列定位，去 CP、FFT、LS 信道估计与每子载波均衡。',equalize=field('启用导频 LS 均衡',True,'boolean'),regularization=number('均衡正则 λ',.00001,.000001,.1))
    block('rx_complete','完整复基带接收器','demodulator','依次执行粗频偏补偿、匹配滤波、Gardner、载波恢复与相关帧同步。',bandwidth=number('载波环带宽',.015,.0001,.1))
    block('frequency_offset','载波频偏','channel','复波形乘 exp(j2πΔft)，可与固定相移和载波恢复组合。',hz=number('频偏 Δf / Hz',10,-10000,10000))
    block('phase_noise','载波相位噪声','channel','每个采样点累加高斯相位增量，形成 Wiener 相位噪声。',std=number('每点相位增量标准差 / °',.1,0,10))
    block('sample_delay','未知帧延迟','channel','插入前置零样本并施加分数采样偏移，由接收帧同步自行定位。',samples=number('整数延迟 / 点',37,0,4096,True),fraction=number('分数延迟 / 点',.3,0,.99))
    block('complex_awgn','复波形白噪声','channel','按发送参考样本功率设置采样 SNR；保留前置衰减的影响。',snr_db=number('发送采样 SNR / dB',20,-10,60))
    block('complex_multipath','复基带多径','channel','因果复 FIR；逗号分隔复数抽头，如 1,0.4+0.2j。',taps=field('复抽头', '1,0.4+0.2j',max_length=180),spacing=number('抽头间隔 / 样本',1,1,32,True))
    for kind,label in [('rayleigh','Rayleigh'),('rician','Rician')]:
        params={'doppler':number('最大多普勒 / Hz（0 为帧内静态）',0,0,1000)}
        if kind=='rician': params['k_db']=number('直达 / 散射功率比 K / dB',6,-10,30)
        block(kind,label+' 衰落','channel','复高斯平坦衰落；非零多普勒使用 32 个散射波的时变模型。',**params)
    block('rx_agc','AGC 自动增益控制','demodulator','按接收功率更新对数增益；多帧运行保持增益状态。',target=number('目标 RMS',1,.1,4),step=number('增益环步长',.05,.001,.5))
    block('rx_noise_estimate','接收噪声方差估计','demodulator','用公共前导 LS 残差或星座判决残差估计 N₀，供软解调使用。',method=select('估计方法',0,{0:'公共前导残差',1:'判决残差'}))
    block('resample','通用有理重采样','demodulator','窗函数 sinc 插值与抗混叠，按 up/down 改变接收采样率。',up=number('插值因子 up',2,1,16,True),down=number('抽取因子 down',1,1,16,True))
    block('rx_fse','T/2 分数间隔均衡','demodulator','匹配滤波后，用公开前导获取帧位置，再以 T/2 抽头间隔进行 NLMS 训练和判决引导。',half_taps=number('单侧抽头数',4,1,12,True),step=number('NLMS 步长',.1,.00001,.5))
    block('rx_ofdm_frequency','OFDM 频偏估计与补偿','demodulator','循环前缀相关估计分数频偏，公开训练符号搜索整数子载波偏移。',search=number('整数频偏搜索范围 ±子载波',4,0,8,True))
    block('rx_ofdm_tracking','OFDM 导频跟踪接收','demodulator','训练符号初始化，随后按每个 OFDM 符号的梳状导频更新信道估计。',method=select('导频 LS 方法',1,{0:'频域线性插值',1:'DFT / 有限冲激响应 LS'}),tracking_gain=number('信道更新系数',.8,.01,1),regularization=number('均衡正则 λ',.00001,.000001,.1))
    block('time_multipath','独立路径时变多径','channel','每条路径独立 Rayleigh / 多普勒过程，功率归一化；多帧保留路径相位与延迟历史。',delays=field('各路径采样延迟','0,1,3',max_length=100),powers_db=field('各路径相对功率 / dB','0,-6,-12',max_length=100),doppler=number('最大多普勒 / Hz',10,0,1000))
    block('burst_noise','Markov 突发噪声','channel','好/坏两态 Markov 信道，以不同 SNR 产生连续噪声突发；支持跨帧状态。',good_to_bad=number('好→坏概率 / 点',.005,0,1),bad_to_good=number('坏→好概率 / 点',.1,0,1),good_snr=number('好状态 SNR / dB',30,-10,60),bad_snr=number('坏状态 SNR / dB',-3,-20,60))
    from src import communication_v045
    communication_v045.register(block,number,field,blocks)
    KINDS.update(set(blocks)-before)


def presets(preset):
    result={}
    def add(key,label,kinds,changes=None): result[key]={'label':label,'program':preset(kinds,changes)}
    add('crc_scramble','检错 · CRC / PRBS / 扰码',['pn_bits','crc_append','scramble','mod_bpsk','awgn','demod_bpsk','descramble','crc_check','sink'],{4:{'esn0_db':12}})
    add('soft_viterbi','软译码 · 卷积码 / QPSK LLR',['random_bits','conv_encode','mod_qpsk','awgn','soft_qpsk','conv_soft_decode','sink'])
    add('ldpc','软译码 · LDPC (128,64)',['random_bits','ldpc_encode','mod_bpsk','awgn','soft_bpsk','ldpc_decode','sink'])
    for scheme,label in MODULATIONS.items():
        waveform=scheme in ('fsk2','msk','gmsk')
        add('digital_'+scheme,'数字调制 · '+label,['random_bits','mod_'+scheme,'complex_awgn' if waveform else 'awgn','demod_'+scheme,'sink'])
    for kind,label in [('compand','μ 律 PCM'),('dpcm','DPCM'),('delta','增量调制')]:
        add('source_'+kind,'信源编码 · '+label,['sine',kind+'_encode','mod_qpsk','awgn','demod_qpsk',kind+'_decode','sink'],{3:{'esn0_db':30},0:{'frequency':2}})
    add('source_alaw','信源编码 · A 律 PCM',['sine','compand_encode','mod_qpsk','ideal','demod_qpsk','compand_decode','sink'],{1:{'law':1},5:{'law':1}})
    add('complex_receiver','同步 · 分步 QPSK 接收机',['random_bits','mod_qpsk','tx_frame','tx_rrc','frequency_offset','sample_delay','complex_awgn','rx_frequency','rx_matched','rx_timing','rx_carrier','rx_frame','demod_qpsk','sink'])
    add('complete_receiver','同步 · 一体化 QPSK 接收机',['text','mod_qpsk','tx_frame','tx_rrc','frequency_offset','sample_delay','complex_awgn','rx_complete','demod_qpsk','sink'])
    add('complex_nlms','均衡 · 复基带 NLMS',['random_bits','mod_qpsk','tx_frame','complex_multipath','awgn','rx_frame','rx_equalizer','demod_qpsk','sink'],{2:{'length':1024},3:{'taps':'1,0.35+0.1j'},4:{'esn0_db':24}})
    add('blind_cma','均衡 · CMA / QPSK',['random_bits','mod_qpsk','tx_frame','complex_multipath','awgn','rx_cma','rx_frame','demod_qpsk','sink'],{0:{'count':4096},2:{'length':1024},3:{'taps':'1,0.2j'},4:{'esn0_db':24}})
    for kind in ('rayleigh','rician'):
        add('fading_'+kind,'衰落 · '+kind+' / 导频 LS',['random_bits','mod_qpsk','tx_pilots',kind,'awgn','rx_pilots','demod_qpsk','sink'],{3:{'doppler':1},4:{'esn0_db':25}})
    add('ofdm','多载波 · OFDM / 多径 / LS',['random_bits','mod_qam16','tx_ofdm','complex_multipath','complex_awgn','rx_ofdm','demod_qam16','sink'],{3:{'taps':'1,0.35+0.15j,0.1'},4:{'snr_db':30}})
    add('agc_soft','接收估计 · AGC / 自动 N₀ / 软译码',['random_bits','conv_encode','mod_qpsk','tx_frame','attenuation','awgn','rx_agc','rx_frame','rx_noise_estimate','soft_qpsk','conv_soft_decode','sink'],{4:{'db':12},5:{'esn0_db':28},9:{'automatic_variance':True}})
    add('resample_receiver','重采样 · 8→12 点 / 码元',['random_bits','mod_qpsk','tx_frame','tx_rrc','ideal','resample','rx_matched','rx_timing','rx_frame','demod_qpsk','sink'],{5:{'up':3,'down':2}})
    add('fractional_equalizer','均衡 · T/2 NLMS',['random_bits','mod_qpsk','tx_frame','tx_rrc','complex_multipath','complex_awgn','rx_matched','rx_fse','rx_frame','demod_qpsk','sink'],{2:{'length':512},4:{'taps':'1,0.3+0.1j','spacing':4},5:{'snr_db':25}})
    add('ofdm_cfo_tracking','OFDM · 频偏 / 时变路径 / 导频跟踪',['random_bits','mod_qpsk','tx_ofdm','frequency_offset','time_multipath','complex_awgn','rx_ofdm_frequency','rx_ofdm_tracking','demod_qpsk','sink'],{0:{'count':2048},3:{'hz':230},4:{'doppler':10},5:{'snr_db':30},7:{'tracking_gain':1}})
    add('burst_interleave','突发噪声 · 交织 / 卷积码 / CRC',['random_bits','crc_append','conv_encode','interleave','mod_bpsk','burst_noise','soft_bpsk','deinterleave','conv_soft_decode','crc_check','sink'],{5:{'bad_snr':2,'good_to_bad':.003},6:{'noise_variance':.1}})
    return result
