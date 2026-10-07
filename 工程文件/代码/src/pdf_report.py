"""Read-only, evidence-based Chinese reports from one frozen experiment."""
from pathlib import Path
from html import escape
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import threading

import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Flowable, KeepTogether, Image

from . import diagnostics
from .advanced_analysis import estimate_welch_psd
from .signal_processing import decimate_for_export, autocorrelation
from .preprocessing import PREPROCESS_METHODS
from .workbench import VERSION, ALGORITHM_VERSION

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'config/report.json').read_text(encoding='utf-8'))
FONT = 'SignalReportCJK'
INK, BLUE, PURPLE, MUTED = '#22334e', '#168494', '#5967b9', '#60718a'
GOALS = {'waveform': '保留波形', 'denoise': '抑噪', 'transient': '保留瞬态'}
_font_lock = threading.Lock()
_font_ready = False
_glyphs = set()
RENDER_LIMIT = threading.BoundedSemaphore(CONFIG['render_workers'])
PARAMETER_KEYS = {'smoothing_window','anomaly_threshold_sigma','repair_impulses','remove_mean','method',
                  'lowpass_cutoff_hz','sample_rate','ema_alpha','kalman_process_noise','kalman_measurement_noise',
                  'kalman_initial_error','window','alpha','cutoff_hz','process_noise_q',
                  'measurement_noise_r','initial_error_p','robust_sigma','start','end','event_id'}


def parameters(value):
    return {k:v for k,v in value.items() if k in PARAMETER_KEYS and
            (v is None or type(v) in (bool,int,float) or isinstance(v,str) and len(v)<=200)}


def options(value=None):
    value = {} if value is None else value
    defaults = {'title': '信号处理与分析报告', 'author': '', 'purpose': '', 'unit': 'a.u.', 'edition': 'standard'}
    if not isinstance(value, dict) or set(value) - set(defaults):
        raise ValueError('报告设置包含未知字段。')
    result = {**defaults, **value}
    for key, limit in [('title', CONFIG['max_title']), ('author', CONFIG['max_author']),
                       ('purpose', CONFIG['max_purpose']), ('unit', 20)]:
        text = result[key]
        if not isinstance(text, str) or len(text) > limit or any(ord(c) < 32 and c not in '\n\t' for c in text):
            raise ValueError(f'报告 {key} 超出长度或包含无效字符。')
        result[key] = text.strip()
    if not result['title'] or not result['unit'] or result['edition'] not in ('brief', 'standard'):
        raise ValueError('请填写报告标题、量纲，并选择简版或标准版。')
    return result


def number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def fmt(value, unit=''):
    v = number(value)
    return '未计算' if v is None else f'{v:.4g}{(" " + unit) if unit else ""}'


def _stats(y, clean):
    centered = y - np.mean(y)
    spectrum = np.abs(np.fft.rfft(centered * np.hanning(len(y)))) / len(y)
    spectrum[0] = 0
    result = {'mean': number(np.mean(y)), 'rms': number(np.sqrt(np.mean(y * y))),
              'std': number(np.std(y)), 'peak': number(np.max(np.abs(y))),
              'peak_to_peak': number(np.ptp(y)),
              'roughness': number(np.sqrt(np.mean(np.diff(y) ** 2))) if len(y) > 1 else None,
              'snr_db': None, 'rmse': None}
    if clean is not None:
        error = float(np.mean((y - clean) ** 2))
        power = float(np.mean(clean ** 2))
        result['rmse'] = math.sqrt(error)
        if power > 1e-12:
            result['snr_db'] = 99.0 if error <= 1e-12 else number(10 * math.log10(power / error))
    return result, spectrum


