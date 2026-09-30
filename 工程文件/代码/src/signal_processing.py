"""Signal generation, preprocessing and feature extraction utilities."""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

import numpy as np


@dataclass
class SignalConfig:
    """Configuration for random signal simulation."""

    sample_rate: float = 200.0
    duration: float = 8.0
    base_frequency: float = 8.0
    amplitude: float = 1.2
    noise_std: float = 0.55
    ar_coefficient: float = 0.86
    impulse_probability: float = 0.012
    seed: int = 42
    signal_model: str = "random_process"
    waveform: str = "random_process"
    noise_model: str = "mixed"

    @property
    def sample_count(self) -> int:
        return int(self.sample_rate * self.duration)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SignalBundle:
    """Container for simulated signal arrays."""

    time: np.ndarray
    clean: np.ndarray
    observed: np.ndarray
    noise: np.ndarray
    impulse_mask: np.ndarray
    config: SignalConfig
    source: str = "simulation"
    has_clean_reference: bool = True


@dataclass
class PreprocessResult:
    """Output of preprocessing stage."""

    signal: np.ndarray
    anomaly_mask: np.ndarray
    removed_mean: float
    smoothing_window: int
    method: str = "robust_mean"
    method_label: str = "鲁棒滑动平均"
    parameters: dict[str, Any] = field(default_factory=dict)


def _triangle_wave(phase: np.ndarray) -> np.ndarray:
    return 2.0 * np.abs(2.0 * (phase - np.floor(phase + 0.5))) - 1.0


def _sawtooth_wave(phase: np.ndarray) -> np.ndarray:
    return 2.0 * (phase - np.floor(phase + 0.5))


def _signal_component(config: SignalConfig, time: np.ndarray) -> np.ndarray:
    phase = config.base_frequency * time
    waveform = config.waveform or config.signal_model
    if waveform in {"sine", "sine_gaussian"}:
        return config.amplitude * np.sin(2 * np.pi * phase)
    if waveform == "square":
        return config.amplitude * np.sign(np.sin(2 * np.pi * phase))
    if waveform == "triangle":
        return config.amplitude * _triangle_wave(phase)
    if waveform == "sawtooth":
        return config.amplitude * _sawtooth_wave(phase)
    if waveform == "multi_sine":
        return (
            config.amplitude * np.sin(2 * np.pi * phase)
            + 0.45 * config.amplitude * np.sin(2 * np.pi * (1.8 * config.base_frequency) * time + 0.5)
            + 0.25 * config.amplitude * np.sin(2 * np.pi * (2.6 * config.base_frequency) * time + 1.2)
        )
    if waveform == "chirp":
        end_frequency = min(config.sample_rate * 0.45, max(config.base_frequency * 3.0, config.base_frequency + 1.0))
        sweep_rate = (end_frequency - config.base_frequency) / max(config.duration, 1e-12)
        return config.amplitude * np.sin(2 * np.pi * (config.base_frequency * time + 0.5 * sweep_rate * time**2))
    harmonic = 0.28 * np.sin(2 * np.pi * (config.base_frequency * 2.4) * time + 0.7)
    slow_trend = 0.18 * np.sin(2 * np.pi * 0.35 * time)
    carrier = config.amplitude * np.sin(2 * np.pi * phase)
    return carrier + harmonic + slow_trend


def _noise_component(config: SignalConfig, rng: np.random.Generator, size: int) -> tuple[np.ndarray, np.ndarray]:
    impulse_mask = rng.random(size) < config.impulse_probability
    impulse_values = rng.choice([-1.0, 1.0], size=size) * rng.uniform(2.0, 3.6, size=size)
    impulses = impulse_mask.astype(float) * impulse_values
    gaussian = rng.normal(0.0, config.noise_std, size=size)
    uniform = rng.uniform(-np.sqrt(3) * config.noise_std, np.sqrt(3) * config.noise_std, size=size)

    ar_noise = np.zeros(size, dtype=float)
    innovations = rng.normal(0.0, config.noise_std, size=size)
    for idx in range(1, size):
        ar_noise[idx] = (
            config.ar_coefficient * ar_noise[idx - 1]
            + np.sqrt(1 - config.ar_coefficient**2) * innovations[idx]
        )

    if config.noise_model in {"gaussian", "sine_gaussian"}:
        return gaussian, np.zeros(size, dtype=bool)
    if config.noise_model == "uniform":
        return uniform, np.zeros(size, dtype=bool)
    if config.noise_model == "impulse":
        return impulses, impulse_mask
    if config.noise_model == "ar":
        return ar_noise, np.zeros(size, dtype=bool)
    if config.noise_model == "gaussian_impulse":
        return gaussian * 0.65 + impulses, impulse_mask
    return ar_noise + gaussian * 0.32 + impulses, impulse_mask


