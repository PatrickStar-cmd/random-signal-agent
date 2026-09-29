"""Time-domain and frequency-domain analysis module."""

from __future__ import annotations

from typing import Any

import numpy as np

from .advanced_analysis import AdvancedAnalysisConfig, advanced_random_process_analysis
from .signal_processing import (
    PreprocessResult,
    SignalBundle,
    estimate_snr,
    extract_frequency_features,
    extract_time_features,
)


def analyze_time_domain(signal: np.ndarray) -> dict[str, float]:
    """Return time-domain statistics."""
    return extract_time_features(signal)


def analyze_frequency_domain(signal: np.ndarray, sample_rate: float) -> dict[str, Any]:
    """Return FFT-based frequency-domain features."""
    return extract_frequency_features(signal, sample_rate)


def summarize_signal_window(
    bundle: SignalBundle,
    processed: PreprocessResult,
    advanced_config: AdvancedAnalysisConfig | None = None,
) -> dict[str, Any]:
    """Build a full analysis summary for one signal window."""
    time_features = analyze_time_domain(processed.signal)
    frequency_features = analyze_frequency_domain(
        processed.signal,
        sample_rate=bundle.config.sample_rate,
    )

    if bundle.has_clean_reference:
        raw_snr: float | None = estimate_snr(bundle.clean, bundle.observed)
        processed_snr: float | None = estimate_snr(bundle.clean, processed.signal)
        snr_improvement: float | None = processed_snr - raw_snr
    else:
        raw_snr = None
        processed_snr = None
        snr_improvement = None
    anomaly_rate = float(np.mean(processed.anomaly_mask))
    return {
        "time_features": time_features,
        "frequency_features": frequency_features,
        "quality": {
            "raw_snr_db": None if raw_snr is None else float(raw_snr),
            "processed_snr_db": None if processed_snr is None else float(processed_snr),
            "snr_improvement_db": None if snr_improvement is None else float(snr_improvement),
            "anomaly_rate": anomaly_rate,
            "detected_anomaly_count": int(np.sum(processed.anomaly_mask)),
            "has_clean_reference": bundle.has_clean_reference,
        },
        "advanced_analysis": advanced_random_process_analysis(
            processed.signal,
            bundle.config.sample_rate,
            advanced_config,
        ),
    }
