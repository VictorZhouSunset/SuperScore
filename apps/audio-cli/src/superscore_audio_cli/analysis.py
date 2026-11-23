from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import numpy as np
import soundfile as sf

NOTE_NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
DEFAULT_ALLOWED_SUBDIVISIONS = (1, 2, 4)
CHORD_TEMPLATES = {
    "": np.array([1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0]),
    "m": np.array([1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0]),
}


def infer_meter_from_grouping(beats: Sequence[float], downbeats: Sequence[float]) -> str:
    if len(beats) < 2 or len(downbeats) < 2:
        return "4/4"

    beat_intervals = np.diff(np.asarray(beats, dtype=np.float64))
    median_interval = float(np.median(beat_intervals))
    if median_interval <= 0:
        return "4/4"

    grouping_votes: list[int] = []
    for gap in np.diff(np.asarray(downbeats, dtype=np.float64)):
        beats_per_bar = int(round(gap / median_interval))
        if 2 <= beats_per_bar <= 6:
            grouping_votes.append(beats_per_bar)

    if not grouping_votes:
        return "4/4"

    counts = {value: grouping_votes.count(value) for value in set(grouping_votes)}
    highest_count = max(counts.values())
    candidates = [value for value, count in counts.items() if count == highest_count]
    winner = min(
        candidates,
        key=lambda value: (
            abs(value - 4),
            0 if value == 4 else 1 if value == 3 else 2,
            value,
        ),
    )
    return f"{winner}/4"


def smooth_beat_grid(beats: Sequence[float]) -> list[float]:
    if len(beats) < 3:
        return [float(beat) for beat in beats]

    smoothed = [float(beats[0])]
    intervals = np.diff(np.asarray(beats, dtype=np.float64))
    reference_interval = float(np.median(intervals[intervals > 0])) if np.any(intervals > 0) else 0.0
    if reference_interval <= 0:
        return [float(beat) for beat in beats]

    for beat in beats[1:]:
        candidate = float(beat)
        expected = smoothed[-1] + reference_interval
        if candidate <= smoothed[-1] or abs(candidate - expected) > reference_interval * 0.35:
            smoothed.append(expected)
        else:
            smoothed.append(candidate)
    return smoothed


def align_chord_changes_to_grid(changes: Sequence[dict], beat_grid: dict) -> list[dict]:
    boundaries = [float(value) for value in beat_grid.get("beats", [])]
    if len(boundaries) < 2:
        return []

    ordered_changes = sorted(
        (
            {
                "start": float(change.get("start", boundaries[0])),
                "end": float(change.get("end", boundaries[-1])),
                "label": str(change.get("label", "N")).strip() or "N",
            }
            for change in changes
        ),
        key=lambda change: (change["start"], change["end"]),
    )
    if not ordered_changes:
        return []

    snapped_starts: list[dict] = []
    previous_index = 0
    for change in ordered_changes:
        snapped_index = _nearest_boundary_index(change["start"], boundaries)
        snapped_index = max(previous_index, min(snapped_index, len(boundaries) - 2))
        if snapped_starts and snapped_starts[-1]["beatStart"] == snapped_index:
            snapped_starts[-1]["label"] = change["label"]
        else:
            snapped_starts.append({"beatStart": snapped_index, "label": change["label"]})
        previous_index = snapped_index

    final_index = _nearest_boundary_index(ordered_changes[-1]["end"], boundaries)
    final_index = max(final_index, snapped_starts[-1]["beatStart"] + 1)
    final_index = min(final_index, len(boundaries) - 1)

    aligned: list[dict] = []
    for index, snapped in enumerate(snapped_starts):
        start_index = snapped["beatStart"]
        next_index = (
            snapped_starts[index + 1]["beatStart"] if index + 1 < len(snapped_starts) else final_index
        )
        end_index = max(next_index, start_index + 1)
        end_index = min(end_index, len(boundaries) - 1)
        if end_index <= start_index:
            continue

        segment = {
            "start": boundaries[start_index],
            "end": boundaries[end_index],
            "label": snapped["label"],
            "beatStart": start_index,
            "beatEnd": end_index,
        }
        if (
            aligned
            and aligned[-1]["label"] == segment["label"]
            and aligned[-1]["beatEnd"] >= segment["beatStart"]
        ):
            aligned[-1]["beatEnd"] = max(aligned[-1]["beatEnd"], segment["beatEnd"])
            aligned[-1]["end"] = boundaries[aligned[-1]["beatEnd"]]
            continue
        aligned.append(segment)
    return aligned


