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
from src.workbench import VERSION


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
        <p>v0.4.0 采用青蓝、薰衣草紫与珊瑚粉渐变、华文中宋与 Times New Roman、清晰的双层框线，以及七个功能分区：工作区、模板与实验、数据导入、对比与报告、诊断实验室、通信实验室、模型与设置。切换分区时保留当前输入。</p>
        <a href="images/ocean-ui-v034.png"><img class="preview-image" src="images/ocean-ui-v034.png" alt="可爱海洋工作区，包含对话、波形频谱和分析工具箱" loading="lazy"></a>
        <p><a href="https://github.com/PatrickStar-cmd/random-signal-agent/releases/tag/v0.4.0">下载 v0.4.0</a>，启动 Python 服务即可体验新版海洋界面。</p></section>''', 1)
    if 'id="pdf-report-preview"' not in page:
        page = page.replace('<main>', '<main>' + '<section id="pdf-report-preview"><h2>把实验整理成一份清晰的 PDF</h2><p>v0.4.0 支持当前实验或最近 50 次处理结果的中文简版/标准版报告：统一封面、汇总表、可跳转目录、逐组矢量图表、指标与复现信息。运行后端后，在“模板与实验 → PDF 分析报告”选择历史、预览并下载。</p><p><a href="report-example.pdf">查看真实实验的示例 PDF</a> · <a href="https://github.com/PatrickStar-cmd/random-signal-agent/releases/tag/v0.4.0">下载 v0.4.0</a></p><a href="images/pdf-report-v031.png"><img class="preview-image" src="images/pdf-report-v031.png" alt="PDF 分析报告的摘要预览与下载" loading="lazy"></a></section>', 1)
    if 'id="communications-preview"' not in page:
        page = page.replace('<main>', '''<main><section id="communications-preview"><h2>📡 用积木搭建通信实验</h2>
        <p>拖动信源、编码、调制、信道与译码积木，先 Build 再 Run，在信宿查看收到的信号、误码率和星座。支持数字通信、模拟信源 + PCM、文字传输，以及工程 JSON 和完整信宿 CSV 导出。</p>
        <p>v0.4.0「通信原理积木编程」已包含通信实验室。交互实验需要启动 Python 后端；此处展示实际运行截图。</p>
        <a href="images/communications-lab.png"><img class="preview-image" src="images/communications-lab.png" alt="通信实验室的积木编程区与信宿接收可视化区" loading="lazy"></a>
        <p><a href="https://github.com/PatrickStar-cmd/random-signal-agent/blob/main/工程文件/代码/docs/communications-lab.md">查看操作与模型说明</a> · <a href="images/communications-empty.png">查看无信号雪花屏</a></p></section>''', 1)
    if 'id="transmission-preview"' not in page:
        page = page.replace('<main>', '''<main><section id="transmission-preview"><h2>v0.4.1 · 传输环节模块补充</h2>
        <p>六类积木、29 个示例：AM/DSB-SC/SSB/VSB/FM/PM、十对线路编译码、2–256-PAM 与六种成形脉冲、带限/ISI/定时信道、自动符号同步及固定/自适应均衡。</p>
        <p>在 Python 后端中 Build、Run，查看波形、频谱、眼图、时钟跟踪或 LMS/NLMS/RLS 均衡收敛。自动同步假设已知帧粗起点，自适应均衡使用实际发送的公共前导。</p>
        <a href="images/communications-recovery.png"><img class="preview-image" src="images/communications-recovery.png" alt="自适应 DFE 的训练前导、均衡后误差与收敛曲线" loading="lazy"></a>
        <p><a href="images/communications-analog.png">模拟调制截图</a> · <a href="images/communications-baseband.png">基带与眼图截图</a> · <a href="https://github.com/PatrickStar-cmd/random-signal-agent/releases/tag/v0.4.1">下载 v0.4.1</a></p></section>''', 1)
    if 'id="block-studio-preview"' not in page:
        page = page.replace('<main>', '''<main><section id="block-studio-preview"><h2>v0.4.2 · 积木编程视图更新</h2>
        <p>六类表情积木工坊、紧凑拼接链路、完整参数面板，以及独立信宿观察与结果分析。选中积木高亮，未选中积木采用 3 px 框线；同步、均衡及高级参数分组展开。</p>
        <p>全部 29 个示例、原生拖放/排序、撤销重做、Build/Run、草稿和工程/完整结果导出继续可用。下面是新版实际运行截图。</p>
        <a href="images/communications-studio.png"><img class="preview-image" src="images/communications-studio.png" alt="海洋风格积木工坊、紧凑链路、信宿观察和完整参数面板" loading="lazy"></a>
        <p><a href="images/communications-studio-recovery.png">查看均衡参数与收敛图</a> · <a href="https://github.com/PatrickStar-cmd/random-signal-agent/releases/tag/v0.4.2">下载 v0.4.2</a></p></section>''', 1)
    if 'id="block-features-preview"' not in page:
        page = page.replace('<main>', '''<main><section id="block-features-preview"><h2>v0.4.3 · 积木功能更新 🧩</h2>
        <p>122 个可添加模块、49 个预设：CRC、PRBS、扰码、压扩与预测编码、FSK/DPSK/MSK/GMSK、软 Viterbi、LDPC、完整复基带接收机、载波与帧同步、CMA、衰落导频估计和 OFDM。</p>
        <p>观察每块接收处理的输出、相关峰和 OFDM 网格；自动扫描 BER/SER/FER，以 Eb/N₀ 对比链路，显示 95% 置信区间并导出 JSON/CSV。</p>
        <a href="images/communications-v043-sweep.jpg"><img class="preview-image" src="images/communications-v043-sweep.jpg" alt="v0.4.3 软译码性能扫描与 95% 置信区间" loading="lazy"></a>
        <p><a href="https://github.com/PatrickStar-cmd/random-signal-agent/releases/tag/v0.4.3">下载 v0.4.3</a> · <a href="https://github.com/PatrickStar-cmd/random-signal-agent/blob/main/工程文件/代码/docs/communications-v043.md">算法与实验说明</a></p></section>''', 1)
    if 'id="block-experience-preview"' not in page:
        page=page.replace('<main>','''<main><section id="block-experience-preview"><h2>v0.4.4 · 积木编程体验更新 🌊</h2>
        <p>130 个可添加模块、54 个示例。搜索收藏、自动补齐接收链路、真实单步、多图联动、命名工程与快照、框选组合积木、共享信道分支、通用扫描续跑、多帧状态和中文 PDF。</p>
        <p>新增 AGC、自动噪声估计、有理数重采样、T/2 均衡、OFDM 频偏与导频跟踪、独立时变多径和突发噪声。</p>
        <a href="images/communications-v044-studio.png"><img class="preview-image" src="images/communications-v044-studio.png" alt="v0.4.4 海洋积木工程、组合接收机与联动观察" loading="lazy"></a>
        <p><a href="https://github.com/PatrickStar-cmd/random-signal-agent/releases/tag/v0.4.4">下载 v0.4.4</a> · <a href="https://github.com/PatrickStar-cmd/random-signal-agent/blob/main/工程文件/代码/docs/communications-v044.md">体验与算法指南</a></p></section>''',1)
    if 'id="rf-analysis-preview"' not in page:
        page=page.replace('<main>','<main>'+'<section id="rf-analysis-preview"><h2>v0.4.5 · 真实收发链路与实验分析更新 🌊</h2><p>150 个可添加模块、64 个示例、7 项实验任务。高阶调制、I/Q 校正、功放、ADC、OFDM 削峰、窄带干扰和打孔编码，配合 Welch、CCDF、ACLR、资源栅格、自动对齐与效率分析。</p><a href="images/communications-v045-analysis.png"><img class="preview-image" src="images/communications-v045-analysis.png" alt="v0.4.5 海洋射频测量仪表" loading="lazy"></a><p><a href="https://github.com/PatrickStar-cmd/random-signal-agent/releases/tag/v0.4.5">下载 v0.4.5</a> · <a href="https://github.com/PatrickStar-cmd/random-signal-agent/blob/main/工程文件/代码/docs/communications-v045.md">射频与测量指南</a></p></section>',1)
    page = page.replace('「通信原理积木编程」已包含通信实验室。', '「积木编程体验更新」包含完整通信实验室。')
    return page.replace('v0.4.0', f'v{VERSION}')


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
      <p>固定种子生成的信号、处理结果与分析指标。</p>
      <p>种子 {bundle.config.seed} · {bundle.config.sample_rate:g} Hz · {bundle.config.duration:g} 秒 · {bundle.config.sample_count} 点 · {bundle.config.base_frequency:g} Hz 主频 · {html.escape(bundle.config.waveform)} + {html.escape(bundle.config.noise_model)}。图中曲线共享纵轴；完整数据见下方下载。</p>
      <p>启动 Python 服务后，即可使用对话、上传分析、麦克风和自动调参。</p>
      <p><a href="https://github.com/PatrickStar-cmd/random-signal-agent#从零复现">查看源码与本地运行步骤</a> ·
      <a href="data/sample.csv" download>下载可上传的两列 CSV</a> ·
      <a href="data/reference.csv" download>下载含干净参考的完整 CSV</a> ·
      <a href="data/result.json">查看参数与完整指标 JSON</a></p>
    </section>'''
    comparison_section = f'''<section><h2>六种预处理方法对比</h2>
      <p>同一输入、固定默认参数（窗口 7 点）的离线比较。</p>
      <p>原始 SNR：{raw_snr:.3f} dB，以本次仿真的干净信号为参考。</p>
      <table><thead><tr><th>方法</th><th>处理后 SNR</th><th>相对原始提升</th></tr></thead><tbody>{rows}</tbody></table>
    </section>'''
    page = page.replace("<main>", "<main>" + introduction, 1)
    page = page.replace("    <section>\n      <h2>智能体执行轨迹", comparison_section + "\n    <section>\n      <h2>智能体执行轨迹", 1)
    page = page.replace("  </style>", "table {width:100%;border-collapse:collapse} th,td {padding:12px;text-align:left;border-bottom:1px solid #e2e8f0} p {line-height:1.7} a {color:#0f766e} @media(max-width:600px){header{padding:22px}main{padding:12px}section{padding:14px}}\n  </style>")
    page = page.replace("<h2>结构化分析结果</h2>", "<details><summary>展开结构化分析结果</summary>")
    page = page.replace("</pre>\n    </section>", "</pre></details>\n    </section>")
    (pages / "images").mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "web/ocean-whale.webp", pages / "images/ocean-whale.webp")
    shutil.copyfile(ROOT / "web/ocean-waves.svg", pages / "images/ocean-waves.svg")
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
