# superscore-audio-cli

Python CLI adapter for SuperScore: Demucs separation, Omnizart / Basic Pitch transcription, beat/chord analysis, MIDI cleanup, and MuseScore export. See [the installation guide](../../docs/INSTALL.md) for environment setup.

## Commands

- `separate --request-file <json>`
- `transcribe --request-file <json>`
- `export-musicxml --request-file <json>`

All commands use contract `v1` and return JSON to stdout.

## Local Run

### Setup

```bash
uv sync --project apps/audio-cli
```

`omnizart` should be installed in a separate environment and configured via tool path.
`basic-pitch` should also be installed in a separate environment and configured via tool path.

### Smoke Check

```bash
uv run --project apps/audio-cli python -c "import numpy, torch, torchaudio"
uv run --project apps/audio-cli demucs --help
```

### Command Example

```bash
uv run --project apps/audio-cli superscore-audio-cli separate --request-file request.json
```

If you see NumPy ABI errors, make sure the same environment contains:
- `numpy<2`
- matching `torch/torchaudio`
- `demucs`
