import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SELECTORS } from "./selectors.mjs";

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const desktopRoot = path.resolve(currentDir, "..", "..");
const repoRoot = path.resolve(desktopRoot, "..", "..");
const appDataRoot = process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming");
const settingsPath = path.join(appDataRoot, "SuperScore", "settings.json");

function safeReadJson(jsonPath) {
  return JSON.parse(fs.readFileSync(jsonPath, "utf8"));
}

function writeJson(jsonPath, value) {
  fs.writeFileSync(jsonPath, JSON.stringify(value, null, 2));
}

function serializeError(error) {
  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message,
      stack: error.stack
    };
  }

  return {
    message: String(error)
  };
}

function readSessionId() {
  try {
    return browser.sessionId ?? null;
  } catch {
    return null;
  }
}

function timestampId() {
  const now = new Date();
  const part = (value) => String(value).padStart(2, "0");
  return `${now.getFullYear()}${part(now.getMonth() + 1)}${part(now.getDate())}-${part(now.getHours())}${part(now.getMinutes())}${part(now.getSeconds())}`;
}

async function readVisibleText(selector) {
  const element = await $(selector);
  if (!(await element.isExisting())) {
    return "";
  }
  return element.getText();
}

function listFilesRecursively(root) {
  if (!fs.existsSync(root)) {
    return [];
  }
  const entries = [];
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const fullPath = path.join(root, entry.name);
    if (entry.isDirectory()) {
      entries.push({
        path: fullPath,
        kind: "dir",
        children: listFilesRecursively(fullPath)
      });
      continue;
    }

    const stats = fs.statSync(fullPath);
    entries.push({
      path: fullPath,
      kind: "file",
      size: stats.size,
      modifiedAt: stats.mtime.toISOString()
    });
  }
  return entries;
}

export function resolveDataRoot() {
  const settings = safeReadJson(settingsPath);
  if (!settings.dataRoot) {
    throw new Error(`SuperScore settings at ${settingsPath} do not include dataRoot`);
  }
  return settings.dataRoot;
}

export function resolveProjectRoot(projectId) {
  const projectRoot = path.join(resolveDataRoot(), projectId);
  if (!fs.existsSync(projectRoot)) {
    throw new Error(`Project root does not exist: ${projectRoot}`);
  }
  return projectRoot;
}

export function createArtifactDir(name) {
  const artifactDir = path.join(repoRoot, "artifacts", "e2e", `${timestampId()}-${name}`);
  fs.mkdirSync(artifactDir, { recursive: true });
  return artifactDir;
}

export function clearGeneratedOutputs(projectRoot) {
  for (const folder of ["stems", "midi", "musicxml"]) {
    const dir = path.join(projectRoot, folder);
    if (!fs.existsSync(dir)) {
      continue;
    }
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const fullPath = path.join(dir, entry.name);
      fs.rmSync(fullPath, { recursive: true, force: true });
    }
  }
}

export function findLatestDiagnosticsDir(projectRoot) {
  const runsRoot = path.join(projectRoot, "runs");
  if (!fs.existsSync(runsRoot)) {
    return "";
  }

  const candidates = fs
    .readdirSync(runsRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => {
      const fullPath = path.join(runsRoot, entry.name);
      return {
        path: fullPath,
        modifiedAt: fs.statSync(fullPath).mtimeMs
      };
    })
    .sort((left, right) => right.modifiedAt - left.modifiedAt);

  return candidates[0]?.path || "";
}

export function snapshotProject(projectRoot, artifactDir) {
  const snapshotPath = path.join(artifactDir, "project-snapshot.json");
  const snapshot = {
    projectRoot,
    capturedAt: new Date().toISOString(),
    folders: {
      input: listFilesRecursively(path.join(projectRoot, "input")),
      stems: listFilesRecursively(path.join(projectRoot, "stems")),
      midi: listFilesRecursively(path.join(projectRoot, "midi")),
      musicxml: listFilesRecursively(path.join(projectRoot, "musicxml")),
      runs: listFilesRecursively(path.join(projectRoot, "runs"))
    }
  };
  writeJson(snapshotPath, snapshot);
  return snapshotPath;
}

export async function collectUiArtifacts(artifactDir, metadata) {
  const errorReportPath = path.join(artifactDir, "ui-artifact-errors.json");
  const captureReport = {
    capturedAt: new Date().toISOString(),
    sessionId: readSessionId(),
    captures: [],
    errors: []
  };
  const recordFailure = (artifactName, error) => {
    captureReport.captures.push({
      artifact: artifactName,
      status: "failed"
    });
    captureReport.errors.push({
      artifact: artifactName,
      error: serializeError(error)
    });
  };
  const recordSuccess = (artifactName) => {
    captureReport.captures.push({
      artifact: artifactName,
      status: "written"
    });
  };

  writeJson(path.join(artifactDir, "run-meta.json"), metadata);

  try {
    await browser.saveScreenshot(path.join(artifactDir, "window.png"));
    recordSuccess("window.png");
  } catch (error) {
    recordFailure("window.png", error);
  }

  for (const [fileName, selector] of [
    ["job-status.txt", SELECTORS.jobStatus],
    ["output-log.txt", SELECTORS.outputLog],
    ["artifact-list.txt", SELECTORS.artifactList]
  ]) {
    try {
      fs.writeFileSync(path.join(artifactDir, fileName), await readVisibleText(selector));
      recordSuccess(fileName);
    } catch (error) {
      recordFailure(fileName, error);
    }
  }

  if (captureReport.errors.length > 0) {
    writeJson(errorReportPath, {
      ...captureReport,
      metadata
    });
  }
}

export async function ensureRealModeEnabled() {
  await $(SELECTORS.openSettingsRoot).click();
  await browser.waitUntil(async () => {
    const modal = await $(SELECTORS.settingsModal);
    return modal.isDisplayed();
  }, {
    timeout: 10000,
    interval: 250,
    timeoutMsg: "settings modal did not open"
  });

  const toggle = await $(SELECTORS.realModeToggle);
  if (!(await toggle.isSelected())) {
    await toggle.click();
  }

  await $(SELECTORS.saveSettings).click();
  await browser.waitUntil(async () => {
    const modal = await $(SELECTORS.settingsModal);
    return (await modal.isDisplayed()) === false;
  }, {
    timeout: 10000,
    interval: 250,
    timeoutMsg: "settings modal did not close after saving"
  });
}

export async function openProject(projectId) {
  const selector = SELECTORS.openProject(projectId);
  await browser.waitUntil(async () => (await $(selector).isExisting()) === true, {
    timeout: 10000,
    interval: 250,
    timeoutMsg: `open-project control did not appear for ${projectId}`
  });
  await $(selector).click();
  await browser.waitUntil(async () => {
    const title = await $(SELECTORS.projectTitle);
    return (await title.getText()) === projectId;
  }, {
    timeout: 10000,
    interval: 250,
    timeoutMsg: `project title did not switch to ${projectId}`
  });
}

export async function waitForTerminalOutcome(timeoutMs = 20 * 60 * 1000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const text = await readVisibleText(SELECTORS.jobStatus);
    if (text.startsWith("Completed")) {
      return { outcome: "completed", jobStatus: text };
    }
    if (text.startsWith("Failed")) {
      return { outcome: "failed", jobStatus: text };
    }
    if (text.startsWith("Canceled")) {
      return { outcome: "canceled", jobStatus: text };
    }
    await browser.pause(1000);
  }
  return {
    outcome: "timeout",
    jobStatus: await readVisibleText(SELECTORS.jobStatus)
  };
}
