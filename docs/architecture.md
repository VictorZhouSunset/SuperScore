# SuperScore v0 Architecture

## Overview

SuperScore uses a Tauri v2 desktop shell with a Rust orchestration backend and Python CLI adapters for audio/ML work.

- Frontend: static web UI (`apps/desktop/web`)
- Backend: Tauri commands and job state machine (`apps/desktop/src-tauri/src/lib.rs`)
- Sidecar tools: Python CLI (`apps/audio-cli`)

## Data Model

Each project is stored as:

```text
data_root/<project_name>/
  input/
  stems/
  analysis/
    beat-grid.json
    chords.json
  midi/
    raw/
    clean/
  musicxml/
  meta.json
```

`meta.json` stores contract version, project metadata, and job history.

Desktop artifact listing mirrors the nested layout instead of flattening it:

- `analysis` for shared notation-analysis files
- `midi-raw` for intermediate transcription output under `midi/raw`
- `midi-clean` for cleaned/exportable MIDI under `midi/clean`

## Pipeline Stages

1. `separate`: input audio -> stem WAVs
2. `transcribe`: input audio + stem WAVs -> analysis artifacts + raw/clean MIDI
3. `export`: cleaned MIDI -> MusicXML

The default runtime profile uses placeholder generation while preserving final tool interfaces, including cleaned MIDI outputs under `midi/clean`.

During `transcribe`, the audio CLI runs three notation-oriented layers around the existing model calls:

- stem conditioning before Basic Pitch on configured melodic stems
- shared beat-grid and chord analysis written under `analysis/`
- MIDI cleanup that keeps `midi/raw` for debugging and writes exportable notation into `midi/clean`

Readable-notation behavior is controlled by the transcribe request options:

- `notationMode`
- `quantizationResolution`
- `allowTuplets`
- `chordOutput`
- `conditionStems`
- `meterOverride`

## Contracts

Tool contracts are versioned with `contractVersion = "v1"` and documented in:

- `docs/contracts/tool-contract-v1.md`

## Runtime Modes

- Placeholder mode (`usePlaceholders = true`): deterministic local artifacts for fast end-to-end validation
- CLI mode (`usePlaceholders = false`): executes external adapter binary `superscore-audio-cli` using the same contract