def refine_slash_chord(
    label: str,
    root_pitch_class: int | None,
    chord_tones: Sequence[int],
    bass_pitch_class: int | None,
) -> str:
    if label == "N" or root_pitch_class is None or bass_pitch_class is None:
        return label
    if bass_pitch_class == root_pitch_class or bass_pitch_class not in chord_tones:
        return label
    return f"{label}/{NOTE_NAMES[bass_pitch_class]}"


def build_beat_grid_payload(
    source_path: Path | None,
    tempo: float,
    meter: str,
    beats: Sequence[float],
    downbeats: Sequence[float],
    confidence: dict[str, float],
) -> dict:
    rounded_beats = [round(float(beat), 6) for beat in beats]
    rounded_downbeats = [round(float(downbeat), 6) for downbeat in downbeats]
    rounded_confidence = {
        key: round(min(max(float(value), 0.0), 1.0), 4)
        for key, value in confidence.items()
    }
    section_start = rounded_beats[0] if rounded_beats else 0.0
    section_end = rounded_beats[-1] if rounded_beats else section_start
    rounded_tempo = round(float(tempo), 3)
    allowed_subdivisions = list(DEFAULT_ALLOWED_SUBDIVISIONS)
    return {
        "sourcePath": str(source_path) if source_path else "",
        "tempo": rounded_tempo,
        "meter": meter,
        "subdivision": 2,
        "allowedSubdivisions": allowed_subdivisions,
        "confidence": rounded_confidence,
        "beats": rounded_beats,
        "downbeats": rounded_downbeats,
        "sections": [
            {
                "start": section_start,
                "end": section_end,
                "tempo": rounded_tempo,
                "meter": meter,
                "allowedSubdivisions": allowed_subdivisions,
                "confidence": rounded_confidence,
            }
        ],
    }


def build_chord_payload(
    source_path: Path | None,
    meter: str,
    segments: Sequence[dict],
) -> dict:
    payload_segments: list[dict] = []
    confidences: list[float] = []
    for segment in segments:
        payload_segment = dict(segment)
        if "confidence" in payload_segment:
            payload_segment["confidence"] = round(float(payload_segment["confidence"]), 4)
            confidences.append(float(payload_segment["confidence"]))
        payload_segments.append(payload_segment)

    overall_confidence = round(float(np.mean(confidences)), 4) if confidences else 0.0
    return {
        "sourcePath": str(source_path) if source_path else "",
        "meter": meter,
        "confidence": overall_confidence,
        "segments": payload_segments,
    }


def build_harmony_mix(project_path: Path, stem_paths: list[Path]) -> Path:
    available_stems = [path for path in stem_paths if path.exists()]
    if not available_stems:
        raise RuntimeError("no stem audio available for harmony mix")

    target_sample_rate: int | None = None
    mono_tracks: list[np.ndarray] = []
    import librosa

    for stem_path in available_stems:
        audio, sample_rate = sf.read(stem_path, always_2d=False)
        mono_audio = _to_mono(audio)
        if mono_audio.size == 0:
            continue
        if target_sample_rate is None:
            target_sample_rate = sample_rate
        elif sample_rate != target_sample_rate:
            mono_audio = librosa.resample(
                mono_audio.astype(np.float32, copy=False),
                orig_sr=sample_rate,
                target_sr=target_sample_rate,
            )
        mono_tracks.append(mono_audio.astype(np.float32, copy=False))

    if not mono_tracks or target_sample_rate is None:
        raise RuntimeError("no non-empty stem audio available for harmony mix")

    max_length = max(track.shape[0] for track in mono_tracks)
    mix = np.zeros(max_length, dtype=np.float32)
    for track in mono_tracks:
        mix[: track.shape[0]] += track

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 0.99:
        mix /= peak

    output_path = project_path / "analysis" / "harmony-mix.wav"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output_path, mix, target_sample_rate, subtype="FLOAT")
    return output_path