def generate_random_signal(config: SignalConfig) -> SignalBundle:
    """Generate a noisy simulated signal from a selected signal/noise pair."""
    for name in ("sample_rate", "duration", "base_frequency", "amplitude", "noise_std",
                 "ar_coefficient", "impulse_probability"):
        if not np.isfinite(getattr(config, name)):
            raise ValueError(f"{name} must be finite")
    if config.sample_rate <= 0 or config.duration <= 0:
        raise ValueError("sample_rate and duration must be positive")
    count = config.sample_rate * config.duration
    if not np.isfinite(count) or count < 1:
        raise ValueError("Simulation must contain at least one sample with a finite sample count")
    if config.noise_std < 0:
        raise ValueError("noise_std must be non-negative")
    if abs(config.ar_coefficient) > 1:
        raise ValueError("ar_coefficient must be between -1 and 1")
    if not 0 <= config.impulse_probability <= 1:
        raise ValueError("impulse_probability must be between 0 and 1")
    rng = np.random.default_rng(config.seed)
    time = np.arange(config.sample_count) / config.sample_rate

    clean = _signal_component(config, time)
    noise, impulse_mask = _noise_component(config, rng, config.sample_count)
    observed = clean + noise
    return SignalBundle(
        time=time,
        clean=clean,
        observed=observed,
        noise=noise,
        impulse_mask=impulse_mask,
        config=config,
        source=f"{config.waveform}+{config.noise_model}",
    )


