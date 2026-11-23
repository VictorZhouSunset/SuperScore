from __future__ import annotations

from bisect import bisect_left
from pathlib import Path
from typing import Iterable

import pretty_midi

MAX_CHORD_TONE_ADJUSTMENT = 1


def cleanup_midi_file(
    src: Path,
    dst: Path,
    beat_grid: dict,
    quantization_resolution: str,
    allow_tuplets: bool,
    chord_map: dict | None = None,
) -> Path:
    midi = pretty_midi.PrettyMIDI(str(src))
    snap_points = _grid_snap_points(beat_grid, quantization_resolution, allow_tuplets)
    if len(snap_points) < 2:
        snap_points = [0.0, max(midi.get_end_time(), 0.25)]

    bar_ranges = _bar_ranges(beat_grid, snap_points)
    for instrument in midi.instruments:
        for note in instrument.notes:
            original_start = note.start
            original_end = note.end
            snapped_start = _snap_note_start(note.start, snap_points)
            snapped_end = _simplify_note_duration(note.end, snapped_start, snap_points)
            clamped_start, clamped_end = _clamp_note_to_bar_ranges(
                snapped_start,
                snapped_end,
                bar_ranges,
                snap_points,
            )
            note.start = clamped_start
            note.end = clamped_end
            note.pitch = _prefer_chord_tone_pitch(
                note.pitch,
                original_start,
                original_end,
                chord_map,
            )

    dst.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(dst))
    return dst


def _grid_snap_points(
    beat_grid: dict,
    quantization_resolution: str,
    allow_tuplets: bool,
) -> list[float]:
    beats = sorted({round(float(beat), 6) for beat in beat_grid.get("beats", [])})
    if len(beats) < 2:
        return beats

    subdivisions = {
        1,
        max(int(beat_grid.get("subdivision", 1) or 1), 1),
        _resolution_subdivision(quantization_resolution),
    }
    if allow_tuplets:
        subdivisions.add(3)

    snap_points = set(beats)
    for start, end in zip(beats, beats[1:]):
        step = end - start
        if step <= 0:
            continue
        for subdivision in sorted(subdivisions):
            for index in range(1, subdivision):
                snap_points.add(round(start + (step * index / subdivision), 6))

    return sorted(snap_points)


