import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from superscore_audio_cli.analysis import (
    align_chord_changes_to_grid,
    estimate_beat_grid,
    infer_meter_from_grouping,
    refine_slash_chord,
    smooth_beat_grid,
)
from superscore_audio_cli.main import _preferred_harmony_stem_paths


class AnalysisTests(unittest.TestCase):
    def test_infer_meter_from_grouping_prefers_three_quarter_when_bars_repeat_every_three_beats(
        self,
    ):
        beats = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        downbeats = [0.0, 3.0]

        meter = infer_meter_from_grouping(beats, downbeats)

        self.assertEqual(meter, "3/4")

    def test_infer_meter_from_grouping_defaults_to_four_four_when_votes_are_tied(self):
        beats = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        downbeats = [0.0, 3.0, 7.0]

        meter = infer_meter_from_grouping(beats, downbeats)

        self.assertEqual(meter, "4/4")

    def test_align_chord_changes_to_grid_snaps_and_merges_adjacent_regions(self):
        beat_grid = {"beats": [0.0, 1.0, 2.0, 3.0, 4.0], "meter": "4/4"}
        changes = [
            {"start": 0.12, "end": 1.42, "label": "C"},
            {"start": 1.51, "end": 2.61, "label": "C"},
            {"start": 2.64, "end": 3.92, "label": "G"},
        ]

        aligned = align_chord_changes_to_grid(changes, beat_grid)

        self.assertEqual(
            aligned,
            [
                {"start": 0.0, "end": 3.0, "label": "C", "beatStart": 0, "beatEnd": 3},
                {"start": 3.0, "end": 4.0, "label": "G", "beatStart": 3, "beatEnd": 4},
            ],
        )

    def test_smooth_beat_grid_replaces_large_outlier_with_expected_step(self):
        beats = [0.0, 1.0, 2.0, 3.72, 4.01]

        smoothed = smooth_beat_grid(beats)

        self.assertEqual(smoothed, [0.0, 1.0, 2.0, 3.0, 4.01])

    def test_refine_slash_chord_uses_bass_note_when_it_is_a_supported_chord_tone(self):
        label = refine_slash_chord("C", 0, [0, 4, 7], 4)

        self.assertEqual(label, "C/E")

    def test_refine_slash_chord_ignores_root_and_non_chord_bass_notes(self):
        self.assertEqual(refine_slash_chord("C", 0, [0, 4, 7], 0), "C")
        self.assertEqual(refine_slash_chord("C", 0, [0, 4, 7], 2), "C")

    def test_preferred_harmony_stem_paths_prioritizes_bass_guitar_and_other(self):
        stem_items = [
            "D:/tmp/vocals.wav",
            "D:/tmp/drums.wav",
            "D:/tmp/other.wav",
            "D:/tmp/bass.wav",
            "D:/tmp/guitar.wav",
        ]

        stem_paths = _preferred_harmony_stem_paths(stem_items)

        self.assertEqual(
            [path.name for path in stem_paths],
            ["bass.wav", "guitar.wav", "other.wav"],
        )

    def test_preferred_harmony_stem_paths_fallback_excludes_vocals_by_default(self):
        stem_items = [
            "D:/tmp/vocals.wav",
            "D:/tmp/drums.wav",
            "D:/tmp/keys.wav",
        ]

        stem_paths = _preferred_harmony_stem_paths(stem_items)

        self.assertEqual([path.name for path in stem_paths], ["keys.wav"])

    def test_estimate_beat_grid_serializes_pickup_downbeats_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            input_path = temp_root / "input.wav"
            output_path = temp_root / "analysis" / "beat-grid.json"
            fake_librosa = types.SimpleNamespace(
                load=lambda path, sr=None, mono=True: (np.zeros(6000, dtype=np.float32), 1000),
                onset=types.SimpleNamespace(
                    onset_strength=lambda y, sr: np.array(
                        [0.1, 0.9, 0.1, 0.1, 0.1, 0.8],
                        dtype=np.float32,
                    )
                ),
                beat=types.SimpleNamespace(
                    beat_track=lambda onset_envelope, sr: (
                        np.array([120.0], dtype=np.float32),
                        np.array([10, 20, 30, 40, 50], dtype=np.int64),
                    )
                ),
                frames_to_time=lambda frames, sr: np.asarray(frames, dtype=np.float64) / 10.0,
                time_to_frames=lambda times, sr: np.asarray(times, dtype=np.int64),
            )

            with patch.dict(sys.modules, {"librosa": fake_librosa}):
                beat_grid = estimate_beat_grid(input_path, None, output_path, None)
            serialized_payload = json.loads(output_path.read_text(encoding="utf-8"))

            expected = {
                "sourcePath": str(input_path),
                "tempo": 120.0,
                "meter": "4/4",
                "subdivision": 2,
                "allowedSubdivisions": [1, 2, 4],
                "confidence": {"tempo": 1.0, "meter": 1.0, "downbeats": 1.0},
                "beats": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
                "downbeats": [1.0, 5.0],
                "sections": [
                    {
                        "start": 0.0,
                        "end": 6.0,
                        "tempo": 120.0,
                        "meter": "4/4",
                        "allowedSubdivisions": [1, 2, 4],
                        "confidence": {"tempo": 1.0, "meter": 1.0, "downbeats": 1.0},
                    }
                ],
            }

            self.assertEqual(beat_grid, expected)
            self.assertEqual(serialized_payload, expected)


if __name__ == "__main__":
    unittest.main()
