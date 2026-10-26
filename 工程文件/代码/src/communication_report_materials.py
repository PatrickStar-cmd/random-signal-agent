"""Selectable measured figures shared by report preview and vector PDF output."""
import math
import numpy as np
from reportlab.lib import colors
from reportlab.platypus import Flowable
from src import pdf_report


def materials(document):
    items = []
    def add(key, title, series=None, rows=None, headers=None, heatmap=None, note=''):
        items.append({'id': key, 'title': title, 'series': series or [], 'rows': rows or [],
                      'headers': headers or [], 'heatmap': heatmap, 'note': note})
    def line(name, values, x=None, interval=None):
        return {'name': name, 'x': list(range(len(values))) if x is None else list(x),
                'y': list(values), 'interval': interval}
    experiments = document.get('experiments') or {}
    batch = experiments.get('batchResult') or {}
    summaries = batch.get('summaries', [])
    if summaries:
        measured = [(i + 1, s) for i, s in enumerate(summaries) if s.get('ber') is not None and s['bit_count'] > 0]
        if measured:
            rows = [[s['name'], s['runs'], s['bit_count'], s['bit_errors'], s['ber']] for _, s in measured]
            add('batch-ber', '批量实验 BER 与 95% 区间',
                [line('BER', [s['ber'] for _, s in measured], [i for i, _ in measured], interval=[s['ber_interval'] for _, s in measured])],
                rows, ['工程', '次数', '比特数', '错误数', 'BER'], note='横轴为批量队列中的工程序号；区间由累计比特计数计算。')
        for key, title in [('goodput_bps', '有效吞吐 / bit/s'), ('mean_delivery_latency_seconds', '交付时延 / s'), ('frame_duration_seconds', '帧发送时长 / s')]:
            series = []
            for i, summary in enumerate(summaries):
                values = sorted(r['metrics'][key] for r in batch.get('rows', []) if r['program_index'] == i and r['metrics'].get(key) is not None)
                if values: series.append(line(summary['name'], [(j + 1) / len(values) for j in range(len(values))], values))
            if series: add('batch-' + key, title + '累积分布', series, note='横轴为实测值，纵轴为累计比例。')
    search = experiments.get('searchResult') or {}
    points = search.get('points', [])
    if points:
        add('target-search', '目标信噪比搜索', [line('BER', [p['ber'] for p in points], [p['snr_db'] for p in points], [p['ber_interval'] for p in points])],
            [[p['snr_db'], p['bit_count'], p['bit_errors'], p['ber'], p['passed']] for p in points], ['SNR / dB', '比特数', '错误数', 'BER', '达标'])
    submission = experiments.get('submission') or {}
    stages = submission.get('stages') or []
    if isinstance(stages, dict): stages = list(stages.values())
    if stages:
        task_stages = submission.get('task', {}).get('stages', [])
        rows = [[i + 1, task_stages[i]['name'] if i < len(task_stages) else '阶段成果', s.get('number', 0) if s else 0, bool(s and s.get('passed'))] for i, s in enumerate(stages)]
        add('classroom-stages', '分阶段学习成果', rows=rows, headers=['阶段', '名称', '提交次数', '达标'],
            note=f"尝试记录 {len(submission.get('attempts', []))} 次；提示记录 {len(submission.get('hint_events', []))} 次。")
    elif experiments.get('taskResult'):
        task = experiments['taskResult']
        add('classroom-stages', '教学任务验收', rows=[[i + 1, s.get('name', s.get('title', '阶段')), s.get('passed')] for i, s in enumerate(task.get('stages', []))], headers=['阶段', '名称', '达标'], note=f"总分 {task.get('score', 0):g}。")
    learning = document.get('learning') or {}
    scan = learning.get('scan') or {}
    if scan.get('points'):
        points = scan['points']
        xs = list(dict.fromkeys(p['x'] for p in points)); ys = list(dict.fromkeys(p['y'] for p in points))
        matrix = [[next((p.get('ber') for p in points if p['x'] == x and p['y'] == y), None) for x in xs] for y in ys]
        add('scan-2d', '二维参数扫描 BER', heatmap={'values': matrix, 'x': xs, 'y': ys}, note='行列标签对应实际扫描参数值。')
    for key, title in [('protocolResult', '闭环重传过程'), ('amcResult', '自适应调制编码过程')]:
        result = learning.get(key) or {}
        events = result.get('events') or result.get('frames') or result.get('timeline') or []
        if events:
            columns = [k for k in ('packet', 'frame', 'attempt', 'start_seconds', 'end_seconds', 'event', 'crc_pass', 'profile', 'snr_db', 'goodput_bps') if any(k in row for row in events)]
            if not columns: columns = list(events[0])[:6]
            add(key, title, rows=[[str(row.get(k, '')) for k in columns] for row in events[:100]], headers=columns,
                note=f"保存 {len(events)} 条事件；图表列出前 100 条。")
    result = document.get('result') or {}
    for kind, value in (result.get('advanced', {}).get('wireless') or {}).items():
        from src import communications as c
        label = c.BLOCKS.get(kind, {}).get('label', kind)
        resources = value.get('resources') or {}
        matrix = value.get('channel_estimate') or value.get('channel_matrix')
        if matrix:
            a = np.asarray(matrix['i']) + 1j * np.asarray(matrix['q'])
            indexed=a.ndim==3
            if a.ndim == 3: a = a[0]
            if a.ndim == 1: a = a[None, :]
            ofdma=bool(resources and isinstance(value.get('users'),list))
            note='行：子载波；列：用户。' if ofdma else ('首个估计矩阵；' if indexed else '')+'行：接收天线；列：发送天线。'
            y=resources.get('subcarriers',list(range(a.shape[0]))) if ofdma else list(range(a.shape[0]))
            add(kind + '-matrix', label + ' · 信道幅度', heatmap={'values': abs(a).tolist(), 'x': list(range(a.shape[1])), 'y': y}, note=note)
        if resources.get('owners'):
            owners = resources['owners'][:64]
            add(kind + '-resources', label + ' · 资源分配', heatmap={'values': owners, 'x': list(range(len(owners[0]))), 'y': list(range(len(owners)))}, note='横轴：子载波；纵轴：OFDM 时隙；数值为用户编号，−1 为空闲。')
        users = value.get('users') or []
        if isinstance(users, list) and any('queue_history' in u for u in users):
            add(kind + '-queues', label + ' · 用户队列', [line('用户 ' + str(u['id'] + 1), u['queue_history']) for u in users if 'queue_history' in u],
                [[u['id'] + 1, u.get('ber'), u.get('throughput_bps'), u.get('mean_delay_seconds')] for u in users], ['用户', 'BER', '吞吐 bit/s', '时延 s'])
        sic = value.get('sic') or {}
        if sic.get('residual_power'):
            positions=sic.get('sample_indices',list(range(len(sic['residual_power']))))
            add(kind + '-sic', label + ' · 干扰抵消残差', [line('样本 ' + str(positions[i]), powers) for i, powers in enumerate(sic['residual_power'][:4])], note='横轴：检测层；纵轴：残余功率。样本位置沿用接收结果的实际时隙／子载波索引。')
        llr = value.get('llr')
        if isinstance(llr, list) and llr: add(kind + '-llr', label + ' · 软信息', [line('LLR', np.asarray(llr).ravel()[:512].tolist())])
        beam = value.get('beam_pattern')
        if beam:
            add(kind + '-beam', label + ' · 波束方向图', [line('波束 ' + str(i + 1), row, beam['angles']) for i, row in enumerate(beam['db'])], note='横轴：角度 / °；纵轴：归一化功率 / dB。')
        noise = value.get('effective_noise_variance')
        if noise: add(kind + '-noise', label + ' · 有效噪声', [line('检测后方差', noise[:512])])
        if value.get('input_amplitude') and value.get('output_amplitude'):
            pairs = sorted(zip(value['input_amplitude'], value['output_amplitude']))
            add(kind + '-amplitude', label + ' · 幅度响应', [line('输出幅度', [v[1] for v in pairs], [v[0] for v in pairs])], note='回环或实际发送波形的输入／输出包络。')
    return items


