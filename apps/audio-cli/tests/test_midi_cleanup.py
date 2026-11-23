import tempfile
import unittest
from pathlib import Path

import pretty_midi

from superscore_audio_cli.midi_cleanup import cleanup_midi_file


class MidiCleanupTests(unittest.TestCase):
    def test_cleanup_snaps_onsets_and_durations_to_grid(self):
        midi = pretty_midi.PrettyMIDI()
        instrument = pretty_midi.Instrument(program=33)
        instrument.notes.append(pretty_midi.Note(velocity=100, pitch=40, start=0.48, end=0.91))
        midi.instruments.append(instrument)

        with tempfile.TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "raw.mid"
            dst = Path(temp_dir) / "clean.mid"
            midi.write(str(src))

            grid = {"beats": [0.0, 0.5, 1.0], "subdivision": 2, "meter": "4/4"}
            cleanup_midi_file(src, dst, grid, quantization_resolution="1/8", allow_tuplets=False)

            cleaned = pretty_midi.PrettyMIDI(str(dst))
            note = cleaned.instruments[0].notes[0]
            self.assertAlmostEqual(note.start, 0.5, places=3)
            self.assertAlmostEqual(note.end, 1.0, places=3)

    def test_cleanup_clamps_note_end_to_containing_bar(self):
        midi = pretty_midi.PrettyMIDI()
        instrument = pretty_midi.Instrument(program=33)
        instrument.notes.append(pretty_midi.Note(velocity=100, pitch=40, start=1.48, end=2.52))
        midi.instruments.append(instrument)

        with tempfile.TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "raw.mid"
            dst = Path(temp_dir) / "clean.mid"
            midi.write(str(src))

            grid = {
                "beats": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5],
                "subdivision": 2,
                "meter": "4/4",
            }
            cleanup_midi_file(src, dst, grid, quantization_resolution="1/8", allow_tuplets=False)

            cleaned = pretty_midi.PrettyMIDI(str(dst))
            note = cleaned.instruments[0].notes[0]
            self.assertAlmostEqual(note.start, 1.5, places=3)
            self.assertAlmostEqual(note.end, 2.0, places=3)

    def test_cleanup_prefers_nearby_chord_tones_without_rewriting_distant_notes(self):
        midi = pretty_midi.PrettyMIDI()
        instrument = pretty_midi.Instrument(program=33)
        instrument.notes.append(pretty_midi.Note(velocity=100, pitch=61, start=0.0, end=0.5))
        instrument.notes.append(pretty_midi.Note(velocity=100, pitch=62, start=0.5, end=1.0))
        instrument.notes.append(pretty_midi.Note(velocity=100, pitch=64, start=1.0, end=1.5))
        midi.instruments.append(instrument)

        with tempfile.TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "raw.mid"
            dst = Path(temp_dir) / "clean.mid"
            midi.write(str(src))

            grid = {"beats": [0.0, 0.5, 1.0, 1.5], "subdivision": 2, "meter": "4/4"}
            chord_map = {"segments": [{"start": 0.0, "end": 1.5, "label": "C"}]}

            cleanup_midi_file(
                src,
                dst,
                grid,
                quantization_resolution="1/8",
                allow_tuplets=False,
                chord_map=chord_map,
            )

            cleaned = pretty_midi.PrettyMIDI(str(dst))
            notes = cleaned.instruments[0].notes
            self.assertEqual(notes[0].pitch, 60)
            self.assertEqual(notes[1].pitch, 62)
            self.assertEqual(notes[2].pitch, 64)

    def test_cleanup_prefers_chord_segment_based_on_note_onset_at_boundaries(self):
        midi = pretty_midi.PrettyMIDI()
        instrument = pretty_midi.Instrument(program=33)
        instrument.notes.append(pretty_midi.Note(velocity=100, pitch=61, start=1.0, end=1.4))
        midi.instruments.append(instrument)

        with tempfile.TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "raw.mid"
            dst = Path(temp_dir) / "clean.mid"
            midi.write(str(src))

            grid = {"beats": [0.0, 0.5, 1.0, 1.5], "subdivision": 2, "meter": "4/4"}
            chord_map = {
                "segments": [
                    {"start": 0.0, "end": 1.0, "label": "C"},
                    {"start": 1.0, "end": 1.5, "label": "D"},
                ]
            }

            cleanup_midi_file(
                src,
                dst,
                grid,
                quantization_resolution="1/8",
                allow_tuplets=False,
                chord_map=chord_map,
            )

            cleaned = pretty_midi.PrettyMIDI(str(dst))
            note = cleaned.instruments[0].notes[0]
            self.assertEqual(note.pitch, 62)

    def test_cleanup_skips_malformed_chord_segments_during_selection(self):
        midi = pretty_midi.PrettyMIDI()
        instrument = pretty_midi.Instrument(program=33)
        instrument.notes.append(pretty_midi.Note(velocity=100, pitch=61, start=0.0, end=0.5))
        midi.instruments.append(instrument)

        with tempfile.TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "raw.mid"
            dst = Path(temp_dir) / "clean.mid"
            midi.write(str(src))

            grid = {"beats": [0.0, 0.5, 1.0], "subdivision": 2, "meter": "4/4"}
            chord_map = {
                "segments": [
                    {"start": "bad", "end": None, "label": "N"},
                    {"start": 0.0, "end": 1.0, "label": "C"},
                ]
            }

            cleanup_midi_file(
                src,
                dst,
                grid,
                quantization_resolution="1/8",
                allow_tuplets=False,
                chord_map=chord_map,
            )

            cleaned = pretty_midi.PrettyMIDI(str(dst))
            note = cleaned.instruments[0].notes[0]
            self.assertEqual(note.pitch, 60)

    def test_cleanup_uses_last_valid_segment_for_exact_final_boundary_with_malformed_trailer(self):
        midi = pretty_midi.PrettyMIDI()
        instrument = pretty_midi.Instrument(program=33)
        instrument.notes.append(pretty_midi.Note(velocity=100, pitch=61, start=1.0, end=1.4))
        midi.instruments.append(instrument)

        with tempfile.TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "raw.mid"
            dst = Path(temp_dir) / "clean.mid"
            midi.write(str(src))

            grid = {"beats": [0.0, 0.5, 1.0, 1.5], "subdivision": 2, "meter": "4/4"}
            chord_map = {
                "segments": [
                    {"start": 0.0, "end": 1.0, "label": "C"},
                    {"start": "bad", "end": None, "label": "N"},
                ]
            }

            cleanup_midi_file(
                src,
                dst,
                grid,
                quantization_resolution="1/8",
                allow_tuplets=False,
                chord_map=chord_map,
            )

            cleaned = pretty_midi.PrettyMIDI(str(dst))
            note = cleaned.instruments[0].notes[0]
            self.assertEqual(note.pitch, 60)


if __name__ == "__main__":
    unittest.main()