def estimate_beat_grid(
    input_path: Path,
    drum_path: Path | None,
    output_path: Path,
    meter_override: str | None,
) -> dict:
    import librosa

    source_path = drum_path if drum_path and drum_path.exists() else input_path
    audio, sample_rate = librosa.load(str(source_path), sr=None, mono=True)
    if audio.size == 0:
        raise RuntimeError(f"cannot estimate beat grid from empty audio: {source_path}")

    onset_envelope = librosa.onset.onset_strength(y=audio, sr=sample_rate)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_envelope, sr=sample_rate)
    beat_times = librosa.frames_to_time(np.asarray(beat_frames), sr=sample_rate).tolist()

    if not beat_times:
        beat_times = [0.0]
    if beat_times[0] > 0.15:
        beat_times.insert(0, 0.0)

    smoothed_beats = smooth_beat_grid(beat_times)
    median_interval = _median_positive_interval(smoothed_beats)
    tempo_value = float(np.asarray(tempo).reshape(-1)[0])
    if median_interval <= 0:
        median_interval = 60.0 / max(tempo_value, 120.0)

    duration = float(audio.shape[0] / sample_rate)
    closing_boundary = (
        duration
        if duration > smoothed_beats[-1] + median_interval * 0.25
        else smoothed_beats[-1] + median_interval
    )
    beat_boundaries = [*smoothed_beats, closing_boundary]

    boundary_frames = librosa.time_to_frames(np.asarray(smoothed_beats), sr=sample_rate)
    boundary_frames = np.clip(boundary_frames, 0, max(len(onset_envelope) - 1, 0))
    accent_strengths = onset_envelope[boundary_frames] if onset_envelope.size else np.zeros(len(smoothed_beats))
    accent_threshold = float(np.median(accent_strengths) + np.std(accent_strengths) * 0.5)
    downbeat_candidate_indices = [
        index
        for index, strength in enumerate(accent_strengths)
        if float(strength) >= accent_threshold
    ]
    downbeat_candidates = [smoothed_beats[index] for index in downbeat_candidate_indices]

    meter = meter_override or infer_meter_from_grouping(smoothed_beats, downbeat_candidates)
    beats_per_bar = _meter_numerator(meter)
    downbeat_phase, downbeat_confidence = _downbeat_phase_and_confidence(
        downbeat_candidate_indices,
        accent_strengths,
        beats_per_bar,
    )
    downbeats = [smoothed_beats[index] for index in range(downbeat_phase, len(smoothed_beats), beats_per_bar)]
    if not downbeats:
        fallback_index = downbeat_candidate_indices[0] if downbeat_candidate_indices else 0
        downbeats = [smoothed_beats[min(fallback_index, len(smoothed_beats) - 1)]]

    grid = build_beat_grid_payload(
        source_path,
        tempo_value,
        meter,
        beat_boundaries,
        downbeats,
        {
            "tempo": _tempo_confidence(smoothed_beats),
            "meter": _meter_confidence(downbeat_candidate_indices, beats_per_bar, meter_override),
            "downbeats": downbeat_confidence,
        },
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(grid, indent=2), encoding="utf-8")
    return grid


def estimate_chords(
    harmony_mix_path: Path,
    bass_path: Path | None,
    beat_grid: dict,
    output_path: Path,
) -> dict:
    import librosa

    beat_boundaries = [float(value) for value in beat_grid.get("beats", [])]
    if len(beat_boundaries) < 2:
        payload = build_chord_payload(harmony_mix_path, beat_grid.get("meter", "4/4"), [])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    harmony_audio, sample_rate = librosa.load(str(harmony_mix_path), sr=None, mono=True)
    if harmony_audio.size == 0:
        raise RuntimeError(f"cannot estimate chords from empty audio: {harmony_mix_path}")
    harmony_chroma = librosa.feature.chroma_stft(y=harmony_audio, sr=sample_rate)
    harmony_times = librosa.frames_to_time(np.arange(harmony_chroma.shape[1]), sr=sample_rate)

    bass_chroma = None
    bass_times = None
    if bass_path and bass_path.exists():
        bass_audio, bass_sample_rate = librosa.load(str(bass_path), sr=None, mono=True)
        if bass_audio.size:
            bass_chroma = librosa.feature.chroma_stft(y=bass_audio, sr=bass_sample_rate)
            bass_times = librosa.frames_to_time(np.arange(bass_chroma.shape[1]), sr=bass_sample_rate)

    raw_changes: list[dict] = []
    for start, end in zip(beat_boundaries[:-1], beat_boundaries[1:]):
        chroma_slice = _average_chroma_between(harmony_chroma, harmony_times, start, end)
        label, root_pitch_class, chord_tones, confidence = _detect_chord_label(chroma_slice)

        bass_pitch_class = None
        if bass_chroma is not None and bass_times is not None:
            bass_slice = _average_chroma_between(bass_chroma, bass_times, start, end)
            if bass_slice.sum() > 0:
                bass_pitch_class = int(np.argmax(bass_slice))
        label = refine_slash_chord(label, root_pitch_class, chord_tones, bass_pitch_class)
        raw_changes.append(
            {
                "start": start,
                "end": end,
                "label": label,
                "confidence": round(confidence, 4),
            }
        )

    segments = align_chord_changes_to_grid(raw_changes, beat_grid)
    for segment in segments:
        matching_confidences = [
            change["confidence"]
            for change in raw_changes
            if change["start"] >= segment["start"] and change["end"] <= segment["end"]
        ]
        if matching_confidences:
            segment["confidence"] = round(float(np.mean(matching_confidences)), 4)

    payload = build_chord_payload(harmony_mix_path, beat_grid.get("meter", "4/4"), segments)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _average_chroma_between(
    chroma: np.ndarray,
    frame_times: np.ndarray,
    start_time: float,
    end_time: float,
) -> np.ndarray:
    mask = (frame_times >= start_time) & (frame_times < end_time)
    if not np.any(mask):
        nearest = int(np.argmin(np.abs(frame_times - start_time)))
        return chroma[:, nearest].astype(np.float64, copy=False)
    return np.mean(chroma[:, mask], axis=1)


