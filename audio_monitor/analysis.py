"""Pure NumPy analysis helpers for captured audio blocks."""

from __future__ import annotations

import numpy as np


DB_FLOOR = -120.0
SIGNAL_THRESHOLD_DBFS = -60.0
CLIP_THRESHOLD = 0.999
SPECTRUM_BANDS = 48


def amplitude_to_dbfs(amplitude: float) -> float:
    """Convert a linear full-scale amplitude to dBFS with a finite floor."""
    if not np.isfinite(amplitude) or amplitude <= 0:
        return DB_FLOOR
    return max(DB_FLOOR, 20.0 * float(np.log10(amplitude)))


def _spectrum_dbfs(samples: np.ndarray, sample_rate: int) -> list[tuple[float, float]]:
    if samples.size < 2:
        return []

    window = np.hanning(samples.size).astype(np.float32, copy=False)
    magnitudes = np.abs(np.fft.rfft(samples * window))
    magnitudes *= 2.0 / max(float(window.sum()), 1.0)
    frequencies = np.fft.rfftfreq(samples.size, 1.0 / sample_rate)
    min_frequency = max(20.0, sample_rate / samples.size)
    max_frequency = min(20_000.0, sample_rate / 2.0)
    if max_frequency <= min_frequency:
        return []

    edges = np.geomspace(min_frequency, max_frequency, SPECTRUM_BANDS + 1)
    result = []
    for lower, upper in zip(edges[:-1], edges[1:]):
        mask = (frequencies >= lower) & (frequencies < upper)
        if not np.any(mask):
            level = DB_FLOOR
        else:
            level = amplitude_to_dbfs(float(np.max(magnitudes[mask])))
        result.append((float(np.sqrt(lower * upper)), level))
    return result


def analyze_block(samples: np.ndarray, sample_rate: int) -> dict:
    """Return real per-input peak/RMS levels and a spectrum for a captured block."""
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim == 1:
        audio = audio.reshape(-1, 1)
    if audio.ndim != 2 or audio.shape[0] == 0 or audio.shape[1] == 0:
        raise ValueError("Audioblock muss Samples und mindestens einen Kanal enthalten.")
    if sample_rate <= 0:
        raise ValueError("Die Abtastrate muss groesser als null sein.")

    audio = np.nan_to_num(audio, copy=True, nan=0.0, posinf=1.0, neginf=-1.0)
    absolute = np.abs(audio)
    peak_linear = np.max(absolute, axis=0)
    rms_linear = np.sqrt(np.mean(np.square(audio, dtype=np.float64), axis=0))
    peaks = [amplitude_to_dbfs(value) for value in peak_linear]
    rms = [amplitude_to_dbfs(value) for value in rms_linear]
    spectrum = [
        _spectrum_dbfs(audio[:, channel], sample_rate)
        for channel in range(audio.shape[1])
    ]

    return {
        "peak_dbfs": peaks,
        "rms_dbfs": rms,
        "signal": [value >= SIGNAL_THRESHOLD_DBFS for value in rms],
        "clipping": [value >= CLIP_THRESHOLD for value in peak_linear],
        "spectrum": spectrum,
    }
