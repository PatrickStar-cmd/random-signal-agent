"""Build the checked-in, backend-free GitHub Pages example from real results."""

from pathlib import Path
from dataclasses import asdict
import csv
import html
import json
import platform
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from src.agents import RandomSignalOrchestrator
from src.preprocessing import PREPROCESS_METHODS, PreprocessConfig, preprocess_signal
from src.signal_processing import SignalConfig, generate_random_signal, estimate_snr
from src.visualization import render_demo_html


def decorate_preview(page):
    """Keep the checked-in static preview consistent when regenerating results."""
    if 'href="showcase.css"' not in page:
        page = page.replace('</head>', '  <link rel="stylesheet" href="showcase.css">\n</head>', 1)
    header = '''<header><div><span class="eyebrow">YOUR LITTLE SIGNAL LAB</span>
      <h1>谛听 · 随机信号智能体</h1><p>从一条波形开始，探索噪声、规律与细节里的异常。</p>
      <p><a href="https://github.com/PatrickStar-cmd/random-signal-agent#readme">开始使用</a> · 固定实验结果预览</p></div>
      <img src="images/ocean-whale.webp" alt="" width="1536" height="1024" decoding="async"></header>'''
    page = re.sub(r'<header>.*?</header>', lambda _: header, page, count=1, flags=re.S)
    if 'id="ocean-preview"' not in page:
        page = page.replace('<main>', '''<main><section id="ocean-preview"><h2>一个轻松探索信号的小实验室</h2>
        <p>海蓝与薰衣草紫渐变、AI 立体鲸鱼插画与六个功能分区：工作区、模板与实验、数据导入、对比与报告、诊断实验室、模型与设置。切换分区时保留当前输入。</p>
        <a href="images/ocean-ui.png"><img class="preview-image" src="images/ocean-ui.png" alt="可爱海洋工作区，包含对话、波形频谱和分析工具箱" loading="lazy"></a>
        <p>海洋界面与模型 API 配置已包含在 <a href="https://github.com/PatrickStar-cmd/random-signal-agent/releases/tag/v0.3.0">v0.3.0 部署包</a>中；交互实验需要启动 Python 服务。</p></section>''', 1)
    return page


def main():
    repository = ROOT.parents[1]
    pages = repository / "docs"
    data = pages / "data"
    data.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / "config/showcase.json").read_text(encoding="utf-8"))
    bundle = generate_random_signal(SignalConfig(**config))
    result = RandomSignalOrchestrator(SignalConfig(**config)).run()
    comparison = []
    for method, metadata in PREPROCESS_METHODS.items():
        preprocess_config = PreprocessConfig(method=method, sample_rate=bundle.config.sample_rate)
        filtered = preprocess_signal(bundle.observed, preprocess_config)
        comparison.append({"method": method, "label": metadata["label"],
                           "parameters": asdict(preprocess_config),
                           "snr_db": estimate_snr(bundle.clean, filtered.signal)})
    raw_snr = estimate_snr(bundle.clean, bundle.observed)
    snapshot = {"environment": {"python": platform.python_version(), "numpy": np.__version__},
                "config": result["config"], "summary": result["summary"],
                "decision": result["decision"], "trace": result["trace"],
                "comparison": comparison}
    (data / "result.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (data / "sample.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_s", "observed_signal"])
        writer.writerows(zip(bundle.time, bundle.observed))
    with (data / "reference.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_s", "clean_signal", "observed_signal", "processed_signal"])
        writer.writerows(zip(result["full_series"]["time"], result["full_series"]["clean"],
                             result["full_series"]["observed"], result["full_series"]["processed"]))
    render_demo_html(result, pages / "index.html")
    page = (pages / "index.html").read_text(encoding="utf-8")
    rows = "".join(f'<tr><td>{html.escape(item["label"])}</td><td>{item["snr_db"]:.3f} dB</td>'
                   f'<td>{item["snr_db"] - raw_snr:+.3f} dB</td></tr>' for item in comparison)
    introduction = f'''<section>
      <h2>固定种子实验 · 静态演示</h2>
      <p>本页由项目 Python 工具链生成，展示真实计算结果，无需登录或配置外部模型。</p>
      <p>种子 {bundle.config.seed} · {bundle.config.sample_rate:g} Hz · {bundle.config.duration:g} 秒 · {bundle.config.sample_count} 点 · {bundle.config.base_frequency:g} Hz 主频 · {html.escape(bundle.config.waveform)} + {html.escape(bundle.config.noise_model)}。图中曲线共享纵轴；完整数据见下方下载。</p>
      <p>这是固定样本结果页。对话、上传分析、麦克风和自动调参需要在本地启动 Python 后端。</p>
      <p><a href="https://github.com/PatrickStar-cmd/random-signal-agent#从零复现">查看源码与本地运行步骤</a> ·
      <a href="data/sample.csv" download>下载可上传的两列 CSV</a> ·
      <a href="data/reference.csv" download>下载含干净参考的完整 CSV</a> ·
      <a href="data/result.json">查看参数与完整指标 JSON</a></p>
    </section>'''
    comparison_section = f'''<section><h2>六种预处理方法对比</h2>
      <p>同一输入、固定默认参数（窗口 7 点）。这是离线比较，Web Agent 自动搜索参数后的结果可能不同。</p>
      <p>原始 SNR：{raw_snr:.3f} dB。SNR 以仿真干净信号为参考，只反映本次样本；上传数据没有参考时不计算真实 SNR。</p>
      <table><thead><tr><th>方法</th><th>处理后 SNR</th><th>相对原始提升</th></tr></thead><tbody>{rows}</tbody></table>
    </section>'''
    page = page.replace("<main>", "<main>" + introduction, 1)
    page = page.replace("    <section>\n      <h2>智能体执行轨迹", comparison_section + "\n    <section>\n      <h2>智能体执行轨迹", 1)
    page = page.replace("  </style>", "table {width:100%;border-collapse:collapse} th,td {padding:12px;text-align:left;border-bottom:1px solid #e2e8f0} p {line-height:1.7} a {color:#0f766e} @media(max-width:600px){header{padding:22px}main{padding:12px}section{padding:14px}}\n  </style>")
    page = page.replace("<h2>结构化分析结果</h2>", "<details><summary>展开结构化分析结果</summary>")
    page = page.replace("</pre>\n    </section>", "</pre></details>\n    </section>")
    (pages / "images").mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "web/ocean-whale.webp", pages / "images/ocean-whale.webp")
    (pages / "index.html").write_text(decorate_preview(page), encoding="utf-8")
    (pages / ".nojekyll").touch()
    log = ROOT / "logs/showcase/latest.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    message = (f"Python {platform.python_version()}, NumPy {np.__version__}\n"
               f"Generated {pages}\nSamples={bundle.config.sample_count}; "
               f"dominant_frequency={result['summary']['frequency_features']['dominant_frequency_hz']:.3f} Hz; "
               f"SNR improvement={result['summary']['quality']['snr_improvement_db']:.3f} dB\n")
    log.write_text(message, encoding="utf-8")
    print(message)


if __name__ == "__main__":
    main()
