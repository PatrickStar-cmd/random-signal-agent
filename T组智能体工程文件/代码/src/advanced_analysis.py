"""Advanced random-process analysis utilities."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np

from .signal_processing import autocorrelation


@dataclass
class AdvancedAnalysisConfig:
    """Parameters for random-process advanced analysis."""

    ar_order: int = 8
    prediction_horizon: int = 24
    max_autocorr_lag: int = 48
    psd_segment_length: int = 256
    psd_overlap: float = 0.5
    residual_lag: int = 24

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def advanced_random_process_analysis(
    signal: np.ndarray,
    sample_rate: float,
    config: AdvancedAnalysisConfig | None = None,
) -> dict[str, Any]:
    """Run AR, autocorrelation, PSD and residual diagnostics on one signal."""

    cfg = config or AdvancedAnalysisConfig()
    samples = np.asarray(signal, dtype=float)
    ar = estimate_ar_model(samples, cfg.ar_order, cfg.prediction_horizon)
    autocorr = estimate_autocorrelation(samples, cfg.max_autocorr_lag)
    psd = estimate_welch_psd(samples, sample_rate, cfg.psd_segment_length, cfg.psd_overlap)
    residual = analyze_prediction_residuals(samples, ar["coefficients"], cfg.residual_lag)
    return {
        "config": cfg.to_dict(),
        "ar_model": ar,
        "autocorrelation": autocorr,
        "power_spectrum": psd,
        "prediction_residual": residual,
    }


def estimate_ar_model(signal: np.ndarray, order: int, horizon: int) -> dict[str, Any]:
    """Estimate AR coefficients by least squares and produce short forecasts."""

    samples = np.asarray(signal, dtype=float)
    order = int(max(1, min(order, max(samples.size - 2, 1), 64)))
    horizon = int(max(1, min(horizon, 256)))
    if samples.size <= order + 1:
        return {
            "order": order,
            "coefficients": [],
            "noise_variance": 0.0,
            "aic": 0.0,
            "bic": 0.0,
            "forecast": [],
            "stability_radius": 0.0,
        }

    rows = samples.size - order
    x = np.empty((rows, order), dtype=float)
    for idx in range(rows):
        x[idx, :] = samples[idx : idx + order][::-1]
    y = samples[order:]
    coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
    fitted = x @ coefficients
    residual = y - fitted
    noise_variance = float(np.mean(residual**2))
    safe_variance = max(noise_variance, 1e-12)
    aic = float(rows * np.log(safe_variance) + 2 * order)
    bic = float(rows * np.log(safe_variance) + order * np.log(max(rows, 1)))
    forecast = _forecast_ar(samples, coefficients, horizon)
    roots = np.roots(np.r_[1.0, -coefficients]) if coefficients.size else np.asarray([])
    stability_radius = float(np.max(np.abs(roots))) if roots.size else 0.0
    return {
        "order": order,
        "coefficients": coefficients.astype(float).tolist(),
        "noise_variance": noise_variance,
        "aic": aic,
        "bic": bic,
        "forecast": forecast.astype(float).tolist(),
        "stability_radius": stability_radius,
    }


def estimate_autocorrelation(signal: np.ndarray, max_lag: int) -> dict[str, Any]:
    """Estimate normalized autocorrelation and simple correlation length."""

    samples = np.asarray(signal, dtype=float)
    max_lag = int(max(1, min(max_lag, max(samples.size - 1, 1), 512)))
    values = autocorrelation(samples, max_lag)
    below = np.flatnonzero(np.abs(values) < 1.0 / np.e)
    correlation_lag = int(below[0]) if below.size else max_lag
    return {
        "max_lag": max_lag,
        "lags": list(range(max_lag + 1)),
        "values": values.astype(float).tolist(),
        "lag1": float(values[1]) if values.size > 1 else 0.0,
        "lag6": float(values[6]) if values.size > 6 else 0.0,
        "correlation_length_lag": correlation_lag,
    }


def estimate_welch_psd(
    signal: np.ndarray,
    sample_rate: float,
    segment_length: int,
    overlap: float,
) -> dict[str, Any]:
    """Estimate PSD with a compact Welch method using NumPy only."""

    samples = np.asarray(signal, dtype=float)
    sample_rate = float(max(sample_rate, 1e-9))
    segment_length = int(max(32, min(segment_length, max(samples.size, 32), 4096)))
    if segment_length > samples.size:
        segment_length = samples.size
    if segment_length < 2:
        return {
            "segment_length": segment_length,
            "overlap": float(overlap),
            "frequencies": [],
            "power": [],
            "dominant_frequency_hz": 0.0,
            "mean_frequency_hz": 0.0,
            "spectral_centroid_hz": 0.0,
            "spectral_entropy": 0.0,
        }

    overlap = float(min(max(overlap, 0.0), 0.9))
    step = max(1, int(segment_length * (1.0 - overlap)))
    window = np.hanning(segment_length)
    scale = sample_rate * np.sum(window**2)
    spectra = []
    for start in range(0, samples.size - segment_length + 1, step):
        segment = samples[start : start + segment_length]
        segment = segment - np.mean(segment)
        spectrum = np.fft.rfft(segment * window)
        spectra.append((np.abs(spectrum) ** 2) / max(scale, 1e-12))
    if not spectra:
        segment = samples[-segment_length:] - np.mean(samples[-segment_length:])
        spectrum = np.fft.rfft(segment * window)
        spectra.append((np.abs(spectrum) ** 2) / max(scale, 1e-12))

    power = np.mean(np.vstack(spectra), axis=0)
    freqs = np.fft.rfftfreq(segment_length, d=1.0 / sample_rate)
    if power.size:
        power[0] = 0.0
    total_power = float(np.sum(power))
    if total_power <= 1e-12:
        probabilities = np.ones_like(power) / max(power.size, 1)
    else:
        probabilities = power / total_power
    dominant_idx = int(np.argmax(power)) if power.size else 0
    mean_frequency = float(np.sum(freqs * np.sqrt(np.maximum(power, 0.0))) / (np.sum(np.sqrt(np.maximum(power, 0.0))) + 1e-12))
    centroid = float(np.sum(freqs * power) / (total_power + 1e-12))
    entropy = float(-np.sum(probabilities * np.log2(probabilities + 1e-12)))
    entropy_norm = entropy / float(np.log2(power.size + 1e-12)) if power.size > 1 else 0.0
    return {
        "segment_length": segment_length,
        "overlap": overlap,
        "frequencies": freqs.astype(float).tolist(),
        "power": power.astype(float).tolist(),
        "dominant_frequency_hz": float(freqs[dominant_idx]) if freqs.size else 0.0,
        "mean_frequency_hz": mean_frequency,
        "spectral_centroid_hz": centroid,
        "spectral_entropy": entropy_norm,
    }


def analyze_prediction_residuals(
    signal: np.ndarray,
    coefficients: list[float],
    residual_lag: int,
) -> dict[str, Any]:
    """Analyze one-step AR prediction residual whiteness."""

    samples = np.asarray(signal, dtype=float)
    coeffs = np.asarray(coefficients, dtype=float)
    order = coeffs.size
    if samples.size <= order + 1 or order == 0:
        residual = samples - np.mean(samples) if samples.size else np.asarray([], dtype=float)
    else:
        rows = samples.size - order
        x = np.empty((rows, order), dtype=float)
        for idx in range(rows):
            x[idx, :] = samples[idx : idx + order][::-1]
        residual = samples[order:] - x @ coeffs

    residual_lag = int(max(1, min(residual_lag, max(residual.size - 1, 1), 256)))
    corr = autocorrelation(residual, residual_lag) if residual.size else np.asarray([1.0])
    energy = float(np.mean(residual**2)) if residual.size else 0.0
    whiteness = float(np.mean(np.abs(corr[1:]))) if corr.size > 1 else 0.0
    return {
        "residual_count": int(residual.size),
        "mean": float(np.mean(residual)) if residual.size else 0.0,
        "variance": float(np.var(residual)) if residual.size else 0.0,
        "rms": float(np.sqrt(energy)),
        "whiteness_score": whiteness,
        "autocorrelation_lag1": float(corr[1]) if corr.size > 1 else 0.0,
        "autocorrelation": corr.astype(float).tolist(),
    }


def _forecast_ar(signal: np.ndarray, coefficients: np.ndarray, horizon: int) -> np.ndarray:
    history = [float(value) for value in np.asarray(signal, dtype=float)]
    order = coefficients.size
    forecast: list[float] = []
    for _ in range(horizon):
        if len(history) < order:
            next_value = history[-1] if history else 0.0
        else:
            recent = np.asarray(history[-order:][::-1], dtype=float)
            next_value = float(np.dot(coefficients, recent))
        history.append(next_value)
        forecast.append(next_value)
    return np.asarray(forecast, dtype=float)
