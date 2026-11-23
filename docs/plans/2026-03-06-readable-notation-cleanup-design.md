# Readable Notation Cleanup Design

**Date:** 2026-03-06

## Goal

Improve SuperScore's symbolic output so the exported MusicXML is a clean starting point for musicians by adding stem conditioning, meter-aware rhythm analysis, shared-grid MIDI cleanup, and chord fallback artifacts.

## Context

The current real pipeline is intentionally thin:

- Demucs stem WAVs are copied as-is.
- `bass`, `vocals`, `guitar`, and `other` are sent directly to Basic Pitch.
- `drums` is sent directly to Omnizart.
- MuseScore converts raw MIDI directly to MusicXML.

This causes two quality problems in practice:

- some stems, especially `bass`, are too weak or muddy for stable transcription
- raw MIDI timing is not cleaned before MusicXML export, so barlines, note values, and beat placement become unreadable

The target for this work is readable notation, not faithful reproduction of every micro-timing detail.

## Requirements

- Keep the current core transcription tools for v1:
  - Demucs
  - Basic Pitch
  - Omnizart
  - MuseScore
- Add pre-transcription conditioning for non-drum stems without replacing Basic Pitch yet.
- Do not assume `4/4`; the rhythm grid must be meter-aware and section-aware.
- Use one shared beat/bar grid across stems so cleanup is musically consistent.
- Prefer accompaniment-only audio for chord detection:
  - use `bass`, `guitar`, and `other` by default
  - exclude `vocals` by default
  - use `drums` for rhythm support, not chord identity
- Preserve raw model output and produce cleaned notation-oriented output separately.
- Allow cleanup and export to rerun without repeating separation and transcription.
- Degrade gracefully with warnings when meter, beat, or chord confidence is low.
- Keep UI changes minimal; focus on output quality and reusable backend contracts.

## Approaches Considered

### 1. Stem conditioning plus simple quantization only

Add gain and filtering before Basic Pitch, then quantize raw MIDI to a fixed subdivision.

Pros:

- smallest implementation
- lowest risk to current pipeline wiring

Cons:

- weak handling for meter changes and unstable downbeats
- no cross-stem synchronization
- no chord fallback artifacts
- still relies on MuseScore to infer readable measures from under-specified MIDI

### 2. Hybrid cleanup pipeline with shared analysis artifacts

Add stem conditioning, beat/downbeat and chord analysis, then clean all transcribed MIDI against a shared musical grid before MusicXML export.

Pros:

- directly addresses both reported failure modes
- keeps existing transcription models
- produces reusable rhythm and harmony artifacts
- supports fast re-export after changing cleanup settings

Cons:

- introduces several new backend modules
- requires contract and artifact layout changes

### 3. Generative or diffusion-style conditioned transcription

Use rhythm/chord structure as conditioning input for a new note-transcription model or multi-pass symbolic generator.

Pros:

- strongest long-term path if a mature model becomes available
- aligns with a future assisted-transcription product direction

Cons:

- no clear drop-in model for `stem audio + external beat/chord constraints`
- much higher model and infrastructure complexity
- too much risk for the current repo stage

## Chosen Approach

Approach 2: a hybrid cleanup pipeline with shared analysis artifacts.

This keeps the current toolchain intact, adds the minimum analysis layers needed to make notation readable, and leaves room for more advanced assisted transcription later.

## Architecture

### Pipeline shape

The notation-focused pipeline becomes:

```text
input audio
  -> separation
  -> accompaniment/rhythm analysis
  -> stem conditioning
  -> transcription
  -> shared-grid MIDI cleanup
  -> MusicXML export
```

For v1, analysis does not need true desktop-level parallel execution. The first implementation may run analysis in the Python adapter after separation and before cleanup, because output quality matters more than runtime. The contracts should still be shaped so a future parallel analysis stage can be added without redesigning artifacts.

### 1. Stem conditioning before transcription

Condition `bass`, `vocals`, `guitar`, and optional `other` before Basic Pitch.

Default conditioning policy:

- loudness normalization to a stable target
- mono-centering or mid-channel emphasis
- low-end cleanup to remove rumble and bleed
- optional harmonic/transient emphasis for bass note salience

Drums stay on the Omnizart path and are not passed through the melodic conditioning chain.

### 2. Shared rhythm analysis

Build a meter-aware beat/bar grid from audio evidence, then reuse it across all stems.

Inputs:

- original mix or mix-derived rhythm signal
- drums stem for beat and downbeat refinement

Outputs:

