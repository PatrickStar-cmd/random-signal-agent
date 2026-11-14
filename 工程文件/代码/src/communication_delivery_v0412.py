"""Named experiment records, complete course recipes and portable measured bundles."""
import base64
import copy
import csv
import hashlib
import gzip
import io
import json
import platform
import zipfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from html import escape
from src import communications as c, communication_studio as studio

ROOT = Path(__file__).resolve().parents[1]


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _metrics(document):
    graph = document.get('graphResult') or {}
    result = graph.get('merged_result') or document.get('result') or {}
    values = {key: value for key, value in result.get('metrics', {}).items() if isinstance(value, (int, float))}
    for branch in graph.get('branches', []):
        values.update({branch['id'] + '.' + key: value for key, value in branch['result']['metrics'].items() if isinstance(value, (int, float))})
    for analysis in graph.get('analyses', []):
        values[analysis['id'] + '.detections'] = len(analysis['detections'])
        values[analysis['id'] + '.crossing_fraction'] = analysis['crossing_fraction']
    return values


def record(document, name):
    """Store the complete reproducible configuration and its measured baseline."""
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValueError('记录名称需要 1 至 100 个字符。')
    doc = studio.validate_document(document)
    metrics = _metrics(doc)
    input_hash = (doc.get('workbenchResult') or doc.get('graphResult') or {}).get('input_hash')
    if not doc.get('graph') and doc.get('result', {}).get('experience', {}).get('frame', 0):
        doc['program']['seed'] = doc['result']['seed']
        doc['result']['experience']['frame'] = 0
    configuration = {'document_schema','name','description','program','graph','graphActiveBranch','tools',
                     'groups','library','subprojects','scratch','variables','annotations','branches','activeBranch',
                     'probes','scope','report','formValues','sweepSettings','breakpoints','workbenchScope'}
    metadata = doc.get('delivery') or {}
    learning = doc.get('learning') or {}
    doc = {k:v for k,v in doc.items() if k in configuration}
    doc['delivery'] = {k:v for k,v in metadata.items() if k in ('lesson','answers')}
    if learning: doc['learning'] = {k:v for k,v in learning.items() if k in ('variables','bindings')}
    encoded = _json(doc); created = datetime.now(timezone.utc).isoformat()
    return {'id': uuid.uuid4().hex[:20], 'name': name.strip(),
            'created': created, 'document_encoding': 'gzip-base64',
            'document_data': base64.b64encode(gzip.compress(encoded, mtime=0)).decode('ascii'),
            'seed': doc.get('graph', {}).get('globals', doc['program'])['seed'],
            'input_hash': input_hash, 'metrics': metrics}


def restore_record(value):
    if value.get('document_encoding') != 'gzip-base64': raise ValueError('请选择有效的命名记录。')
    with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(value['document_data'], validate=True))) as data:
        raw = data.read(c.CONFIG['max_project_bytes'] + 1)
    if len(raw) > c.CONFIG['max_project_bytes']: raise ValueError('记录工程超过文档大小上限。')
    return {'document': studio.validate_document(json.loads(raw))}


def _configuration(document):
    graph = document.get('graph')
    if graph:
        from src.communication_graph_v0411 import lanes
        parameters = {f'globals.{key}': value for key, value in graph['globals'].items()}
        blocks = {lane + '/' + block['id']: block for lane, members in lanes(graph) for block in members}
        edges = graph['edges']
        for key, value in graph['merge'].items(): parameters['merge.' + key] = value
        for item in graph['analyses']:
            for key, value in item['params'].items(): parameters[item['id'] + '.' + key] = value
    else:
        program = document['program']
        parameters = {f'globals.{key}': program[key] for key in ('seed', 'sample_rate', 'sample_count', 'symbol_rate')}
        blocks = {'linear/' + b['id']: b for b in program['blocks']}
        keys = list(blocks)
        edges = [{'from': a, 'to': b} for a, b in zip(keys, keys[1:])]
    for path, block in blocks.items():
        parameters[path + '.kind'] = block['kind']
        for key, value in block['params'].items(): parameters[path + '.' + key] = value
    parameters['tools'] = document.get('tools', [])
    return parameters, {json.dumps(edge, sort_keys=True, ensure_ascii=False) for edge in edges}


