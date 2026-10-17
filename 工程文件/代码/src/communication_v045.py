"""RF experiment catalogue and guided comparison tasks."""

def register(block,number,field,blocks):
    def select(label,default,labels):return field(label,default,'select',choices=list(labels),choice_labels=labels)
    for scheme,label in [('psk8','8PSK'),('qam64','64QAM'),('qam256','256QAM')]:
        block('mod_'+scheme,label+' 调制','modulator','单位平均符号能量，Gray 星座映射。')
        block('demod_'+scheme,label+' 硬解调','demodulator','最近星座点判决。',compensate=field('已知增益 / 相位补偿',True,'boolean'))
        block('soft_'+scheme,label+' 软解调','demodulator','Max-log LLR；正数偏向 0，供软 Viterbi / LDPC。',noise_variance=number('复噪声方差 N₀',.1,.000001,100),compensate=field('已知增益 / 相位补偿',True,'boolean'),automatic_variance=field('使用接收噪声方差估计',False,'boolean'))
    block('iq_imbalance','🪞 I/Q 幅相不平衡','channel','设置 Q 路相对 I 路的增益与正交相位误差。',gain_db=number('Q/I 增益误差 / dB',2,-12,12),phase_deg=number('正交相位误差 / °',10,-60,60))
    block('dc_offset','📍 直流偏置','channel','复基带两路叠加固定偏置。',i=number('I 路偏置',.2,-4,4),q=number('Q 路偏置',-.1,-4,4))
    block('rx_iq','🪞 I/Q 训练校正','demodulator','由接收公共前导估计广义线性模型 a·x+b·x*，求逆消除镜像；接在帧同步后。')
    block('rx_dc','📍 直流消除','demodulator','整帧均值消除或一阶 DC blocker，IIR 状态跨帧保持。',method=select('消除方式',0,{0:'帧均值',1:'IIR 高通'}),pole=number('IIR 极点半径',.995,.8,.9999))
    block('tx_pa','🔊 功放非线性','modulator','Rapp 幅度软饱和，或 Saleh 幅相模型；输入回退控制驱动功率。',model=select('功放模型',0,{0:'Rapp',1:'Saleh'}),backoff_db=number('输入回退 / dB',3,0,30),saturation=number('幅度尺度',1,.1,8),smoothness=number('Rapp 平滑因子',2,1,10),phase_deg=number('Saleh 相位渐近值 / °',30,0,90))
    block('adc','🎚️ ADC 量化与饱和','channel','I/Q 两路独立均匀量化，显示超量程样本数。',bits=number('每路量化位数',8,2,16,True),full_scale=number('每路量程 ±',2,.05,16))
    block('tx_clip_filter','✂️ OFDM 削峰与滤波','modulator','4 倍插值削峰，投影回有效子载波，迭代后重建 CP。',threshold_db=number('削峰门限 / RMS dB',5,0,15),iterations=number('削峰滤波迭代次数',2,1,8,True))
    block('narrowband','📡 窄带单音干扰','channel','叠加指定频率和幅度的连续复正弦干扰，跨帧保持相位。',hz=number('干扰频率 / Hz',200,-100000,100000),amplitude=number('干扰幅度',.8,0,8))
    block('rx_notch','📡 复基带陷波','demodulator','指定频率单位圆零点与同角度极点；极点越接近 1，陷波越窄。',hz=number('陷波频率 / Hz',200,-100000,100000),pole=number('极点半径',.98,.5,.999))
    rate={'rate':select('目标码率',2,{2:'2/3',3:'3/4'})}
    block('puncture','🧵 卷积码打孔','tx_converter','对 (7,5)₈ 卷积码按周期删除校验位，需接在卷积编码之后。',**rate)
    block('depuncture','🧵 软信息解打孔','rx_converter','在删除位置填入中性 LLR=0，恢复母码长度，送软 Viterbi。',**rate)
    blocks['tx_ofdm']['params'].update(active_count=number('有效子载波数（0 为全部非直流）',0,0,127,True),pilot_interval=number('导频间隔 / 子载波',4,2,16,True))


