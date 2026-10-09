"""Immutable, session-owned processing results for selectable PDF reports."""
import copy
import hashlib
import json
import time
import uuid

import numpy as np

from .dialogue_agent import ConversationState
from . import diagnostics, pdf_report
from .signal_processing import decimate_for_export
from .workbench import snapshot, restore


def capture_result(store, db, key, state):
    if state.bundle is None or state.processed is None:
        return
    if db.execute('SELECT 1 FROM report_history WHERE id=?', (key,)).fetchone():
        return
    # Keep numerical evidence, not conversational or API configuration data.
    fields = ('bundle', 'processed', 'preprocess_results', 'preprocess_comparison', 'comparison_goal')
    frozen = ConversationState(state.session_id, **{k: copy.deepcopy(getattr(state, k)) for k in fields})
    lab = diagnostics.lab_for(state)
    allowed = ('input_sha256', 'blind', 'revealed', 'analysis', 'baseline', 'reference_clean', 'truth', 'seed')
    frozen.diagnostic_lab = {k: copy.deepcopy(lab[k]) for k in allowed if k in lab}
    frozen.bundle.source = pdf_report.source_kind(frozen.bundle)
    document, raw = snapshot(frozen)
    data_file = hashlib.sha256(raw).hexdigest() + '.npz'
    path = store.root / data_file
    if not path.exists():
        temporary = store.root / (uuid.uuid4().hex + '.tmp')
        temporary.write_bytes(raw)
        temporary.replace(path)
    created = time.time()
    metadata = {'id': key, 'kind': 'history', 'name': state.processed.method_label or '诊断验证处理',
                'created': created, 'sample_count': len(state.bundle.observed),
                'sample_rate': float(state.bundle.config.sample_rate),
                'locked': bool(lab.get('blind') and not lab.get('revealed'))}
    db.execute('INSERT INTO report_history VALUES (?,?,?,?,?,?)',
               (key, state.session_id, document, data_file, json.dumps(metadata, ensure_ascii=False), created))
    db.execute('DELETE FROM report_history WHERE session=? AND id NOT IN '
               '(SELECT id FROM report_history WHERE session=? ORDER BY created DESC,rowid DESC LIMIT ?)',
               (state.session_id, state.session_id, pdf_report.CONFIG['history_limit']))


def listing(store, session):
    with store.connect() as db:
        rows = db.execute('SELECT metadata FROM report_history WHERE session=? ORDER BY created DESC,rowid DESC',
                          (session,)).fetchall()
    with store.connect() as db:
        saved=db.execute("SELECT id,name,updated,document FROM snapshots WHERE session=? AND name<>'Autosave' ORDER BY updated DESC",(session,)).fetchall()
    snapshots=[]
    for row in saved:
        lab=json.loads(row['document'])['state']['fields'].get('diagnostic_lab',{})
        snapshots.append({'id':row['id'],'name':row['name'],'created':row['updated'],'kind':'snapshot',
                          'locked':bool(lab.get('blind') and not lab.get('revealed'))})
    return {'history': [json.loads(r['metadata']) for r in rows], 'snapshots': snapshots,
            'limit': pdf_report.CONFIG['history_limit']}


def selection(value):
    limit = pdf_report.CONFIG['history_limit']
    if not isinstance(value, list) or not 1 <= len(value) <= limit:
        raise ValueError(f'请选择 1 至 {limit} 组结果。')
    result = []
    for entry in value:
        if (not isinstance(entry, dict) or set(entry) != {'kind', 'id'} or
                entry['kind'] not in ('history', 'snapshot') or
                not isinstance(entry['id'], str) or not 1 <= len(entry['id']) <= 128):
            raise ValueError('报告选择包含无效结果。')
        key = (entry['kind'], entry['id'])
        if key in result:
            raise ValueError('同一结果不能重复选择。')
        result.append(key)
    return result


def load_entry(store, session, kind, key):
    # Caller holds file_lock through restore/build so cleanup cannot remove data.
    if kind == 'snapshot':
        with store.connect() as db:
            row = db.execute("SELECT name,updated FROM snapshots WHERE id=? AND session=? AND name<>'Autosave'",
                             (key, session)).fetchone()
        if row is None:
            raise KeyError('已选快照不存在于当前会话。')
        return store.load(key, session), {'id': key, 'kind': kind, 'name': row['name'], 'created': row['updated']}
    if kind != 'history':
        raise ValueError('未知报告结果来源。')
    with store.connect() as db:
        row = db.execute('SELECT * FROM report_history WHERE id=? AND session=?', (key, session)).fetchone()
    if row is None:
        raise KeyError('已选历史结果已滚出最近 50 次或不属于当前会话。')
    return restore(row['document'], (store.root / row['data_file']).read_bytes()), json.loads(row['metadata'])


def collection(store, session, chosen, preferences):
    chosen = selection(chosen)
    opts = pdf_report.options(preferences)
    groups = []
    # Release full arrays after each group; retained facts contain bounded plots.
    with store.file_lock:
        for kind, key in chosen:
            state, metadata = load_entry(store, session, kind, key)
            facts = pdf_report.build(state, {**opts, 'purpose': '', 'author': ''})
            groups.append({'metadata': metadata, 'facts': facts})
            del state
    return pdf_report.build_collection(groups, opts)


def plot(store, session, kind, key):
    with store.file_lock:
        state, _ = load_entry(store, session, kind, key)
        lab = diagnostics.lab_for(state)
        if lab.get('blind') and not lab.get('revealed'):
            raise ValueError('盲测存档未揭晓，不能预览报告图表。')
        if state.bundle is None:
            raise ValueError('该快照没有采样数据。')
        b = state.bundle
        series = [b.time, b.observed] + ([state.processed.signal] if state.processed is not None else [])
        sampled = decimate_for_export(*series, max_points=160)
    x = np.asarray(sampled[0]); ys = [np.asarray(a) for a in sampled[1:]]
    lo = min(float(y.min()) for y in ys); hi = max(float(y.max()) for y in ys)
    span = max(hi - lo, 1e-12); length = max(float(x[-1] - x[0]), 1e-12)
    lines = []
    for y, color in zip(ys, ('#168494', '#5967b9')):
        points = ' '.join(f'{6+228*(t-x[0])/length:.2f},{74-68*(v-lo)/span:.2f}' for t,v in zip(x,y))
        lines.append(f'<polyline fill="none" stroke="{color}" stroke-width="1.2" points="{points}"/>')
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 80"><rect width="240" height="80" rx="8" fill="#f3f8fc"/>' + ''.join(lines) + '</svg>'
