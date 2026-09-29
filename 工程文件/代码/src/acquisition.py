"""Signal acquisition module.

This module separates the perception layer from later preprocessing and
analysis. It supports both simulated random signal acquisition and loading a
user-provided signal file.
"""

from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from .signal_processing import SignalBundle, SignalConfig, generate_random_signal


@dataclass(frozen=True)
class AcquisitionChannel:
    """A signal perception channel exposed to the dialogue agent."""

    id: str
    label: str
    description: str
    autonomous: bool = False
    available: bool = True


@dataclass
class AcquisitionPlan:
    """Resolved acquisition strategy for one dialogue turn."""

    channel: AcquisitionChannel
    config: SignalConfig
    policy: str
    goal: str
    candidate_channels: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel.id,
            "channel_label": self.channel.label,
            "channel_description": self.channel.description,
            "autonomous": self.channel.autonomous,
            "available": self.channel.available,
            "policy": self.policy,
            "goal": self.goal,
            "candidate_channels": self.candidate_channels,
            "config": self.config.to_dict(),
        }


ACQUISITION_CHANNELS: dict[str, AcquisitionChannel] = {
    "simulated_lab": AcquisitionChannel(
        id="simulated_lab",
        label="仿真实验室",
        description="按用户指定的采样率、时长、信号模型和噪声模型生成随机观测窗口。",
    ),
    "realtime_stream": AcquisitionChannel(
        id="realtime_stream",
        label="实时流式采集",
        description="把仿真观测按时间片流式拼接，模拟在线采集过程。",
        autonomous=True,
    ),
    "autonomous_sweep": AcquisitionChannel(
        id="autonomous_sweep",
        label="自主巡检采集",
        description="智能体根据任务目标自主选择信号-噪声组合和采集通道。",
        autonomous=True,
    ),
    "uploaded_file": AcquisitionChannel(
        id="uploaded_file",
        label="用户文件通道",
        description="从用户上传的 CSV/TXT 数据中读取信号样本。",
    ),
    "sensor_gateway": AcquisitionChannel(
        id="sensor_gateway",
        label="外部传感器网关",
        description="预留真实硬件或远程采集 API 接入点；当前云端未绑定真实设备。",
        autonomous=True,
        available=False,
    ),
}


def list_acquisition_channels() -> list[dict[str, Any]]:
    """Return channel metadata for UI rendering and model context."""
    return [asdict(channel) for channel in ACQUISITION_CHANNELS.values()]


def simulate_signal(config: SignalConfig | None = None) -> SignalBundle:
    """Acquire a synthetic random signal from the simulator."""
    return generate_random_signal(config or SignalConfig())


def stream_simulated_signal(
    config: SignalConfig | None = None,
    chunk_seconds: float = 1.0,
) -> Iterator[SignalBundle]:
    """Yield simulated signal chunks to mimic real-time acquisition."""
    bundle = simulate_signal(config)
    chunk_size = max(1, int(bundle.config.sample_rate * chunk_seconds))
    total = bundle.observed.size

    for start in range(0, total, chunk_size):
        end = min(total, start + chunk_size)
        chunk_config = SignalConfig(
            sample_rate=bundle.config.sample_rate,
            duration=(end - start) / bundle.config.sample_rate,
            base_frequency=bundle.config.base_frequency,
            amplitude=bundle.config.amplitude,
            noise_std=bundle.config.noise_std,
            ar_coefficient=bundle.config.ar_coefficient,
            impulse_probability=bundle.config.impulse_probability,
            seed=bundle.config.seed,
            signal_model=bundle.config.signal_model,
            waveform=bundle.config.waveform,
            noise_model=bundle.config.noise_model,
        )
        yield SignalBundle(
            time=bundle.time[start:end],
            clean=bundle.clean[start:end],
            observed=bundle.observed[start:end],
            noise=bundle.noise[start:end],
            impulse_mask=bundle.impulse_mask[start:end],
            config=chunk_config,
            source=bundle.source,
            has_clean_reference=bundle.has_clean_reference,
        )


def build_acquisition_plan(
    config: SignalConfig,
    channel_id: str = "simulated_lab",
    goal: str = "manual",
    policy: str = "user_specified",
    candidate_channels: list[str] | None = None,
) -> AcquisitionPlan:
    """Create a validated acquisition plan."""
    channel = ACQUISITION_CHANNELS.get(channel_id, ACQUISITION_CHANNELS["simulated_lab"])
    return AcquisitionPlan(
        channel=channel,
        config=config,
        policy=policy,
        goal=goal,
        candidate_channels=candidate_channels or [channel.id],
    )


