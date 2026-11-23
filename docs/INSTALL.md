# Installation and running (Windows)

Run commands from the repository root in PowerShell. Use pnpm for JavaScript and uv for Python environments. This guide targets the original Windows development platform.

## Desktop prerequisites

Install Git, Node.js 22+, pnpm 10, Rust (MSVC), Visual Studio Build Tools with Desktop development with C++ and Windows SDK, and WebView2 Runtime. Install uv for the audio pipeline.

```powershell
pnpm install --frozen-lockfile
pnpm tauri:dev
```

Default placeholder mode supports exploring the UI before installing audio models.

## Audio adapter and Demucs

The adapter uses Python 3.11 with locked dependencies, PyTorch / torchaudio 2.2.2, and NumPy below version 2.

```powershell
uv python install 3.11
uv sync --locked --project apps/audio-cli
uv run --project apps/audio-cli superscore-audio-cli --help
uv run --project apps/audio-cli python -c "import numpy, torch, torchaudio; print(torch.__version__); print('CUDA:', torch.cuda.is_available())"
uv run --project apps/audio-cli demucs --help
```

Demucs downloads model weights on first use. Allow time and network access for the initial run. The original local environment used CPU inference.

## Basic Pitch environment

The local project used Basic Pitch 0.4.0 with Python 3.10, separate from the adapter environment.

```powershell
uv python install 3.10
uv venv --python 3.10 .venv-amt-main
uv pip install --python .venv-amt-main/Scripts/python.exe "basic-pitch==0.4.0"
& ./.venv-amt-main/Scripts/basic-pitch.exe --help
```

## Omnizart drum environment

The original local setup used Python 3.9, Omnizart 0.5.0, TensorFlow 2.5.0, NumPy 1.19.5, and librosa 0.8.1. This legacy stack is isolated from Demucs and Basic Pitch.

Starting installation commands:

```powershell
uv python install 3.9
uv venv --python 3.9 .venv-amt-omnizart
uv pip install --python .venv-amt-omnizart/Scripts/python.exe "omnizart==0.5.0"
& ./.venv-amt-omnizart/Scripts/omnizart.exe --help
& ./.venv-amt-omnizart/Scripts/omnizart.exe download-checkpoints --help
```

Use `omnizart download-checkpoints` to obtain model checkpoints. Fresh installation of this legacy stack may require package-specific build prerequisites and compatible dependency pins. [The original environment inventory](omnizart-local-environment.txt) records installed versions for troubleshooting; it is an environment snapshot, not a freshly resolved lockfile.

The adapter automatically invokes `omnizart_drum_wrapper.py` using the Python interpreter beside `omnizart.exe`. The wrapper adjusts feature extraction and threading for Windows. Keep the executable and interpreter in the same environment.

## MuseScore and audio import tools

Install MuseScore 4; its executable commonly resides at `C:\Program Files\MuseScore 4\bin\MuseScore4.exe`. Install FFmpeg and yt-dlp for YouTube import and add their executable directories to PATH.

```powershell
ffmpeg -version
yt-dlp --version
```

Local audio import works independently of YouTube download setup. Process audio you have permission to use; keep download cookies outside Git.

## Configure Settings and process audio

Replace `<repo>` with your clone's absolute location, choose a writable data root, and save Settings.

| Setting | Typical Windows path |
| --- | --- |
| Audio CLI | `<repo>\apps\audio-cli\.venv\Scripts\superscore-audio-cli.exe` |
| Demucs | `<repo>\apps\audio-cli\.venv\Scripts\demucs.exe` |
| Basic Pitch | `<repo>\.venv-amt-main\Scripts\basic-pitch.exe` |
| Omnizart | `<repo>\.venv-amt-omnizart\Scripts\omnizart.exe` |
| MuseScore | `C:\Program Files\MuseScore 4\bin\MuseScore4.exe` |
| yt-dlp | Absolute path to the installed executable |

Enable **Real execution (disable placeholders)**. Settings persist across restarts; update tool paths if the clone moves.

Create a project, import local audio or a YouTube URL, keep **Transcribe guitar** enabled, and click **Start Pipeline**. The default model is `htdemucs_6s`. Compare `midi/raw` and `midi/clean`, then open `musicxml` files in your notation editor.

## Tests and builds

```powershell
uv run --project apps/audio-cli python -m unittest discover -s apps/audio-cli/tests -v
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml -- --check
cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml
pnpm tauri:build
```

Model environments and weights remain external to the desktop package. `pnpm build` is only a static-frontend placeholder command; `pnpm tauri:build` compiles and packages the app.

The optional `pnpm bootstrap` helper installs JS dependencies, syncs the main Python environment, and performs CLI, audio-backend, and Rust-format checks. Basic Pitch, Omnizart, MuseScore, and model checkpoints are configured separately; review each step's console output.

### Original desktop E2E harness

```powershell
cargo install tauri-driver --locked
pnpm --filter @superscore/desktop e2e
```

This Windows harness builds the app, obtains an Edge driver, and drives the UI. The real-pipeline scenario expects an existing project named **MySong1** with imported audio and configured tools. It clears generated stems/MIDI/MusicXML and terminates existing SuperScore / test-driver processes. Use a dedicated test project and close active work first.

The scenario captures terminal outcomes and diagnostics, including failed jobs. For audio-pipeline acceptance, inspect actual completion and expected per-stem outputs.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Placeholder outputs | Enable Real execution and save Settings. |
| Missing executable | Set an absolute tool path and run the tool with `--help`. |
| NumPy / torch ABI error | Sync the adapter from `uv.lock`; keep model environments separate. |
| Missing guitar stem | Keep Transcribe guitar enabled to select `htdemucs_6s`. |
| Drum setup error | Check Python 3.9 environment, drum checkpoint, and wrapper interpreter. |
| YouTube import error | Check yt-dlp, FFmpeg, and source availability; try local audio. |
| MusicXML export error | Check MuseScore path and cleaned MIDI. |
| Some stems missing | Inspect warnings / failed artifacts with Allow partial success enabled. |
| Unexpected notation | Compare raw and clean MIDI; cleanup quantizes timing and adjusts nearby chord tones. |

First GitHub upload: **2026-11-23**. Local development and the original successful real-mode run predate publication.
