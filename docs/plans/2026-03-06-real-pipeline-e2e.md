# Real Pipeline E2E Harness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a repo-local harness that launches SuperScore, runs the real pipeline against `MySong1`, and always captures durable diagnostics for debugging.

**Architecture:** Add small backend diagnostics primitives in the Tauri Rust layer, stabilize the current UI with test ids, and add a narrow Windows/Tauri E2E harness that drives the real app path in binary mode and stores run artifacts. The first scenario is intentionally single-project and single-flow to keep the loop reliable while debugging pipeline failures.

**Tech Stack:** Tauri v2, Rust, pnpm, WebdriverIO, tauri-driver, PowerShell on Windows

---

### Task 1: Stabilize the current app UI for automation

**Files:**
- Modify: `apps/desktop/web/index.html`
- Test: `apps/desktop/e2e/specs/real-pipeline.e2e.ts`

**Step 1: Write the failing test**

Create `apps/desktop/e2e/specs/real-pipeline.e2e.ts` with a first assertion that expects stable selectors such as `[data-testid="project-grid"]`, `[data-testid="open-settings"]`, and `[data-testid="start-pipeline"]` to exist after the app launches.

```ts
it("shows stable automation hooks for the pipeline flow", async () => {
  await expect($('[data-testid="project-grid"]')).toBeExisting();
  await expect($('[data-testid="open-settings"]')).toBeExisting();
  await expect($('[data-testid="start-pipeline"]')).toBeExisting();
});
```

**Step 2: Run test to verify it fails**

Run: `pnpm --filter @superscore/desktop e2e`
Expected: FAIL because the E2E package or selectors do not exist yet.

**Step 3: Write minimal implementation**

Add `data-testid` attributes to the current controls and surfaces needed for the real run:

- project grid and open buttons
- settings buttons and modal
- real-mode checkbox
- start pipeline button
- job-status element
- output log surface
- artifact list

**Step 4: Run test to verify it passes**

Run: `pnpm --filter @superscore/desktop e2e`
Expected: The selector-existence assertions pass once the harness is in place.

**Step 5: Commit**

```bash
git add apps/desktop/web/index.html apps/desktop/e2e/specs/real-pipeline.e2e.ts
git commit -m "test: add stable selectors for desktop e2e"
```

### Task 2: Add durable backend diagnostics for each pipeline job

**Files:**
- Modify: `apps/desktop/src-tauri/src/lib.rs`
- Test: `apps/desktop/src-tauri/src/lib.rs`

**Step 1: Write the failing test**

Add a Rust unit test near the existing tests that writes a synthetic diagnostics bundle for a fake job id and asserts that summary and subprocess files are created under a deterministic diagnostics directory.

```rust
#[test]
fn writes_job_diagnostics_bundle() {
    let root = tempdir().unwrap();
    let job_id = "job-123";
    let dir = job_diagnostics_dir(root.path(), job_id);
    write_job_summary(&dir, &serde_json::json!({"state": "failed"})).unwrap();
    assert!(dir.join("summary.json").exists());
}
```

**Step 2: Run test to verify it fails**

Run: `cargo test writes_job_diagnostics_bundle`
Expected: FAIL because diagnostics helpers do not exist yet.

**Step 3: Write minimal implementation**

Add small helper functions in `lib.rs` to:

- compute a per-job diagnostics directory under the project root
- persist stage request payloads
- persist raw stdout and stderr for tool subprocesses
- persist a final summary JSON
- persist appended job log lines or event snapshots

Wire these helpers into the real pipeline path so the app records diagnostics for:

- preflight failures
- separation
- transcription
- export
- final terminal state

Update `CliRunner` so subprocess output can be written before errors are summarized away.

**Step 4: Run test to verify it passes**

