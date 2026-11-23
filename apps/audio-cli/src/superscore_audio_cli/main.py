from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from superscore_audio_cli.analysis import (
    build_beat_grid_payload,
    build_chord_payload,
    build_harmony_mix,
    estimate_beat_grid,
    estimate_chords,
)
from superscore_audio_cli.conditioning import condition_file
from superscore_audio_cli.midi_cleanup import cleanup_midi_file

CONTRACT_VERSION = "v1"
TOOL_VERSION = "adapter-0.2.0"
STEMS = ("drums", "bass", "guitar", "vocals", "other")
LOW_CONFIDENCE_THRESHOLD = 0.5


def _read_request(path: str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    version = payload.get("contractVersion")
    if version != CONTRACT_VERSION:
        raise ValueError(f"unsupported contractVersion `{version}`")
    return payload


def _emit_ok(
    artifacts: list[dict],
    warnings: list[str] | None = None,
    failed_artifacts: list[dict] | None = None,
) -> int:
    response = {
        "status": "ok",
        "toolVersion": TOOL_VERSION,
        "artifacts": artifacts,
        "warnings": warnings or [],
        "failedArtifacts": failed_artifacts or [],
    }
    print(json.dumps(response, indent=2))
    return 0


def _emit_error(message: str, code: str = "tool_failed") -> int:
    response = {"status": "error", "error": {"code": code, "message": message}}
    print(json.dumps(response), file=sys.stderr)
    return 1


def _options(request: dict) -> dict:
    return request.get("options") or {}


def _tool_paths(options: dict) -> dict:
    return options.get("toolPaths") or {}


def _resolve_executable(override: str | None, candidates: list[str]) -> str | None:
    if override:
        from_path = shutil.which(override)
        if from_path:
            return from_path
        override_path = Path(override)
        if override_path.exists():
            return str(override_path)
    for candidate in candidates:
        from_path = shutil.which(candidate)
        if from_path:
            return from_path
    return None


def _tool_env() -> dict[str, str]:
    env = os.environ.copy()
    # Basic Pitch prints Unicode status banners on startup, which crash on the
    # default Windows cp1252 locale unless child Python processes use UTF-8.
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


def _run_command(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_tool_env(),
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        reason = stderr if stderr else stdout
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}"
            + (f" :: {reason}" if reason else "")
        )
    return result


def _resolve_adjacent_python(executable: str) -> str | None:
    executable_path = Path(executable)
    for candidate in ("python.exe", "python", "python3"):
        resolved = executable_path.with_name(candidate)
        if resolved.exists():
            return str(resolved)
    return None


def _omnizart_drum_wrapper_script() -> Path:
    return Path(__file__).with_name("omnizart_drum_wrapper.py")


