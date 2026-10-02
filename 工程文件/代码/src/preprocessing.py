"""Noise preprocessing module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .signal_processing import PreprocessResult, moving_average, validate_signal_samples


@dataclass
class PreprocessConfig:
    """Configurable preprocessing options."""

    smoothing_window: int = 7
    anomaly_threshold_sigma: float = 3.0
    repair_impulses: bool = True
    remove_mean: bool = True
    method: str = "robust_mean"
    lowpass_cutoff_hz: float | None = None
    sample_rate: float | None = None
    ema_alpha: float = 0.22
    kalman_process_noise: float = 0.02
    kalman_measurement_noise: float = 0.25
    kalman_initial_error: float = 1.0


PREPROCESS_METHODS: dict[str, dict[str, str]] = {
    "robust_mean": {
        "label": "鲁棒滑动平均",
        "description": "MAD 异常点检测 + 局部中值修复 + 去均值 + 滑动平均，适合含脉冲干扰和宽带噪声的课程实验信号。",
    },
    "median": {
        "label": "中值滤波",
        "description": "用中值窗口压制尖峰脉冲，尽量保留边缘和突变，适合异常点明显的观测序列。",
    },
    "ema": {
        "label": "指数平滑",
        "description": "递推低通平滑，响应更连续，适合模拟实时采集中的轻量在线预处理。",
    },
    "fft_lowpass": {
        "label": "FFT 低通",
        "description": "在频域截断高频分量，再反变换回时域，适合主频集中且高频噪声较强的信号。",
    },
    "hybrid": {
        "label": "混合增强",
        "description": "先修复脉冲异常点，再做中值滤波和滑动平均，适合噪声类型复杂的信号。",
    },
    "kalman": {
        "label": "卡尔曼滤波",
        "description": "把观测信号建模为带测量噪声的随机过程，用递推状态估计抑制噪声，适合在线实时去噪和跟踪。",
    },
}


METHOD_ALIASES: dict[str, str] = {
    "robust": "robust_mean",
    "mean": "robust_mean",
    "moving_average": "robust_mean",
    "smooth": "robust_mean",
    "滑动平均": "robust_mean",
    "均值": "robust_mean",
    "鲁棒": "robust_mean",
    "median": "median",
    "med": "median",
    "中值": "median",
    "中位数": "median",
    "ema": "ema",
    "exponential": "ema",
    "指数": "ema",
    "递推": "ema",
    "fft": "fft_lowpass",
    "lowpass": "fft_lowpass",
    "low-pass": "fft_lowpass",
    "低通": "fft_lowpass",
    "hybrid": "hybrid",
    "mix": "hybrid",
    "混合": "hybrid",
    "增强": "hybrid",
    "kalman": "kalman",
    "kalman_filter": "kalman",
    "卡尔曼": "kalman",
    "卡尔曼滤波": "kalman",
    "状态估计": "kalman",
}


def normalize_preprocess_method(method: str | None) -> str:
    """Map user-facing method names and aliases to an internal method id."""
    if not method:
        return "robust_mean"
    key = method.strip().lower()
    return METHOD_ALIASES.get(key, key if key in PREPROCESS_METHODS else "robust_mean")


def list_preprocess_methods() -> list[dict[str, str]]:
    """Return preprocessing methods that the dialogue agent can offer."""
    return [
        {"id": method_id, **metadata}
        for method_id, metadata in PREPROCESS_METHODS.items()
    ]


def preprocess_signal(
    signal: np.ndarray,
    config: PreprocessConfig | None = None,
) -> PreprocessResult:
    """Apply the configured noise preprocessing method."""
    cfg = config or PreprocessConfig()
    method = normalize_preprocess_method(cfg.method)
    samples = validate_signal_samples(signal)

    if method == "median":
        return _median_preprocess(samples, cfg)
    if method == "ema":
        return _ema_preprocess(samples, cfg)
    if method == "fft_lowpass":
        return _fft_lowpass_preprocess(samples, cfg)
    if method == "hybrid":
        return _hybrid_preprocess(samples, cfg)
    if method == "kalman":
        return _kalman_preprocess(samples, cfg)
    return _robust_mean_preprocess(samples, cfg)


def _base_repair(samples: np.ndarray, cfg: PreprocessConfig) -> tuple[np.ndarray, np.ndarray, float, float]:
    median = float(np.median(samples))
    mad = float(np.median(np.abs(samples - median)))
    robust_sigma = 1.4826 * mad if mad > 1e-12 else float(np.std(samples))
    upper = median + cfg.anomaly_threshold_sigma * robust_sigma
    lower = median - cfg.anomaly_threshold_sigma * robust_sigma
    anomaly_mask = (samples > upper) | (samples < lower)

    repaired = samples.copy()
    if cfg.repair_impulses:
        for idx in np.flatnonzero(anomaly_mask):
            left = max(0, idx - 4)
            right = min(samples.size, idx + 5)
            local_indices = np.arange(left, right)
            local_values = samples[left:right]
            local_values = local_values[local_indices != idx]
            repaired[idx] = float(np.median(local_values)) if local_values.size else median

    removed_mean = float(np.mean(repaired)) if cfg.remove_mean else 0.0
    return repaired - removed_mean, anomaly_mask, removed_mean, robust_sigma


def _make_result(
    signal: np.ndarray,
    anomaly_mask: np.ndarray,
    removed_mean: float,
    window: int,
    method: str,
    parameters: dict[str, Any],
) -> PreprocessResult:
    metadata = PREPROCESS_METHODS[method]
    return PreprocessResult(
        signal=signal,
        anomaly_mask=anomaly_mask,
        removed_mean=removed_mean,
        smoothing_window=window,
        method=method,
        method_label=metadata["label"],
        parameters=parameters,
    )


def _odd_window(window: int) -> int:
    window = min(511, max(1, int(window)))
    return window if window % 2 == 1 else window + 1


def _median_filter(signal: np.ndarray, window: int) -> np.ndarray:
    window = _odd_window(window)
    if window <= 1:
        return signal.copy()
    pad = window // 2
    padded = np.pad(signal, (pad, pad), mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, window)
    result = np.empty(signal.size, dtype=float)
    batch = max(1, 1_000_000 // window)
    for start in range(0, signal.size, batch):
        result[start:start + batch] = np.median(windows[start:start + batch], axis=1)
    return result


def _ema_filter(signal: np.ndarray, alpha: float) -> np.ndarray:
    alpha = float(np.clip(alpha, 0.02, 0.95))
    filtered = np.empty_like(signal, dtype=float)
    filtered[0] = signal[0] if signal.size else 0.0
    for idx in range(1, signal.size):
        filtered[idx] = alpha * signal[idx] + (1.0 - alpha) * filtered[idx - 1]
    return filtered


def _robust_mean_preprocess(samples: np.ndarray, cfg: PreprocessConfig) -> PreprocessResult:
    centered, anomaly_mask, removed_mean, robust_sigma = _base_repair(samples, cfg)
    window = _odd_window(cfg.smoothing_window)
    smoothed = moving_average(centered, window)
    return _make_result(
        smoothed,
        anomaly_mask,
        removed_mean,
        window,
        "robust_mean",
        {
            "window": window,
            "anomaly_threshold_sigma": float(cfg.anomaly_threshold_sigma),
            "robust_sigma": float(robust_sigma),
        },
    )


def _median_preprocess(samples: np.ndarray, cfg: PreprocessConfig) -> PreprocessResult:
    centered, anomaly_mask, removed_mean, robust_sigma = _base_repair(samples, cfg)
    window = _odd_window(cfg.smoothing_window)
    filtered = _median_filter(centered, window)
    return _make_result(
        filtered,
        anomaly_mask,
        removed_mean,
        window,
        "median",
        {
            "window": window,
            "anomaly_threshold_sigma": float(cfg.anomaly_threshold_sigma),
            "robust_sigma": float(robust_sigma),
        },
    )


def _ema_preprocess(samples: np.ndarray, cfg: PreprocessConfig) -> PreprocessResult:
    centered, anomaly_mask, removed_mean, robust_sigma = _base_repair(samples, cfg)
    alpha = float(np.clip(cfg.ema_alpha, 0.02, 0.95))
    filtered = _ema_filter(centered, alpha)
    return _make_result(
        filtered,
        anomaly_mask,
        removed_mean,
        1,
        "ema",
        {
            "alpha": alpha,
            "anomaly_threshold_sigma": float(cfg.anomaly_threshold_sigma),
            "robust_sigma": float(robust_sigma),
        },
    )


def _fft_lowpass_preprocess(samples: np.ndarray, cfg: PreprocessConfig) -> PreprocessResult:
    centered, anomaly_mask, removed_mean, robust_sigma = _base_repair(samples, cfg)
    sample_rate = float(cfg.sample_rate or 1.0)
    default_cutoff = max(sample_rate * 0.18, 1.0)
    cutoff = float(cfg.lowpass_cutoff_hz or default_cutoff)
    cutoff = min(max(cutoff, 0.1), sample_rate / 2.0)
    spectrum = np.fft.rfft(centered)
    freqs = np.fft.rfftfreq(centered.size, d=1.0 / sample_rate)
    spectrum[freqs > cutoff] = 0.0
    filtered = np.fft.irfft(spectrum, n=centered.size)
    return _make_result(
        filtered,
        anomaly_mask,
        removed_mean,
        1,
        "fft_lowpass",
        {
            "cutoff_hz": cutoff,
            "sample_rate": sample_rate,
            "anomaly_threshold_sigma": float(cfg.anomaly_threshold_sigma),
            "robust_sigma": float(robust_sigma),
        },
    )


def _hybrid_preprocess(samples: np.ndarray, cfg: PreprocessConfig) -> PreprocessResult:
    centered, anomaly_mask, removed_mean, robust_sigma = _base_repair(samples, cfg)
    window = _odd_window(max(3, cfg.smoothing_window))
    medianed = _median_filter(centered, window)
    smoothed = moving_average(medianed, window)
    cutoff = None
    if cfg.lowpass_cutoff_hz and cfg.sample_rate:
        sample_rate = float(cfg.sample_rate)
        cutoff = min(max(float(cfg.lowpass_cutoff_hz), 0.1), sample_rate / 2.0)
        spectrum = np.fft.rfft(smoothed)
        freqs = np.fft.rfftfreq(smoothed.size, d=1.0 / sample_rate)
        spectrum[freqs > cutoff] = 0.0
        smoothed = np.fft.irfft(spectrum, n=smoothed.size)
    parameters = {
        "window": window,
        "anomaly_threshold_sigma": float(cfg.anomaly_threshold_sigma),
        "robust_sigma": float(robust_sigma),
    }
    if cutoff is not None:
        parameters["cutoff_hz"] = float(cutoff)
        parameters["sample_rate"] = float(cfg.sample_rate)
    return _make_result(
        smoothed,
        anomaly_mask,
        removed_mean,
        window,
        "hybrid",
        parameters,
    )


def _kalman_preprocess(samples: np.ndarray, cfg: PreprocessConfig) -> PreprocessResult:
    centered, anomaly_mask, removed_mean, robust_sigma = _base_repair(samples, cfg)
    q = float(max(cfg.kalman_process_noise, 1e-9))
    r = float(max(cfg.kalman_measurement_noise, 1e-9))
    p = float(max(cfg.kalman_initial_error, 1e-9))

    filtered = np.empty_like(centered, dtype=float)
    if centered.size:
        estimate = float(centered[0])
        filtered[0] = estimate
        for idx in range(1, centered.size):
            predicted_estimate = estimate
            predicted_error = p + q
            gain = predicted_error / (predicted_error + r)
            estimate = predicted_estimate + gain * (float(centered[idx]) - predicted_estimate)
            p = (1.0 - gain) * predicted_error
            filtered[idx] = estimate

    return _make_result(
        filtered,
        anomaly_mask,
        removed_mean,
        1,
        "kalman",
        {
            "process_noise_q": q,
            "measurement_noise_r": r,
            "initial_error_p": float(max(cfg.kalman_initial_error, 1e-9)),
            "anomaly_threshold_sigma": float(cfg.anomaly_threshold_sigma),
            "robust_sigma": float(robust_sigma),
        },
    )