def compare(before, after):
    a, b = (restore_record(value)['document'] if 'document_data' in value else studio.validate_document(value.get('document', value)) for value in (before, after))
    pa, ea = _configuration(a); pb, eb = _configuration(b)
    ma, mb = before.get('metrics', _metrics(a)), after.get('metrics', _metrics(b))
    return {'parameters': [{'path': key, 'before': pa.get(key), 'after': pb.get(key)}
                           for key in sorted(pa.keys() | pb.keys()) if pa.get(key) != pb.get(key)],
            'connections': {'added': [json.loads(v) for v in sorted(eb - ea)], 'removed': [json.loads(v) for v in sorted(ea - eb)]},
            'metrics': [{'metric': key, 'before': ma.get(key), 'after': mb.get(key),
                         'difference': mb[key] - ma[key] if key in ma and key in mb else None}
                        for key in sorted(ma.keys() | mb.keys())],
            'seeds': [a.get('graph', {}).get('globals', a['program'])['seed'], b.get('graph', {}).get('globals', b['program'])['seed']]}


# Each recipe names an existing, executable communication chain and a full lesson.
LESSONS = [
 ('analog', '模拟调制与恢复', 'analog_am', '理解载波、调制度和包络恢复。', '提高调制度后，包络和恢复误差如何变化？', ['运行 AM 预设并保存基线。', '改变调制度并观察已调波形与恢复波形。', '载入 FM 预设，用相同信息信号比较频谱。'], ['包络形状', '恢复信号 RMSE', '频谱占用'], '说明调制度变化如何影响恢复波形。', '比较 AM 与 FM 在同类噪声下的恢复质量。', 'rmse', 2),
 ('digital', '数字调制与星座', 'digital', '连接比特映射、星座距离和误码。', '增加信噪比后，星座云和误码率如何变化？', ['运行 QPSK 并标记信道观察点。', '扫描噪声参数，保持种子列表一致。', '记录误码计数与星座形状。'], ['星座散布', 'BER', '比特数'], '用星座距离解释观测到的误码变化。', '换用 16QAM 比较相同信噪比下的结果。', 'ber', .2),
 ('coding', '编码与软判决译码', 'soft_viterbi', '观察软信息如何参与卷积码译码。', 'LLR 幅度与接收可信度有什么关系？', ['运行软 Viterbi 预设。', '查看软解调输出与译码路径。', '使用已有硬软译码对照，记录同种子误码。'], ['LLR', '译码路径', '编码前后误码'], '指出软判决改进对应的实际接收信息。', '比较不同噪声水平下的硬软译码差值。', 'ber', .1),
 ('sync', '载波与符号同步', 'complex_receiver', '理解频偏、相位与符号定时恢复。', '频偏增大时，接收星座会怎样旋转？', ['标记同步前后观察点。', '改变信道频偏并运行。', '检查同步估计和恢复星座。'], ['频偏估计', '同步前后星座', 'EVM'], '关联同步参数与接收质量。', '在同一种子下对比两组恢复参数。', 'ber', .2),
 ('equalizer', '多径与自适应均衡', 'complex_nlms', '观察符号间干扰和均衡器收敛。', '步长增加时，收敛速度和残余误差怎样变化？', ['运行多径 NLMS 链路。', '查看均衡前后波形和抽头。', '改变步长并保存命名记录。'], ['均衡误差', '滤波抽头', 'BER'], '解释步长与接收误差的关系。', '改用 DFE 并比较相同信道输入。', 'ber', .2),
 ('ofdm', 'OFDM 与频率选择性信道', 'ofdm_cfo_tracking', '理解循环前缀、导频和子载波均衡。', '多径时延接近循环前缀长度时会出现什么现象？', ['运行导频跟踪 OFDM 链路。', '观察频域信道估计与星座。', '改变循环前缀及配对接收参数后比较。'], ['子载波响应', 'EVM', '频偏轨迹'], '根据实际频域结果解释循环前缀的作用。', '载入 TDL 信道示例观察时变多径。', 'ber', .2),
 ('rf', '射频非线性与数字预失真', 'memory_pa_dpd', '观察功放非线性和回环训练补偿。', '补偿前后频谱扩展和幅度响应怎样变化？', ['运行记忆功放与 DPD 示例。', '载入未补偿参考工程作为对照。', '用相同种子查看频谱和幅度响应。'], ['功放幅度响应', 'PAPR', 'EVM'], '用回环实测曲线说明补偿效果。', '改变功放参数后重新训练并比较。', 'ber', .2),
 ('spatial', '多天线与空间接收', 'mimo_mmse_sic', '理解空间流、信道矩阵与逐层抵消。', '先检测不同空间流如何影响残余干扰？', ['运行 MMSE-SIC。', '定位一个时隙并联动查看矩阵与星座。', '比较检测前后的残余功率。'], ['信道矩阵', '检测顺序', 'SIC 残差'], '说明空间检测如何恢复并行数据流。', '与 ZF-SIC 或 MUSIC/MVDR 示例比较。', 'ber', .2),
 ('protocol', '重传与自适应传输', 'business_packets', '连接实际物理误码、CRC 反馈和交付吞吐。', '增加重试预算时，交付率和时延如何变化？', ['运行文件分包链路。', '在闭环协议中选择当前物理链路并运行 ARQ。', '比较同预算 HARQ，记录 ACK、实际时长和吞吐。'], ['CRC 与 ACK', '重试次数', '有效吞吐及交付时延'], '说明可靠交付与传输开销的关系。', '在自适应速率任务中观察 MCS 档位变化。', 'ber', .2),
 ('iq', '录波回放与业务恢复', 'iq_replay', '通过真实复采样数据完成接收回放。', '固定同一段录波后，接收参数变化会影响哪些结果？', ['载入内置 I/Q 录波并运行。', '导出 SigMF，再导入同一文件。', '将录波与工程一起导出成果包并复跑。'], ['采样率与接收样本数', '星座', '恢复数据'], '记录录波格式、采样率与接收设置。', '回放自描述连续物理帧录波并观察重捕获。', 'received_bits', 1),
 ('branches', '共享输入与分支汇合', '@equalizer', '在完全相同的信道观测上比较 NLMS 与 DFE。', '改变分支 B 的步长后，哪些区段需要重新执行？', ['运行两分支均衡示例并保存基线。', '只修改 DFE 步长，执行局部重跑。', '比较两分支、汇合结果和实际执行记录。'], ['共享输入摘要', '分支 BER', '汇合结果', '复用积木数'], '指出本次修改的范围及其实际影响。', '比较选择一路与 LLR 加权汇合。', 'ber', .1),
 ('sensing', '多目标通感与 CFAR', '@sensing', '在同一帧内观察通信恢复与多目标检测。', '降低虚警概率后，门限与检测清单怎样变化？', ['运行多目标 OFDM 示例。', '查看功率、门限与局部噪声热图。', '调整 CFAR 参数后局部重跑并比较检测峰。'], ['距离速度峰', '检测门限', '有效检测区域', '通信 BER'], '对照目标配置说明测距测速与门限变化。', '设置静止目标和负速度目标并比较。', 'ber', .1),
]


