# Readable Notation Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add stem conditioning, shared rhythm/chord analysis, and meter-aware MIDI cleanup so SuperScore exports readable MusicXML from cleaned symbolic data.

**Architecture:** Keep the existing Demucs, Basic Pitch, Omnizart, and MuseScore toolchain, but insert three backend layers around it: per-stem conditioning before Basic Pitch, shared beat/chord analysis stored under `analysis/`, and a notation-oriented MIDI cleanup pass that writes `midi/raw` and `midi/clean` before export. The first pass stays sequential inside the current pipeline so output quality improves without adding new desktop orchestration complexity.

**Tech Stack:** Tauri v2, Rust, Python 3.11, uv, Demucs, Basic Pitch, Omnizart, MuseScore, `numpy`, `soundfile`, `torchaudio`, `librosa`, `pretty_midi`

---

### Task 1: Extend project layout and request contracts for notation cleanup

**Files:**
- Modify: `apps/desktop/src-tauri/src/lib.rs`
- Modify: `docs/architecture.md`
- Modify: `docs/contracts/tool-contract-v1.md`
- Test: `apps/desktop/src-tauri/src/lib.rs`

**Step 1: Write the failing test**

Add a Rust unit test near the existing project-layout tests that asserts new notation folders are created and the new request fields serialize correctly.

```rust
#[test]
fn creates_analysis_and_split_midi_dirs() {
    let root = tempfile::tempdir().unwrap();
    ensure_project_structure(root.path()).unwrap();

    assert!(root.path().join("analysis").exists());
    assert!(root.path().join("midi").join("raw").exists());
    assert!(root.path().join("midi").join("clean").exists());
}
```

**Step 2: Run test to verify it fails**

Run: `cargo test creates_analysis_and_split_midi_dirs --manifest-path apps/desktop/src-tauri/Cargo.toml`
Expected: FAIL because the current project layout only creates `input`, `stems`, `midi`, and `musicxml`.

**Step 3: Write minimal implementation**

In `apps/desktop/src-tauri/src/lib.rs`:

- extend project-directory creation to include:
  - `analysis/`
  - `midi/raw/`
  - `midi/clean/`
- extend `TranscribeRequest` with `input_path`
- extend `TranscribeOptions` with notation-cleanup settings:
  - `notation_mode`
  - `quantization_resolution`
  - `allow_tuplets`
  - `chord_output`
  - `condition_stems`
  - `meter_override`
- keep `ExportMusicXmlRequest` pointed at cleaned MIDI output paths

Update `docs/architecture.md` and `docs/contracts/tool-contract-v1.md` to reflect the new artifact layout and request fields.

**Step 4: Run test to verify it passes**

Run: `cargo test creates_analysis_and_split_midi_dirs --manifest-path apps/desktop/src-tauri/Cargo.toml`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/desktop/src-tauri/src/lib.rs docs/architecture.md docs/contracts/tool-contract-v1.md
git commit -m "feat: add notation cleanup contract scaffolding"
```

### Task 2: Add deterministic stem conditioning before Basic Pitch

**Files:**
- Create: `apps/audio-cli/src/superscore_audio_cli/conditioning.py`
- Modify: `apps/audio-cli/src/superscore_audio_cli/main.py`
- Test: `apps/audio-cli/tests/test_conditioning.py`

**Step 1: Write the failing test**

Create `apps/audio-cli/tests/test_conditioning.py` with narrow synthetic-audio expectations for bass conditioning.

```python
import unittest
import numpy as np

from superscore_audio_cli.conditioning import condition_audio


class ConditioningTests(unittest.TestCase):
    def test_bass_conditioning_makes_signal_mono_and_normalized(self):
        stereo = np.stack([
            np.sin(np.linspace(0, 20, 4096)),
            0.25 * np.sin(np.linspace(0, 20, 4096)),
        ], axis=1).astype(np.float32)

        conditioned, sample_rate = condition_audio("bass", stereo, 44100)

        self.assertEqual(conditioned.ndim, 1)
        self.assertEqual(sample_rate, 44100)
        self.assertGreater(np.max(np.abs(conditioned)), 0.6)