def _resolution_subdivision(quantization_resolution: str) -> int:
    try:
        _, denominator = quantization_resolution.split("/", maxsplit=1)
        return max(int(denominator) // 4, 1)
    except (AttributeError, TypeError, ValueError):
        return 1


def _snap_note_start(start: float, snap_points: list[float]) -> float:
    return _nearest_snap_point(start, snap_points)


def _simplify_note_duration(end: float, snapped_start: float, snap_points: list[float]) -> float:
    snapped_end = _nearest_snap_point(end, snap_points)
    if snapped_end > snapped_start:
        return snapped_end

    next_point = _next_snap_point(snapped_start, snap_points)
    if next_point is not None:
        return next_point

    minimum_step = _minimum_step(snap_points)
    return round(snapped_start + minimum_step, 6)


def _clamp_note_to_bar_ranges(
    start: float,
    end: float,
    bar_ranges: list[tuple[float, float]],
    snap_points: list[float],
) -> tuple[float, float]:
    if not bar_ranges:
        return start, max(end, start + _minimum_step(snap_points))

    bar_start, bar_end = _containing_bar_range(start, bar_ranges)
    clamped_start = min(max(start, bar_start), bar_end)
    clamped_end = min(max(end, bar_start), bar_end)
    if clamped_end > clamped_start:
        return clamped_start, clamped_end

    next_point = _next_snap_point(clamped_start, snap_points)
    if next_point is not None and next_point <= bar_end:
        return clamped_start, next_point
    return clamped_start, min(bar_end, round(clamped_start + _minimum_step(snap_points), 6))


def _bar_ranges(beat_grid: dict, snap_points: list[float]) -> list[tuple[float, float]]:
    beats = sorted({round(float(beat), 6) for beat in beat_grid.get("beats", [])})
    if len(beats) < 2:
        return [(snap_points[0], snap_points[-1])] if len(snap_points) >= 2 else []

    beats_per_bar = _beats_per_bar(beat_grid.get("meter"))
    ranges: list[tuple[float, float]] = []
    for index in range(0, len(beats) - 1, beats_per_bar):
        end_index = min(index + beats_per_bar, len(beats) - 1)
        start = beats[index]
        end = beats[end_index]
        if end > start:
            ranges.append((start, end))
    return ranges or [(beats[0], beats[-1])]


def _beats_per_bar(meter: str | None) -> int:
    try:
        numerator, _ = str(meter or "4/4").split("/", maxsplit=1)
        return max(int(numerator), 1)
    except ValueError:
        return 4


def _prefer_chord_tone_pitch(
    pitch: int,
    start: float,
    end: float,
    chord_map: dict | None,
) -> int:
    segment = _matching_chord_segment(start, end, chord_map)
    if not segment:
        return pitch

    chord_tones = _chord_tones(segment.get("label"))
    if not chord_tones or pitch % 12 in chord_tones:
        return pitch

    candidate = _nearest_chord_tone_pitch(pitch, chord_tones, MAX_CHORD_TONE_ADJUSTMENT)
    return candidate if candidate is not None else pitch


def _matching_chord_segment(start: float, end: float, chord_map: dict | None) -> dict | None:
    if not chord_map:
        return None

    valid_segments = [
        (segment, bounds)
        for segment in chord_map.get("segments", [])
        if (bounds := _segment_bounds(segment)) is not None
    ]
    ordered_segments = sorted(valid_segments, key=lambda item: _segment_sort_key(item[0]))
    for index, (segment, bounds) in enumerate(ordered_segments):
        segment_start, segment_end = bounds
        if start < segment_start:
            continue
        if start < segment_end:
            return segment
        is_last_segment = index == len(ordered_segments) - 1
        if is_last_segment and start == segment_end:
            return segment
    return None


def _chord_tones(label: str | None) -> set[int]:
    normalized = (label or "").strip()
    if not normalized or normalized == "N":
        return set()

    root_name = normalized.split("/", maxsplit=1)[0]
    if root_name.endswith("m") and len(root_name) > 1:
        quality = "m"
        root_name = root_name[:-1]
    else:
        quality = ""

    note_to_pc = {
        "C": 0,
        "B#": 0,
        "C#": 1,
        "Db": 1,
        "D": 2,
        "D#": 3,
        "Eb": 3,
        "E": 4,
        "Fb": 4,
        "E#": 5,
        "F": 5,
        "F#": 6,
        "Gb": 6,
        "G": 7,
        "G#": 8,
        "Ab": 8,
        "A": 9,
        "A#": 10,
        "Bb": 10,
        "B": 11,
        "Cb": 11,
    }
    root_pc = note_to_pc.get(root_name)
    if root_pc is None:
        return set()

    intervals = (0, 3, 7) if quality == "m" else (0, 4, 7)
    return {(root_pc + interval) % 12 for interval in intervals}


def _nearest_chord_tone_pitch(
    pitch: int,
    chord_tones: set[int],
    max_adjustment: int,
) -> int | None:
    for distance in range(1, max_adjustment + 1):
        downward = pitch - distance
        upward = pitch + distance
        if downward % 12 in chord_tones:
            return downward
        if upward % 12 in chord_tones:
            return upward
    return None


def _segment_bounds(segment: dict) -> tuple[float, float] | None:
    try:
        return float(segment.get("start", 0.0)), float(segment.get("end", 0.0))
    except (AttributeError, TypeError, ValueError):
        return None


def _segment_sort_key(segment: dict) -> tuple[int, float, float]:
    bounds = _segment_bounds(segment)
    if bounds is None:
        return (1, 0.0, 0.0)
    return (0, bounds[0], bounds[1])


def _containing_bar_range(
    start: float,
    bar_ranges: list[tuple[float, float]],
) -> tuple[float, float]:
    for index, (bar_start, bar_end) in enumerate(bar_ranges):
        is_last_bar = index == len(bar_ranges) - 1
        if bar_start <= start < bar_end:
            return bar_start, bar_end
        if is_last_bar and start == bar_end:
            return bar_start, bar_end

    if start < bar_ranges[0][0]:
        return bar_ranges[0]
    return bar_ranges[-1]


def _nearest_snap_point(value: float, snap_points: list[float]) -> float:
    if not snap_points:
        return round(float(value), 6)

    index = bisect_left(snap_points, value)
    candidates = []
    if index < len(snap_points):
        candidates.append(snap_points[index])
    if index > 0:
        candidates.append(snap_points[index - 1])
    return min(candidates, key=lambda point: (abs(point - value), point))


def _next_snap_point(value: float, snap_points: Iterable[float]) -> float | None:
    for point in snap_points:
        if point > value:
            return point
    return None


def _minimum_step(snap_points: list[float]) -> float:
    steps = [right - left for left, right in zip(snap_points, snap_points[1:]) if right - left > 0]
    return round(min(steps), 6) if steps else 0.05
