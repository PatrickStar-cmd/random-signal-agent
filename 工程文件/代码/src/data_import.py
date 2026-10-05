"""Preview and validate selected CSV/TXT columns without silently dropping rows."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import math
import re
import numpy as np
from .signal_processing import SignalBundle, SignalConfig
from .limits import LIMITS
from .tasks import check_cancelled

UNITS = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9}


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def inspect_data(raw, options=None):
    options = options or {}
    allowed = {"delimiter", "header", "signal_column", "time_column", "time_unit", "sample_rate"}
    if not isinstance(options, dict) or set(options) - allowed:
        raise ValueError("Unknown import options")
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeError as exc:
        raise ValueError("请将文件保存为 UTF-8 编码的 CSV/TXT。") from exc
    if not text.strip():
        raise ValueError("文件没有数据。")
    delimiter = options.get('delimiter', 'auto')
    if delimiter not in ('auto', 'comma', 'semicolon', 'tab', 'space'):
        raise ValueError("Invalid delimiter")
    if delimiter == 'auto':
        try:
            char = csv.Sniffer().sniff(text[:65536], delimiters=',;\t').delimiter
            delimiter = {',':'comma',';':'semicolon','\t':'tab'}[char]
        except csv.Error:
            first = next(line for line in io.StringIO(text) if line.strip())
            delimiter = next((name for name, char in [('tab','\t'),('semicolon',';'),('comma',',')] if char in first), 'space')
    entries = []
    def add(line, row):
        if len(row) > 64 or len(entries) >= LIMITS['max_samples'] + 1:
            raise ValueError(f"最多 {LIMITS['max_samples']} 行数据、64 列。")
        entries.append((line, row))
    if delimiter == 'space':
        for line, value in enumerate(io.StringIO(text), 1):
            if value.strip():
                add(line, re.split(r'\s+', value.strip(), maxsplit=64))
    else:
        reader = csv.reader(io.StringIO(text), delimiter={'comma':',','semicolon':';','tab':'\t'}[delimiter], strict=True)
        try:
            for row in reader:
                if row:
                    add(reader.line_num, [cell.strip() for cell in row])
        except csv.Error as exc:
            raise ValueError(f"CSV 第 {reader.line_num} 行格式错误：{exc}") from exc
    if not entries:
        raise ValueError("文件没有数据。")
    if len(entries) > LIMITS['max_samples'] + 1 or any(len(row) > 64 for _, row in entries):
        raise ValueError(f"最多 {LIMITS['max_samples']} 行数据、64 列。")
    header = options.get('header', 'auto')
    if header not in ('auto', 'yes', 'no'):
        raise ValueError("Invalid header option")
    has_header = header == 'yes' or (header == 'auto' and all(cell and _number(cell) is None for cell in entries[0][1]))
    first_row = entries[0][1]
    data = entries[1:] if has_header else entries
    if not data or len(data) > LIMITS['max_samples']:
        raise ValueError(f"需要 1–{LIMITS['max_samples']} 行数据。")
    width = max(len(row) for _, row in entries)
    columns = [first_row[i][:160] if has_header and i < len(first_row) and first_row[i] else f'列 {i+1}' for i in range(width)]
    signal_column = options.get('signal_column', 1 if width > 1 else 0)
    time_column = options.get('time_column', 0 if width > 1 else None)
    for column in (signal_column, time_column):
        if column is not None and (type(column) is not int or not 0 <= column < width):
            raise ValueError("Column index is outside the file")
    if signal_column is None or signal_column == time_column:
        raise ValueError("请选择不同的时间列和信号列。")
    unit = options.get('time_unit', 's')
    if not isinstance(unit, str) or unit not in UNITS:
        raise ValueError("Invalid time unit")
    rate = options.get('sample_rate', 200)
    if type(rate) not in (float, int) or not math.isfinite(rate) or not 0 < rate <= 192000:
        raise ValueError("采样率须在 0–192000 Hz 之间。")
    mapping = {'delimiter':delimiter,'header':'yes' if has_header else 'no','signal_column':signal_column,
               'time_column':time_column,'time_unit':unit,'sample_rate':rate}
    issues, issue_count = [], 0
    def issue(line, column, message):
        nonlocal issue_count
        issue_count += 1
        if len(issues) < 20:
            issues.append({'line':line,'column':column+1 if column is not None else None,'message':message})
    times, samples = [], []
    for index, (line, row) in enumerate(data):
        if index % 1024 == 0:
            check_cancelled()
        for column, target in ((signal_column, samples), (time_column, times)):
            if column is None:
                continue
            cell = row[column] if column < len(row) else ''
            value = _number(cell)
            if value is None or not math.isfinite(value):
                issue(line, column, '缺失值或非有限数值，请修正后重新导入')
                target.append(float('nan'))
            else:
                target.append(value * UNITS[unit] if column == time_column else value)
    observed = np.asarray(samples)
    t = np.asarray(times) if time_column is not None else np.arange(len(samples)) / rate
    if time_column is not None and np.isfinite(t).all() and len(t) > 1:
        intervals = np.diff(t)
        invalid = np.flatnonzero(~np.isfinite(intervals) | (intervals <= 0))
        for index in invalid:
            issue(data[int(index)+1][0], time_column, '时间重复、倒序或间隔无效')
        if not len(invalid):
            dt = float(np.median(intervals))
            rate = 1.0 / dt
            irregular = np.flatnonzero(~np.isclose(intervals, dt, rtol=1e-3, atol=max(dt*1e-6,1e-12)))
            for index in irregular:
                issue(data[int(index)+1][0], time_column, '采样间隔不均匀，暂不自动插值')
            if not math.isfinite(rate) or not 0 < rate <= 192000:
                issue(data[0][0], time_column, '推断采样率超出范围，请检查时间单位')
    if rate > 0 and math.isfinite(rate) and not math.isfinite(len(samples)/rate):
        issue(data[0][0], time_column, '采样率过小，时间范围超出数值精度')
    digest = hashlib.sha256(raw).hexdigest()
    token = hashlib.sha256((digest + json.dumps(mapping, sort_keys=True)).encode()).hexdigest()
    preview = {'columns':columns,'rows':len(data),'preview':[{'line':line,'cells':[v[:160] for v in row]} for line,row in data[:20]],
               'mapping':mapping,'file_sha256':digest,'token':token,'valid':issue_count==0,'issues':issues,'issue_count':issue_count,
               'sample_rate':rate if math.isfinite(rate) else None, 'duration':len(samples)/rate if math.isfinite(rate) and rate>0 and math.isfinite(len(samples)/rate) else None}
    bundle = None
    if not issue_count:
        bundle = SignalBundle(time=t, observed=observed, clean=observed.copy(), noise=np.zeros_like(observed),
            impulse_mask=np.zeros(len(samples),dtype=bool), config=SignalConfig(sample_rate=rate,duration=len(samples)/rate),
            source='file',has_clean_reference=False)
    return preview, bundle