def courses():
    return [{'id': row[0], 'title': row[1], 'objective': row[3], 'number': i + 1} for i, row in enumerate(LESSONS)]


def course(key):
    try: row = next(v for v in LESSONS if v[0] == key)
    except StopIteration as exc: raise ValueError('请选择课程列表中的实验。') from exc
    key, title, preset, objective, prediction, steps, observations, conclusion, challenge, metric, threshold = row
    doc = {'document_schema': 2, 'name': title}
    if preset.startswith('@'):
        from src import communication_graph_v0411 as graph
        doc['graph'] = graph.demo(preset[1:]); doc['program'] = graph.projection(doc['graph'], doc['graph']['branches'][0]['id'])
    else: doc['program'] = copy.deepcopy(c.PRESETS[preset]['program'])
    lesson = {'id': key, 'title': title, 'objective': objective, 'prediction': prediction, 'steps': steps,
              'observations': observations, 'conclusion': conclusion, 'challenge': challenge,
              'seeds': [42, 1042, 2042], 'metric': metric, 'operator': '>=' if key == 'iq' else '<=', 'threshold': threshold}
    doc['tools'] = [{'id': 'course-check', 'kind': 'assertion', 'metric': metric, 'operator': lesson['operator'], 'value': threshold}]
    doc['delivery'] = {'lesson': lesson, 'answers': {'prediction': '', 'observation': '', 'conclusion': '', 'challenge': ''}, 'records': []}
    return {'lesson': lesson, 'document': studio.validate_document(doc)}