def _detect_chord_label(chroma_vector: np.ndarray) -> tuple[str, int | None, list[int], float]:
    energy = float(np.sum(chroma_vector))
    if energy <= 1e-6:
        return "N", None, [], 0.0

    normalized = chroma_vector.astype(np.float64, copy=False)
    normalized /= max(float(np.linalg.norm(normalized)), 1e-6)

    best_label = "N"
    best_root = None
    best_tones: list[int] = []
    best_score = -1.0

    for root in range(12):
        for quality, template in CHORD_TEMPLATES.items():
            rolled_template = np.roll(template, root)
            score = float(np.dot(normalized, rolled_template))
            if score > best_score:
                best_score = score
                best_label = f"{NOTE_NAMES[root]}{quality}"
                best_root = root
                best_tones = [root, (root + (4 if quality == "" else 3)) % 12, (root + 7) % 12]

    if best_score < 0.52:
        return "N", None, [], best_score
    return best_label, best_root, best_tones, best_score


def _median_positive_interval(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    diffs = np.diff(np.asarray(values, dtype=np.float64))
    diffs = diffs[diffs > 0]
    if diffs.size == 0:
        return 0.0
    return float(np.median(diffs))


def _meter_numerator(meter: str) -> int:
    try:
        return max(int(str(meter).split("/", maxsplit=1)[0]), 1)
    except (ValueError, TypeError):
        return 4


def _nearest_boundary_index(value: float, boundaries: Sequence[float]) -> int:
    distances = [abs(float(boundary) - value) for boundary in boundaries]
    return int(min(range(len(boundaries)), key=lambda index: distances[index]))


def _tempo_confidence(beats: Sequence[float]) -> float:
    if len(beats) < 3:
        return 0.0
    intervals = np.diff(np.asarray(beats, dtype=np.float64))
    intervals = intervals[intervals > 0]
    if intervals.size < 2:
        return 0.0
    median_interval = float(np.median(intervals))
    if median_interval <= 0:
        return 0.0
    deviation = float(np.mean(np.abs(intervals - median_interval))) / median_interval
    return min(max(1.0 - deviation, 0.0), 1.0)


def _meter_confidence(
    downbeat_candidate_indices: Sequence[int],
    beats_per_bar: int,
    meter_override: str | None,
) -> float:
    if meter_override:
        return 1.0
    if len(downbeat_candidate_indices) < 2 or beats_per_bar <= 0:
        return 0.0
    gaps = np.diff(np.asarray(downbeat_candidate_indices, dtype=np.int64))
    if gaps.size == 0:
        return 0.0
    matching_gaps = np.count_nonzero(np.abs(gaps - beats_per_bar) <= 1)
    return float(matching_gaps / gaps.size)


def _downbeat_phase_and_confidence(
    downbeat_candidate_indices: Sequence[int],
    accent_strengths: np.ndarray,
    beats_per_bar: int,
) -> tuple[int, float]:
    if beats_per_bar <= 0 or not downbeat_candidate_indices:
        return 0, 0.0

    phase_scores = np.zeros(beats_per_bar, dtype=np.float64)
    total_weight = 0.0
    for index in downbeat_candidate_indices:
        weight = max(float(accent_strengths[index]), 0.0)
        phase_scores[index % beats_per_bar] += weight
        total_weight += weight

    if total_weight <= 1e-9:
        return downbeat_candidate_indices[0] % beats_per_bar, 0.0

    best_phase = int(np.argmax(phase_scores))
    return best_phase, float(phase_scores[best_phase] / total_weight)


def _to_mono(audio: np.ndarray) -> np.ndarray:
    array = np.asarray(audio, dtype=np.float32)
    if array.ndim == 1:
        return array
    return np.mean(array, axis=1)
