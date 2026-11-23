Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "Installing JS dependencies with pnpm..."
pnpm install

Write-Host "Syncing Python CLI environment with uv..."
uv sync --project apps/audio-cli

Write-Host "Python CLI smoke check..."
uv run --project apps/audio-cli superscore-audio-cli --help | Out-Null
uv run --project apps/audio-cli python -c "import numpy, torch, torchaudio" | Out-Null
uv run --project apps/audio-cli python -c "import torchaudio; backends = torchaudio.list_audio_backends(); assert backends, 'no torchaudio backend available'" | Out-Null

Write-Host "Rust format check..."
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml -- --check

Write-Host "Bootstrap checks complete."