def _csv(rows):
    out = io.StringIO(newline=''); writer = csv.writer(out); writer.writerows(rows)
    return out.getvalue().encode('utf-8-sig')


def _figure_svg(item):
    """Small standalone export of precisely the same measured report material."""
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="960" height="480" viewBox="0 0 960 480">',
             '<rect width="960" height="480" fill="#f4fbff"/>', '<g font-family="sans-serif" font-size="15" fill="#294e69">',
             '<text x="50" y="28">' + escape(item['title']) + '</text>']
    heat = item['heatmap']
    if heat:
        rows, cols = len(heat['values']), len(heat['values'][0]); finite = [v for row in heat['values'] for v in row if v is not None]
        low, high = min(finite, default=0), max(finite, default=1)
        for i, row in enumerate(heat['values']):
            for j, value in enumerate(row):
                z = 0 if value is None else (value - low) / max(high - low, 1e-12)
                y = rows - 1 - i if heat.get('origin_bottom') else i
                parts.append(f'<rect x="{60+j*840/cols}" y="{55+y*350/rows}" width="{840/cols+.1}" height="{350/rows+.1}" fill="hsl(210 55% {95-55*z}%)"/>')
        for marker in heat.get('markers', []):
            y = rows - 1 - marker['row'] if heat.get('origin_bottom') else marker['row']
            parts.append(f'<circle cx="{60+(marker["column"]+.5)*840/cols}" cy="{55+(y+.5)*350/rows}" r="5" fill="none" stroke="#bc8b26" stroke-width="2"/>')
        region = heat.get('valid_region')
        if region:
            y = rows - region['row'][1] if heat.get('origin_bottom') else region['row'][0]
            parts.append(f'<rect x="{60+region["column"][0]*840/cols}" y="{55+y*350/rows}" width="{(region["column"][1]-region["column"][0])*840/cols}" height="{(region["row"][1]-region["row"][0])*350/rows}" fill="none" stroke="#bc8b26" stroke-width="2"/>')
        parts.append('<text x="60" y="445">' + escape(f'X: {heat["x"][0]:.5g} → {heat["x"][-1]:.5g}   Y: {heat["y"][0]:.5g} → {heat["y"][-1]:.5g}') + '</text>')
    elif item['series']:
        xs = [v for series in item['series'] for v in series['x'] if v is not None]
        ys = [v for series in item['series'] for v in series['y'] if v is not None]
        if xs and ys:
            lo, hi, ymin, ymax = min(xs), max(xs), min(0, min(ys)), max(ys)
            for i, series in enumerate(item['series']):
                points = ' '.join(f'{60+(x-lo)/max(hi-lo,1e-12)*840},{405-(y-ymin)/max(ymax-ymin,1e-12)*350}' for x, y in zip(series['x'], series['y']) if x is not None and y is not None)
                parts.append(f'<polyline points="{points}" fill="none" stroke="{["#477ac7","#9673c8","#339a94"][i%3]}" stroke-width="2"/>')
    return (''.join(parts) + '</g></svg>').encode()


