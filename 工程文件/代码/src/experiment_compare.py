"""Read-only snapshot comparisons and portable, escaped HTML reports."""
from __future__ import annotations
import hashlib
import json
import math
from html import escape
import numpy as np
from .signal_processing import decimate_for_export


def _finite(value):
    return float(value) if value is not None and math.isfinite(float(value)) else None


def _identity(bundle):
    digest = hashlib.sha256()
    digest.update(str((float(bundle.config.sample_rate), bool(bundle.has_clean_reference))).encode())
    for values in (bundle.time, bundle.observed, *([bundle.clean] if bundle.has_clean_reference else [])):
        array = np.ascontiguousarray(values, dtype='<f8')
        digest.update(str(array.shape).encode()); digest.update(array.tobytes())
    return digest.hexdigest()


def compare_experiments(store, session, ids):
    if not isinstance(ids, list) or not 2 <= len(ids) <= 4 or any(not isinstance(key,str) for key in ids) or len(set(ids)) != len(ids):
        raise ValueError("请选择 2–4 个不同的已保存实验。")
    names = {row['id']:row['name'] for row in store.list(session)}
    if any(key not in names for key in ids):
        raise KeyError("Experiment not found in this browser session")
    rows = []
    with store.file_lock:
        for key in ids:
            state = store.load(key, session)
            from .diagnostics import lab_for
            lab = lab_for(state)
            if lab.get('blind') and not lab.get('revealed'):
                raise ValueError('请先打开并揭晓盲测快照，再进行跨实验对比。')
            bundle = state.bundle
            if bundle is None:
                raise ValueError("Selected experiment has no signal")
            result = state.processed
            values = result.signal if result is not None else bundle.observed
            comparison = state.preprocess_comparison or {}
            method = next((row for row in comparison.get('methods',[]) if result is not None and row['method']==result.method), {})
            # Time uses original seconds; curves and metrics keep physical scale.
            t, signal = decimate_for_export(bundle.time, values, max_points=520)
            centered = values - np.mean(values)
            spectrum = np.abs(np.fft.rfft(centered * np.hanning(len(values)))) / len(values)
            freqs = np.fft.rfftfreq(len(values), 1.0 / bundle.config.sample_rate)
            spectrum[0] = 0
            freq, amplitude = decimate_for_export(freqs, spectrum, max_points=520)
            rmse = snr = None
            if bundle.has_clean_reference:
                noise_power = float(np.mean((values-bundle.clean)**2))
                clean_power = float(np.mean(bundle.clean**2))
                rmse = math.sqrt(noise_power)
                snr = (99.0 if noise_power <= 1e-12 else 10*math.log10(clean_power/noise_power)) if clean_power > 0 else None
            rows.append({'id':key,'name':names[key],'input_sha256':_identity(bundle),'source':bundle.source,
                'sample_rate':bundle.config.sample_rate,'sample_count':len(values),'goal':state.comparison_goal,
                'method':result.method_label if result else '原始观测','parameters':result.parameters if result else {},
                'signal_config':bundle.config.to_dict(),'has_reference':bundle.has_clean_reference,
                'score_version':comparison.get('score_version'),'score':_finite(method.get('score')),
                'duration_ms':_finite(method.get('duration_ms')),'rms':_finite(np.sqrt(np.mean(values**2))),
                'peak':_finite(np.max(np.abs(values))),'rmse':_finite(rmse),'snr_db':_finite(snr),
                'dominant_frequency_hz':_finite(freqs[int(np.argmax(spectrum))]) if np.any(spectrum) else 0,
                'waveform':{'x':t,'y':signal},'spectrum':{'x':freq,'y':amplitude}})
    same_input = len({row['input_sha256'] for row in rows}) == 1
    same_goal = len({row['goal'] for row in rows}) == 1
    same_score = len({row['score_version'] for row in rows}) == 1 and rows[0]['score_version'] is not None
    comparable = same_input and same_goal and same_score and all(row['score'] is not None for row in rows)
    note = ('输入数据、参考信号、比较目标和评分版本一致，可直接比较评分。' if comparable else
            '仅展示各实验指标与参数差异；输入、参考、目标或评分信息不一致，不进行跨实验评分排名。')
    return {'experiments':rows,'same_input':same_input,'same_goal':same_goal,'score_comparable':comparable,
            'note':note,'plot_note':'叠加图共享坐标与量纲；FFT 幅值采用 Hann 窗并除以样本数，用于相对观察。计算指标使用完整样本。'}