- beat times
- downbeat/bar positions
- meter by section
- confidence per section
- allowed subdivision grid for cleanup

The rhythm grid should be smoothed for notation readability. In readable-notation mode, section-level tempo and meter stability is preferred over capturing expressive micro-timing.

### 3. Chord fallback analysis

Build chord estimates from harmony-first audio instead of the full mix.

Primary input:

- accompaniment-only signal built from `bass + guitar + other`

Refinement roles:

- `bass` refines root motion and slash/inversion candidates
- `guitar` and `other` refine chord quality
- `vocals` are ignored by default in v1

Chord changes should align to the shared rhythm grid so chord symbols land on readable positions.

### 4. MIDI cleanup before MusicXML export

Every stem produces two symbolic outputs:

- raw MIDI from the transcription model
- cleaned MIDI aligned to the shared grid

Cleanup responsibilities:

- snap note onsets to the shared beat/subdivision grid
- simplify note durations for readable notation
- ensure notes belong to legal bar positions
- apply soft chord-aware rescoring so clearly harmonic tones are preferred without deleting passing tones or suspensions
- preserve drum hits on the same shared grid used by the rest of the score

The MusicXML exporter must consume cleaned MIDI, not raw MIDI.

## Data and Artifact Layout

Add an `analysis/` folder to the project root:

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

Artifacts:

- `analysis/beat-grid.json`
- `analysis/chords.json`
- `midi/raw/<stem>.mid`
- `midi/clean/<stem>.mid`
- `musicxml/<stem>.musicxml`

Keeping raw and cleaned MIDI separate makes cleanup/export reruns cheap and debuggable.

## Settings Surface

The first backend-facing settings should be narrow and notation-oriented:

- notation mode:
  - `readable` only for v1
- quantization resolution:
  - `auto`
  - `1/8`
  - `1/16`
  - `1/8-triplet`
  - `1/16-triplet`
- allow tuplets:
  - `true` / `false`
- chord output:
  - `off`
  - `symbols`
  - `symbols-and-track`
- stem conditioning:
  - enabled by default for `bass`, `vocals`, and `guitar`
- meter detection:
  - `auto`, with optional manual override later

Cleanup and export should be rerunnable independently from separation and transcription so users can iterate quickly on readability settings.

## Contracts

The current three-stage contract can remain, but the request payloads need extra notation options and the project layout must support analysis outputs and raw/clean MIDI outputs.

Expected contract evolution:

- `transcribe` accepts conditioning and notation-analysis options
- `transcribe` or a dedicated future `analyze` stage writes analysis artifacts
- `export-musicxml` reads cleaned MIDI by default
- `meta.json` and job diagnostics record whether outputs are raw or cleaned and which notation settings were used

The first implementation should avoid a contract explosion; only add fields required for readable-notation mode.

## Error Handling

- If beat or downbeat confidence is low, continue and emit warnings in job output and diagnostics.
- If chord confidence is low, omit chord symbols or mark them low-confidence rather than blocking export.
- If one stem fails transcription, other stems should still clean and export.
- If cleanup cannot place events into stable bars, preserve raw MIDI and fail the cleaned export explicitly rather than silently producing unreadable MusicXML.

## Testing Strategy

### Unit tests

- stem conditioning transforms
- beat/downbeat smoothing
- meter-aware bar construction
- quantization and duration simplification
- chord root and slash-chord refinement logic
- raw versus cleaned output routing

### Integration tests

- sidecar request/response tests for analysis and cleanup outputs
- fixture-based audio-to-artifact runs on a small set of representative stems
- export tests confirming MusicXML is produced from cleaned MIDI

### Verification criteria

- cleaned MIDI events align to legal bar positions and configured subdivisions
- MusicXML opens in MuseScore with sane measures and readable note values
- bass transcription improves on known weak stems after conditioning
- chord artifacts are still useful when individual note transcription is weak

## Scope Boundaries

In scope:

- backend/audio-cli quality improvements
- project artifact layout changes for analysis and raw/clean MIDI
- notation-oriented cleanup before MusicXML export
- chord fallback artifacts

Out of scope for the first pass:

- new transcription models
- UI redesign
- true desktop-level parallel stage orchestration
- advanced generative accompaniment synthesis

## Success Criteria

- The exported MusicXML becomes a readable starting point instead of a timing mess.
- Bass and other weak stems become more transcription-friendly through conditioning alone.
- All stems share one musically coherent bar/beat structure.
- Chord artifacts remain useful even when detailed note transcription is imperfect.