```

**Step 2: Run test to verify it fails**

Run: `uv run --project apps/audio-cli python -m unittest apps/audio-cli/tests/test_conditioning.py -v`
Expected: FAIL because `conditioning.py` and `condition_audio` do not exist.

**Step 3: Write minimal implementation**

Create `apps/audio-cli/src/superscore_audio_cli/conditioning.py` with:

- `condition_audio(stem: str, audio: np.ndarray, sample_rate: int) -> tuple[np.ndarray, int]`
- `condition_file(stem: str, src: Path, dst: Path) -> Path`
- per-stem recipes:
  - `bass`: mono fold, loudness normalization, high-pass cleanup below rumble region, upper-harmonic emphasis
  - `vocals`: mono or mid emphasis, loudness normalization
  - `guitar`: loudness normalization, light low-end cleanup
  - `other`: light normalization only
  - `drums`: no-op

In `apps/audio-cli/src/superscore_audio_cli/main.py`, route every Basic Pitch stem through `condition_file(...)` into the per-stem temp directory before calling `_run_basic_pitch(...)`.

**Step 4: Run test to verify it passes**

Run: `uv run --project apps/audio-cli python -m unittest apps/audio-cli/tests/test_conditioning.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/audio-cli/src/superscore_audio_cli/conditioning.py apps/audio-cli/src/superscore_audio_cli/main.py apps/audio-cli/tests/test_conditioning.py
git commit -m "feat: condition stems before basic pitch"
```

### Task 3: Add shared beat-grid and chord-analysis artifacts

**Files:**
- Modify: `apps/audio-cli/pyproject.toml`
- Create: `apps/audio-cli/src/superscore_audio_cli/analysis.py`
- Modify: `apps/audio-cli/src/superscore_audio_cli/main.py`
- Test: `apps/audio-cli/tests/test_analysis.py`

**Step 1: Write the failing test**

Create `apps/audio-cli/tests/test_analysis.py` with deterministic grid and chord-shaping tests that do not require a full audio fixture.

```python
import unittest

from superscore_audio_cli.analysis import (
    infer_meter_from_grouping,
    align_chord_changes_to_grid,
)


class AnalysisTests(unittest.TestCase):
    def test_infer_meter_from_grouping_prefers_three_quarter_when_bars_repeat_every_three_beats(self):
        beats = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        downbeats = [0.0, 3.0]

        meter = infer_meter_from_grouping(beats, downbeats)

        self.assertEqual(meter, "3/4")
```

**Step 2: Run test to verify it fails**

Run: `uv run --project apps/audio-cli python -m unittest apps/audio-cli/tests/test_analysis.py -v`
Expected: FAIL because `analysis.py` and the helper functions do not exist.

**Step 3: Write minimal implementation**

In `apps/audio-cli/pyproject.toml`, add:

- `librosa>=0.10,<0.12`
- `pretty_midi>=0.2.10,<0.3`

Create `apps/audio-cli/src/superscore_audio_cli/analysis.py` with:

- `build_harmony_mix(project_path: Path, stem_paths: list[Path]) -> Path`
- `estimate_beat_grid(input_path: Path, drum_path: Path | None, output_path: Path, meter_override: str | None) -> dict`
- `estimate_chords(harmony_mix_path: Path, bass_path: Path | None, beat_grid: dict, output_path: Path) -> dict`
- pure helpers for:
  - meter inference
  - beat smoothing
  - alignment of chord changes to the shared grid
  - bass-root refinement for slash chords

In `apps/audio-cli/src/superscore_audio_cli/main.py`:

- create `analysis/beat-grid.json`
- create `analysis/chords.json`
- exclude `vocals` from the harmony mix by default
- use `bass + guitar + other` as the preferred chord-analysis source set

**Step 4: Run test to verify it passes**

Run: `uv run --project apps/audio-cli python -m unittest apps/audio-cli/tests/test_analysis.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/audio-cli/pyproject.toml apps/audio-cli/src/superscore_audio_cli/analysis.py apps/audio-cli/src/superscore_audio_cli/main.py apps/audio-cli/tests/test_analysis.py
git commit -m "feat: add beat-grid and chord analysis artifacts"
```

### Task 4: Add notation-oriented MIDI cleanup against the shared grid

**Files:**
- Create: `apps/audio-cli/src/superscore_audio_cli/midi_cleanup.py`
- Modify: `apps/audio-cli/src/superscore_audio_cli/main.py`
- Test: `apps/audio-cli/tests/test_midi_cleanup.py`

**Step 1: Write the failing test**

Create `apps/audio-cli/tests/test_midi_cleanup.py` with a simple note-snapping case.

```python
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
```

**Step 2: Run test to verify it fails**

Run: `uv run --project apps/audio-cli python -m unittest apps/audio-cli/tests/test_midi_cleanup.py -v`
Expected: FAIL because `midi_cleanup.py` does not exist.

**Step 3: Write minimal implementation**

Create `apps/audio-cli/src/superscore_audio_cli/midi_cleanup.py` with:

- `cleanup_midi_file(src: Path, dst: Path, beat_grid: dict, quantization_resolution: str, allow_tuplets: bool, chord_map: dict | None = None) -> Path`
- helpers for:
  - converting the beat grid into snap points
  - snapping note starts
  - simplifying note durations
  - clamping notes into legal bar ranges
  - applying a soft chord-aware pitch preference without deleting non-chord tones

In `apps/audio-cli/src/superscore_audio_cli/main.py`:

- write model output to `midi/raw/<stem>.mid`
- run cleanup into `midi/clean/<stem>.mid`
- return cleaned MIDI paths in the CLI success payload so export consumes the cleaned files

**Step 4: Run test to verify it passes**

Run: `uv run --project apps/audio-cli python -m unittest apps/audio-cli/tests/test_midi_cleanup.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/audio-cli/src/superscore_audio_cli/midi_cleanup.py apps/audio-cli/src/superscore_audio_cli/main.py apps/audio-cli/tests/test_midi_cleanup.py
git commit -m "feat: clean midi against shared notation grid"
```

### Task 5: Integrate the analysis and cleanup pipeline end-to-end

**Files:**
- Modify: `apps/audio-cli/src/superscore_audio_cli/main.py`
- Modify: `apps/audio-cli/tests/test_main.py`
- Modify: `apps/desktop/src-tauri/src/lib.rs`

**Step 1: Write the failing test**

Add an integration-style unit test to `apps/audio-cli/tests/test_main.py` that patches the heavy runners and asserts raw MIDI, cleaned MIDI, and analysis artifacts are written in the expected locations.

```python
@patch.object(main, "_run_basic_pitch")
@patch.object(main, "_run_omnizart_drum")
@patch.object(main, "estimate_beat_grid")
@patch.object(main, "estimate_chords")
@patch.object(main, "cleanup_midi_file")
def test_transcribe_real_writes_analysis_and_cleaned_outputs(...):
    ...
    self.assertTrue((project_root / "analysis" / "beat-grid.json").exists())
    self.assertTrue((project_root / "midi" / "raw" / "bass.mid").exists())
    self.assertTrue((project_root / "midi" / "clean" / "bass.mid").exists())
