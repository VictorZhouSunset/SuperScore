import assert from "node:assert/strict";
import { SELECTORS } from "../support/selectors.mjs";
import {
  clearGeneratedOutputs,
  collectUiArtifacts,
  createArtifactDir,
  ensureRealModeEnabled,
  findLatestDiagnosticsDir,
  openProject,
  resolveProjectRoot,
  snapshotProject,
  waitForTerminalOutcome
} from "../support/project-run.mjs";

describe("SuperScore real pipeline harness", () => {
  it("runs MySong1 and preserves diagnostics for debugging", async function() {
    this.timeout(20 * 60 * 1000);

    const projectId = "MySong1";
    const artifactDir = createArtifactDir("real-pipeline");
    const projectRoot = resolveProjectRoot(projectId);
    let outcome = { outcome: "not-started", jobStatus: "" };
    let diagnosticsDir = "";
    let snapshotPath = "";

    try {
      await browser.waitUntil(async () => (await $(SELECTORS.projectGrid).isExisting()) === true, {
        timeout: 10000,
        interval: 250,
        timeoutMsg: "project grid did not appear in the SuperScore window"
      });
      await ensureRealModeEnabled();
      await openProject(projectId);
      clearGeneratedOutputs(projectRoot);
      await $(SELECTORS.startPipeline).click();
      outcome = await waitForTerminalOutcome();
    } finally {
      diagnosticsDir = findLatestDiagnosticsDir(projectRoot);
      snapshotPath = snapshotProject(projectRoot, artifactDir);
      await collectUiArtifacts(artifactDir, {
        artifactDir,
        projectId,
        projectRoot,
        outcome,
        diagnosticsDir,
        snapshotPath
      });
    }

    assert.equal(["completed", "failed", "timeout"].includes(outcome.outcome), true);
    assert.equal(diagnosticsDir.length > 0, true);
    assert.equal(snapshotPath.endsWith("project-snapshot.json"), true);
  });
});
