import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { execFileSync, spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { download as downloadEdgeDriver } from "edgedriver";

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.resolve(currentDir, "..");
const longRunCommandTimeoutMs = 10 * 60 * 1000;
const longRunSpecTimeoutMs = 25 * 60 * 1000;
const tauriBinaryPath = path.join(
  appRoot,
  "src-tauri",
  "target",
  "debug",
  process.platform === "win32" ? "superscore-desktop.exe" : "superscore-desktop"
);
let tauriDriverProcess;

function resolveTauriDriverPath() {
  const cargoBinary = path.join(
    os.homedir(),
    ".cargo",
    "bin",
    process.platform === "win32" ? "tauri-driver.exe" : "tauri-driver"
  );

  if (fs.existsSync(cargoBinary)) {
    return cargoBinary;
  }

  return process.platform === "win32" ? "tauri-driver.exe" : "tauri-driver";
}

function waitForPort(port, timeoutMs = 30000) {
  const startedAt = Date.now();

  return new Promise((resolve, reject) => {
    const attempt = () => {
      const socket = net.createConnection({ port, host: "127.0.0.1" });
      socket.once("connect", () => {
        socket.end();
        resolve();
      });
      socket.once("error", () => {
        socket.destroy();
        if (Date.now() - startedAt >= timeoutMs) {
          reject(new Error(`Timed out waiting for port ${port}`));
          return;
        }
        setTimeout(attempt, 250);
      });
    };

    attempt();
  });
}

function waitForPortClosed(port, timeoutMs = 30000) {
  const startedAt = Date.now();

  return new Promise((resolve, reject) => {
    const attempt = () => {
      const socket = net.createConnection({ port, host: "127.0.0.1" });
      socket.once("connect", () => {
        socket.destroy();
        if (Date.now() - startedAt >= timeoutMs) {
          reject(new Error(`Timed out waiting for port ${port} to close`));
          return;
        }
        setTimeout(attempt, 250);
      });
      socket.once("error", () => {
        socket.destroy();
        resolve();
      });
    };

    attempt();
  });
}

function runCommand(command, args, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      stdio: "inherit",
      windowsHide: true
    });

    child.once("exit", (code) => {
      if (code === 0) {
        resolve();
        return;
      }

      reject(new Error(`${command} ${args.join(" ")} exited with code ${code ?? "null"}`));
    });

    child.once("error", reject);
  });
}

async function cleanupStaleProcesses() {
  if (process.platform !== "win32") {
    return;
  }

  for (const imageName of ["superscore-desktop.exe", "tauri-driver.exe", "msedgedriver.exe"]) {
    try {
      execFileSync("taskkill.exe", ["/F", "/T", "/IM", imageName], {
        stdio: "ignore",
        windowsHide: true
      });
    } catch {
      // Ignore when the process is not running.
    }
  }

  await waitForPortClosed(4444).catch(() => {});
}

async function startTauriDriver() {
  const nativeDriverPath = await downloadEdgeDriver();
  tauriDriverProcess = spawn(resolveTauriDriverPath(), ["--native-driver", nativeDriverPath], {
    cwd: appRoot,
    stdio: "inherit",
    windowsHide: true
  });

  await waitForPort(4444);
}

function stopTauriDriver() {
  if (!tauriDriverProcess || tauriDriverProcess.killed) {
    return;
  }

  tauriDriverProcess.kill();
}

export const config = {
  hostname: "127.0.0.1",
  port: 4444,
  path: "/",
  runner: "local",
  connectionRetryTimeout: longRunCommandTimeoutMs,
  specs: ["./specs/**/*.e2e.mjs"],
  maxInstances: 1,
  framework: "mocha",
  reporters: ["spec"],
  capabilities: [
    {
      "tauri:options": {
        application: tauriBinaryPath
      }
    }
  ],
  mochaOpts: {
    ui: "bdd",
    timeout: longRunSpecTimeoutMs
  },
  async onPrepare() {
    await cleanupStaleProcesses();
    await runCommand("pnpm", ["exec", "tauri", "build", "--debug", "--no-bundle"], appRoot);
  },
  async beforeSession() {
    await cleanupStaleProcesses();
    await startTauriDriver();
  },
  async afterSession() {
    stopTauriDriver();
    await cleanupStaleProcesses();
  }
};