def build(state, preferences=None):
    """Whitelist report data; never copy chat, credentials or server paths."""
    opts = options(preferences)
    b = state.bundle
    if b is None:
        raise ValueError('请先生成或导入信号，再生成分析报告。')
    lab = diagnostics.lab_for(state)
    if lab.get('blind') and not lab.get('revealed'):
        raise ValueError('请先揭晓盲测，再生成完整 PDF 分析报告。')
    y = np.asarray(b.observed, dtype=float)
    processed = np.asarray(state.processed.signal, dtype=float) if state.processed else None
    if not len(y) or any(not np.isfinite(a).all() or np.max(np.abs(a)) > 1e100 for a in [b.time, y] + ([processed] if processed is not None else [])):
        raise ValueError('报告数据必须为有限采样，绝对值不超过 1e100。')
    if processed is not None and len(processed) != len(y):
        raise ValueError('处理结果与观测数据点数不一致。')
    fs = float(b.config.sample_rate)
    if not math.isfinite(fs) or fs <= 0 or fs > 192000:
        raise ValueError('报告采样率须在 0–192000 Hz 范围。')
    relative = np.asarray(b.time) - b.time[0]
    uniform = len(y) < 2 or np.allclose(np.diff(relative), 1 / fs, rtol=1e-3, atol=max(1e-12, 1e-6/fs))
    clean = np.asarray(b.clean) if b.has_clean_reference else None
    if clean is not None and (len(clean) != len(y) or not np.isfinite(clean).all() or np.max(np.abs(clean)) > 1e100):
        raise ValueError('参考信号无效。')
    raw, amplitude = _stats(y, clean)
    after, after_amplitude = _stats(processed, clean) if processed is not None else (None, None)
    series = [relative, y] + ([processed] if processed is not None else [])
    plotted = decimate_for_export(*series, max_points=CONFIG['plot_points'])
    plots = {'waveform': {'x': plotted[0], 'ys': plotted[1:], 'xlabel': '相对时间 / s', 'ylabel': opts['unit']}}
    primary = processed if processed is not None else y
    primary_amplitude = after_amplitude if processed is not None else amplitude
    main_frequency = None
    if uniform and len(y) >= 4:
        frequencies = np.fft.rfftfreq(len(y), 1/fs)
        fseries = [frequencies, amplitude] + ([after_amplitude] if after_amplitude is not None else [])
        points = decimate_for_export(*fseries, max_points=CONFIG['plot_points'])
        plots['spectrum'] = {'x': points[0], 'ys': points[1:], 'xlabel': '频率 / Hz', 'ylabel': '相对幅值', 'nonnegative': True}
        if np.sum(primary_amplitude**2) > 1e-12:
            main_frequency = float(frequencies[np.argmax(primary_amplitude)])
        psd = estimate_welch_psd(primary, fs, 256, .5)
        plots['psd'] = {'x': psd['frequencies'], 'ys': [psd['power']], 'xlabel': '频率 / Hz', 'ylabel': opts['unit'] + '²/Hz', 'nonnegative': True}
        if np.var(primary) > 1e-12:
            lag = min(48, len(y)-1)
            plots['correlation'] = {'x': (np.arange(lag+1)/fs).tolist(), 'ys': [autocorrelation(primary, lag).tolist()], 'xlabel': '滞后时间 / s', 'ylabel': '相关系数', 'correlation': True}
    methods = []
    comparison = state.preprocess_comparison or {}
    for row in comparison.get('methods', [])[:6]:
        method = row.get('method')
        if method not in PREPROCESS_METHODS:
            continue
        methods.append({'method': method, 'label': PREPROCESS_METHODS[method]['label'], 'score': number(row.get('score')),
                        'snr_db': number(row.get('processed_snr_db')) if clean is not None else None,
                        'duration_ms': number(row.get('duration_ms')), 'parameters': parameters(row.get('parameters', {}))})
    current = state.processed
    method_name = PREPROCESS_METHODS.get(current.method, {}).get('label', '诊断验证处理') if current else '尚未处理'
    summary = [f'本次分析包含 {len(y):,} 个采样点，采样率为 {fmt(fs, "Hz")}；' +
               (f'当前结果采用{method_name}。' if current else '当前仅有原始观测，尚未执行信号处理。')]
    if main_frequency is not None:
        summary.append(f'当前信号的主要频率成分位于 {fmt(main_frequency, "Hz")} 附近。该值来自去均值并加 Hann 窗后的频谱峰值。')
    else:
        summary.append('当前采样条件或交流谱能量不足，未给出可靠的主频估计。')
    if after:
        if raw['snr_db'] is not None and after['snr_db'] is not None:
            change = after['snr_db'] - raw['snr_db']
            summary.append(f'以干净参考计算，SNR 从 {fmt(raw["snr_db"], "dB")} 变为 {fmt(after["snr_db"], "dB")}，' +
                           (f'提高 {fmt(change, "dB")}。' if change >= 0 else f'下降 {fmt(-change, "dB")}；建议检查处理参数对有效成分的影响。'))
        elif clean is None:
            summary.append(f'处理前后 RMS 分别为 {fmt(raw["rms"])} 和 {fmt(after["rms"])}。数据没有干净参考，幅值变化不能直接证明真实误差减小。')
        else:
            summary.append('参考信号功率过低，未计算 SNR；可结合 RMSE 和波形判断处理变化。')
    limitations = ['指标使用全部采样计算；波形显示保留极值并限制绘图点数。', '频谱幅值用于相对比较，不作为校准后的物理幅值。']
    if clean is None:
        limitations.append('无干净参考：真实 SNR、RMSE 和真实误差改善未计算。')
    elif (raw['snr_db'] == 99 or (after and after['snr_db'] == 99)):
        limitations.append('误差功率不超过 1e-12 时，SNR 以 99 dB 的约定上限显示。')
    if not uniform:
        limitations.append('时间间隔与配置采样率不一致：仅报告时域结果，不生成频谱、PSD 或自相关图。')
    if len(y) < 4:
        limitations.append('少于 4 个采样点，未生成频域分析。')
    if np.var(primary) <= 1e-12:
        limitations.append('当前序列近似常量，自相关未定义，未绘制相关图。')
    if clean is None and methods:
        limitations.append('无参考评分为同一输入和目标下的启发式比较，不能等同于真实去噪效果。')
    diagnosis = None
    if lab.get('analysis'):
        params = {k:v for k,v in lab['analysis']['parameters'].items() if k != 'effective_window'}
        result = diagnostics.analyze(state, params)
        diagnosis = {k:result[k] for k in ('parameters','events','spectrogram','frequency_resolution_hz','hop_seconds','note')}
    digest = hashlib.sha256()
    for array in [b.time, y] + ([clean] if clean is not None else []) + ([processed] if processed is not None else []):
        digest.update(np.asarray(array, dtype='<f8').tobytes())
    source = str(b.source)
    simulated = source.startswith(('simulat', 'simulation'))
    facts = {'options': opts, 'report_version': CONFIG['version'], 'app_version': VERSION, 'algorithm_version': ALGORITHM_VERSION,
             'source': '仿真信号' if simulated else ('麦克风采样' if 'microphone' in source else '导入或外部采样'),
             'sample_count': len(y), 'sample_rate': fs, 'duration_seconds': len(y)/fs,
             'observed_span_seconds': float(relative[-1]), 'has_reference': clean is not None, 'uniform': bool(uniform),
             'method': method_name, 'parameters': parameters(current.parameters) if current else {}, 'goal': GOALS.get(state.comparison_goal, '保留波形'),
             'configuration': b.config.to_dict() if simulated else {'sample_rate': fs},
             'before': raw, 'after': after, 'main_frequency_hz': main_frequency,
             'methods': methods, 'summary': summary, 'limitations': limitations, 'plots': plots, 'diagnosis': diagnosis,
             'input_result_sha256': digest.hexdigest()}
    facts['token'] = hashlib.sha256(json.dumps(facts, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return facts


def preview(facts):
    sections = ['实验概览', '波形与处理结果']
    if 'spectrum' in facts['plots']: sections.append('频域与随机过程特征')
    if facts['options']['edition'] == 'standard':
        if facts['methods']: sections.append('方法比较与参数')
        if facts['diagnosis']: sections.append('异常诊断')
        sections.append('结论与复现信息')
    return {k:facts[k] for k in ('token', 'options', 'summary', 'limitations', 'before', 'after', 'app_version')} | {'sections': sections}


def _font():
    global _font_ready, _glyphs
    with _font_lock:
        if not _font_ready:
            font = TTFont(FONT, str(ROOT / CONFIG['font']))
            pdfmetrics.registerFont(font)
            pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT, italic=FONT, boldItalic=FONT)
            _glyphs = set(font.face.charToGlyph)
            _font_ready = True


def _text(value):
    # Keep unsupported decorative emoji from becoming missing-glyph boxes.
    return ''.join(c if ord(c) in _glyphs or c in '\n\t' else f'[U+{ord(c):04X}]' for c in str(value))


class Chart(Flowable):
    def __init__(self, data, labels=None, height=175):
        super().__init__(); self.data=data; self.labels=labels or ['当前信号']; self.width=491; self.height=height

    def draw(self):
        c=self.canv; data=self.data; left,bottom,w,h=55,32,424,self.height-67
        xs=np.asarray(data['x']); ys=[np.asarray(y) for y in data['ys']]
        if not len(xs): return
        lo,hi=min(float(np.min(y)) for y in ys),max(float(np.max(y)) for y in ys)
        padding=max((hi-lo)*.08, abs(hi)*.05, 1e-6);lo-=padding;hi+=padding
        if data.get('nonnegative'):lo=0
        if data.get('correlation'):lo,hi=-1.05,1.05
        xmin,xmax=float(xs[0]),float(xs[-1]); dx=max(xmax-xmin,1e-12)
        c.setFont(FONT,8)
        for i in range(5):
            x=left+w*i/4;y=bottom+h*i/4
            c.setStrokeColor(colors.HexColor('#e3e9f1'));c.line(left,y,left+w,y);c.line(x,bottom,x,bottom+h)
            c.setFillColor(colors.HexColor(MUTED));c.drawRightString(left-6,y-3,fmt(lo+(hi-lo)*i/4));c.drawCentredString(x,bottom-13,fmt(xmin+dx*i/4))
        for index,values in enumerate(ys):
            color=[BLUE,PURPLE][index%2];c.setStrokeColor(colors.HexColor(color));c.setLineWidth(1.1)
            p=c.beginPath()
            for j,(x,y) in enumerate(zip(xs,values)):
                point=(left+w*(float(x)-xmin)/dx,bottom+h*(float(y)-lo)/(hi-lo))
                if j==0:p.moveTo(*point)
                else:p.lineTo(*point)
            c.drawPath(p)
            c.setFillColor(colors.HexColor(color));c.drawString(left+index*140,self.height-11,_text(self.labels[min(index,len(self.labels)-1)]))
        c.setFillColor(colors.HexColor(MUTED));c.drawCentredString(left+w/2,5,_text(data['xlabel']));c.drawString(2,self.height-26,_text(data['ylabel']))


class Heatmap(Flowable):
    width=491; height=195
    def __init__(self, grid):
        super().__init__();self.grid=grid;self.width=491;self.height=195
    def draw(self):
        c=self.canv; grid=self.grid; rows=grid['db'];bins=len(grid['frequency']);left,bottom,w,h=40,30,440,145
        for i,row in enumerate(rows):
            for j,value in enumerate(row):
                ratio=max(0,min(1,(value+80)/80));c.setFillColor(colors.Color(.15+.7*ratio,.2+.65*ratio,.65-.4*ratio))
                c.rect(left+i*w/len(rows),bottom+j*h/bins,w/len(rows)+.1,h/bins+.1,stroke=0,fill=1)
        c.setFont(FONT,8);c.setFillColor(colors.HexColor(MUTED));c.drawString(left,15,fmt(grid['time'][0],'s'));c.drawCentredString(left+w/2,4,'相对时间 / s');c.drawRightString(left+w,15,fmt(grid['time'][-1],'s'));c.drawString(0,bottom+h,fmt(grid['frequency'][-1],'Hz'));c.drawString(0,bottom,'0 Hz')


def render(facts):
    """Produce a selectable-text PDF; shared facts match its preview token."""
    if not RENDER_LIMIT.acquire(blocking=False):
        from .tasks import TaskBusy
        raise TaskBusy('报告生成繁忙，请稍后重试。')
    try:
        return _render(facts)
    finally:
        RENDER_LIMIT.release()


def _render(f):
    _font(); opts=f['options']; output=io.BytesIO(); W,H=A4
    styles={key:ParagraphStyle(key,fontName=FONT,fontSize=size,leading=leading,textColor=colors.HexColor(color),spaceAfter=space,alignment=TA_LEFT,wordWrap='CJK')
            for key,size,leading,color,space in [('title',23,32,INK,16),('h1',16,24,INK,14),('h2',12,19,PURPLE,9),('body',10.2,17,INK,9),('small',8,12,MUTED,7)]}
    for key in ('h1','h2'): styles[key].keepWithNext=True
    story=[]
    def para(text,style='body'):return Paragraph(escape(_text(text)).replace('\n','<br/>'),styles[style])
    def add(text,style='body'):story.append(para(text,style))
    def table(rows,widths=None):
        cells=[[para(v,'small') for v in row] for row in rows]
        obj=Table(cells,colWidths=widths or [491/len(rows[0])]*len(rows[0]),repeatRows=1,hAlign='LEFT')
        obj.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0fa')),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#dce5ee')),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
        story.extend([obj,Spacer(1,12)])
    def figure(key,title,height=180):
        if key not in f['plots']:return
        labels=['原始观测','当前处理'] if len(f['plots'][key]['ys'])>1 else ['当前处理' if f['after'] else '原始观测']
        story.append(KeepTogether([para(title,'h2'),Chart(f['plots'][key],labels,height)]));story.append(Spacer(1,8))
    def page(title):story.extend([PageBreak(),para(title,'h1')])
    stamp=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    def decoration(c,doc):
        if doc.page>CONFIG['max_pages']:raise ValueError('报告超过页数上限，请缩短说明或参数。')
        c.saveState();c.setStrokeColor(colors.HexColor('#d9e5f0'));c.line(52,H-38,W-52,H-38);c.line(52,39,W-52,39)
        c.setFont(FONT,8);c.setFillColor(colors.HexColor(MUTED));c.drawString(52,H-29,'谛听 / SIGNAL ANALYSIS');c.drawRightString(W-52,H-29,'v'+VERSION)
        c.drawString(52,26,'实验 '+f['input_result_sha256'][:12]);c.drawRightString(W-52,26,'第 '+str(doc.page)+' 页')
        c.restoreState()
    add('信号处理与分析','small')
    cover=Table([[para(opts['title'],'title'),Image(str(ROOT/'web/ocean-whale.webp'),width=96,height=64)]],colWidths=[380,111])
    cover.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
    story.append(cover);story.append(Spacer(1,12));add(('作者：'+opts['author']+'   ' if opts['author'] else '')+'生成时间：'+stamp,'small')
    add('实验概览','h2')
    table([['数据来源','点数','采样率','采样时长'],[f['source'],f'{f["sample_count"]:,}',fmt(f['sample_rate'],'Hz'),fmt(f['duration_seconds'],'s')]])
    if opts['purpose']:add('分析目的','h2');add(opts['purpose'])
    add('主要发现','h2')
    for text in f['summary']:add(text)
    add('当前方法：'+f['method']+'。比较目标：'+f['goal']+'。')
    add('数据与解释边界','h2')
    for text in f['limitations']:add(text,'small')
    page('波形与处理结果')
    figure('waveform','原始观测与当前结果',220 if opts['edition']=='standard' else 150)
    metrics=[('mean','均值'),('rms','RMS'),('std','标准差'),('peak','绝对峰值'),('peak_to_peak','峰峰值'),('roughness','相邻样本变化量'),('snr_db','SNR / dB'),('rmse','参考 RMSE')]
    if opts['edition']=='brief': metrics=[m for m in metrics if m[0] in ('rms','peak','snr_db','rmse')]
    table([['指标','原始观测','当前处理']]+[[label,fmt(f['before'][key]),fmt(f['after'][key]) if f['after'] else '尚未处理'] for key,label in metrics],[170,160,161])
    add('均值反映直流偏移，RMS 反映整体幅值；相邻样本变化量是相邻点差值的均方根。更平滑或幅值更小不一定代表恢复了真实信号。')
    if 'spectrum' in f['plots']:
        if opts['edition']=='standard':page('频域与随机过程特征')
        figure('spectrum','加窗频谱',180 if opts['edition']=='standard' else 130)
        add('先去均值、乘 Hann 窗，FFT 幅值除以点数。横轴为频率，纵轴用于同一数据条件下的相对比较。','small')
        if opts['edition']=='standard':
            figure('psd','Welch 功率谱密度',155)
            add('采用最多 256 点的 Hann 分段与 50% 重叠，单边 PSD 使用采样率及窗能量归一化；分段去均值。','small')
            figure('correlation','当前信号自相关',145)
            add('自相关显示不同时间间隔的线性关联；周期性峰值可作为周期结构的线索，不单独据此判断随机性或故障。','small')
    if opts['edition']=='standard':
        if f['methods']:
            page('方法比较与参数')
            add('各方法使用本次实验的同一输入与比较目标。得分用于当前候选方法的相对选择；有干净参考时可结合 SNR 判断，无参考时属于启发式诊断。')
            table([['方法','得分','SNR / dB','搜索耗时 / ms']]+[[m['label'],fmt(m['score']),fmt(m['snr_db']),fmt(m['duration_ms'])] for m in f['methods']],[165,95,105,126])
            add('当前处理：'+f['method']+'。候选比较体现当前搜索范围，不保证在其他信号上仍最优。')
            for m in f['methods']:
                story.append(KeepTogether([para(m['label'],'h2'),para('；'.join(f'{k} = {v}' for k,v in m['parameters'].items()) or '无额外参数','small')]))
        if f['diagnosis']:
            page('异常诊断')
            d=f['diagnosis'];add(d['note']);story.append(Heatmap(d['spectrogram']))
            add(f'频率间隔 {fmt(d["frequency_resolution_hz"],"Hz")}，帧步长 {fmt(d["hop_seconds"],"s")}。颜色为本区间相对最大 PSD 的 -80 至 0 dB；两端补零区域可能产生边缘伪影。','small')
            evidence_names={'frequency_hz':'频率 / Hz','peak_band_fraction':'峰值频带功率占比','power_ratio':'相对基线功率倍数','curvature_peak':'二阶变化峰值','threshold':'判断阈值','samples':'区间点数','absolute_tolerance':'零值容差','plateau_value':'平台幅值','mean_departure':'均值偏离','initial_frequency_hz':'初始主频 / Hz','interval_frequency_hz':'区间主频 / Hz','resolution_hz':'频率间隔 / Hz'}
            table([['特征','相对时间 / s','证据与其他解释']]+[[e['label'],fmt(e['start'])+' - '+fmt(e['end']),'；'.join(evidence_names.get(k,k)+'：'+fmt(v) for k,v in e['evidence'].items())+'\n'+e['alternatives']] for e in d['events']],[100,95,296])
            if not d['events']:add('未检测到显著特征；这不能证明不存在异常。')
        page('结论与复现信息')
        for text in f['summary']:add(text)
        add('后续建议','h2')
        add('保存当前实验快照并导出完整实验 ZIP，可保留本次采样和参数。比较其他方案时固定输入与目标，结合波形、频谱和参考误差评估取舍。')
        if not f['has_reference']:add('如需评估真实恢复误差，建议补充同步的干净参考或已知标定数据。')
        table([['项目','记录'],['应用 / 算法 / 报告版式',f'{VERSION} / {ALGORITHM_VERSION} / {CONFIG["version"]}'],['绘图与计算',f'图表最多 {CONFIG["plot_points"]} 点；指标使用全部 {f["sample_count"]} 点'],['数据与结果 SHA-256',f['input_result_sha256']],['预览内容标识',f['token']]], [150,341])
        add('采样与处理参数','h2')
        for group in [f['configuration'],f['parameters']]:
            for key,value in group.items():add(f'{key}：{value}','small')
        add('相同参数、种子与运行环境可以复现仿真；导入完整实验包可保留已有采样。报告不包含模型 Key、聊天历史或服务器文件路径。','small')
    doc=SimpleDocTemplate(output,pagesize=A4,leftMargin=52,rightMargin=52,topMargin=58,bottomMargin=52,title=_text(opts['title']),author=_text(opts['author']),pageCompression=1)
    doc.build(story,onFirstPage=decoration,onLaterPages=decoration)
    return output.getvalue()
