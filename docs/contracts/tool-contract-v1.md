# SuperScore Tool Contract v1

All sidecar calls use `contractVersion = "v1"` and are executed through:

- `superscore-audio-cli separate --request-file <path>`
- `superscore-audio-cli transcribe --request-file <path>`
- `superscore-audio-cli export-musicxml --request-file <path>`

## Shared Request Envelope

```json
{
  "contractVersion": "v1",
  "projectPath": "/absolute/project/path",
  "outputPath": "/absolute/output/path",
  "options": {
    "realExecution": true
  }
}
```

## Tool Path Discovery

All commands support optional overrides:

```json
{
  "options": {
    "toolPaths": {
      "demucs": "/path/to/demucs",
      "omnizart": "/path/to/omnizart",
      "basicPitch": "/path/to/basic-pitch",
      "musescore": "/path/to/musescore",
      "ytDlp": "/path/to/yt-dlp"
    }
  }
}
```

If an override is omitted, adapter defaults to PATH discovery.

## Separate Request

```json
{
  "contractVersion": "v1",
  "projectPath": "/project",
  "inputPath": "/project/input/song.wav",
  "outputPath": "/project/stems",
  "options": {
    "realExecution": true,
    "model": "htdemucs",
    "toolPaths": { "demucs": "demucs" }
  }
}
```

## Transcribe Request

```json
{
  "contractVersion": "v1",
  "projectPath": "/project",
  "inputPath": "/project/input/song.wav",
  "stemPaths": ["/project/stems/drums.wav", "/project/stems/guitar.wav"],
  "outputPath": "/project/midi/clean",
  "options": {
    "realExecution": true,
    "allowPartialSuccess": true,
    "transcribeGuitar": true,
    "transcribeOther": false,
    "notationMode": "readable",
    "quantizationResolution": "auto",
    "allowTuplets": false,
    "chordOutput": "symbols",
    "conditionStems": ["bass", "vocals", "guitar"],
    "meterOverride": null,
    "toolPaths": {
      "omnizart": "omnizart",
      "basicPitch": "basic-pitch"
    }
  }
}
```

Routing policy in v1:

- `drums` -> Omnizart drum
- `vocals`, `bass`, `guitar` -> Basic Pitch
- `other` -> skipped by default (unless `transcribeOther = true`)
- `outputPath` is the cleaned MIDI destination consumed by export
- notation cleanup may also write `analysis/*` and intermediate `midi/raw/*` artifacts under `projectPath`
- successful transcribe responses return only exportable cleaned `midi` artifacts, while `analysis/*` and `midi/raw/*` remain on disk under `projectPath`

Readable-notation options in `transcribe`:

- `notationMode = "readable"` enables beat-grid cleanup before export
- `quantizationResolution` selects the preferred snap grid for note starts and durations
- `allowTuplets` allows tuplets in the cleaned grid when enabled
- `chordOutput` controls whether chord analysis is surfaced with the cleaned notation output
- `conditionStems` identifies stems that should be conditioned before Basic Pitch runs
- `meterOverride` lets the desktop pin a meter when auto-detection is unreliable

## Export MusicXML Request

```json
{
  "contractVersion": "v1",
  "projectPath": "/project",
  "midiPaths": ["/project/midi/clean/drums.mid"],
  "outputPath": "/project/musicxml",
  "options": {
    "realExecution": true,
    "allowPartialSuccess": true,
    "toolPaths": { "musescore": "musescore" }
  }
}
```

`midiPaths` must reference cleaned MIDI outputs. Raw MIDI stays under `midi/raw` for debugging and cleanup reruns. The desktop must select only transcribe artifacts with kind `midi` when building this request.

## Success Response

```json
{
  "status": "ok",
  "toolVersion": "adapter-0.2.0",
  "artifacts": [{ "kind": "midi", "path": "/project/midi/clean/vocals.mid" }],
  "warnings": ["skipping transcription for stem `other` by policy"],
  "failedArtifacts": [{ "kind": "midi", "path": "/project/midi/clean/drums.mid" }]
}
```

- `warnings` is always present (possibly empty).
- `failedArtifacts` is always present (possibly empty).

## Error Response

Non-zero exits must emit JSON to stderr:

```json
{
  "status": "error",
  "error": {
    "code": "tool_failed",
    "message": "human-readable reason"
  }
}
```