def acquire_with_plan(plan: AcquisitionPlan) -> SignalBundle:
    """Acquire a signal according to a resolved plan."""
    if plan.channel.id == "uploaded_file":
        raise ValueError("uploaded_file channel must be acquired through load_signal_file")

    if plan.channel.id == "sensor_gateway" and not plan.channel.available:
        # Keep the demo usable while being explicit in metadata that no hardware
        # gateway is bound in the current cloud deployment.
        bundle = simulate_signal(plan.config)
        bundle.source = f"sensor_gateway_stub/{plan.config.waveform}+{plan.config.noise_model}"
        return bundle

    if plan.channel.id == "realtime_stream":
        chunks = list(stream_simulated_signal(plan.config, chunk_seconds=1.0))
        if not chunks:
            bundle = simulate_signal(plan.config)
        else:
            bundle = SignalBundle(
                time=np.concatenate([chunk.time for chunk in chunks]),
                clean=np.concatenate([chunk.clean for chunk in chunks]),
                observed=np.concatenate([chunk.observed for chunk in chunks]),
                noise=np.concatenate([chunk.noise for chunk in chunks]),
                impulse_mask=np.concatenate([chunk.impulse_mask for chunk in chunks]),
                config=plan.config,
                source=f"realtime_stream/{plan.config.waveform}+{plan.config.noise_model}",
                has_clean_reference=True,
            )
        return bundle

    bundle = simulate_signal(plan.config)
    prefix = "autonomous_sweep" if plan.channel.id == "autonomous_sweep" else "simulated_lab"
    bundle.source = f"{prefix}/{plan.config.waveform}+{plan.config.noise_model}"
    return bundle


def _parse_numeric_rows(path: Path) -> list[list[float]]:
    """Read numeric rows from CSV/TXT files while tolerating headers."""
    rows: list[list[float]] = []
    text = path.read_text(encoding="utf-8-sig")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [part for part in re.split(r"[\s,;，]+", line) if part]
        numeric: list[float] = []
        for part in parts:
            try:
                numeric.append(float(part))
            except ValueError:
                numeric = []
                break
        if numeric:
            rows.append(numeric)
    return rows


def load_signal_file(path: str | Path, sample_rate: float = 200.0) -> SignalBundle:
    """Load a user-submitted signal file.

    Supported formats:
    - one numeric column: signal amplitude, with sample_rate supplied manually
    - two or more numeric columns: first column is time, second column is signal
    - CSV, TXT and whitespace-separated data are accepted
    """
    file_path = Path(path)
    rows = _parse_numeric_rows(file_path)
    if not rows:
        raise ValueError(f"No numeric signal samples found in {file_path}")

    if len(rows[0]) >= 2:
        time = np.asarray([row[0] for row in rows], dtype=float)
        observed = np.asarray([row[1] for row in rows], dtype=float)
        if time.size >= 2:
            dt = float(np.median(np.diff(time)))
            inferred_rate = 1.0 / dt if dt > 0 else sample_rate
        else:
            inferred_rate = sample_rate
    else:
        observed = np.asarray([row[0] for row in rows], dtype=float)
        inferred_rate = sample_rate
        time = np.arange(observed.size, dtype=float) / inferred_rate

    duration = float(time[-1] - time[0]) if time.size >= 2 else observed.size / inferred_rate
    config = SignalConfig(
        sample_rate=float(inferred_rate),
        duration=max(duration, observed.size / inferred_rate),
    )
    return SignalBundle(
        time=time,
        clean=observed.copy(),
        observed=observed,
        noise=np.zeros_like(observed),
        impulse_mask=np.zeros(observed.size, dtype=bool),
        config=config,
        source="file",
        has_clean_reference=False,
    )


def export_signal_csv(bundle: SignalBundle, output_path: str | Path) -> None:
    """Export acquired signal samples to CSV."""
    path = Path(output_path)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["time_s", "observed_signal"])
        for time_value, sample in zip(bundle.time, bundle.observed):
            writer.writerow([f"{float(time_value):.8f}", f"{float(sample):.8f}"])