COLORS = ('#7c3aed','#0891b2','#e66b1b','#15803d')


def comparison_svg(data, field):
    rows = data['experiments']
    points = [row[field] for row in rows]
    xmin, xmax = min(min(p['x']) for p in points), max(max(p['x']) for p in points)
    ymin, ymax = min(min(p['y']) for p in points), max(max(p['y']) for p in points)
    dx, dy = max(xmax-xmin,1e-12), max(ymax-ymin,1e-12)
    lines = []
    for row, color in zip(rows,COLORS):
        p=row[field]
        coords=' '.join(f'{60+800*(x-xmin)/dx:.2f},{250-210*(y-ymin)/dy:.2f}' for x,y in zip(p['x'],p['y']))
        lines.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="1.4"><title>{escape(row["name"])}</title></polyline>')
    label = '时间 / s' if field=='waveform' else '频率 / Hz'
    return (f'<svg viewBox="0 0 920 295" role="img" aria-label="{label}">'
            '<path d="M60 35V250H860" fill="none" stroke="#94a3b8"/>' + ''.join(lines) +
            f'<g fill="currentColor" font-size="12"><text x="60" y="275">{xmin:.4g}</text><text x="800" y="275">{xmax:.4g}</text>'
            f'<text x="400" y="288">{label}</text><text x="0" y="45">{ymax:.4g}</text><text x="0" y="250">{ymin:.4g}</text></g></svg>')


def comparison_html(data):
    labels = [('name','实验'),('method','处理方法'),('goal','目标'),('sample_count','点数'),('sample_rate','Hz'),
              ('rms','RMS'),('peak','峰值'),('dominant_frequency_hz','主频 / Hz'),('rmse','RMSE'),('snr_db','SNR / dB'),('duration_ms','搜索 / ms')]
    if data['score_comparable']:
        labels.append(('score','评分'))
    def value(value):
        return '—' if value is None else f'{value:.5g}' if isinstance(value,float) else str(value)
    table = '<table><thead><tr>'+''.join('<th>'+label+'</th>' for _,label in labels)+'</tr></thead><tbody>'
    for row in data['experiments']:
        table += '<tr>'+''.join('<td>'+escape(value(row.get(key)))+'</td>' for key,_ in labels)+'</tr>'
    table += '</tbody></table>'
    legend = ''.join(f'<span style="color:{color}">● {escape(row["name"])}</span>　' for row,color in zip(data['experiments'],COLORS))
    params = [{k:v for k,v in row.items() if k not in ('waveform','spectrum')} for row in data['experiments']]
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        '<title>实验对比报告</title><style>body{font:15px/1.65 system-ui;max-width:1200px;margin:30px auto;padding:20px;color:#182238}table{border-collapse:collapse;white-space:nowrap}td,th{padding:10px;text-align:left;border-bottom:1px solid #ddd}.scroll{overflow:auto}svg{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5fa;padding:18px}</style>'
        f'<h1>实验对比报告</h1><p>{escape(data["note"])}</p><p>无干净参考时，RMSE 和真实 SNR 显示为 —。</p><div class="scroll">{table}</div>'
        f'<h2>波形</h2><p>{legend}</p>{comparison_svg(data,"waveform")}<h2>频谱</h2>{comparison_svg(data,"spectrum")}'
        f'<p>{escape(data["plot_note"])}</p><h2>参数与输入摘要</h2><pre>{escape(json.dumps(params,ensure_ascii=False,indent=2))}</pre></html>').encode()