```

**Step 2: Run test to verify it fails**

Run: `uv run --project apps/audio-cli python -m unittest apps/audio-cli/tests/test_main.py -v`
Expected: FAIL because the current transcribe flow writes only one MIDI output folder and no analysis artifacts.

**Step 3: Write minimal implementation**

In `apps/audio-cli/src/superscore_audio_cli/main.py`:

- load `input_path` from the request
- build analysis artifacts once per transcription run
- run conditioning only for Basic Pitch stems
- write raw MIDI into `midi/raw`
- write cleaned MIDI into `midi/clean`
- keep warnings for low-confidence analysis or partial stem failures

In `apps/desktop/src-tauri/src/lib.rs`:

- pass `input_path` from the imported audio file into `TranscribeRequest`
- point the export step at cleaned MIDI artifacts
- preserve warnings in job logs so low-confidence analysis is visible to the user

**Step 4: Run test to verify it passes**

Run: `uv run --project apps/audio-cli python -m unittest apps/audio-cli/tests/test_main.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/audio-cli/src/superscore_audio_cli/main.py apps/audio-cli/tests/test_main.py apps/desktop/src-tauri/src/lib.rs
git commit -m "feat: wire notation cleanup through the pipeline"
```

### Task 6: Verify export behavior and document the new artifact model

**Files:**
- Modify: `README.md`
- Modify: `docs/contracts/tool-contract-v1.md`
- Modify: `docs/architecture.md`
- Verify: `apps/audio-cli/tests/test_conditioning.py`
- Verify: `apps/audio-cli/tests/test_analysis.py`
- Verify: `apps/audio-cli/tests/test_midi_cleanup.py`
- Verify: `apps/audio-cli/tests/test_main.py`
- Verify: `apps/desktop/src-tauri/src/lib.rs`

**Step 1: Run focused audio-cli tests**

Run: `uv run --project apps/audio-cli python -m unittest apps/audio-cli/tests/test_conditioning.py apps/audio-cli/tests/test_analysis.py apps/audio-cli/tests/test_midi_cleanup.py apps/audio-cli/tests/test_main.py -v`
Expected: PASS

**Step 2: Run focused desktop Rust tests**

Run: `cargo test creates_analysis_and_split_midi_dirs --manifest-path apps/desktop/src-tauri/Cargo.toml`
Expected: PASS

**Step 3: Document the new developer workflow**

Update `README.md`, `docs/contracts/tool-contract-v1.md`, and `docs/architecture.md` to explain:

- the `analysis/` artifact folder
- `midi/raw` versus `midi/clean`
- that MusicXML export now uses cleaned MIDI
- the readable-notation settings that affect cleanup

**Step 4: Re-run the documentation check**

Run: `rg -n "analysis/|midi/raw|midi/clean|readable" README.md docs/contracts/tool-contract-v1.md docs/architecture.md`
Expected: Matches the new documentation lines.

**Step 5: Commit**

```bash
git add README.md docs/contracts/tool-contract-v1.md docs/architecture.md
git commit -m "docs: describe readable notation cleanup artifacts"
```