def prepare(document):
    available = materials(document)
    options = document.get('report') or {}
    chosen = options.get('materials', [v['id'] for v in available])
    if not isinstance(chosen, list) or len(chosen) > 64 or any(not isinstance(k, str) for k in chosen):
        raise ValueError('请选择最多 64 项报告素材。')
    captions = options.get('captions') or {}
    if not isinstance(captions, dict) or any(not isinstance(v, str) or len(v) > 1200 for v in captions.values()):
        raise ValueError('每张图注最多 1200 字。')
    conclusion = options.get('conclusion', '')
    if not isinstance(conclusion, str) or len(conclusion) > 8000: raise ValueError('实验结论最多 8000 字。')
    selected = [{**item, 'caption': captions.get(item['id'], '')} for item in available if item['id'] in chosen]
    return available, selected, conclusion


class MaterialFigure(Flowable):
    """Small vector chart; uses the same numeric payload as the browser preview."""
    def __init__(self, item):
        super().__init__(); self.item = item; self.width = 490; self.height = 220

    def draw(self):
        cv = self.canv; cv.setFont(pdf_report.FONT, 8)
        left, bottom, width, height = 48, 33, 422, 165
        heatmap = self.item['heatmap']
        if heatmap:
            values = heatmap['values']; finite = [v for row in values for v in row if v is not None and math.isfinite(v)]
            lo, hi = min(finite, default=0), max(finite, default=1)
            rows, cols = len(values), len(values[0])
            for i, row in enumerate(values):
                for j, value in enumerate(row):
                    fraction = 0 if value is None else (value - lo) / max(hi - lo, 1e-12)
                    cv.setFillColor(colors.Color(.88 - .55 * fraction, .94 - .42 * fraction, .98 - .2 * fraction))
                    cv.rect(left + j * width / cols, bottom + (rows - 1 - i) * height / rows, width / cols, height / rows, fill=1, stroke=0)
            cv.setFillColor(colors.HexColor('#395675'))
            cv.drawString(left, 12, f"X: {heatmap['x'][0]} → {heatmap['x'][-1]}   Y: {heatmap['y'][0]} → {heatmap['y'][-1]}   值: {lo:.4g} → {hi:.4g}")
            return
        series = self.item['series']; xs = [x for s in series for x in s['x'] if isinstance(x, (int, float)) and math.isfinite(x)]
        ys = [y for s in series for y in s['y'] if isinstance(y, (int, float)) and math.isfinite(y)]
        ys += [y for s in series for pair in s.get('interval') or [] for y in pair if math.isfinite(y)]
        if not xs or not ys: return
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(0, min(ys)), max(ys)
        if xmin==xmax: xmin-=.5; xmax+=.5
        px = lambda x: left + (x - xmin) / max(xmax - xmin, 1e-12) * width
        py = lambda y: bottom + (y - ymin) / max(ymax - ymin, 1e-12) * height
        cv.setStrokeColor(colors.HexColor('#c5d5e6')); cv.rect(left, bottom, width, height)
        cv.setFillColor(colors.HexColor('#395675'))
        for fraction in (0, .5, 1):
            cv.drawRightString(left - 5, bottom + fraction * height, f'{ymin + fraction * (ymax - ymin):.3g}')
            cv.drawCentredString(left + fraction * width, bottom - 16, f'{xmin + fraction * (xmax - xmin):.3g}')
        for i, s in enumerate(series):
            color=colors.HexColor(['#477ac7', '#9673c8', '#339a94', '#bd8a39'][i % 4]); cv.setStrokeColor(color); cv.setFillColor(color)
            cv.drawString(left + (i % 3) * 140, self.height - 12 - (i // 3) * 11, str(s['name'])[:18])
            previous = None
            for j, (x, y) in enumerate(zip(s['x'], s['y'])):
                if y is None or not math.isfinite(y): previous = None; continue
                point = px(x), py(y)
                if previous: cv.line(*previous, *point)
                cv.circle(*point, 1.7, fill=1, stroke=0)
                if s.get('interval'): cv.line(px(x), py(s['interval'][j][0]), px(x), py(s['interval'][j][1]))
                previous = point
