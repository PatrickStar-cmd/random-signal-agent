"""SVG and HTML rendering helpers."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Iterable


def _scale_points(
    x_values: Iterable[float],
    y_values: Iterable[float],
    width: int,
    height: int,
    padding: int,
    y_bounds: tuple[float, float] | None = None,
) -> str:
    xs = list(x_values)
    ys = list(y_values)
    if not xs or not ys:
        return ""
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = y_bounds if y_bounds is not None else (min(ys), max(ys))
    if abs(x_max - x_min) < 1e-12:
        x_max = x_min + 1.0
    if abs(y_max - y_min) < 1e-12:
        y_max = y_min + 1.0

    points = []
    for x, y in zip(xs, ys):
        px = padding + (x - x_min) / (x_max - x_min) * (width - 2 * padding)
        py = height - padding - (y - y_min) / (y_max - y_min) * (height - 2 * padding)
        points.append(f"{px:.2f},{py:.2f}")
    return " ".join(points)


def line_chart_svg(
    title: str,
    x_values: list[float],
    series: list[tuple[str, list[float], str]],
    width: int = 860,
    height: int = 280,
) -> str:
    """Render a small SVG line chart."""
    padding = 36
    polylines = []
    legends = []
    all_values = [value for _, values, _ in series for value in values]
    y_bounds = (min(all_values), max(all_values)) if all_values else None
    for idx, (name, y_values, color) in enumerate(series):
        points = _scale_points(x_values, y_values, width, height, padding, y_bounds)
        polylines.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            f'stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" />'
        )
        legends.append(
            f'<g transform="translate({padding + idx * 150},20)">'
            f'<rect width="16" height="4" y="-3" fill="{color}" rx="2"/>'
            f'<text x="22" y="2" font-size="12" fill="#334155">{html.escape(name)}</text>'
            "</g>"
        )

    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">
  <rect width="{width}" height="{height}" fill="#ffffff" rx="6"/>
  <line x1="{padding}" y1="{height - padding}" x2="{width - padding}" y2="{height - padding}" stroke="#94a3b8"/>
  <line x1="{padding}" y1="{padding}" x2="{padding}" y2="{height - padding}" stroke="#94a3b8"/>
  <text x="{padding}" y="{height - 10}" font-size="12" fill="#64748b">time / frequency</text>
  {''.join(legends)}
  {''.join(polylines)}
</svg>
""".strip()


def metric_card(label: str, value: str, note: str = "") -> str:
    """Render an HTML metric card."""
    return (
        '<div class="metric">'
        f'<span>{html.escape(label)}</span>'
        f'<strong>{html.escape(value)}</strong>'
        f'<small>{html.escape(note)}</small>'
        "</div>"
    )


def render_demo_html(result: dict, output_path: Path) -> None:
    """Render an offline HTML demo page."""
    summary = result["summary"]
    decision = result["decision"]
    series = result["series"]
    time_features = summary["time_features"]
    freq_features = summary["frequency_features"]
    quality = summary["quality"]

    signal_chart = line_chart_svg(
        "随机信号采集与预处理",
        series["time"],
        [
            ("原始观测", series["observed"], "#0f766e"),
            ("预处理后", series["processed"], "#dc2626"),
            ("干净参考", series["clean"], "#2563eb"),
        ],
    )
    power_chart = line_chart_svg(
        "功率谱分析",
        series["frequency"],
        [("功率谱", series["power"], "#7c3aed")],
    )
    trace_items = "\n".join(
        f"<li><b>{html.escape(item['agent'])}</b>：{html.escape(item['action'])}。"
        f"{html.escape(item['detail'])}</li>"
        for item in result["trace"]
    )
    action_items = "\n".join(
        f"<li>{html.escape(action)}</li>" for action in decision["recommended_actions"]
    )
    cards = [
        metric_card("状态", decision["status"], decision["filter_level"]),
        metric_card("SNR 提升", f"{quality['snr_improvement_db']:.2f} dB", "预处理前后对比"),
        metric_card("主频", f"{freq_features['dominant_frequency_hz']:.2f} Hz", "FFT 峰值"),
        metric_card("谱熵", f"{freq_features['spectral_entropy']:.3f}", "越高表示频谱越分散"),
        metric_card("RMS", f"{time_features['rms']:.3f}", "信号有效值"),
        metric_card("异常点率", f"{quality['anomaly_rate'] * 100:.2f}%", "鲁棒检测结果"),
    ]
    embedded_json = json.dumps(result["summary"], ensure_ascii=False, indent=2)

    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>随机信号智能体项目演示</title>
  <style>
    body {{
      margin: 0;
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      color: #172033;
      background: #f6f8fb;
    }}
    header {{
      background: #0f172a;
      color: #f8fafc;
      padding: 28px 36px;
      border-bottom: 4px solid #0f766e;
    }}
    header h1 {{ margin: 0 0 8px; font-size: 28px; }}
    header p {{ margin: 0; color: #cbd5e1; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
    section {{
      margin-bottom: 20px;
      background: #ffffff;
      border: 1px solid #d8dee9;
      border-radius: 8px;
      padding: 20px;
    }}
    h2 {{ margin: 0 0 14px; font-size: 20px; color: #0f172a; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
      gap: 12px;
    }}
    .metric {{
      border: 1px solid #d8dee9;
      border-radius: 6px;
      padding: 12px;
      background: #fbfdff;
      min-height: 82px;
    }}
    .metric span {{ display: block; color: #64748b; font-size: 13px; }}
    .metric strong {{ display: block; margin-top: 5px; font-size: 23px; color: #0f766e; }}
    .metric small {{ display: block; margin-top: 5px; color: #64748b; }}
    .charts {{ display: grid; gap: 16px; }}
    svg {{ width: 100%; height: auto; border: 1px solid #e2e8f0; border-radius: 8px; }}
    li {{ margin: 8px 0; line-height: 1.55; }}
    pre {{
      overflow: auto;
      background: #0f172a;
      color: #e2e8f0;
      border-radius: 8px;
      padding: 16px;
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <header>
    <h1>随机信号智能体项目演示</h1>
    <p>感知采集、噪声预处理、时频域特征分析、决策控制闭环</p>
  </header>
  <main>
    <section>
      <h2>核心指标</h2>
      <div class="metrics">{''.join(cards)}</div>
    </section>
    <section>
      <h2>算法演示</h2>
      <div class="charts">{signal_chart}{power_chart}</div>
    </section>
    <section>
      <h2>智能体执行轨迹</h2>
      <ol>{trace_items}</ol>
    </section>
    <section>
      <h2>控制建议</h2>
      <ul>{action_items}</ul>
    </section>
    <section>
      <h2>结构化分析结果</h2>
      <pre>{html.escape(embedded_json)}</pre>
    </section>
  </main>
</body>
</html>
"""
    output_path.write_text(html_text, encoding="utf-8")
