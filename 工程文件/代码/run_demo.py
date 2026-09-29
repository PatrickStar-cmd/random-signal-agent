"""Run the random signal agent demo and generate course deliverables."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.agents import RandomSignalOrchestrator
from src.signal_processing import SignalConfig
from src.visualization import render_demo_html


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
DOCS_DIR = ROOT / "docs"


def write_json(result: dict, path: Path) -> None:
    """Write JSON with Chinese-friendly encoding."""
    serializable = {key: value for key, value in result.items() if key != "full_series"}
    path.write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_csv(result: dict, path: Path) -> None:
    """Write full signal samples to CSV."""
    full = result["full_series"]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["time_s", "clean_signal", "observed_signal", "processed_signal"])
        for row in zip(full["time"], full["clean"], full["observed"], full["processed"]):
            writer.writerow([f"{value:.8f}" for value in row])


def write_design_report(result: dict, path: Path) -> None:
    """Write a report by appending concrete experiment results to the template."""
    template = (DOCS_DIR / "design_report_template.md").read_text(encoding="utf-8")
    quality = result["summary"]["quality"]
    time_features = result["summary"]["time_features"]
    freq_features = result["summary"]["frequency_features"]
    decision = result["decision"]
    trace_lines = "\n".join(
        f"- **{item['agent']}**：{item['action']}。{item['detail']}"
        for item in result["trace"]
    )
    action_lines = "\n".join(f"- {item}" for item in decision["recommended_actions"])

    def fmt_db(value: float | None) -> str:
        return "无干净参考，未计算" if value is None else f"{value:.3f} dB"

    experiment = f"""

## 8. 本次运行记录

### 8.1 智能体轨迹

{trace_lines}

### 8.2 关键指标

| 指标 | 数值 |
| --- | ---: |
| 原始 SNR | {fmt_db(quality['raw_snr_db'])} |
| 预处理后 SNR | {fmt_db(quality['processed_snr_db'])} |
| SNR 提升 | {fmt_db(quality['snr_improvement_db'])} |
| 异常点率 | {quality['anomaly_rate'] * 100:.3f}% |
| RMS | {time_features['rms']:.3f} |
| 一阶自相关 | {time_features['lag1_autocorrelation']:.3f} |
| 主频 | {freq_features['dominant_frequency_hz']:.3f} Hz |
| 谱熵 | {freq_features['spectral_entropy']:.3f} |

### 8.3 决策输出

- 状态判定：{decision['status']}
- 滤波策略：{decision['filter_level']}
- 下一窗口平滑长度：{decision['control_parameters']['next_smoothing_window']} 点
- 跟踪频率：{decision['control_parameters']['track_frequency_hz']:.3f} Hz

### 8.4 控制建议

{action_lines}
"""
    path.write_text(template + experiment, encoding="utf-8")


def main() -> None:
    """Run the complete project demonstration."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config = SignalConfig(
        sample_rate=200.0,
        duration=8.0,
        base_frequency=8.0,
        amplitude=1.2,
        noise_std=0.55,
        ar_coefficient=0.86,
        impulse_probability=0.012,
        seed=42,
    )
    result = RandomSignalOrchestrator(config=config).run()

    write_json(result, OUTPUT_DIR / "analysis_result.json")
    write_csv(result, OUTPUT_DIR / "signal_samples.csv")
    render_demo_html(result, OUTPUT_DIR / "demo.html")
    write_design_report(result, OUTPUT_DIR / "design_report.md")

    print("随机信号智能体项目演示已完成。")
    print(f"输出目录: {OUTPUT_DIR}")
    print(f"状态判定: {result['decision']['status']}")
    print(f"主频: {result['summary']['frequency_features']['dominant_frequency_hz']:.2f} Hz")
    print(f"SNR 提升: {result['summary']['quality']['snr_improvement_db']:.2f} dB")


if __name__ == "__main__":
    main()