def presets(preset):
    entries={}
    def add(key,label,kinds,changes=None):entries[key]={'label':label,'program':preset(kinds,changes)}
    for scheme in ('psk8','qam64','qam256'):
        add('rf_'+scheme,'🛰️ 高阶调制 · '+scheme.upper(),['random_bits','mod_'+scheme,'awgn','demod_'+scheme,'sink'],{2:{'esn0_db':25}})
    add('rf_iq','🪞 I/Q 不平衡与校正',['random_bits','mod_qam64','tx_frame','iq_imbalance','awgn','rx_frame','rx_iq','demod_qam64','sink'],{4:{'esn0_db':30}})
    add('rf_dc','📍 直流偏置与消除',['random_bits','mod_qpsk','dc_offset','rx_dc','demod_qpsk','sink'])
    add('rf_adc','🎚️ ADC 位数与量程',['random_bits','mod_qam64','ideal','rx_agc','adc','demod_qam64','sink'])
    add('rf_pa','🔊 功放与 OFDM',['random_bits','mod_qam64','tx_ofdm','tx_pa','complex_awgn','rx_ofdm','demod_qam64','sink'],{2:{'active_count':48},4:{'snr_db':35}})
    add('rf_clip','✂️ OFDM 削峰取舍',['random_bits','mod_qam16','tx_ofdm','tx_clip_filter','tx_pa','complex_awgn','rx_ofdm','demod_qam16','sink'],{2:{'active_count':48},5:{'snr_db':35}})
    add('rf_notch','📡 窄带干扰与陷波',['random_bits','mod_qpsk','tx_frame','tx_rrc','narrowband','rx_notch','rx_matched','rx_timing','rx_frame','demod_qpsk','sink'],{4:{'hz':600},5:{'hz':600},7:{'manual':True,'offset':0}})
    add('rf_puncture','🧵 打孔卷积码与软译码',['random_bits','conv_encode','puncture','mod_qpsk','awgn','soft_qpsk','depuncture','conv_soft_decode','sink'])
    return entries


TASKS=[
    {'id':'order','title':'🛰️ 调制阶数与效率','preset':'rf_qam64','goal':'比较 16 / 64 / 256QAM 的误码率与净信息速率。','kind':'modulation','values':['qam16','qam64','qam256']},
    {'id':'iq','title':'🪞 I/Q 不平衡与校正','preset':'rf_iq','goal':'对同一训练链路比较校正关闭和开启时的 EVM。','kind':'toggle','block':'rx_iq'},
    {'id':'pa','title':'🔊 功放输入回退','preset':'rf_pa','goal':'比较输入回退对带外频谱、EVM 和输出功率的影响。','kind':'parameter','block':'tx_pa','parameter':'backoff_db','values':[0,3,6,9]},
    {'id':'adc','title':'🎚️ ADC、量程与 AGC','preset':'rf_adc','goal':'比较 ADC 位数；再调整量程，观察 AGC 在量化前的作用。','kind':'parameter','block':'adc','parameter':'bits','values':[3,4,6,8,12]},
    {'id':'clip','title':'✂️ 削峰门限与失真','preset':'rf_clip','goal':'比较削峰门限对 PAPR、EVM 和功放频谱扩展的影响。','kind':'parameter','block':'tx_clip_filter','parameter':'threshold_db','values':[2,4,6,8,12]},
    {'id':'notch','title':'📡 窄带干扰与抑制','preset':'rf_notch','goal':'比较相同干扰下陷波关闭与开启时的 BER 与频谱。','kind':'toggle','block':'rx_notch'},
    {'id':'rate','title':'🧵 码率与纠错性能','preset':'rf_puncture','goal':'比较母码 1/2 与打孔 2/3、3/4 的纠错能力和效率。','kind':'coding','values':[1,2,3]},
]


def task_programs(task_id, program):
    import copy
    from src import communications as c
    task=next((v for v in TASKS if v['id']==task_id),None)
    if task is None: raise ValueError('未知实验任务。')
    result=[]
    for value in task.get('values',[False,True]):
        p=copy.deepcopy(program);blocks=p['blocks'];name=str(value)
        if task['kind']=='modulation':
            for b in blocks:
                if b['kind'].startswith(('mod_','demod_','soft_')):
                    prefix=b['kind'].split('_')[0];b['kind']=prefix+'_'+value
                    b['params']={k:b['params'].get(k,v['default']) for k,v in c.BLOCKS[b['kind']]['params'].items()}
            name=value.upper()
        elif task['kind']=='toggle':
            if not any(b['kind']==task['block'] for b in blocks): raise ValueError('当前链路缺少任务的处理积木，请载入任务链路。')
            if not value: p['blocks']=[b for b in blocks if b['kind']!=task['block']]
            name='启用补偿' if value else '关闭补偿'
        elif task['kind']=='parameter':
            b=next((b for b in blocks if b['kind']==task['block']),None)
            if b is None: raise ValueError('当前链路缺少任务参数，请载入任务链路。')
            b['params'][task['parameter']]=value;name=c.BLOCKS[b['kind']]['params'][task['parameter']]['label']+' = '+str(value)
        else:
            if not any(b['kind']=='puncture' for b in blocks): raise ValueError('请载入打孔卷积码任务链路。')
            if value==1: p['blocks']=[b for b in blocks if b['kind'] not in ('puncture','depuncture')]
            else:
                for b in blocks:
                    if b['kind'] in ('puncture','depuncture'): b['params']['rate']=value
            name={1:'母码 1/2',2:'打孔 2/3',3:'打孔 3/4'}[value]
        c.build(p);result.append({'name':name,'program':p})
    return task,result
