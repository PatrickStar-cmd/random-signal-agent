"""Selectable measured figures shared by report preview and vector PDF output."""
import math
import json
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
    design = document.get('v0410') or {}
    inspection = design.get('inspection') or {}
    diagnostics = inspection.get('diagnostics') or []
    if diagnostics:
        add('run-diagnostics', '本次运行 · 测量诊断',
            rows=[[row['block_id'], row['title'], json.dumps(row['evidence'], ensure_ascii=False), row['hint']] for row in diagnostics],
            headers=['积木', '规则', '实际测量', '观察建议'])
    profile = inspection.get('profile') or result.get('experience', {}).get('observations') or []
    profile = sorted((row for row in profile if isinstance(row.get('elapsed_ms'), (int, float))), key=lambda row: row['elapsed_ms'], reverse=True)
    if profile:
        add('run-profile', '本次运行 · 积木耗时排序', [line('耗时 / ms', [row['elapsed_ms'] for row in profile], list(range(1, len(profile) + 1)))],
            [[row.get('label', row['id']), row['elapsed_ms'], row.get('rms'), row.get('peak')] for row in profile],
            ['积木', '耗时 ms', 'RMS', '峰值'], note='横轴为按实测耗时降序排列的积木序号。')
    traces = inspection.get('traces') or result.get('advanced', {}).get('algorithm_traces') or []
    for trace in traces:
        raw = trace.get('trace') or {}; raw = raw.get('learning') or raw
        history = raw.get('history') or []
        if not history:
            continue
        series = []
        for key, title in [('unsatisfied_checks', '未满足校验'), ('changed_bits', '改变比特数'), ('mean_abs_posterior', '平均后验可靠度')]:
            if any(key in row for row in history):
                series.append(line(title, [row.get(key) for row in history], [row.get('iteration', i + 1) for i, row in enumerate(history)]))
        for key in ('scores', 'path_metrics'):
            width = min(8, max((len(row.get(key, [])) for row in history), default=0))
            for index in range(width):
                series.append(line('状态 / 路径 ' + str(index), [row.get(key, [])[index] if index < len(row.get(key, [])) else None for row in history]))
        summary_keys = [key for key in ('step', 'iteration', 'bit', 'frozen', 'unsatisfied_checks', 'changed_bits', 'mean_abs_posterior') if any(key in row for row in history)]
        rows = [[i + 1, *[row.get(key) for key in summary_keys]] for i, row in enumerate(history[:64])]
        add('run-trace-' + trace['block_id'], '本次算法步骤 · ' + trace['kind'] + ' · ' + trace['block_id'], series, rows, ['步骤', *summary_keys],
            note=f"实际输入 {trace.get('input', {}).get('count', 0)} 点，输出 {trace.get('output', {}).get('count', 0)} 点；显示本次前 {min(64, len(history))} 步。")
    optimization = design.get('optimization') or {}
    if optimization.get('candidates'):
        a, b = optimization['objectives']; candidates = optimization['candidates']
        groups = [('Pareto 方案', [row for row in candidates if row['pareto']]), ('满足约束', [row for row in candidates if row['feasible'] and not row['pareto']]), ('待满足约束', [row for row in candidates if not row['feasible']])]
        series = [line(title, [row['metrics'][b['metric']] for row in rows], [row['metrics'][a['metric']] for row in rows]) for title, rows in groups if rows]
        add('design-pareto', '受约束选参 · Pareto 实测方案', series,
            [[row['index'] + 1, str(row['values']), row['metrics'][a['metric']], row['metrics'][b['metric']], row['feasible'], row['pareto']] for row in candidates],
            ['候选', '参数 A / B', a['metric'], b['metric'], '满足约束', 'Pareto'],
            note=f"横轴 {a['metric']}（{a['direction']}），纵轴 {b['metric']}（{b['direction']}）；共 {optimization.get('completed', 0)} 次测量，使用相同种子与帧序号。")
    scenario = design.get('scenarioResult') or {}
    if scenario.get('rows'):
        rows = scenario['rows']; metric = scenario['settings']['recovery']['metric']; events = scenario['settings']['events']
        add('scenario-metrics', '帧级场景 · ' + metric, [line(metric, [row['metrics'].get(metric) for row in rows], [row['frame'] for row in rows])],
            [[row['frame'], row['block_id'], row['parameter'], row['value'], row['transition']] for row in events],
            ['事件帧', '积木', '参数', '目标值', '变化方式'], note=f"帧号从 1 开始，跨帧保留 {scenario.get('state_count', 0)} 组运行状态。")
        add('scenario-recovery', '帧级场景 · 恢复帧数',
            rows=[[row['event_frame'], row['window_end'], row['recovered_frame'], row['recovery_frames'], row['confirmation_frame']] for row in scenario['recoveries']],
            headers=['事件帧', '观察截止', '恢复起始', '恢复帧数', '确认帧'],
            note=f"每个事件窗口内连续 {scenario['settings']['recovery']['consecutive']} 帧满足阈值后确认恢复。")
    classroom = design.get('teacher') or {}
    if classroom.get('rows'):
        add('teacher-review', '教师评阅 · ' + classroom['task']['title'],
            rows=[[row['student'], str(row['completed_stages']) + '/' + str(row['total_stages']), row['imported_score'], (row.get('recheck') or {}).get('score'), row['attempts'], row['hints'], row.get('comment', '')[:80] + ('…' if len(row.get('comment', '')) > 80 else '')] for row in classroom['rows']],
            headers=['学生', '阶段', '原始分数', '重验分数', '尝试', '提示', '评语'],
            note='重验分数使用各阶段独立工程快照与题目原始种子重新计算。')
        comments = [[row['student'], row['comment'][offset:offset + 200]] for row in classroom['rows']
                    for offset in range(0, len(row.get('comment', '')), 200)]
        if comments:
            add('teacher-comments', '教师评阅 · 完整评语', rows=comments, headers=['学生', '评语'])
    flow = design.get('flowResult') or {}
    if flow.get('merged_result'):
        branches = [*flow.get('branches', []), {'name': '汇合输出', 'result': flow['merged_result']}]
        add('flow-merge', '多路接收 · 汇合对照', rows=[[branch['name'], branch['result']['metrics'].get('ber'), branch['result']['metrics'].get('evm_percent')] for branch in branches],
            headers=['接收方案', 'BER', 'EVM %'], note='汇合设置：' + json.dumps({key: value for key, value in flow.get('merge', {}).items() if key in ('mode', 'domain', 'weights', 'select', 'count', 'sample_rate')}, ensure_ascii=False))
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
            note='行：子载波；列：用户。' if ofdma else ('行：单路；列：信道抽头。' if kind=='rx_mlse' else ('首个估计矩阵；' if indexed else '')+'行：接收天线；列：发送天线。')
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
        mlse = value.get('mlse') or {}
        if mlse.get('metric_history'):
            history = mlse['metric_history']; width = min(8, len(history[0]))
            add(kind + '-trellis', label + ' · 实际路径度量', [line('状态 ' + str(index), [row[index] for row in history]) for index in range(width)],
                [[i + 1, state, mlse['input_indices'][i]] for i, state in enumerate(mlse['survivor_states'])], ['步骤', '幸存状态', '输出符号索引'],
                note=f"网格共 {mlse['state_count']} 个状态，实际计算 {mlse['metric_evaluations']} 次分支度量；图中显示前 {width} 个状态。")
        music = value.get('music') or {}
        if music.get('angles'):
            add(kind + '-music', label + ' · MUSIC 空间谱', [line('归一化空间谱 / dB', music['spectrum_db'], music['angles'])],
                [[i + 1, angle, i == music['target_index']] for i, angle in enumerate(music['estimated_angles'])], ['源', '估计角度 / °', '目标信号'],
                note=f"接收快照 {music['snapshots']} 个；子阵长度 {music['subarray_length']}；目标角度由公共训练识别。")
        if kind == 'tdl_channel' and value.get('delays_ns'):
            add('tdl-delay-power', value['profile'] + ' · 时延功率谱',
                [line('实测抽头功率', value['measured_path_power'], value['delays_ns']), line('目标平均功率', value['powers'], value['delays_ns'])],
                [[i + 1, delay, value['powers_db'][i], value['measured_path_power'][i]] for i, delay in enumerate(value['delays_ns'])],
                ['路径', '时延 / ns', '配置功率 / dB', '实测功率'], note=f"RMS 时延扩展 {value['rms_delay_ns']:.5g} ns；多普勒 {value['doppler_hz']:.5g} Hz。")
            gains = value.get('path_gains') or {}
            if gains.get('i'):
                amplitude = abs(np.asarray(gains['i']) + 1j * np.asarray(gains['q']))
                add('tdl-path-time', value['profile'] + ' · 抽头时间演化', heatmap={'values': amplitude.tolist(), 'x': list(range(1, amplitude.shape[1] + 1)), 'y': value['sample_indices']}, note='横轴为路径序号，纵轴为真实连续采样位置，颜色为抽头幅度。')
        if kind == 'rx_self_frame' and value.get('frames'):
            columns = ['sequence', 'start_sample', 'payload_bits', 'mcs_name', 'header_crc_pass', 'payload_crc_pass', 'duplicate']
            add('self-frame-events', label + ' · 连续帧接收', rows=[[row.get(key) for key in columns] for row in value['frames']],
                headers=['序号', '起始采样', '载荷比特', 'MCS', '帧头 CRC', '载荷 CRC', '重复帧'],
                note=f"已接收 {value['received_bits']} / {value['total_bits']} 个业务比特，完整组装：{value['complete_payload']}。")
        sensing = value.get('sensing') or {}
        if sensing.get('power_db'):
            add(kind + '-range-doppler', label + ' · 距离速度图',
                heatmap={'values': sensing['power_db'], 'x': sensing['range_axis_m'], 'y': sensing['velocity_axis_mps']},
                rows=[[sensing['range_m'], sensing['velocity_mps'], sensing['detected'], sensing['peak_background_db'], sensing['range_resolution_m'], sensing['velocity_resolution_mps']]],
                headers=['距离 m', '速度 m/s', '检测', '峰背景比 dB', '距离分辨率 m', '速度分辨率 m/s'],
                note='横轴：实际距离 / m；纵轴：实际径向速度 / m/s；颜色：接收距离多普勒功率 / dB。')
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
