from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

_MAX_PEAK = 0.99
_TARGET_RMS = {
    "bass": 0.18,
    "vocals": 0.2,
    "guitar": 0.18,
    "other": 0.14,
}


def _fold_to_mono(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        return audio.astype(np.float32, copy=False)
    if audio.ndim != 2:
        raise ValueError(f"unsupported audio shape: {audio.shape}")
    return np.mean(audio, axis=1, dtype=np.float32)


def _rms_normalize(audio: np.ndarray, target_rms: float, max_peak: float = _MAX_PEAK) -> np.ndarray:
    if audio.size == 0:
        return audio.astype(np.float32, copy=False)

    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64), dtype=np.float64)))
    if rms <= 1e-8:
        return audio.astype(np.float32, copy=False)

    normalized = audio.astype(np.float64, copy=False) * (target_rms / rms)
    peak = float(np.max(np.abs(normalized)))
    if peak > max_peak:
        normalized *= max_peak / peak
    return normalized.astype(np.float32, copy=False)


def _apply_frequency_weights(
    audio: np.ndarray,
    sample_rate: int,
    rumble_cutoff_hz: float | None = None,
    harmonic_center_hz: float | None = None,
    harmonic_width_hz: float | None = None,
    harmonic_gain: float = 0.0,
) -> np.ndarray:
    if audio.ndim == 2:
        channels = [
            _apply_frequency_weights(
                audio[:, channel],
                sample_rate,
                rumble_cutoff_hz=rumble_cutoff_hz,
                harmonic_center_hz=harmonic_center_hz,
                harmonic_width_hz=harmonic_width_hz,
                harmonic_gain=harmonic_gain,
            )
            for channel in range(audio.shape[1])
        ]
        return np.stack(channels, axis=1)

    if audio.size == 0:
        return audio.astype(np.float32, copy=False)

    spectrum = np.fft.rfft(audio.astype(np.float64, copy=False))
    freqs = np.fft.rfftfreq(audio.shape[0], d=1.0 / sample_rate)
    weights = np.ones_like(freqs, dtype=np.float64)

    if rumble_cutoff_hz:
        weights *= np.clip(freqs / rumble_cutoff_hz, 0.0, 1.0)

    if harmonic_center_hz and harmonic_width_hz and harmonic_gain:
        harmonic_profile = np.exp(
            -0.5 * ((freqs - harmonic_center_hz) / harmonic_width_hz) ** 2
        )
        weights *= 1.0 + (harmonic_gain * harmonic_profile)

    conditioned = np.fft.irfft(spectrum * weights, n=audio.shape[0])
    return conditioned.astype(np.float32, copy=False)


def condition_audio(stem: str, audio: np.ndarray, sample_rate: int) -> tuple[np.ndarray, int]:
    stem_key = stem.lower()
    audio_array = np.asarray(audio, dtype=np.float32)

    if stem_key == "drums":
        return audio_array, sample_rate

    if stem_key == "bass":
        conditioned = _fold_to_mono(audio_array)
        conditioned = _apply_frequency_weights(
            conditioned,
            sample_rate,
            rumble_cutoff_hz=35.0,
            harmonic_center_hz=1200.0,
            harmonic_width_hz=700.0,
            harmonic_gain=0.35,
        )
        return _rms_normalize(conditioned, target_rms=_TARGET_RMS["bass"]), sample_rate

    if stem_key == "vocals":
        conditioned = _fold_to_mono(audio_array)
        return _rms_normalize(conditioned, target_rms=_TARGET_RMS["vocals"]), sample_rate

    if stem_key == "guitar":
        conditioned = _apply_frequency_weights(audio_array, sample_rate, rumble_cutoff_hz=70.0)
        return _rms_normalize(conditioned, target_rms=_TARGET_RMS["guitar"]), sample_rate

    if stem_key == "other":
        return _rms_normalize(audio_array, target_rms=_TARGET_RMS["other"]), sample_rate

    return _rms_normalize(audio_array, target_rms=_TARGET_RMS["guitar"]), sample_rate


def condition_file(stem: str, src: Path, dst: Path) -> Path:
    audio, sample_rate = sf.read(src, always_2d=False)
    conditioned, conditioned_sample_rate = condition_audio(stem, audio, sample_rate)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sf.write(dst, conditioned, conditioned_sample_rate, subtype="FLOAT")
    return dst
