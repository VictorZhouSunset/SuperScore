import fs from "node:fs";
import fsPromises from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.resolve(currentDir, "../..");
const repoRoot = path.resolve(appRoot, "../..");

function timestampLabel(date = new Date()) {
  return date.toISOString().replaceAll(":", "-").replaceAll(".", "-");
}

async function ensureDir(dirPath) {
  await fsPromises.mkdir(dirPath, { recursive: true });
  return dirPath;
}

async function writeJson(filePath, value) {
  await ensureDir(path.dirname(filePath));
  await fsPromises.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function waitForProjectCard(projectId, timeoutMs = 15000) {
  const selector = `[data-project-id="${projectId}"] .open-project`;
  await browser.waitUntil(async () => (await $(selector).isExisting()) === true, {
    timeout: timeoutMs,
    timeoutMsg: `Project button for ${projectId} did not appear`
  });
  return $(selector);
}

async function resolveSettingsPath() {
  const appDataRoot =
    process.env.APPDATA ?? path.join(os.homedir(), "AppData", "Roaming");
  return path.join(appDataRoot, "SuperScore", "settings.json");
}

async function resolveProjectRoot(projectId) {
  const settingsPath = await resolveSettingsPath();
  const settings = JSON.parse(await fsPromises.readFile(settingsPath, "utf8"));
  const projectRoot = path.join(settings.dataRoot, projectId);
  return { projectRoot, settingsPath };
}

async function openProject(projectId) {
  const trigger = await waitForProjectCard(projectId);
  await trigger.waitForClickable({ timeout: 15000 });
  await trigger.click();
  await browser.waitUntil(async () => (await $("#projectTitle").getText()) === projectId, {
    timeout: 15000,
    timeoutMsg: `Project ${projectId} did not open`
  });
}

async function ensureRealModeEnabled() {
  const settingsButton = await $('[data-testid="open-settings-project"]');
  await settingsButton.waitForClickable({ timeout: 10000 });
  await settingsButton.click();

  const modal = await $("#settingsModal");
  await modal.waitForDisplayed({ timeout: 10000 });

  const realModeToggle = await $('[data-testid="real-mode-toggle"]');
  if (!(await realModeToggle.isSelected())) {
    await realModeToggle.click();
  }

  const saveButton = await $("#saveSettingsBtn");
  await saveButton.waitForClickable({ timeout: 10000 });
  await saveButton.click();
  await modal.waitForDisplayed({ timeout: 10000, reverse: true });
}

async function startPipeline() {
  const startButton = await $('[data-testid="start-pipeline"]');
  await startButton.waitForClickable({ timeout: 10000 });
  await startButton.click();

  const jobStatus = await $('[data-testid="job-status"]');
  await browser.waitUntil(async () => (await jobStatus.getText()) !== "No active job", {
    timeout: 20000,
    timeoutMsg: "Pipeline did not start"
  });
}

function outcomeFromStatus(jobStatusText) {
  const lower = jobStatusText.trim().toLowerCase();
  if (lower.startsWith("completed")) {
    return "completed";
  }
  if (lower.startsWith("failed")) {
    return "failed";
  }
  if (lower.startsWith("canceled")) {
    return "canceled";
  }
  return null;
}

async function waitForTerminalOutcome(timeoutMs = 15 * 60 * 1000) {
  const jobStatus = await $('[data-testid="job-status"]');
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    const jobStatusText = await jobStatus.getText();
    const outcome = outcomeFromStatus(jobStatusText);
    if (outcome) {
      return { outcome, jobStatusText };
    }
    await browser.pause(2000);
  }

  return {
    outcome: "timeout",
    jobStatusText: await jobStatus.getText()
  };
}

async function getText(selector) {
  const element = await $(selector);
  if (!(await element.isExisting())) {
    return "";
  }
  return element.getText();
}

async function latestDiagnosticsDir(projectRoot, notBeforeMs) {
  const runsRoot = path.join(projectRoot, "runs");
  if (!fs.existsSync(runsRoot)) {
    return "";
  }

  const entries = await fsPromises.readdir(runsRoot, { withFileTypes: true });
  const candidates = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) {
      continue;
    }
    const fullPath = path.join(runsRoot, entry.name);
    const stats = await fsPromises.stat(fullPath);
    if (stats.mtimeMs >= notBeforeMs - 1000) {
      candidates.push({ fullPath, mtimeMs: stats.mtimeMs });
    }
  }

  candidates.sort((left, right) => right.mtimeMs - left.mtimeMs);
  return candidates[0]?.fullPath ?? "";
}

async function captureUiArtifacts(artifactDir) {
  const uiSnapshotPath = path.join(artifactDir, "ui-state.json");
  const screenshotPath = path.join(artifactDir, "app.png");

  const snapshot = {
    projectTitle: await getText("#projectTitle"),
    jobStatusText: await getText('[data-testid="job-status"]'),
    outputText: await getText('[data-testid="output-log"]'),
    artifactListText: await getText('[data-testid="artifact-list"]'),
    statusHeadlineText: await getText("#statusHeadline"),
    statusOutputText: await getText("#statusOutput")
  };

  await writeJson(uiSnapshotPath, snapshot);
  await browser.saveScreenshot(screenshotPath);

  return { screenshotPath, uiSnapshotPath };
}

export async function runRealPipelineScenario({ projectId }) {
  const startedAt = new Date();
  const startedAtMs = startedAt.getTime();
  const { projectRoot, settingsPath } = await resolveProjectRoot(projectId);
  if (!fs.existsSync(projectRoot)) {
    throw new Error(`Project root not found for ${projectId}: ${projectRoot}`);
  }

  const artifactDir = await ensureDir(
    path.join(repoRoot, "artifacts", "e2e", `${timestampLabel(startedAt)}-${projectId}`)
  );
  await writeJson(path.join(artifactDir, "scenario.json"), {
    projectId,
    projectRoot,
    settingsPath,
    startedAt: startedAt.toISOString()
  });

  const projectGrid = await $('[data-testid="project-grid"]');
  await projectGrid.waitForExist({ timeout: 15000 });

  await openProject(projectId);
  await ensureRealModeEnabled();
  await startPipeline();

  const terminal = await waitForTerminalOutcome();
  const { screenshotPath, uiSnapshotPath } = await captureUiArtifacts(artifactDir);
  const diagnosticsDir = await latestDiagnosticsDir(projectRoot, startedAtMs);

  const result = {
    projectId,
    artifactDir,
    screenshotPath,
    uiSnapshotPath,
    diagnosticsDir,
    outcome: terminal.outcome,
    jobStatusText: terminal.jobStatusText,
    startedAt: startedAt.toISOString(),
    finishedAt: new Date().toISOString()
  };
  await writeJson(path.join(artifactDir, "run-meta.json"), result);

  return result;
}