Run: `cargo test writes_job_diagnostics_bundle`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/desktop/src-tauri/src/lib.rs
git commit -m "feat: persist desktop pipeline diagnostics"
```

### Task 3: Add a repo-local Tauri E2E harness

**Files:**
- Modify: `apps/desktop/package.json`
- Create: `apps/desktop/e2e/package.json`
- Create: `apps/desktop/e2e/tsconfig.json`
- Create: `apps/desktop/e2e/wdio.conf.ts`
- Create: `apps/desktop/e2e/specs/real-pipeline.e2e.ts`
- Create: `apps/desktop/e2e/support/project-run.ts`
- Create: `apps/desktop/e2e/support/selectors.ts`

**Step 1: Write the failing test**

Create the real scenario spec that:

- launches the app
- opens `MySong1`
- ensures real mode is enabled
- starts the pipeline
- waits for a terminal job state

Have it assert that either:

- the job completes, or
- the job fails but produces a visible failure state and diagnostics path

```ts
it("runs the real pipeline for MySong1 and captures diagnostics", async () => {
  await openProject("MySong1");
  await ensureRealModeEnabled();
  const result = await runPipelineAndCollectArtifacts();
  expect(["completed", "failed", "timeout"]).toContain(result.outcome);
  expect(result.artifactDir).toBeTruthy();
});
```

**Step 2: Run test to verify it fails**

Run: `pnpm --filter @superscore/desktop e2e`
Expected: FAIL because the WDIO/Tauri harness is not configured yet.

**Step 3: Write minimal implementation**

Add the desktop E2E package and configuration:

- install and configure WebdriverIO and the Tauri service pieces needed for Windows desktop automation
- launch the built app binary
- expose helper functions for project open, settings open, real-mode toggle, pipeline start, and terminal-state wait
- save screenshot and UI text artifacts under a repo-local `artifacts/e2e/<timestamp>/` directory

Keep orchestration explicit in the repo rather than delegating to a generic wrapper script.

**Step 4: Run test to verify it passes**

Run: `pnpm --filter @superscore/desktop e2e`
Expected: PASS as a harness run. The app outcome may be `completed` or `failed`, but the automation itself must finish with saved artifacts.

**Step 5: Commit**

```bash
git add apps/desktop/package.json apps/desktop/e2e
git commit -m "test: add tauri desktop e2e harness"
```

### Task 4: Add project-output cleanup and artifact snapshotting

**Files:**
- Modify: `apps/desktop/e2e/support/project-run.ts`
- Modify: `apps/desktop/e2e/specs/real-pipeline.e2e.ts`

**Step 1: Write the failing test**

Add assertions that the runner clears stale outputs in `stems`, `midi`, and `musicxml` before starting, then writes a post-run snapshot file describing the current project contents.

```ts
it("clears stale outputs and saves a project snapshot", async () => {
  const result = await runPipelineAndCollectArtifacts();
  expect(result.snapshotPath).toMatch(/project-snapshot\.json$/);
});
```

**Step 2: Run test to verify it fails**

Run: `pnpm --filter @superscore/desktop e2e`
Expected: FAIL because cleanup and snapshot capture do not exist yet.

**Step 3: Write minimal implementation**

In the E2E support helpers:

- clear stale generated files from `MySong1/stems`, `MySong1/midi`, and `MySong1/musicxml`
- preserve `input/` and `meta.json`
- write a JSON snapshot of relevant project folders after the run

**Step 4: Run test to verify it passes**

Run: `pnpm --filter @superscore/desktop e2e`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/desktop/e2e/support/project-run.ts apps/desktop/e2e/specs/real-pipeline.e2e.ts
git commit -m "test: snapshot desktop pipeline project outputs"
```

### Task 5: Document the developer workflow

**Files:**
- Modify: `README.md`
- Test: `README.md`

**Step 1: Write the failing test**

Define the missing documentation assertions manually:

- the README should explain how to run the real pipeline E2E harness
- it should describe where diagnostics and screenshots are stored
- it should call out that the harness targets `MySong1`

**Step 2: Run test to verify it fails**

Run: `rg -n "e2e|MySong1|artifacts/e2e|runs" README.md`
Expected: Missing or incomplete matches.

**Step 3: Write minimal implementation**

Add a short README section that covers:

- prerequisites for the real environment
- the `pnpm` command to run the harness
- where repo-side artifacts are stored
- where backend per-job diagnostics are stored in the project data root

**Step 4: Run test to verify it passes**

Run: `rg -n "e2e|MySong1|artifacts/e2e|runs" README.md`
Expected: Matches the new documentation lines.

**Step 5: Commit**

```bash
git add README.md
git commit -m "docs: describe desktop real-pipeline e2e loop"
```

### Task 6: Verify the full loop end to end

**Files:**
- Verify: `apps/desktop/src-tauri/src/lib.rs`
- Verify: `apps/desktop/e2e/specs/real-pipeline.e2e.ts`
- Verify: `README.md`

**Step 1: Run focused Rust diagnostics tests**

Run: `cargo test writes_job_diagnostics_bundle`
Expected: PASS

**Step 2: Run the desktop E2E harness**

Run: `pnpm --filter @superscore/desktop e2e`
Expected: The harness launches the app, drives `MySong1`, and saves repo artifacts even if the app pipeline ends in failure.

**Step 3: Inspect the generated artifacts**

Run: `Get-ChildItem -Recurse artifacts/e2e | Select-Object FullName,Length,LastWriteTime`
Expected: A fresh timestamped artifact directory exists with screenshots and run metadata.

**Step 4: Inspect project diagnostics**

Run: `Get-ChildItem -Recurse <data_root>/MySong1 | Select-String -Pattern "runs|summary.json|stderr|stdout"`
Expected: Files exist for the most recent job diagnostics bundle.

**Step 5: Commit**

```bash
git add apps/desktop/src-tauri/src/lib.rs apps/desktop/e2e README.md
git commit -m "chore: verify desktop real-pipeline e2e workflow"
```
