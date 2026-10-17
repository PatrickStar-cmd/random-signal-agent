"""Typed, bounded digital and analog pipelines; no user code is executed.

Symbols are complex baseband samples at one sample/symbol, nominal Es=1.
AWGN uses transmit-referred Es/N0, so attenuation actually reduces receive SNR.
Analog modulation uses sampled complex envelopes and transmit-power-referred SNR.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path
import re

import numpy as np
from src import analog_modulation, baseband, receiver_recovery
from src import communication_catalog, communication_codecs, advanced_communications
from src import communication_runtime as runtime

CONFIG = json.loads((Path(__file__).resolve().parents[1] / 'config/communications.json').read_text(encoding='utf-8'))


def number(label, default, low, high, integer=False):
    return {'label': label, 'type': 'integer' if integer else 'number', 'default': default, 'min': low, 'max': high}


def field(label, default, kind='text', **extra):
    return {'label': label, 'type': kind, 'default': default, **extra}


BLOCKS = {}
def block(kind, label, category, description, **params):
    BLOCKS[kind] = {'kind': kind, 'label': label, 'category': category, 'description': description, 'params': params}


block('random_bits', '随机比特', 'source', '生成 0/1 比特；多个数字信源按积木顺序拼接。', count=number('比特数', 512, 8, CONFIG['max_source_bits'], True))
block('bit_pattern', '自定义比特', 'source', '输入一段由 0 和 1 组成的序列。', pattern=field('比特序列', '1011001011100001', max_length=CONFIG['max_source_bits']))
block('text', '文本信源', 'source', '将文字转换为 UTF-8 比特流。', text=field('发送文本', '你好，海洋通信实验室 🐳', max_length=256))
for kind, label in [('sine', '正弦信号'), ('square', '方波信号')]:
    block(kind, label, 'source', '多个模拟信源逐点相加；可直接模拟调制，或经 PCM 进入数字链路。', amplitude=number('幅值', .7, 0, 8), frequency=number('频率 / Hz', 8, 0, 24000), phase=number('初相 / °', 0, -180, 180))
block('gaussian', '高斯随机信号', 'source', '模拟信源的随机分量，与其他模拟信源叠加。', std=number('标准差', .15, 0, 4))
block('pcm_encode', 'PCM 编码', 'tx_converter', '将模拟样本均匀量化并转换为比特；超量程样本饱和。', bits=number('量化位数', 8, 2, 12, True), full_scale=number('量程 ±', 2, .1, 32))
block('repeat_encode', '重复码编码', 'tx_converter', '每个比特重复发送，接收端进行多数判决。', factor=field('重复次数', 3, 'select', choices=[3, 5, 7]))
block('hamming_encode', 'Hamming (7,4) 编码', 'tx_converter', '每 4 个数据位生成 7 位码字，可纠正每码字的一个错误。')
block('conv_encode', '卷积码编码', 'tx_converter', '码率 1/2、约束长度 3，生成多项式 (7,5)₈；零尾终止。')
block('interleave', '块交织', 'tx_converter', '按行写入、按列读出，分散连续错误。', columns=number('交织列数', 8, 2, 64, True))
for scheme, label in [('bpsk', 'BPSK'), ('qpsk', 'QPSK'), ('qam16', '16-QAM')]:
    block('mod_' + scheme, label + ' 调制', 'modulator', '单位标称符号能量的复基带映射；QPSK / QAM 使用 Gray 映射。')
    block('demod_' + scheme, label + ' 解调', 'demodulator', '最近星座点硬判决；可选择理想已知增益与相位补偿。', compensate=field('已知增益 / 相位补偿', True, 'boolean'))
for scheme, label in analog_modulation.LABELS.items():
    params = {'amplitude': number('载波幅度 / A', 1, .1, 8)}
    if scheme in ('am', 'fm', 'pm'):
        unit = {'am': '调幅灵敏度 / 1/单位', 'fm': '频偏灵敏度 / Hz/单位', 'pm': '相偏灵敏度 / rad/单位'}[scheme]
        params['sensitivity'] = number(unit, 16 if scheme == 'fm' else 1, .01, 24000 if scheme == 'fm' else 16)
    if scheme in ('ssb', 'vsb'): params['upper'] = field('保留上边带（关闭为下边带）', True, 'boolean')
    if scheme == 'ssb': params['method'] = field('生成方式', 0, 'select', choices=[0, 1], choice_labels={0: '相移法 / Hilbert', 1: '理想边带滤波法'})
    if scheme == 'vsb': params['vestige_hz'] = number('残留边带宽度 / Hz', 4, .01, 24000)
    description = {'am': '线性调制：保留载波，支持过调制与包络/相干检波对比。',
                   'dsb': '线性调制：抑制载波，保留两个边带，相干解调。',
                   'ssb': '线性调制：相移或滤波法保留一个边带，相干解调。',
                   'vsb': '线性调制：互补滚降滤波，保留一个完整边带及另一边带的残留。',
                   'fm': '非线性调制：瞬时频偏跟随模拟信源，调小/调大灵敏度观察窄带/宽带调频。',
                   'pm': '非线性调制：瞬时相偏跟随模拟信源，恒包络复基带表示。'}[scheme]
    block('mod_' + scheme, label + ' 模拟调制', 'modulator', description, **params)
    receive = {'compensate': field('已知增益 / 相位补偿', True, 'boolean'), 'cutoff_hz': number('解调低通截止 / Hz（0 关闭）', 0, 0, 24000)}
    if scheme == 'am': receive['method'] = field('检波方式', 0, 'select', choices=[0, 1], choice_labels={0: '包络检波', 1: '相干解调'})
    detector = '包络或相干检波' if scheme == 'am' else '相位差鉴频' if scheme == 'fm' else '参考相位解缠' if scheme == 'pm' else '相干解调'
    block('demod_' + scheme, label + ' 模拟解调', 'demodulator', detector + '，恢复模拟样本；增益标定使用配对调制器的配置。', **receive)
block('ideal', '理想信道', 'channel', '原样传输，适合先验证编译和收发配对。')
block('awgn', '高斯白噪声', 'channel', 'Es/N0 参考发送端单位符号能量；衰减会降低实际接收信噪比。', esn0_db=number('发送端 Es/N0 / dB', 12, -10, 60))
block('analog_awgn', '模拟白噪声', 'channel', '模拟链路专用；按发送复包络整帧实测功率设置每采样点 SNR，前置衰减会降低接收 SNR。', snr_db=number('发送端采样 SNR / dB', 20, -10, 60))
block('attenuation', '信道衰减', 'channel', '正 dB 表示衰减；作用于经过该积木的整个信号。', db=number('衰减 / dB', 3, 0, 60))
block('phase_shift', '相位偏移', 'channel', '旋转复基带信号的相位。', degrees=number('相位偏移 / °', 30, -180, 180))
block('dropout', '符号丢失', 'channel', '随机将部分符号归零。', probability=number('丢失概率', .03, 0, 1))
block('repeat_decode', '重复码译码', 'rx_converter', '按奇数次重复分组，多数判决还原。', factor=field('重复次数', 3, 'select', choices=[3, 5, 7]))
block('hamming_decode', 'Hamming (7,4) 译码', 'rx_converter', '综合征定位并翻转一位；多位错误可能误纠正。')
block('conv_decode', 'Viterbi 译码', 'rx_converter', '对 (7,5)₈ 卷积码进行完整帧硬判决 Viterbi 译码。')
block('deinterleave', '解交织', 'rx_converter', '按配对交织器的形状还原比特顺序并去除填充。', columns=number('交织列数', 8, 2, 64, True))
block('pcm_decode', 'PCM 译码', 'rx_converter', '还原量化样本；位数和量程须与发送端一致。', bits=number('量化位数', 8, 2, 12, True), full_scale=number('量程 ±', 2, .1, 32))
for scheme, label in baseband.LINE_CODES.items():
    params = {}
    if scheme in ('ami', 'hdb3', 'diff', 'miller', 'cmi'):
        params['initial_positive'] = field('初始电平/首个传号为正', scheme != 'miller', 'boolean')
    if scheme in ('ami', 'hdb3'): params['rz'] = field('使用归零 RZ 波形', scheme == 'ami', 'boolean')
    if scheme == 'hdb3':
        params['order'] = number('阶数 n（3 为 HDB3）', 3, 1, 8, True)
        params['initial_parity'] = field('初始传号奇偶状态', 0, 'select', choices=[0,1], choice_labels={0:'偶数（默认初态）',1:'奇数'})
    rules = {'nrz_unipolar':'1→+1，0→0。','nrz_polar':'1→+1，0→−1。','rz_unipolar':'1→(+1,0)，0→(0,0)。','rz_polar':'1→(+1,0)，0→(−1,0)。',
             'diff':'1 翻转，0 保持；接收端作相邻电平比较。','ami':'传号正负交替，0 为零；可选择 RZ。','manchester':'1→(+1,−1)，0→(−1,+1)。',
             'miller':'1 在位中间翻转，连续 0 在位边界翻转。','cmi':'0→(−1,+1)，1 交替使用(+1,+1)/(−1,−1)。','hdb3':'连续 n+1 个零替换为 0…0V 或 B…0V，接收端识别违例还原。'}[scheme]
    block('line_'+scheme+'_encode', label+' 编码', 'tx_converter', rules+' 输出线路电平，须接基带波形形成器。', **params)
    block('line_'+scheme+'_decode', label+' 译码', 'rx_converter', '对基带判决电平逆变换，初态与参数须与编码器一致。', **params)
for kind, label in [('baseband','基带波形形成'),('pam','多电平 PAM')]:
    transmit = {'amplitude':number('电平幅度 / A',1,.1,8),'sps':field('每码元采样点',8,'select',choices=[4,8,16,32]),
                'pulse':field('发送脉冲',0,'select',choices=list(range(6)),choice_labels=dict(enumerate(baseband.PULSE_NAMES))),
                'span':field('长脉冲跨度 / 码元',8,'select',choices=[4,6,8,12,16]),'rolloff':number('RC/RRC 滚降系数 α',.35,0,1),
                'training_symbols':number('公共训练前导 / 码元',0,0,2048,True)}
    if kind == 'pam':
        transmit.update(order=field('PAM 阶数 M',4,'select',choices=[2,4,8,16,256]),gray=field('Gray 电平标记',True,'boolean'))
    block('mod_'+kind,label,'modulator','把'+('线路电平' if kind=='baseband' else '比特分组映射为多电平并')+'形成多采样点实基带波形。',**transmit)
    block('demod_'+kind,'基带抽样判决' if kind=='baseband' else '多电平 PAM 接收','demodulator','接收滤波、自动符号同步、抽样及线性/判决反馈均衡；支持公共前导训练，帧起点粗定位已知。',
          compensate=field('已知衰减补偿',True,'boolean'),filter=field('接收滤波',1,'select',choices=[0,1,2],choice_labels={0:'直接抽样',1:'匹配滤波',2:'理想低通'}),
          cutoff_hz=number('接收低通截止 / Hz',1000,.01,1600000),sample_offset=number('抽样偏移 / 码元',0,-.49,.49),
          timing_mode=field('符号同步',0,'select',choices=[0,1,2,3],choice_labels=dict(enumerate(receiver_recovery.TIMING_NAMES))),
          loop_bandwidth=number('归一化定时环路带宽',.01,.0001,.08),gate_spacing=number('早迟门间隔 Δ / 码元',.25,.1,.49),
          equalizer=field('均衡结构',0,'select',choices=[0,1,2,3,4,5],choice_labels={0:'关闭',1:'课件有限阶迫零 ZF',2:'有限阶正则 MMSE',3:'已知响应 DFE',4:'自适应线性',5:'自适应 DFE'}),
          half_taps=number('前向单侧抽头数 N',1,1,8,True),regularization=number('MMSE / DFE / RLS 正则 λ',.01,.000001,10),
          feedback_taps=number('DFE 反馈抽头数',4,1,16,True),
          adaptive_algorithm=field('自适应算法',1,'select',choices=[0,1,2],choice_labels=dict(enumerate(receiver_recovery.ADAPTIVE_NAMES))),
          step_size=number('LMS / NLMS 步长 μ',.2,.00001,1.5),forgetting_factor=number('RLS 遗忘因子',.995,.95,1),
          adapt_after_training=field('训练后按判决继续自适应',True,'boolean'))
block('sample_awgn','基带白噪声','channel','实基带波形专用；按发送有效数据段功率设置实噪声采样 SNR，不含零保护区。',snr_db=number('发送采样 SNR / dB',20,-10,60))
for kind,label in [('lowpass_channel','带限低通信道'),('bandlimited_awgn','带限 AWGN 信道')]:
    params={'cutoff_hz':number('单边截止带宽 W / Hz',750,.01,1600000)}
    if kind=='bandlimited_awgn': params['snr_db']=number('带限前发送采样 SNR / dB',20,-10,60)
    block(kind,label,'channel','基带波形专用；理想平坦低通 C(f)，有限帧周期滤波。'+('信号和实白噪声均限带至 W。' if kind=='bandlimited_awgn' else ''),**params)
block('bandpass_channel','带通信道','channel','实基带波形的双边带通；用于观察基带信号直接经过不匹配带通信道的失真。',center_hz=number('中心频率 / Hz',1000,.01,1600000),bandwidth_hz=number('通带总宽 / Hz',800,.01,1600000))
block('ac_coupling','交流耦合信道','channel','一阶高通 H(f)=jf/(fc+jf)，抑制直流/低频，观察线路码基线失真。',cutoff_hz=number('高通截止 / Hz',100,.01,1600000))
block('isi_channel','ISI 抽头信道','channel','实基带波形 FIR；逗号分隔前游/主/后游抽头，参考位置指定零延时抽头。',taps=field('抽头系数', '1,0.5',max_length=160),spacing=number('抽头间隔 / 采样点',8,1,64,True),origin=number('零延时抽头位置（从 0 起）',0,0,16,True))
block('timing_offset','定时偏移信道','channel','线性插值产生分数码元延时；接收端可手动改变抽样偏移来观察眼图。',offset=number('延时 / 码元',.25,-.49,.49))
block('clock_drift','采样时钟漂移','channel','实基带采样时钟偏差，插值产生随帧时间增长的定时误差；正 ppm 表示接收波形时间拉长。',ppm=number('时钟误差 / ppm',300,-500,500))
block('sink', '信宿', 'sink', '显示接收端译码后的信号。固定在链路末端。')

communication_catalog.register(block, number, field, BLOCKS)
PAIRS = {'pcm_decode': 'pcm_encode', 'repeat_decode': 'repeat_encode', 'hamming_decode': 'hamming_encode', 'conv_decode': 'conv_encode', 'deinterleave': 'interleave'}
PAIRS.update(communication_codecs.PAIRS)
PAIRS.update({'line_'+scheme+'_decode':'line_'+scheme+'_encode' for scheme in baseband.LINE_CODES})
SOURCES = {k for k, v in BLOCKS.items() if v['category'] == 'source'}
ENCODERS = set(PAIRS.values())
CHANNELS = {k for k, v in BLOCKS.items() if v['category'] == 'channel'}


def preset(kinds, changes=None):
    changes = changes or {}
    return {'schema': CONFIG['schema'], **CONFIG['defaults'], 'blocks': [
        {'id': f'block-{i}', 'kind': k, 'params': {**{name: spec['default'] for name, spec in BLOCKS[k]['params'].items()}, **changes.get(i, {})}}
        for i, k in enumerate(kinds)]}


PRESETS = {
    'digital': {'label': '数字通信', 'program': preset(['random_bits', 'hamming_encode', 'mod_qpsk', 'attenuation', 'awgn', 'demod_qpsk', 'hamming_decode', 'sink'])},
    'analog': {'label': '模拟信源 + PCM', 'program': preset(['sine', 'sine', 'pcm_encode', 'conv_encode', 'mod_qpsk', 'awgn', 'demod_qpsk', 'conv_decode', 'pcm_decode', 'sink'], {1: {'frequency': 24, 'amplitude': .25}, 5: {'esn0_db': 16}})},
    'text': {'label': '文字传输', 'program': preset(['text', 'repeat_encode', 'mod_bpsk', 'awgn', 'demod_bpsk', 'repeat_decode', 'sink'])}
}
for scheme, label in analog_modulation.LABELS.items():
    PRESETS['analog_' + scheme] = {'label': ('非线性 · ' if scheme in ('fm', 'pm') else '线性 · ') + label,
                                  'program': preset(['sine', 'mod_' + scheme, 'analog_awgn', 'demod_' + scheme, 'sink'])}
PRESETS['fm_narrow'] = {'label': '非线性 · 窄带 FM', 'program': preset(['sine', 'mod_fm', 'analog_awgn', 'demod_fm', 'sink'], {1: {'sensitivity': 1}})}
for scheme,label in baseband.LINE_CODES.items():
    PRESETS['line_'+scheme]={'label':'线路码 · '+label,'program':preset(['bit_pattern','line_'+scheme+'_encode','mod_baseband','ideal','demod_baseband','line_'+scheme+'_decode','sink'],{0:{'pattern':'11010010000000001011'}})}
PRESETS['pam4']={'label':'基带 · 4-PAM / RRC / 带限 AWGN','program':preset(['random_bits','mod_pam','bandlimited_awgn','demod_pam','sink'],{1:{'pulse':5}})}
PRESETS['baseband_isi']={'label':'基带 · ISI 与迫零均衡','program':preset(['random_bits','line_nrz_polar_encode','mod_baseband','isi_channel','demod_baseband','line_nrz_polar_decode','sink'],{3:{'taps':'-0.25,1,0.3333333333333333','origin':1},4:{'equalizer':1}})}
for mode,label in [(1,'非线性时钟提取'),(2,'早迟门自动同步'),(3,'Gardner 自动同步')]:
    PRESETS['recovery_timing_'+str(mode)]={'label':'同步 · '+label,'program':preset(['random_bits','line_nrz_polar_encode','mod_baseband','timing_offset','clock_drift','sample_awgn','demod_baseband','line_nrz_polar_decode','sink'],{0:{'count':2048},2:{'pulse':5,'rolloff':.6,'training_symbols':256},3:{'offset':.35},4:{'ppm':0 if mode==1 else 300},5:{'snr_db':25},6:{'timing_mode':mode,'loop_bandwidth':.005}})}
for key,label,mode,algorithm in [('fixed_dfe','已知响应 DFE',3,1),('linear_nlms','NLMS 自适应线性',4,1),('dfe_nlms','NLMS 自适应 DFE',5,1),('dfe_rls','RLS 自适应 DFE',5,2)]:
    PRESETS['recovery_'+key]={'label':'均衡 · '+label,'program':preset(['random_bits','line_nrz_polar_encode','mod_baseband','isi_channel','sample_awgn','demod_baseband','line_nrz_polar_decode','sink'],{0:{'count':2048},2:{'training_symbols':0 if mode==3 else 1024},3:{'taps':'1,0.7' if mode==4 else '1,0.9'},4:{'snr_db':25},5:{'equalizer':mode,'adaptive_algorithm':algorithm,'half_taps':4 if mode==4 else 1}})}


PRESETS.update(communication_catalog.presets(preset))
from src import communication_v045, communication_rf
PRESETS.update(communication_v045.presets(preset))


def catalog():
    from src.communication_studio import contract
    blocks=[{**v,'inputs':contract(k)[0],'output':contract(k)[1]} for k,v in BLOCKS.items()]
    return {'schema': CONFIG['schema'], 'defaults': CONFIG['defaults'], 'blocks': blocks, 'presets': PRESETS, 'tasks': communication_v045.TASKS, 'limits': {k: v for k, v in CONFIG.items() if k.startswith('max_')}}


def numeric(value, name, low, high, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high or (integer and int(value) != value):
        raise ValueError(f'{name}须为 {low}–{high} 范围内的' + ('整数。' if integer else '数值。'))
    return int(value) if integer else float(value)


def normalize(raw, draft=False):
    allowed = {'schema', 'seed', 'sample_rate', 'sample_count', 'symbol_rate', 'blocks'}
    if not isinstance(raw, dict) or set(raw) - allowed or raw.get('schema') != CONFIG['schema'] or isinstance(raw.get('schema'), bool):
        raise ValueError('通信工程格式无效或版本不匹配。')
    p = {'schema': CONFIG['schema']}
    def value_number(value, name, lo, hi, integer=False):
        if draft:
            if value is None: return None
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(name + '须为有限数值。')
            return value
        return numeric(value, name, lo, hi, integer)
    for key, lo, hi, integer in [('seed', 0, 4294967294, True), ('sample_rate', 16, 48000, False), ('sample_count', 32, CONFIG['max_samples'], True), ('symbol_rate', 1, 100000, False)]:
        p[key] = value_number(raw.get(key, CONFIG['defaults'][key]), key, lo, hi, integer)
    items = raw.get('blocks')
    if not isinstance(items, list) or not 1 <= len(items) <= CONFIG['max_blocks']:
        raise ValueError(f'工程需要 1–{CONFIG["max_blocks"]} 个积木。')
    p['blocks'] = []; ids = set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {'id', 'kind', 'params'}:
            raise ValueError('积木格式无效。')
        kind = item.get('kind'); key = item.get('id')
        if not isinstance(kind, str) or kind not in BLOCKS or not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', key) or key in ids:
            raise ValueError('积木类型或标识无效，标识不可重复。')
        ids.add(key); params = item.get('params', {})
        if not isinstance(params, dict) or set(params) - set(BLOCKS[kind]['params']):
            raise ValueError(f'{BLOCKS[kind]["label"]}包含未知参数。')
        values = {}
        for name, spec in BLOCKS[kind]['params'].items():
            v = params.get(name, spec['default']); label = spec['label']
            if spec['type'] in ('number', 'integer'):
                v = value_number(v, label, spec['min'], spec['max'], spec['type'] == 'integer')
            elif spec['type'] == 'boolean':
                if type(v) is not bool: raise ValueError(label + '须为布尔值。')
            elif spec['type'] == 'select':
                if type(v) is not int or v not in spec['choices']: raise ValueError(label + '不在可选范围内。')
            elif not isinstance(v, str) or not (0 if draft else 1) <= len(v) <= spec['max_length']:
                raise ValueError(label + '长度无效。')
            # Omit default-valued recovery extensions to preserve existing
            # schema-1 baseband canonical programs and Build tokens.
            optional = receiver_recovery.TX_DEFAULT_FIELDS if kind in ('mod_baseband','mod_pam') else receiver_recovery.RX_DEFAULT_FIELDS if kind in ('demod_baseband','demod_pam') else {'automatic_variance'} if kind.startswith('soft_') else {'active_count','pilot_interval'} if kind=='tx_ofdm' else set()
            if name not in optional or v != spec['default']: values[name] = v
        if not draft and kind == 'bit_pattern' and not re.fullmatch('[01]+', values['pattern']): raise ValueError('自定义比特只能包含 0 和 1。')
        if not draft and kind in ('sine', 'square') and values['frequency'] >= p['sample_rate'] / 2: raise ValueError('信源频率须低于采样率的一半。')
        p['blocks'].append({'id': key, 'kind': kind, 'params': values})
    return p


def build(raw):
    p = normalize(raw); items = p['blocks']; sources = []
    if any(b['kind'] in communication_catalog.KINDS for b in items) and not any(b['kind'].startswith('line_') or b['kind'] in ('mod_baseband','mod_pam') for b in items):
        return advanced_communications.build(p)
    if any(b['kind'].startswith('line_') or b['kind'] in ('mod_baseband','demod_baseband','mod_pam','demod_pam') or b['kind'] in baseband.WAVE_CHANNELS for b in items):
        return baseband.build(p)
    for b in items:
        if b['kind'] in SOURCES: sources.append(b)
        else: break
    if not sources: raise ValueError('从积木箱添加至少一个信源，再连接发送端。')
    analog = sources[0]['kind'] in ('sine', 'square', 'gaussian')
    if any((b['kind'] in ('sine', 'square', 'gaussian')) != analog for b in sources): raise ValueError('模拟信源可以叠加，数字信源可以拼接；两类信源不能直接混合。')
    count = p['sample_count'] if analog else sum(b['params']['count'] if b['kind'] == 'random_bits' else len(b['params']['pattern']) if b['kind'] == 'bit_pattern' else len(b['params']['text'].encode('utf-8')) * 8 for b in sources)
    if count > CONFIG['max_source_bits'] and not analog: raise ValueError(f'合并后的数字信源超过 {CONFIG["max_source_bits"]} 位。')
    domain = '模拟样本' if analog else '比特'; direction = 'tx'; stack = []; scheme = None; channels = 0; attenuation = 0; analog_transmit = None
    plan = [{'id': b['id'], 'label': BLOCKS[b['kind']]['label'], 'output': domain, 'count': p['sample_count'] if analog else (b['params'].get('count') or len(b['params'].get('pattern', '')) or len(b['params']['text'].encode('utf-8')) * 8)} for b in sources]
    for index, b in enumerate(items[len(sources):], len(sources)):
        k = b['kind']; params = b['params']; before = count
        def fail(message): raise ValueError(f'第 {index + 1} 块「{BLOCKS[k]["label"]}」：{message}')
        if k in SOURCES: fail('信源须放在链路开头，连续排列。')
        elif k in ENCODERS:
            if direction != 'tx' or domain == '复基带符号': fail('编码器须放在调制器之前。')
            if k == 'pcm_encode':
                if domain != '模拟样本': fail('PCM 编码需要模拟信源。')
                count *= params['bits']; domain = '比特'
            else:
                if domain != '比特': fail('先添加 PCM 编码，把模拟信源转为比特。')
                if k == 'repeat_encode': count *= params['factor']
                elif k == 'hamming_encode': count = math.ceil(count / 4) * 7
                elif k == 'conv_encode': count = (count + 2) * 2
                else: count = math.ceil(count / params['columns']) * params['columns']
            stack.append((k, params, before))
        elif k.startswith('mod_'):
            if direction != 'tx' or scheme: fail('每条链路仅放置一个调制器，且须位于信道之前。')
            scheme = k[4:]
            if scheme in analog_modulation.SCHEMES:
                if domain != '模拟样本' or stack: fail('模拟调制器需要原始模拟信源，不经过 PCM 或信道编码。')
                analog_transmit = params
                analog_modulation.modulate(source_data(p)[0], scheme, params, p['sample_rate'])
                count += int(scheme in ('fm', 'pm')); domain = '模拟复包络'
            else:
                if domain != '比特': fail('数字调制器需要比特输入；模拟信源请先经 PCM 编码，或选择模拟调制器。')
                count = math.ceil(count / {'bpsk': 1, 'qpsk': 2, 'qam16': 4}[scheme]); domain = '复基带符号'
            direction = 'channel'
        elif k in CHANNELS:
            if direction != 'channel': fail('信道须放在调制器与解调器之间。')
            if k == 'awgn' and analog_transmit is not None: fail('模拟链路请选择「模拟白噪声」，其参数为采样 SNR。')
            if k == 'analog_awgn' and analog_transmit is None: fail('模拟白噪声需要模拟调制器；数字链路请选择「高斯白噪声」。')
            channels += 1
            if k == 'attenuation': attenuation += params['db']
            if attenuation > 100: fail('总衰减须不超过 100 dB。')
        elif k.startswith('demod_'):
            if direction != 'channel' or not channels: fail('先添加调制器和至少一个信道积木（也可选择理想信道）。')
            if scheme != k[6:]: fail('解调方式须与发送端调制方式一致。')
            mod_plan = next(v for v in plan if v.get('kind', '').startswith('mod_'))
            count = mod_plan['input_count']; domain = '模拟样本' if analog_transmit is not None else '比特'; direction = 'rx'
            if analog_transmit is not None: analog_modulation.validate(scheme, analog_transmit, params, p['sample_rate'])
        elif k in PAIRS:
            if direction != 'rx' or domain != '比特' or not stack: fail('没有可以配对的发送端编码器。')
            encoder, expected, original = stack.pop()
            if PAIRS[k] != encoder or params != expected: fail('按发送端编码的相反顺序译码，并保持配对参数一致。')
            count = original
            if k == 'pcm_decode': domain = '模拟样本'
        elif k == 'sink':
            if index != len(items) - 1 or direction != 'rx' or stack or domain != ('模拟样本' if analog else '比特'): fail('信宿须位于末端，之前需要完整的解调与配对译码。')
        else: fail('无法连接此积木。')
        if count > CONFIG['max_bits']: fail(f'中间数据超过 {CONFIG["max_bits"]} 点/位，请减少信源长度或编码层数。')
        plan.append({'id': b['id'], 'kind': k, 'label': BLOCKS[k]['label'], 'input_count': before, 'count': count, 'output': domain})
    if items[-1]['kind'] != 'sink': raise ValueError('链路末端需要信宿。')
    token = hashlib.sha256(json.dumps(p, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()
    result = {'program': p, 'token': token, 'plan': plan, 'summary': f'{len(sources)} 个信源 · {len(items)} 个积木 · {count} ' + ('个接收样本' if analog else '个接收比特'), 'source_kind': 'analog' if analog else 'digital', 'model': '复基带 · 1 样本/符号 · 理想定时 · 硬判决'}
    if analog_transmit is not None:
        result.update(transport='analog', model='模拟复包络 · 采样时钟 · 理想帧滤波 · ' + analog_modulation.LABELS[scheme])
    return result


def hamming_encode(bits):
    d = np.pad(bits, (0, -len(bits) % 4)).reshape(-1, 4)
    out = np.zeros((len(d), 7), dtype=np.uint8)
    out[:, [2, 4, 5, 6]] = d
    out[:, 0] = d[:, 0] ^ d[:, 1] ^ d[:, 3]
    out[:, 1] = d[:, 0] ^ d[:, 2] ^ d[:, 3]
    out[:, 3] = d[:, 1] ^ d[:, 2] ^ d[:, 3]
    return out.ravel()


def hamming_decode(bits):
    d = bits.reshape(-1, 7).copy()
    s = (d[:, 0] ^ d[:, 2] ^ d[:, 4] ^ d[:, 6]) + 2 * (d[:, 1] ^ d[:, 2] ^ d[:, 5] ^ d[:, 6]) + 4 * (d[:, 3] ^ d[:, 4] ^ d[:, 5] ^ d[:, 6])
    rows = np.flatnonzero(s); d[rows, s[rows] - 1] ^= 1
    return d[:, [2, 4, 5, 6]].ravel(), len(rows)


def transition(state, bit):
    a, b = state >> 1, state & 1
    return (bit << 1) | a, (bit ^ a ^ b, bit ^ b)


def conv_encode(bits):
    state = 0; output = []
    for bit in itertools.chain(bits.tolist(), [0, 0]):
        state, pair = transition(state, bit); output.extend(pair)
    return np.array(output, dtype=np.uint8)


def viterbi_decode(bits):
    pairs = bits.reshape(-1, 2); scores = [0, math.inf, math.inf, math.inf]; path = np.zeros((len(pairs), 4), dtype=np.uint8)
    for i, pair in enumerate(pairs):
        updated = [math.inf] * 4
        for prev in range(4):
            for bit in (0, 1):
                dest, expected = transition(prev, bit)
                score = scores[prev] + int(pair[0] != expected[0]) + int(pair[1] != expected[1])
                if score < updated[dest]: updated[dest] = score; path[i, dest] = prev
        scores = updated
    decoded = np.zeros(len(pairs), dtype=np.uint8); state = 0
    for i in range(len(pairs) - 1, -1, -1): decoded[i] = state >> 1; state = int(path[i, state])
    return decoded[:-2]


def constellation(scheme):
    if scheme in ('psk8','qam64','qam256'): return communication_rf.constellation(scheme)
    width = {'bpsk': 1, 'qpsk': 2, 'qam16': 4}[scheme]
    labels = np.array(list(itertools.product([0, 1], repeat=width)), dtype=np.uint8)
    b = labels.astype(float)
    if scheme == 'bpsk': points = (1 - 2 * b[:, 0]).astype(complex)
    elif scheme == 'qpsk': points = (1 - 2 * b[:, 0] + 1j * (1 - 2 * b[:, 1])) / math.sqrt(2)
    else:
        levels = np.array([-3, -1, 3, 1])
        points = (levels[labels[:, 0] * 2 + labels[:, 1]] + 1j * levels[labels[:, 2] * 2 + labels[:, 3]]) / math.sqrt(10)
    return labels, points


def modulate(bits, scheme):
    labels, points = constellation(scheme); width = labels.shape[1]
    groups = np.pad(bits, (0, -len(bits) % width)).reshape(-1, width)
    indices = groups.dot(2 ** np.arange(width - 1, -1, -1))
    return points[indices], indices


def demodulate(symbols, scheme):
    labels, points = constellation(scheme)
    indices = np.argmin(np.abs(symbols[:, None] - points[None, :]) ** 2, axis=1)
    return labels[indices].ravel(), indices


def source_data(p):
    source_rng = np.random.default_rng(np.random.SeedSequence(p['seed']).spawn(2)[0])
    t = np.arange(p['sample_count']) / p['sample_rate']; signals = []; texts = []
    for b in p['blocks']:
        k, q = b['kind'], b['params']
        if k not in SOURCES: break
        if k == 'random_bits': y = source_rng.integers(0, 2, q['count'], dtype=np.uint8)
        elif k == 'pn_bits': y = communication_codecs.pn(q['count'], q['degree'], q['initial'])
        elif k == 'bit_pattern': y = np.array([int(c) for c in q['pattern']], dtype=np.uint8)
        elif k == 'text':
            encoded = q['text'].encode('utf-8'); texts.append(encoded); y = np.unpackbits(np.frombuffer(encoded, dtype=np.uint8))
        elif k == 'gaussian': y = source_rng.normal(0, q['std'], len(t))
        else:
            s = np.sin(2 * np.pi * q['frequency'] * t + np.deg2rad(q['phase']))
            y = q['amplitude'] * (s if k == 'sine' else np.where(s >= 0, 1., -1.))
        ctx=runtime.CURRENT.get()
        if ctx and getattr(ctx,'source_active',False):
            runtime.enter(b); y=runtime.record(b,y,p['sample_rate'])
        signals.append(y)
    analog = p['blocks'][0]['kind'] in ('sine', 'square', 'gaussian')
    source = np.sum(signals, axis=0) if analog else np.concatenate(signals)
    return source, texts, len(signals)


def run(raw, token):
    compiled = build(raw)
    if not isinstance(token, str) or token != compiled['token']: raise ValueError('配置已改变或尚未 Build，请重新构建后再 Run。')
    p = compiled['program']; analog = compiled['source_kind'] == 'analog'
    noise_rng = np.random.default_rng(np.random.SeedSequence(p['seed']).spawn(2)[1])
    ctx=runtime.CURRENT.get()
    if ctx: ctx.source_active=True
    try: source, texts, source_count = source_data(p)
    finally:
        if ctx: ctx.source_active=False
    if compiled.get('transport') == 'advanced':
        return advanced_communications.run(compiled, source, texts, source_count, noise_rng)
    if compiled.get('transport') == 'baseband':
        result = baseband.run(compiled, source, texts, source_count, noise_rng)
        json.dumps(result, allow_nan=False)
        return result
    if compiled.get('transport') == 'analog':
        result = analog_modulation.run(compiled, source, noise_rng, CONFIG)
        json.dumps(result, allow_nan=False)
        return result
    data = source.copy(); reference_bits = None if analog else source.copy(); encoded_bits = None; stack = []; gain = 1 + 0j
    channel_symbols = None; decision_symbols = None; tx_symbols = None; demapped = None; decided_indices = None; clipped = 0; corrections = 0
    for b in p['blocks'][source_count:]:
        runtime.enter(b)
        k, q = b['kind'], b['params']; before = len(data)
        if k in ENCODERS:
            stack.append((k, q, before))
            if k == 'pcm_encode':
                fs, bits = q['full_scale'], q['bits']; clipped = int(np.count_nonzero(np.abs(data) > fs))
                quantized = np.rint((np.clip(data, -fs, fs) + fs) / (2 * fs) * (2 ** bits - 1)).astype(np.uint16)
                data = ((quantized[:, None] >> np.arange(bits - 1, -1, -1)) & 1).astype(np.uint8).ravel(); reference_bits = data.copy()
            elif k == 'repeat_encode': data = np.repeat(data, q['factor'])
            elif k == 'hamming_encode': data = hamming_encode(data)
            elif k == 'conv_encode': data = conv_encode(data)
            else: data = np.pad(data, (0, -len(data) % q['columns'])).reshape(-1, q['columns']).T.ravel()
        elif k.startswith('mod_'):
            encoded_bits = data.copy(); scheme = k[4:]; data, transmitted_indices = modulate(data, scheme); tx_symbols = data.copy()
        elif k == 'awgn': data = data + math.sqrt(10 ** (-q['esn0_db'] / 10) / 2) * (noise_rng.normal(size=len(data)) + 1j * noise_rng.normal(size=len(data)))
        elif k in ('attenuation', 'phase_shift'):
            factor = 10 ** (-q['db'] / 20) if k == 'attenuation' else np.exp(1j * np.deg2rad(q['degrees']))
            data = data * factor; gain *= factor
        elif k == 'dropout': data = data * (noise_rng.random(len(data)) >= q['probability'])
        elif k.startswith('demod_'):
            channel_symbols = data.copy(); decision_symbols = data / gain if q['compensate'] else data.copy()
            data, decided_indices = demodulate(decision_symbols, scheme); data = data[:len(encoded_bits)]; demapped = data.copy()
        elif k in PAIRS:
            encoder, params, size = stack.pop()
            if k == 'repeat_decode': data = (data.reshape(-1, q['factor']).sum(axis=1) > q['factor'] // 2).astype(np.uint8)
            elif k == 'hamming_decode': data, n = hamming_decode(data); corrections += n
            elif k == 'conv_decode': data = viterbi_decode(data)
            elif k == 'deinterleave': data = data.reshape(q['columns'], -1).T.ravel()
            else:
                decoded_bits = data.copy(); values = data.reshape(-1, q['bits']).dot(2 ** np.arange(q['bits'] - 1, -1, -1))
                data = values / (2 ** q['bits'] - 1) * 2 * q['full_scale'] - q['full_scale']
            data = data[:size]
        data=runtime.record(b,data,p['symbol_rate'])
    if not analog: decoded_bits = data.astype(np.uint8)
    errors = int(np.count_nonzero(reference_bits != decoded_bits)); coded_errors = int(np.count_nonzero(encoded_bits != demapped))
    full_count = len(data); shown = min(full_count, CONFIG['plot_points']); scatter = min(len(tx_symbols), CONFIG['scatter_points'])
    metrics = {'bit_count': len(reference_bits), 'bit_errors': errors, 'ber': errors / len(reference_bits), 'coded_bit_count': len(encoded_bits), 'coded_bit_errors': coded_errors, 'coded_ber': coded_errors / len(encoded_bits), 'symbol_count': len(tx_symbols), 'symbol_errors': int(np.count_nonzero(transmitted_indices != decided_indices)), 'effective_rate': len(reference_bits) / len(encoded_bits), 'evm_percent': float(100 * np.sqrt(np.mean(np.abs(decision_symbols - tx_symbols) ** 2) / np.mean(np.abs(tx_symbols) ** 2))), 'rmse': float(np.sqrt(np.mean((data - source) ** 2))) if analog else None, 'clipped_samples': clipped, 'hamming_syndromes': corrections}
    labels, points = constellation(scheme)
    result = {'token': compiled['token'], 'seed': p['seed'], 'summary': compiled['summary'], 'model': compiled['model'], 'metrics': metrics, 'plan': compiled['plan'], 'sink': {'kind': compiled['source_kind'], 'values': data.tolist(), 'reference': source.tolist(), 'sample_rate': p['sample_rate'] if analog else None, 'count': full_count, 'plot_count': shown}, 'channel': {'count': len(channel_symbols), 'plot_count': min(len(channel_symbols), CONFIG['plot_points']), 'symbol_rate': p['symbol_rate'], 'i': channel_symbols[:CONFIG['plot_points']].real.tolist(), 'q': channel_symbols[:CONFIG['plot_points']].imag.tolist()}, 'constellation': {'scheme': scheme, 'count': scatter, 'i': decision_symbols[:scatter].real.tolist(), 'q': decision_symbols[:scatter].imag.tolist(), 'ideal_i': points.real.tolist(), 'ideal_q': points.imag.tolist(), 'labels': [''.join(map(str, v)) for v in labels]}, 'text': None}
    if not analog and len(texts) == source_count: result['text'] = {'sent': b''.join(texts).decode('utf-8'), 'received': np.packbits(decoded_bits).tobytes().decode('utf-8', errors='replace')}
    # This is also the JSON-export contract: never return NaN/Infinity.
    json.dumps(result, allow_nan=False)
    result['analysis']=communication_rf.analyze(tx_symbols,channel_symbols,tx_symbols,decision_symbols,p['symbol_rate'],len(reference_bits))
    metrics.update(net_bit_rate=result['analysis']['net_bit_rate'],spectral_efficiency=result['analysis']['spectral_efficiency'],papr_db=result['analysis']['tx']['papr_db'])
    return result
