# SuperScore

A local desktop workflow for turning band recordings into separated stems, MIDI, and editable MusicXML scores.

> **Project history:** SuperScore was originally developed and version-controlled in a local Git repository, with no GitHub repository. It was first uploaded to GitHub on **November 23, 2026 (2026-11-23)**. This publication is a cleaned source snapshot; the original local development history predates the GitHub repository.
>
> **项目历史：** SuperScore 原先只在本地 Git 仓库中开发和管理，没有放到 GitHub；于 **2026 年 11 月 23 日**首次上传 GitHub。本次上传为整理后的源码快照，项目开发早于 GitHub 仓库创建时间。

## Audio pipeline

```text
Local audio / YouTube URL
  → Demucs v4 stem separation
  → Omnizart Drum (drums) / Basic Pitch (melodic stems)
  → beat- and chord-aware MIDI cleanup
  → MuseScore CLI → MusicXML
```

| Stage | Implementation |
| --- | --- |
| Separation | Demucs v4; `htdemucs_6s` with guitar transcription enabled (default), `htdemucs` otherwise |
| Drum transcription | Omnizart Drum with a Windows compatibility wrapper |
| Bass / vocals / guitar | Basic Pitch; guitar enabled by default |
| Other-stem transcription | Optional Basic Pitch path, disabled by default |
| Input conditioning | Per-stem normalization and frequency weighting using NumPy / SoundFile |
| Beat / chord analysis | librosa beat tracking, chroma features, and custom chord-template rules |
| MIDI cleanup | pretty_midi; grid quantization, bar alignment, nearby chord-tone adjustment |
| Score export | MuseScore CLI converts cleaned MIDI to MusicXML |

The app preserves raw and cleaned MIDI. Its notation workflow prioritizes readable rhythm and editable scores.

## Architecture

- **Desktop:** Tauri v2, Rust, static HTML/CSS/JavaScript frontend.
- **Orchestration:** Rust manages projects, jobs, diagnostics, and external processes.
- **Audio tools:** Python CLI exposes `separate`, `transcribe`, and `export-musicxml` through a versioned JSON contract.
- **Storage:** local project folders; model tools run on the user's machine.

```text
apps/desktop/       Desktop UI, Rust backend, desktop E2E harness
apps/audio-cli/     Python adapters, analysis, cleanup, unit tests
docs/              Installation, architecture, contracts, historical plans
scripts/           Local setup helpers
```

## Quick start (Windows)

Install Git, Node.js 22+, pnpm 10, Rust with the MSVC toolchain, Visual Studio C++ build tools / Windows SDK, and WebView2 Runtime.

```powershell
git clone https://github.com/VictorZhouSunset/SuperScore.git
cd SuperScore
pnpm install --frozen-lockfile
pnpm tauri:dev
```

Default mode uses placeholder artifacts to exercise project creation and the job UI. For audio inference, follow **[Installation and running](docs/INSTALL.md)** to install Python tools, configure executable paths, and enable **Real execution** in Settings.

Build the desktop application with `pnpm tauri:build`. The packaged desktop application uses separately installed Python tools, model weights, and MuseScore. `pnpm build` only reports the static frontend location.

## Run a song

1. Open Settings, configure the data root and tool paths, and enable **Real execution**.
2. Create and open a project.
3. Enter a local audio file path and click **Import Local**, or use **Import YouTube**.
4. Keep **Transcribe guitar** enabled for the default model route.
5. Click **Start Pipeline** and inspect status and generated artifacts.
6. Open MusicXML files in MuseScore or another notation editor.

**Allow partial success** preserves successful stems if another stem encounters an error. Review per-stem diagnostics alongside overall status.

```text
data_root/<project>/
  input/
  stems/
  analysis/          beat-grid.json, chords.json
  midi/raw/
  midi/clean/
  musicxml/
  meta.json
```

## Validation and current scope

- The original local real-mode run on **2026-03-08** completed in about **574 seconds**, producing five stem WAVs and bass/drums/guitar/vocals MIDI and MusicXML artifacts.
- Publication checks on **2026-11-23** passed: **26 Python tests**, **20 Rust tests**, Rust formatting, JavaScript syntax, and frozen-lockfile pnpm installation. Full-song inference and installer packaging were not rerun for this documentation/source publication.
- This is a source publication. Historical audio, cookies, screenshots, local environments, and machine-specific agent configuration are excluded.
- Default mode uses placeholders; real execution requires external tools and model weights.
- The separation adapter collects five named stems, including guitar. Keep guitar transcription enabled to select `htdemucs_6s`; the four-stem `htdemucs` route needs an output-handling update to satisfy that contract. The six-stem model's additional piano output is not collected separately.
- The desktop E2E harness targets an existing `MySong1` project and clears its generated outputs. Read the setup guide before running it.

## Documentation

- [Installation, configuration, tests, troubleshooting](docs/INSTALL.md)
- [Architecture](docs/architecture.md)
- [Tool contract v1](docs/contracts/tool-contract-v1.md)
- [Python CLI](apps/audio-cli/README.md)

Historical plans under `docs/plans/` describe development intent at the time; source code and the current setup guide describe this publication.
