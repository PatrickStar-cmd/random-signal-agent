"""Multi-agent workflow for random signal analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .acquisition import simulate_signal
from .analysis import summarize_signal_window
from .preprocessing import PreprocessConfig, preprocess_signal
from .signal_processing import (
    PreprocessResult,
    SignalBundle,
    SignalConfig,
    decimate_for_export,
)


@dataclass
class AgentMessage:
    """Trace message emitted by an agent."""

    agent: str
    action: str
    detail: str


@dataclass
class AnalysisState:
    """Shared state passed through the agent pipeline."""

    config: SignalConfig
    bundle: SignalBundle | None = None
    processed: PreprocessResult | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    trace: list[AgentMessage] = field(default_factory=list)

    def log(self, agent: str, action: str, detail: str) -> None:
        self.trace.append(AgentMessage(agent=agent, action=action, detail=detail))


class SensorAgent:
    """Perception agent that simulates real-time random signal acquisition."""

    name = "SensorAgent"

    def run(self, state: AnalysisState) -> AnalysisState:
        state.bundle = simulate_signal(state.config)
        state.log(
            self.name,
            "采集随机信号",
            (
                f"采样率 {state.config.sample_rate:.0f} Hz，时长 "
                f"{state.config.duration:.1f} s，共 {state.config.sample_count} 点。"
            ),
        )
        return state


class PreprocessAgent:
    """Agent that performs robust noise preprocessing."""

    name = "PreprocessAgent"

    def __init__(self, smoothing_window: int = 7) -> None:
        self.smoothing_window = smoothing_window

    def run(self, state: AnalysisState) -> AnalysisState:
        if state.bundle is None:
            raise RuntimeError("SensorAgent must run before PreprocessAgent.")
        state.processed = preprocess_signal(
            state.bundle.observed,
            PreprocessConfig(smoothing_window=self.smoothing_window),
        )
        anomaly_count = int(state.processed.anomaly_mask.sum())
        state.log(
            self.name,
            "噪声预处理",
            (
                f"检测并修复 {anomaly_count} 个脉冲异常点，"
                f"去除均值 {state.processed.removed_mean:.4f}，"
                f"滑动平均窗口 {state.processed.smoothing_window}。"
            ),
        )
        return state


class FeatureAgent:
    """Agent that extracts time-domain and frequency-domain features."""

    name = "FeatureAgent"

    def run(self, state: AnalysisState) -> AnalysisState:
        if state.bundle is None or state.processed is None:
            raise RuntimeError("SensorAgent and PreprocessAgent must run before FeatureAgent.")
        state.summary = summarize_signal_window(state.bundle, state.processed)
        time_features = state.summary["time_features"]
        freq_features = state.summary["frequency_features"]
        state.log(
            self.name,
            "提取时频域特征",
            (
                f"RMS={time_features['rms']:.3f}，"
                f"一阶自相关={time_features['lag1_autocorrelation']:.3f}，"
                f"主频={freq_features['dominant_frequency_hz']:.2f} Hz，"
                f"谱熵={freq_features['spectral_entropy']:.3f}。"
            ),
        )
        return state


class DecisionAgent:
    """Agent that maps signal features to control actions."""

    name = "DecisionAgent"

    def run(self, state: AnalysisState) -> AnalysisState:
        if not state.summary:
            raise RuntimeError("FeatureAgent must run before DecisionAgent.")

        quality = state.summary["quality"]
        time_features = state.summary["time_features"]
        freq_features = state.summary["frequency_features"]
        snr = quality["processed_snr_db"]
        entropy = freq_features["spectral_entropy"]
        anomaly_rate = quality["anomaly_rate"]
        dominant_frequency = freq_features["dominant_frequency_hz"]

        actions: list[str] = []
        if snr is None:
            level = "自适应滤波"
            actions.append("上传信号缺少干净参考，不能直接计算真实 SNR")
            actions.append("建议结合历史基线或静默段估计噪声功率")
        elif snr < 3.0:
            level = "强滤波"
            actions.append("扩大滑动平均窗口到 11-15 点")
            actions.append("延长采样窗口以提高统计稳定性")
        elif snr < 8.0:
            level = "中等滤波"
            actions.append("保持鲁棒异常点抑制，并使用 7-9 点平滑窗口")
        else:
            level = "轻滤波"
            actions.append("降低平滑强度，优先保留瞬态细节")

        if anomaly_rate > 0.015:
            actions.append("触发脉冲干扰告警，建议检查采集线路或传感器接触")
        if entropy > 0.55:
            actions.append("频谱较分散，建议检查宽带噪声源并提高屏蔽")
        if abs(dominant_frequency - state.config.base_frequency) <= 0.75:
            actions.append("主频与目标频率一致，可继续跟踪该频段能量变化")
        if time_features["lag1_autocorrelation"] > 0.85:
            actions.append("时间相关性强，可引入 AR 模型或卡尔曼滤波进行预测")

        if snr is None:
            status = "已分析"
        elif snr >= 8.0 and entropy <= 0.55 and anomaly_rate <= 0.015:
            status = "稳定"
        elif snr >= 3.0:
            status = "可用但需抑噪"
        else:
            status = "噪声占优"

        state.decision = {
            "status": status,
            "filter_level": level,
            "recommended_actions": actions,
            "control_parameters": {
                "next_smoothing_window": 9 if snr is None else (13 if snr < 3.0 else (9 if snr < 8.0 else 5)),
                "next_window_seconds": 8.0 if snr is None else (12.0 if snr < 3.0 else 8.0),
                "track_frequency_hz": dominant_frequency,
            },
        }
        state.log(
            self.name,
            "生成控制决策",
            f"判定状态为“{status}”，控制策略为“{level}”。",
        )
        return state


class RandomSignalOrchestrator:
    """Coordinator for the random signal analysis agents."""

    def __init__(self, config: SignalConfig | None = None) -> None:
        self.config = config or SignalConfig()
        self.sensor_agent = SensorAgent()
        self.preprocess_agent = PreprocessAgent()
        self.feature_agent = FeatureAgent()
        self.decision_agent = DecisionAgent()

    def run(self) -> dict[str, Any]:
        state = AnalysisState(config=self.config)
        for agent in (
            self.sensor_agent,
            self.preprocess_agent,
            self.feature_agent,
            self.decision_agent,
        ):
            state = agent.run(state)

        if state.bundle is None or state.processed is None:
            raise RuntimeError("Pipeline did not produce signal outputs.")

        time_small, raw_small, processed_small, clean_small = decimate_for_export(
            state.bundle.time,
            state.bundle.observed,
            state.processed.signal,
            state.bundle.clean,
        )
        spectrum = state.summary["frequency_features"]["spectrum"]
        freq_small, power_small = decimate_for_export(
            spectrum["frequencies"],
            spectrum["power"],
            max_points=360,
        )

        return {
            "config": state.config.to_dict(),
            "summary": {
                "time_features": state.summary["time_features"],
                "frequency_features": {
                    key: value
                    for key, value in state.summary["frequency_features"].items()
                    if key != "spectrum"
                },
                "quality": state.summary["quality"],
            },
            "decision": state.decision,
            "trace": [message.__dict__ for message in state.trace],
            "series": {
                "time": time_small,
                "observed": raw_small,
                "processed": processed_small,
                "clean": clean_small,
                "frequency": freq_small,
                "power": power_small,
            },
            "full_series": {
                "time": state.bundle.time.tolist(),
                "observed": state.bundle.observed.tolist(),
                "processed": state.processed.signal.tolist(),
                "clean": state.bundle.clean.tolist(),
            },
        }
