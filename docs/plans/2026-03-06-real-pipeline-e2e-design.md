# Real Pipeline E2E Harness Design

**Date:** 2026-03-06

## Goal

Create a repeatable repo-local harness that launches the SuperScore desktop app, runs the real audio pipeline against the existing `MySong1` test project, and preserves enough evidence to debug failures without manual copy/paste from the UI.

## Context

SuperScore already exposes the full workflow in the desktop UI:

- open an existing project
- import audio if needed
- switch between placeholder and real execution
- start the pipeline
- watch job state and logs
- inspect generated artifacts

The current gap is observability and repeatability. The app can fail during real runs, but the most useful diagnostics remain transient in memory or only partially reflected in the visible UI.

## Requirements

- Exercise the real pipeline, not placeholders.
- Reuse the existing roaming-data test project `MySong1`.
- Allow the harness to overwrite or clear prior outputs in that test project.
- Drive the same app path a user follows, not a synthetic backend-only shortcut.
- Preserve durable diagnostics for every automated run.
- Keep the implementation minimal and repo-local rather than depending on generic external wrappers.

## Approaches Considered

### 1. Tauri UI E2E harness with durable diagnostics

Use a repo-local Tauri E2E harness to launch the desktop binary, drive the current UI, and collect both backend and UI artifacts per run.

Pros:

- matches the real user flow
- catches UI state, settings, and backend integration issues together
- produces evidence that can be used to fix failures
- repeatable from `pnpm`

Cons:

- more setup than a backend-only runner
- desktop automation can be fragile if selectors are not stabilized

### 2. Backend-only pipeline runner

Invoke the pipeline commands directly without driving the window.

Pros:

- faster to build and run
- less automation overhead

Cons:

- misses UI-specific regressions
- does not validate the app shell and persisted settings flow
- weaker match for the actual user problem

### 3. Ad hoc remote control only

Rely on session-scoped remote-control tooling without adding repo-local automation.

Pros:

- lowest upfront code cost

Cons:

- not repeatable
- poor for regression checking
- weak artifact discipline

## Chosen Approach

Approach 1: a minimal repo-local Tauri E2E harness with durable diagnostics.

This is the best fit for the stated goal: open SuperScore, run the real pipeline on `MySong1`, and preserve enough information to diagnose and fix failures.

## Architecture

### App instrumentation

Add stable `data-testid` hooks to the existing desktop UI controls required by the run:

- settings entry points
- real-mode toggle
- project open button
- pipeline start button
- job-status surface
- visible log panels
- artifact list

Selectors should be explicit and stable so the automation is not coupled to button text, layout depth, or cosmetic changes.

### Backend diagnostics

Add durable per-job diagnostics written by the Rust backend for real pipeline runs. Each job should produce a diagnostics folder under the project, keyed by job id, containing:

- stage request JSON payloads
- raw subprocess stdout
- raw subprocess stderr
- job summary JSON
- job event/log stream snapshot

This data should be written regardless of whether the job succeeds or fails. A failed run without durable logs is not acceptable.

### E2E runner

Add a small repo-local Windows/Tauri harness that:

1. builds or launches the app binary
2. opens SuperScore
3. opens project `MySong1`
4. ensures real mode is enabled
5. optionally clears old outputs in `stems/`, `midi/`, and `musicxml/`
6. starts the pipeline
7. waits for a terminal state
8. captures UI evidence and points to the backend diagnostics directory

The initial harness should target binary mode for determinism instead of a hot-reload dev loop.

## Data Flow

1. The runner launches the built desktop app.
2. The UI automation opens `MySong1` in the existing roaming data root.
3. The app persists current settings and starts a real pipeline job.
4. The Rust backend records stage transitions, warnings, request payloads, and subprocess output under a per-job diagnostics directory.
5. The UI updates the visible job status and log surfaces.
6. The runner waits for `completed`, `failed`, or timeout.
7. On completion, failure, or timeout, the runner saves repo-side artifacts such as:
   - screenshot
   - job-status text
   - visible log text
   - artifact-list text
   - output folder snapshot

## Error Handling

- If required tools are missing or fail preflight, the backend diagnostics must preserve the exact failing command output.
- If the UI run times out, the harness still records the current screen state and project snapshot.
- If the pipeline fails, the E2E test should treat diagnostics capture as success of the harness itself. The run may still report the app outcome as failed.
- If `MySong1` is missing, the harness should fail fast with a clear configuration error.

## Testing Strategy

### Backend

- Add focused Rust tests for diagnostics-path creation and file-writing behavior where feasible.
- Keep logic for diagnostics writing small and testable.

### UI automation

- Add one narrow end-to-end scenario for the real pipeline path on `MySong1`.
- The first scenario should prioritize artifact capture and deterministic control over broad assertions.

### Verification

- Run the targeted Rust tests for diagnostics behavior.
- Run the new E2E command locally against the existing Windows environment.
- Confirm that a failing pipeline still leaves behind actionable diagnostics.

## Scope Boundaries

In scope:

- repo-local automation setup
- stable selectors for the existing UI
- durable diagnostics for real pipeline jobs
- one real-path E2E scenario for `MySong1`

Out of scope for the first pass:

- multi-project matrix runs
- CI integration
- broad UI coverage beyond the pipeline path
- redesigning the desktop UI

## Risks

- Desktop automation can be flaky if selector coverage is incomplete.
- Long-running ML stages may require generous timeouts and careful artifact collection.
- Real external tools can fail for environment reasons unrelated to the app, so exact subprocess capture is required.

## Success Criteria

- A single `pnpm` command can launch SuperScore and run the real pipeline against `MySong1`.
- Every run produces enough evidence to debug success, failure, or timeout without manual UI copy/paste.
- The harness is stable enough to be rerun during bug-fixing work in this repo.