def _find_newest_midi(search_root: Path) -> Path:
    mids = sorted(
        [*search_root.rglob("*.mid"), *search_root.rglob("*.midi")],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not mids:
        raise RuntimeError(f"no midi output found in {search_root}")
    return mids[0]


def _copy_artifact(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _project_root_for_request(request: dict) -> Path:
    project_path = request.get("projectPath")
    if project_path:
        return Path(project_path)

    input_path = request.get("inputPath")
    if input_path:
        candidate = Path(input_path)
        if len(candidate.parents) >= 2:
            return candidate.parents[1]

    output_path = Path(request["outputPath"])
    if output_path.name in {"clean", "raw"} and len(output_path.parents) >= 2:
        return output_path.parents[1]
    return output_path.parent


def _analysis_paths(project_path: Path) -> tuple[Path, Path]:
    analysis_dir = project_path / "analysis"
    return analysis_dir / "beat-grid.json", analysis_dir / "chords.json"


def _midi_output_dirs(request: dict) -> tuple[Path, Path]:
    output_dir = Path(request["outputPath"])
    if output_dir.name == "raw":
        return output_dir, output_dir.parent / "clean"
    if output_dir.name == "clean":
        return output_dir.parent / "raw", output_dir
    if output_dir.name == "midi":
        return output_dir / "raw", output_dir / "clean"

    project_path = request.get("projectPath")
    if project_path:
        midi_root = Path(project_path) / "midi"
        return midi_root / "raw", midi_root / "clean"
    return output_dir / "raw", output_dir / "clean"


def _find_stem_path(stem_items: list[str], stem_name: str) -> Path | None:
    for stem_item in stem_items:
        stem_path = Path(stem_item)
        if stem_path.stem.lower() == stem_name:
            return stem_path
    return None


def _preferred_harmony_stem_paths(stem_items: list[str]) -> list[Path]:
    preferred = [
        path
        for stem_name in ("bass", "guitar", "other")
        if (path := _find_stem_path(stem_items, stem_name)) is not None
    ]
    if preferred:
        return preferred
    return [
        Path(stem_item)
        for stem_item in stem_items
        if Path(stem_item).stem.lower() not in {"drums", "vocals"}
    ]


def _write_json_artifact(path: Path, payload: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _read_json_artifact(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_placeholder_midi(path: Path) -> None:
    import pretty_midi

    path.parent.mkdir(parents=True, exist_ok=True)
    pretty_midi.PrettyMIDI().write(str(path))


def _cleanup_context(request: dict) -> tuple[dict, dict | None]:
    beat_grid_path, chords_path = _analysis_paths(_project_root_for_request(request))
    return _read_json_artifact(beat_grid_path) or {}, _read_json_artifact(chords_path)


def _cleanup_midi_target(
    raw_path: Path,
    clean_path: Path,
    beat_grid: dict,
    chord_map: dict | None,
    options: dict,
) -> Path:
    return cleanup_midi_file(
        raw_path,
        clean_path,
        beat_grid,
        quantization_resolution=str(options.get("quantizationResolution", "1/16")),
        allow_tuplets=bool(options.get("allowTuplets", False)),
        chord_map=chord_map,
    )


def _append_low_confidence_beat_grid_warning(beat_grid: dict, warnings: list[str]) -> None:
    confidence = beat_grid.get("confidence") or {}
    try:
        meter_confidence = float(confidence.get("meter", 1.0))
        downbeat_confidence = float(confidence.get("downbeats", 1.0))
    except (TypeError, ValueError):
        return

    if (
        meter_confidence < LOW_CONFIDENCE_THRESHOLD
        or downbeat_confidence < LOW_CONFIDENCE_THRESHOLD
    ):
        warnings.append(
            "beat-grid analysis confidence is low "
            f"(meter={meter_confidence:.2f}, downbeats={downbeat_confidence:.2f}); "
            "bar alignment may be unreliable"
        )


def _append_low_confidence_chord_warning(chords: dict, warnings: list[str]) -> None:
    try:
        confidence = float(chords.get("confidence", 1.0))
    except (TypeError, ValueError):
        return

    if confidence < LOW_CONFIDENCE_THRESHOLD:
        warnings.append(
            f"chord analysis confidence is low ({confidence:.2f}); "
            "chord symbols may be unreliable"
        )


def _fallback_beat_grid(input_path: Path | None, output_path: Path, meter_override: str | None) -> dict:
    meter = meter_override or "4/4"
    beat_grid = build_beat_grid_payload(
        input_path,
        120.0,
        meter,
        [0.0, 0.5, 1.0],
        [0.0],
        {
            "tempo": 0.0,
            "meter": 1.0 if meter_override else 0.0,
            "downbeats": 0.0,
        },
    )
    return _write_json_artifact(output_path, beat_grid)


def _fallback_chords(output_path: Path, beat_grid: dict, source_path: Path | None) -> dict:
    chords = build_chord_payload(source_path, beat_grid.get("meter", "4/4"), [])
    return _write_json_artifact(output_path, chords)


def _build_analysis_artifacts(
    request: dict,
    options: dict,
    real_execution: bool,
    warnings: list[str],
) -> list[dict]:
    project_path = _project_root_for_request(request)
    beat_grid_path, chords_path = _analysis_paths(project_path)
    input_path_value = request.get("inputPath")
    input_path = Path(input_path_value) if input_path_value else None
    stem_items = request.get("stemPaths") or []
    meter_override = options.get("meterOverride")

    beat_grid = _fallback_beat_grid(input_path, beat_grid_path, meter_override)
    if real_execution and input_path and input_path.exists():
        drum_path = _find_stem_path(stem_items, "drums")
        try:
            beat_grid = estimate_beat_grid(input_path, drum_path, beat_grid_path, meter_override)
            _append_low_confidence_beat_grid_warning(beat_grid, warnings)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"beat-grid analysis fell back to defaults: {exc}")
    else:
        if real_execution:
            warnings.append(
                "beat-grid analysis used fallback defaults because no readable input audio was provided"
            )

    harmony_stem_paths = _preferred_harmony_stem_paths(stem_items)
    bass_path = _find_stem_path(stem_items, "bass")
    if real_execution and harmony_stem_paths:
        try:
            harmony_mix_path = build_harmony_mix(project_path, harmony_stem_paths)
            chords = estimate_chords(harmony_mix_path, bass_path, beat_grid, chords_path)
            _append_low_confidence_chord_warning(chords, warnings)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"chord analysis fell back to an empty grid-aligned result: {exc}")
            _fallback_chords(chords_path, beat_grid, None)
    else:
        if real_execution and not harmony_stem_paths:
            warnings.append("chord analysis skipped because no harmony stems were available")
        _fallback_chords(chords_path, beat_grid, None)

    return [
        {"kind": "analysis", "path": str(beat_grid_path)},
        {"kind": "analysis", "path": str(chords_path)},
    ]


def _separate_placeholder(request: dict) -> int:
    output_dir = Path(request["outputPath"])
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for stem in STEMS:
        target = output_dir / f"{stem}.wav"
        target.write_text(f"placeholder wav for {stem}\n", encoding="utf-8")
        artifacts.append({"kind": "stem", "path": str(target)})
    return _emit_ok(artifacts)


def _transcribe_placeholder(request: dict) -> int:
    raw_dir, clean_dir = _midi_output_dirs(request)
    raw_dir.mkdir(parents=True, exist_ok=True)
    clean_dir.mkdir(parents=True, exist_ok=True)
    options = _options(request)
    allow_partial_success = bool(options.get("allowPartialSuccess", True))
    warnings: list[str] = []
    _build_analysis_artifacts(request, options, real_execution=False, warnings=warnings)
    artifacts: list[dict] = []
    failed_artifacts: list[dict] = []
    beat_grid, chord_map = _cleanup_context(request)
    for stem_path in request["stemPaths"]:
        stem_name = Path(stem_path).stem
        raw_path = raw_dir / f"{stem_name}.mid"
        clean_path = clean_dir / f"{stem_name}.mid"
        try:
            _write_placeholder_midi(raw_path)
            _cleanup_midi_target(raw_path, clean_path, beat_grid, chord_map, options)
            artifacts.append({"kind": "midi", "path": str(clean_path)})
        except Exception as exc:  # noqa: BLE001
            failed_artifacts.append({"kind": "midi", "path": str(clean_path)})
            if allow_partial_success:
                warnings.append(f"failed to transcribe `{stem_name}`: {exc}")
                continue
            raise
    if not artifacts:
        return _emit_error("transcription produced no midi artifacts")
    return _emit_ok(artifacts, warnings=warnings, failed_artifacts=failed_artifacts)


def _export_musicxml_placeholder(request: dict) -> int:
    output_dir = Path(request["outputPath"])
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for midi_path in request["midiPaths"]:
        stem_name = Path(midi_path).stem
        target = output_dir / f"{stem_name}.musicxml"
        target.write_text(f"placeholder musicxml for {stem_name}\n", encoding="utf-8")
        artifacts.append({"kind": "musicxml", "path": str(target)})
    return _emit_ok(artifacts)


def _separate_real(request: dict) -> int:
    input_path = Path(request["inputPath"])
    output_dir = Path(request["outputPath"])
    output_dir.mkdir(parents=True, exist_ok=True)
    if not input_path.exists():
        raise RuntimeError(f"input file not found: {input_path}")

    options = _options(request)
    tool_paths = _tool_paths(options)
    model = options.get("model", "htdemucs")
    demucs_exec = _resolve_executable(tool_paths.get("demucs"), ["demucs"])
    if not demucs_exec:
        raise RuntimeError("demucs executable not found (set options.toolPaths.demucs or PATH)")

    with tempfile.TemporaryDirectory(prefix="superscore-demucs-") as temp_dir:
        temp_root = Path(temp_dir)
        _run_command(
            [demucs_exec, "-n", model, "-o", str(temp_root), str(input_path)],
            cwd=temp_root,
        )
        artifacts = []
        for stem in STEMS:
            matches = sorted(temp_root.rglob(f"{stem}.wav"))
            if not matches:
                raise RuntimeError(f"demucs output missing stem `{stem}`")
            target = output_dir / f"{stem}.wav"
            _copy_artifact(matches[0], target)
            artifacts.append({"kind": "stem", "path": str(target)})
    return _emit_ok(artifacts)


def _resolve_transcription_strategy(stem: str, options: dict) -> str:
    transcribe_guitar = bool(options.get("transcribeGuitar", True))
    transcribe_other = bool(options.get("transcribeOther", False))
    if stem == "drums":
        return "omnizart"
    if stem in ("vocals", "bass"):
        return "basic-pitch"
    if stem == "guitar":
        return "basic-pitch" if transcribe_guitar else "skip"
    if stem == "other":
        return "basic-pitch" if transcribe_other else "skip"
    return "skip"


def _run_omnizart_drum(omnizart_exec: str, stem_path: Path, temp_dir: Path) -> Path:
    wrapper_python = _resolve_adjacent_python(omnizart_exec)
    wrapper_script = _omnizart_drum_wrapper_script()
    if wrapper_python and wrapper_script.exists():
        _run_command(
            [wrapper_python, str(wrapper_script), str(stem_path), str(temp_dir)],
            cwd=temp_dir,
        )
        return _find_newest_midi(temp_dir)

    command_variants = [
        [omnizart_exec, "drum", "transcribe", str(stem_path), "-o", str(temp_dir)],
        [omnizart_exec, "drum", "transcribe", str(stem_path)],
    ]
    last_error: Exception | None = None
    for args in command_variants:
        try:
            _run_command(args, cwd=temp_dir)
            return _find_newest_midi(temp_dir)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"omnizart drum transcription failed: {last_error}")


def _run_basic_pitch(basic_pitch_exec: str, stem_path: Path, temp_dir: Path) -> Path:
    _run_command([basic_pitch_exec, str(temp_dir), str(stem_path)], cwd=temp_dir)
    return _find_newest_midi(temp_dir)


def _transcribe_real(request: dict) -> int:
    raw_dir, clean_dir = _midi_output_dirs(request)
    raw_dir.mkdir(parents=True, exist_ok=True)
    clean_dir.mkdir(parents=True, exist_ok=True)
    options = _options(request)
    tool_paths = _tool_paths(options)
    allow_partial_success = bool(options.get("allowPartialSuccess", True))

    omnizart_exec = _resolve_executable(
        tool_paths.get("omnizart"), ["omnizart", "omnizart.exe"]
    )
    basic_pitch_exec = _resolve_executable(
        tool_paths.get("basicPitch"),
        ["basic-pitch", "basic_pitch", "basic-pitch.exe"],
    )

    warnings: list[str] = []
    _build_analysis_artifacts(
        request,
        options,
        real_execution=True,
        warnings=warnings,
    )
    artifacts: list[dict] = []
    beat_grid, chord_map = _cleanup_context(request)
    failed_artifacts: list[dict] = []
    for stem_item in request["stemPaths"]:
        stem_path = Path(stem_item)
        stem = stem_path.stem.lower()
        strategy = _resolve_transcription_strategy(stem, options)
        if strategy == "skip":
            warnings.append(f"skipping transcription for stem `{stem}` by policy")
            continue

        try:
            with tempfile.TemporaryDirectory(prefix=f"superscore-transcribe-{stem}-") as temp_dir:
                temp_root = Path(temp_dir)
                if strategy == "omnizart":
                    if not omnizart_exec:
                        raise RuntimeError("omnizart executable not found")
                    midi_src = _run_omnizart_drum(omnizart_exec, stem_path, temp_root)
                else:
                    if not basic_pitch_exec:
                        raise RuntimeError("basic-pitch executable not found")
                    conditioned_stem_path = temp_root / f"{stem}-conditioned.wav"
                    condition_file(stem, stem_path, conditioned_stem_path)
                    midi_src = _run_basic_pitch(basic_pitch_exec, conditioned_stem_path, temp_root)

                raw_path = raw_dir / f"{stem}.mid"
                clean_path = clean_dir / f"{stem}.mid"
                _copy_artifact(midi_src, raw_path)
                _cleanup_midi_target(
                    raw_path,
                    clean_path,
                    beat_grid,
                    chord_map,
                    options,
                )
                artifacts.append({"kind": "midi", "path": str(clean_path)})
        except Exception as exc:  # noqa: BLE001
            failed_artifacts.append({"kind": "midi", "path": str(clean_dir / f"{stem}.mid")})
            if allow_partial_success:
                warnings.append(f"failed to transcribe `{stem}`: {exc}")
                continue
            raise

    if not any(artifact.get("kind") == "midi" for artifact in artifacts):
        return _emit_error("transcription produced no midi artifacts")
    return _emit_ok(artifacts, warnings=warnings, failed_artifacts=failed_artifacts)


def _export_musicxml_real(request: dict) -> int:
    output_dir = Path(request["outputPath"])
    output_dir.mkdir(parents=True, exist_ok=True)
    options = _options(request)
    tool_paths = _tool_paths(options)
    allow_partial_success = bool(options.get("allowPartialSuccess", True))
    musescore_exec = _resolve_executable(
        tool_paths.get("musescore"),
        ["musescore", "musescore4", "MuseScore4", "mscore"],
    )
    if not musescore_exec:
        return _emit_error("musescore executable not found")

    artifacts: list[dict] = []
    warnings: list[str] = []
    failed_artifacts: list[dict] = []
    for midi_item in request["midiPaths"]:
        midi_path = Path(midi_item)
        stem = midi_path.stem
        target = output_dir / f"{stem}.musicxml"
        try:
            _run_command([musescore_exec, "-o", str(target), str(midi_path)])
            artifacts.append({"kind": "musicxml", "path": str(target)})
        except Exception as exc:  # noqa: BLE001
            failed_artifacts.append({"kind": "musicxml", "path": str(target)})
            if allow_partial_success:
                warnings.append(f"failed to export `{stem}` to MusicXML: {exc}")
                continue
            raise

    if not artifacts:
        return _emit_error("musicxml export produced no artifacts")
    return _emit_ok(artifacts, warnings=warnings, failed_artifacts=failed_artifacts)


def _separate(request: dict) -> int:
    options = _options(request)
    if bool(options.get("realExecution", False)):
        return _separate_real(request)
    return _separate_placeholder(request)


def _transcribe(request: dict) -> int:
    options = _options(request)
    if bool(options.get("realExecution", False)):
        return _transcribe_real(request)
    return _transcribe_placeholder(request)


def _export_musicxml(request: dict) -> int:
    options = _options(request)
    if bool(options.get("realExecution", False)):
        return _export_musicxml_real(request)
    return _export_musicxml_placeholder(request)


def main() -> int:
    parser = argparse.ArgumentParser(prog="superscore-audio-cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("separate", "transcribe", "export-musicxml"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--request-file", required=True)

    args = parser.parse_args()

    try:
        request = _read_request(args.request_file)
        if args.command == "separate":
            return _separate(request)
        if args.command == "transcribe":
            return _transcribe(request)
        if args.command == "export-musicxml":
            return _export_musicxml(request)
        return _emit_error(f"unknown command: {args.command}", code="bad_command")
    except Exception as exc:  # noqa: BLE001
        return _emit_error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
