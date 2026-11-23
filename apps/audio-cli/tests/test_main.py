import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pretty_midi

from superscore_audio_cli import main
from superscore_audio_cli.main import _run_command


class RunCommandTests(unittest.TestCase):
    def test_run_command_forces_utf8_for_child_python_processes(self):
        result = _run_command(
            [sys.executable, "-c", "print(chr(0x2728) * 3)"]
        )

        self.assertEqual(
            result.stdout.strip().encode("unicode_escape"),
            b"\\u2728\\u2728\\u2728",
        )

    def test_run_omnizart_drum_prefers_wrapper_via_companion_python(self):
        stem_path = Path("C:/temp/drums.wav")
        output_dir = Path("C:/temp/out")

        with tempfile.TemporaryDirectory() as temp_dir:
            scripts_dir = Path(temp_dir)
            omnizart_exec = scripts_dir / "omnizart.exe"
            companion_python = scripts_dir / "python.exe"
            omnizart_exec.write_text("", encoding="utf-8")
            companion_python.write_text("", encoding="utf-8")

            commands: list[tuple[list[str], Path | None]] = []

            def fake_run_command(args: list[str], cwd: Path | None = None):
                commands.append((args, cwd))
                return object()

            expected_midi = output_dir / "drums.mid"
            with patch.object(main, "_run_command", side_effect=fake_run_command):
                with patch.object(main, "_find_newest_midi", return_value=expected_midi):
                    midi_path = main._run_omnizart_drum(str(omnizart_exec), stem_path, output_dir)

        self.assertEqual(midi_path, expected_midi)
        self.assertEqual(len(commands), 1)
        args, cwd = commands[0]
        self.assertEqual(
            args,
            [
                str(companion_python),
                str(Path(main.__file__).with_name("omnizart_drum_wrapper.py")),
                str(stem_path),
                str(output_dir),
            ],
        )
        self.assertEqual(cwd, output_dir)

    def test_transcribe_real_conditions_basic_pitch_stems_but_not_drums(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "midi" / "clean"
            request = {
                "outputPath": str(output_dir),
                "stemPaths": [str(temp_root / "bass.wav"), str(temp_root / "drums.wav")],
                "options": {
                    "realExecution": True,
                    "allowPartialSuccess": False,
                },
            }

            conditioned_calls: list[tuple[str, Path, Path]] = []
            basic_pitch_calls: list[tuple[str, Path, Path]] = []
            omnizart_calls: list[tuple[str, Path, Path]] = []

            def fake_condition_file(stem: str, src: Path, dst: Path) -> Path:
                conditioned_calls.append((stem, src, dst))
                return dst

            def fake_run_basic_pitch(executable: str, stem_path: Path, temp_dir: Path) -> Path:
                basic_pitch_calls.append((executable, stem_path, temp_dir))
                return temp_root / "bass.mid"

            def fake_run_omnizart_drum(executable: str, stem_path: Path, temp_dir: Path) -> Path:
                omnizart_calls.append((executable, stem_path, temp_dir))
                return temp_root / "drums.mid"

            with patch.object(main, "_resolve_executable", side_effect=["omnizart.exe", "basic-pitch.exe"]):
                with patch.object(main, "condition_file", side_effect=fake_condition_file):
                    with patch.object(main, "_run_basic_pitch", side_effect=fake_run_basic_pitch):
                        with patch.object(main, "_run_omnizart_drum", side_effect=fake_run_omnizart_drum):
                            with patch.object(main, "_copy_artifact"):
                                with patch.object(
                                    main,
                                    "_cleanup_midi_target",
                                    side_effect=lambda raw, clean, beat_grid, chord_map, options: clean,
                                ):
                                    with patch.object(main, "_emit_ok", return_value=0):
                                        result = main._transcribe_real(request)

        self.assertEqual(result, 0)
        self.assertEqual(len(conditioned_calls), 1)
        conditioned_stem, conditioned_src, conditioned_dst = conditioned_calls[0]
        self.assertEqual(conditioned_stem, "bass")
        self.assertEqual(conditioned_src, temp_root / "bass.wav")
        self.assertEqual(conditioned_dst.name, "bass-conditioned.wav")
        self.assertEqual(len(basic_pitch_calls), 1)
        self.assertEqual(basic_pitch_calls[0][1], conditioned_dst)
        self.assertEqual(len(omnizart_calls), 1)
        self.assertEqual(omnizart_calls[0][1], temp_root / "drums.wav")

    def test_transcribe_placeholder_returns_only_cleaned_midi_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            request = {
                "outputPath": str(temp_root / "midi"),
                "stemPaths": [str(temp_root / "bass.wav")],
            }

            with patch.object(
                main,
                "_build_analysis_artifacts",
                return_value=[
                    {"kind": "analysis", "path": str(temp_root / "analysis" / "beat-grid.json")},
                    {"kind": "analysis", "path": str(temp_root / "analysis" / "chords.json")},
                ],
            ):
                with patch.object(main, "_emit_ok", return_value=0) as emit_ok:
                    result = main._transcribe_placeholder(request)

        self.assertEqual(result, 0)
        emit_ok.assert_called_once()
        artifacts = emit_ok.call_args.args[0]
        self.assertEqual(
            artifacts,
            [{"kind": "midi", "path": str(temp_root / "midi" / "clean" / "bass.mid")}],
        )

    def test_transcribe_real_omits_analysis_artifacts_and_reports_cleanup_failures(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "midi"
            bass_midi = temp_root / "bass-source.mid"
            vocals_midi = temp_root / "vocals-source.mid"
            pretty_midi.PrettyMIDI().write(str(bass_midi))
            pretty_midi.PrettyMIDI().write(str(vocals_midi))
            request = {
                "outputPath": str(output_dir),
                "stemPaths": [str(temp_root / "bass.wav"), str(temp_root / "vocals.wav")],
                "options": {
                    "realExecution": True,
                    "allowPartialSuccess": True,
                },
            }

            def fake_run_basic_pitch(executable: str, stem_path: Path, temp_dir: Path) -> Path:
                if stem_path.name.startswith("bass-"):
                    return bass_midi
                return vocals_midi

            def fake_cleanup_midi_file(
                src: Path,
                dst: Path,
                beat_grid: dict,
                quantization_resolution: str,
                allow_tuplets: bool,
                chord_map: dict | None = None,
            ) -> Path:
                if src.name == "bass.mid":
                    raise RuntimeError("cleanup failed")
                pretty_midi.PrettyMIDI(str(src)).write(str(dst))
                return dst

            with patch.object(main, "_resolve_executable", side_effect=["omnizart.exe", "basic-pitch.exe"]):
                with patch.object(main, "condition_file", side_effect=lambda stem, src, dst: dst):
                    with patch.object(main, "_run_basic_pitch", side_effect=fake_run_basic_pitch):
                        with patch.object(
                            main,
                            "_build_analysis_artifacts",
                            return_value=[
                                {"kind": "analysis", "path": str(temp_root / "analysis" / "beat-grid.json")},
                                {"kind": "analysis", "path": str(temp_root / "analysis" / "chords.json")},
                            ],
                        ):
                            with patch.object(main, "cleanup_midi_file", side_effect=fake_cleanup_midi_file):
                                with patch.object(main, "_emit_ok", return_value=0) as emit_ok:
                                    result = main._transcribe_real(request)

        self.assertEqual(result, 0)
        emit_ok.assert_called_once()
        artifacts = emit_ok.call_args.args[0]
        warnings = emit_ok.call_args.kwargs["warnings"]
        failed_artifacts = emit_ok.call_args.kwargs["failed_artifacts"]
        self.assertEqual(
            artifacts,
            [{"kind": "midi", "path": str(temp_root / "midi" / "clean" / "vocals.mid")}],
        )
        self.assertEqual(
            failed_artifacts,
            [{"kind": "midi", "path": str(temp_root / "midi" / "clean" / "bass.mid")}],
        )
        self.assertIn("failed to transcribe `bass`: cleanup failed", warnings)

    def test_transcribe_real_writes_analysis_raw_and_clean_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            input_path = temp_root / "input" / "song.wav"
            input_path.parent.mkdir(parents=True, exist_ok=True)
            input_path.write_bytes(b"audio")

            bass_stem = temp_root / "stems" / "bass.wav"
            bass_stem.parent.mkdir(parents=True, exist_ok=True)
            bass_stem.write_bytes(b"bass")

            output_dir = temp_root / "midi"
            bass_midi = temp_root / "bass-source.mid"
            pretty_midi.PrettyMIDI().write(str(bass_midi))
            harmony_mix = temp_root / "analysis" / "harmony.wav"

            request = {
                "projectPath": str(temp_root),
                "inputPath": str(input_path),
                "outputPath": str(output_dir),
                "stemPaths": [str(bass_stem)],
                "options": {
                    "realExecution": True,
                    "allowPartialSuccess": False,
                },
            }

            def fake_estimate_beat_grid(
                source_path: Path,
                drum_path: Path | None,
                output_path: Path,
                meter_override: str | None,
            ) -> dict:
                payload = {
                    "sourcePath": str(source_path),
                    "tempo": 120.0,
                    "meter": "4/4",
                    "subdivision": 2,
                    "allowedSubdivisions": [1, 2, 4],
                    "confidence": {"tempo": 0.8, "meter": 0.7, "downbeats": 0.6},
                    "beats": [0.0, 0.5, 1.0],
                    "downbeats": [0.0],
                    "sections": [],
                }
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(payload), encoding="utf-8")
                return payload

            def fake_build_harmony_mix(project_path: Path, stem_paths: list[Path]) -> Path:
                self.assertEqual(project_path, temp_root)
                self.assertEqual(stem_paths, [bass_stem])
                harmony_mix.parent.mkdir(parents=True, exist_ok=True)
                harmony_mix.write_bytes(b"harmony")
                return harmony_mix

            def fake_estimate_chords(
                harmony_mix_path: Path,
                bass_path: Path | None,
                beat_grid: dict,
                output_path: Path,
            ) -> dict:
                self.assertEqual(harmony_mix_path, harmony_mix)
                self.assertEqual(bass_path, bass_stem)
                self.assertEqual(beat_grid["meter"], "4/4")
                payload = {
                    "sourcePath": str(harmony_mix_path),
                    "meter": "4/4",
                    "confidence": 0.75,
                    "segments": [{"start": 0.0, "end": 1.0, "label": "C"}],
                }
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(payload), encoding="utf-8")
                return payload

            def fake_cleanup_midi_file(
                src: Path,
                dst: Path,
                beat_grid: dict,
                quantization_resolution: str,
                allow_tuplets: bool,
                chord_map: dict | None = None,
            ) -> Path:
                self.assertEqual(src, temp_root / "midi" / "raw" / "bass.mid")
                self.assertEqual(dst, temp_root / "midi" / "clean" / "bass.mid")
                self.assertEqual(beat_grid["meter"], "4/4")
                self.assertEqual(chord_map["segments"][0]["label"], "C")
                pretty_midi.PrettyMIDI(str(src)).write(str(dst))
                return dst

            with patch.object(main, "_resolve_executable", side_effect=["omnizart.exe", "basic-pitch.exe"]):
                with patch.object(main, "estimate_beat_grid", side_effect=fake_estimate_beat_grid) as estimate_beat_grid:
                    with patch.object(main, "build_harmony_mix", side_effect=fake_build_harmony_mix) as build_harmony_mix:
                        with patch.object(main, "estimate_chords", side_effect=fake_estimate_chords) as estimate_chords:
                            with patch.object(main, "condition_file", side_effect=lambda stem, src, dst: dst):
                                with patch.object(main, "_run_basic_pitch", return_value=bass_midi):
                                    with patch.object(main, "cleanup_midi_file", side_effect=fake_cleanup_midi_file):
                                        with patch.object(main, "_emit_ok", return_value=0) as emit_ok:
                                            result = main._transcribe_real(request)

            self.assertEqual(result, 0)
            estimate_beat_grid.assert_called_once()
            build_harmony_mix.assert_called_once()
            estimate_chords.assert_called_once()
            emit_ok.assert_called_once()
            artifacts = emit_ok.call_args.args[0]
            self.assertEqual(
                artifacts,
                [{"kind": "midi", "path": str(temp_root / "midi" / "clean" / "bass.mid")}],
            )
            self.assertEqual(emit_ok.call_args.kwargs["warnings"], [])
            self.assertTrue((temp_root / "analysis" / "beat-grid.json").exists())
            self.assertTrue((temp_root / "analysis" / "chords.json").exists())
            self.assertTrue((temp_root / "midi" / "raw" / "bass.mid").exists())
            self.assertTrue((temp_root / "midi" / "clean" / "bass.mid").exists())

    def test_build_analysis_artifacts_writes_fallback_payloads_with_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            input_path = temp_root / "input" / "song.wav"
            request = {
                "inputPath": str(input_path),
                "outputPath": str(temp_root / "midi"),
                "stemPaths": [],
            }
            warnings: list[str] = []

            artifacts = main._build_analysis_artifacts(
                request,
                {"meterOverride": "3/4"},
                real_execution=False,
                warnings=warnings,
            )
            beat_grid = json.loads((temp_root / "analysis" / "beat-grid.json").read_text(encoding="utf-8"))
            chords = json.loads((temp_root / "analysis" / "chords.json").read_text(encoding="utf-8"))

        self.assertEqual(
            artifacts,
            [
                {"kind": "analysis", "path": str(temp_root / "analysis" / "beat-grid.json")},
                {"kind": "analysis", "path": str(temp_root / "analysis" / "chords.json")},
            ],
        )
        self.assertEqual(warnings, [])
        self.assertEqual(
            beat_grid,
            {
                "sourcePath": str(input_path),
                "tempo": 120.0,
                "meter": "3/4",
                "subdivision": 2,
                "allowedSubdivisions": [1, 2, 4],
                "confidence": {"tempo": 0.0, "meter": 1.0, "downbeats": 0.0},
                "beats": [0.0, 0.5, 1.0],
                "downbeats": [0.0],
                "sections": [
                    {
                        "start": 0.0,
                        "end": 1.0,
                        "tempo": 120.0,
                        "meter": "3/4",
                        "allowedSubdivisions": [1, 2, 4],
                        "confidence": {"tempo": 0.0, "meter": 1.0, "downbeats": 0.0},
                    }
                ],
            },
        )
        self.assertEqual(
            chords,
            {
                "sourcePath": "",
                "meter": "3/4",
                "confidence": 0.0,
                "segments": [],
            },
        )

    def test_build_analysis_artifacts_warns_on_low_confidence_analysis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            input_path = temp_root / "input" / "song.wav"
            input_path.parent.mkdir(parents=True, exist_ok=True)
            input_path.write_bytes(b"audio")

            bass_stem = temp_root / "stems" / "bass.wav"
            bass_stem.parent.mkdir(parents=True, exist_ok=True)
            bass_stem.write_bytes(b"bass")

            request = {
                "projectPath": str(temp_root),
                "inputPath": str(input_path),
                "outputPath": str(temp_root / "midi"),
                "stemPaths": [str(bass_stem)],
            }
            warnings: list[str] = []

            low_confidence_grid = {
                "sourcePath": str(input_path),
                "tempo": 118.0,
                "meter": "4/4",
                "subdivision": 2,
                "allowedSubdivisions": [1, 2, 4],
                "confidence": {"tempo": 0.92, "meter": 0.41, "downbeats": 0.36},
                "beats": [0.0, 0.5, 1.0],
                "downbeats": [0.0],
                "sections": [],
            }
            low_confidence_chords = {
                "sourcePath": str(temp_root / "analysis" / "harmony.wav"),
                "meter": "4/4",
                "confidence": 0.34,
                "segments": [{"start": 0.0, "end": 1.0, "label": "C"}],
            }

            with patch.object(main, "estimate_beat_grid", return_value=low_confidence_grid):
                with patch.object(main, "build_harmony_mix", return_value=temp_root / "analysis" / "harmony.wav"):
                    with patch.object(main, "estimate_chords", return_value=low_confidence_chords):
                        main._build_analysis_artifacts(
                            request,
                            {},
                            real_execution=True,
                            warnings=warnings,
                        )

        self.assertEqual(
            warnings,
            [
                "beat-grid analysis confidence is low (meter=0.41, downbeats=0.36); bar alignment may be unreliable",
                "chord analysis confidence is low (0.34); chord symbols may be unreliable",
            ],
        )

    def test_transcribe_real_emits_error_when_only_analysis_artifacts_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            request = {
                "outputPath": str(temp_root / "midi"),
                "stemPaths": [str(temp_root / "bass.wav")],
                "options": {
                    "realExecution": True,
                    "allowPartialSuccess": True,
                },
            }

            with patch.object(main, "_resolve_executable", side_effect=["omnizart.exe", None]):
                with patch.object(
                    main,
                    "_build_analysis_artifacts",
                    return_value=[{"kind": "analysis", "path": str(temp_root / "analysis" / "beat-grid.json")}],
                ):
                    with patch.object(main, "_emit_error", return_value=1) as emit_error:
                        with patch.object(main, "_emit_ok", return_value=0) as emit_ok:
                            result = main._transcribe_real(request)

        self.assertEqual(result, 1)
        emit_error.assert_called_once_with("transcription produced no midi artifacts")
        emit_ok.assert_not_called()


if __name__ == "__main__":
    unittest.main()