def moving_average(signal: np.ndarray, window: int) -> np.ndarray:
    """Apply a centered moving average while preserving signal length."""
    window = max(1, int(window))
    if window == 1:
        return signal.copy()
    kernel = np.ones(window, dtype=float) / window
    pad_left = window // 2
    pad_right = window - 1 - pad_left
    padded = np.pad(signal, (pad_left, pad_right), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def validate_signal_samples(signal: np.ndarray) -> np.ndarray:
    """Convert a signal to a non-empty, finite, one-dimensional float array."""
    samples = np.asarray(signal, dtype=float)
    if samples.ndim != 1 or samples.size == 0:
        raise ValueError("Signal must be a non-empty one-dimensional array")
    if not np.all(np.isfinite(samples)):
        raise ValueError("Signal samples must be finite")
    return samples


def robust_preprocess(signal: np.ndarray, smoothing_window: int = 7) -> PreprocessResult:
    """Suppress impulse noise, remove DC component and smooth white noise."""
    signal = validate_signal_samples(signal)
    median = float(np.median(signal))
    mad = float(np.median(np.abs(signal - median)))
    robust_sigma = 1.4826 * mad if mad > 1e-12 else float(np.std(signal))
    threshold = median + 3.0 * robust_sigma
    lower = median - 3.0 * robust_sigma
    anomaly_mask = (signal > threshold) | (signal < lower)

    repaired = signal.copy()
    anomaly_indices = np.flatnonzero(anomaly_mask)
    for idx in anomaly_indices:
        left = max(0, idx - 4)
        right = min(signal.size, idx + 5)
        neighborhood = np.delete(signal[left:right], np.where(np.arange(left, right) == idx))
        repaired[idx] = float(np.median(neighborhood)) if neighborhood.size else median

    removed_mean = float(np.mean(repaired))
    centered = repaired - removed_mean
    smoothed = moving_average(centered, smoothing_window)
    return PreprocessResult(
        signal=smoothed,
        anomaly_mask=anomaly_mask,
        removed_mean=removed_mean,
        smoothing_window=smoothing_window,
    )


def autocorrelation(signal: np.ndarray, max_lag: int) -> np.ndarray:
    """Estimate normalized autocorrelation from lag 0 to max_lag."""
    signal = np.asarray(signal, dtype=float)
    centered = signal - np.mean(signal)
    variance = np.dot(centered, centered)
    if variance <= 1e-12:
        return np.ones(max_lag + 1)
    values = [1.0]
    for lag in range(1, max_lag + 1):
        values.append(float(np.dot(centered[:-lag], centered[lag:]) / variance))
    return np.asarray(values)


def estimate_snr(clean: np.ndarray, observed_or_processed: np.ndarray) -> float:
    """Estimate SNR in dB against a known clean simulation reference."""
    clean = np.asarray(clean, dtype=float)
    candidate = np.asarray(observed_or_processed, dtype=float)
    noise = candidate - clean
    signal_power = float(np.mean(clean**2))
    noise_power = float(np.mean(noise**2))
    if noise_power <= 1e-12:
        return 99.0
    return 10.0 * np.log10(signal_power / noise_power)


def extract_time_features(signal: np.ndarray) -> dict[str, float]:
    """Extract time-domain random signal statistics."""
    signal = np.asarray(signal, dtype=float)
    mean = float(np.mean(signal))
    centered = signal - mean
    std = float(np.std(signal))
    rms = float(np.sqrt(np.mean(signal**2)))
    abs_signal = np.abs(signal)
    abs_mean = float(np.mean(abs_signal))
    peak = float(np.max(abs_signal)) if signal.size else 0.0
    peak_to_peak = float(np.ptp(signal)) if signal.size else 0.0
    root_amplitude = float(np.mean(np.sqrt(abs_signal)) ** 2) if signal.size else 0.0
    skewness = float(np.mean(centered**3) / (std**3 + 1e-12))
    kurtosis = float(np.mean(centered**4) / (std**4 + 1e-12))
    zero_crossing_rate = float(np.mean(np.diff(np.signbit(signal)) != 0))
    corr = autocorrelation(signal, 12)
    return {
        "mean": mean,
        "variance": float(np.var(signal)),
        "std": std,
        "rms": rms,
        "peak": peak,
        "peak_to_peak": peak_to_peak,
        "crest_factor": float(peak / (rms + 1e-12)),
        "skewness": skewness,
        "kurtosis": kurtosis,
        "impulse_factor": float(peak / (abs_mean + 1e-12)),
        "shape_factor": float(rms / (abs_mean + 1e-12)),
        "clearance_factor": float(peak / (root_amplitude + 1e-12)),
        "zero_crossing_rate": zero_crossing_rate,
        "lag1_autocorrelation": float(corr[1]) if corr.size > 1 else 0.0,
        "lag6_autocorrelation": float(corr[6]) if corr.size > 6 else 0.0,
    }


def extract_frequency_features(signal: np.ndarray, sample_rate: float) -> dict[str, Any]:
    """Extract FFT-based frequency-domain features."""
    signal = np.asarray(signal, dtype=float)
    centered = signal - np.mean(signal)
    window = np.hanning(signal.size)
    spectrum = np.fft.rfft(centered * window)
    freqs = np.fft.rfftfreq(signal.size, d=1.0 / sample_rate)
    magnitude = np.abs(spectrum)
    power = np.abs(spectrum) ** 2
    magnitude[0] = 0.0
    power[0] = 0.0
    total_magnitude = float(np.sum(magnitude))
    total_power = float(np.sum(power))
    if total_power <= 1e-12:
        probabilities = np.ones_like(power) / max(power.size, 1)
    else:
        probabilities = power / total_power

    dominant_idx = int(np.argmax(power)) if power.size else 0
    mean_frequency = float(np.sum(freqs * magnitude) / (total_magnitude + 1e-12))
    centroid = float(np.sum(freqs * power) / (total_power + 1e-12))
    rms_frequency = float(np.sqrt(np.sum((freqs**2) * power) / (total_power + 1e-12)))
    frequency_variance = float(
        np.sum(((freqs - centroid) ** 2) * power) / (total_power + 1e-12)
    )
    frequency_std = float(np.sqrt(frequency_variance))
    bandwidth = float(
        np.sqrt(np.sum(((freqs - centroid) ** 2) * power) / (total_power + 1e-12))
    )
    entropy = float(-np.sum(probabilities * np.log2(probabilities + 1e-12)))
    entropy_norm = entropy / float(np.log2(power.size + 1e-12)) if power.size > 1 else 0.0
    cumulative = np.cumsum(power)
    rolloff_idx = int(np.searchsorted(cumulative, 0.85 * total_power)) if total_power > 0 else 0
    top_indices = np.argsort(power)[-5:][::-1] if power.size else np.asarray([], dtype=int)
    top_peaks = [
        {"frequency_hz": float(freqs[idx]), "power": float(power[idx])}
        for idx in top_indices
    ]
    return {
        "dominant_frequency_hz": float(freqs[dominant_idx]) if freqs.size else 0.0,
        "dominant_power": float(power[dominant_idx]) if power.size else 0.0,
        "mean_frequency_hz": mean_frequency,
        "spectral_centroid_hz": centroid,
        "rms_frequency_hz": rms_frequency,
        "frequency_variance_hz2": frequency_variance,
        "frequency_std_hz": frequency_std,
        "spectral_bandwidth_hz": bandwidth,
        "spectral_entropy": entropy_norm,
        "spectral_rolloff_85_hz": float(freqs[min(rolloff_idx, freqs.size - 1)]),
        "top_peaks": top_peaks,
        "spectrum": {
            "frequencies": freqs.tolist(),
            "power": power.tolist(),
        },
    }


def summarize_window(
    bundle: SignalBundle,
    processed: PreprocessResult,
) -> dict[str, Any]:
    """Build a complete feature summary for one signal window."""
    time_features = extract_time_features(processed.signal)
    frequency_features = extract_frequency_features(
        processed.signal,
        sample_rate=bundle.config.sample_rate,
    )
    raw_snr = estimate_snr(bundle.clean, bundle.observed)
    processed_snr = estimate_snr(bundle.clean, processed.signal)
    anomaly_rate = float(np.mean(processed.anomaly_mask))
    return {
        "time_features": time_features,
        "frequency_features": frequency_features,
        "quality": {
            "raw_snr_db": float(raw_snr),
            "processed_snr_db": float(processed_snr),
            "snr_improvement_db": float(processed_snr - raw_snr),
            "anomaly_rate": anomaly_rate,
            "detected_anomaly_count": int(np.sum(processed.anomaly_mask)),
        },
    }


def decimate_for_export(*arrays: np.ndarray, max_points: int = 520) -> list[list[float]]:
    """Downsample arrays for compact HTML/JSON rendering."""
    if not arrays:
        return []
    count = len(arrays[0])
    step = max(1, int(np.ceil(count / max_points)))
    return [np.asarray(array)[::step].astype(float).tolist() for array in arrays]