def bundle(document):
    """The archive is self-contained data plus a runner for the installed engine."""
    from src import communication_report as report
    from src.workbench import VERSION
    doc = studio.validate_document(document)
    facts = report.facts(doc)
    files = {'document.json': _json(doc), 'result.json': _json(doc.get('graphResult') or doc.get('result') or {}),
             'report.pdf': report.render(doc), 'requirements.txt': (ROOT / 'requirements-repro.txt').read_bytes()}
    # The runner is deliberately relative to its own archive directory.
    files['reproduce.py'] = '''"""Run using the installed RandomSign environment: python reproduce.py --runtime PATH."""
import argparse, json, sys
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--runtime',type=Path,default=Path.cwd());args=parser.parse_args()
sys.path.insert(0,str(args.runtime.resolve()))
from src import communication_workbench_v0412 as workbench
folder=Path(__file__).resolve().parent
document=json.loads((folder/'document.json').read_text(encoding='utf-8'))
result=workbench.run_document(document)
(folder/'reproduced-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\\n',encoding='utf-8')
print('Reproduced experiment:',folder/'reproduced-result.json')
'''.encode()
    files['metrics.csv'] = _csv([['metric', 'value'], *_metrics(doc).items()])
    for item in facts['selected_materials']:
        key = item['id'].replace('/', '_')
        if item['rows']: files[f'measurements/{key}.csv'] = _csv([item['headers'], *item['rows']])
        if item['series'] or item['heatmap']: files[f'figures/{key}.svg'] = _figure_svg(item)
    blocks = doc['program']['blocks']
    if doc.get('graph'):
        from src.communication_graph_v0411 import lanes
        blocks = [block for _, members in lanes(doc['graph']) for block in members]
    for index, block in enumerate(blocks):
        data = block['params'].get('data')
        if block['kind'] in ('iq_source', 'audio_source', 'image_source', 'file_source') and data and data != 'builtin':
            name = f'inputs/{index:02d}-{block["kind"]}.bin'
            files[name] = base64.b64decode(data, validate=True)
            files[name + '.json'] = _json({'block_id': block['id'], 'kind': block['kind'], 'parameters': {k: v for k, v in block['params'].items() if k != 'data'}})
    files['README.txt'] = ('通信实验成果包\n\n在同版本 RandomSign 的 Python 环境执行：\n'
        'python reproduce.py --runtime "安装目录/工程文件/代码"\n\n'
        'document.json 保存工程、输入和种子；result.json 保存原始实测结果。\n'
        'metrics.csv 与 measurements/ 为实测数值，figures/ 为独立 SVG，report.pdf 为最终报告。\n'
        'inputs/ 保存工程内导入的原始数据，document.json 同时保留对应数据及格式。\n'
        '在实验记录与课程面板导入本 ZIP，可恢复完整工程。\n').encode('utf-8')
    manifest = {'bundle_schema': 1, 'app_version': VERSION, 'python': platform.python_version(),
                'name': doc['name'], 'seed': doc.get('graph', {}).get('globals', doc['program'])['seed'],
                'graph_token': (doc.get('graphResult') or {}).get('graph_token'),
                'input_hash': (doc.get('workbenchResult') or doc.get('graphResult') or {}).get('input_hash'),
                'input_scope': (doc.get('workbenchResult') or {}).get('input_scope', 'shared_channel' if doc.get('graph') else 'source'),
                'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data in files.items()}}
    files['manifest.json'] = _json(manifest)
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items(): archive.writestr(name, data)
    return out.getvalue()


def export_bundle(document):
    return {'filename': '通信实验成果.zip', 'data': base64.b64encode(bundle(document)).decode('ascii')}


def import_bundle(data):
    if isinstance(data, str): data = base64.b64decode(data, validate=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or '\\' in name for name in names):
            raise ValueError('成果包文件路径需要唯一且位于包内。')
        if sum(v.file_size for v in archive.infolist()) > 64 * 1024 * 1024: raise ValueError('成果包解压数据上限为 64 MiB。')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('bundle_schema') != 1: raise ValueError('请选择版本 1 的通信实验成果包。')
        if set(names) != set(manifest['files']) | {'manifest.json'}: raise ValueError('成果包文件清单与内容不一致。')
        for name, entry in manifest['files'].items():
            value = archive.read(name)
            if len(value) != entry['bytes'] or hashlib.sha256(value).hexdigest() != entry['sha256']:
                raise ValueError('成果文件校验失败：' + name)
        document = studio.validate_document(json.loads(archive.read('document.json')))
        document.pop('projectId', None); document.pop('projectVersion', None)
        return {'document': document, 'manifest': manifest}
