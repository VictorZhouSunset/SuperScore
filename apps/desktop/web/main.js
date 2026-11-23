const state = {
  settings: null,
  projects: [],
  currentProject: null,
  currentJobId: null
};

const runtime = {
  invokeFn: null,
  event: null,
  ready: false,
  mode: "none"
};

const statusState = {
  lines: [],
  maxLines: 220
};

const pollState = {
  timer: null,
  ticker: null,
  lastSignature: "",
  jobId: null,
  startedAtMs: 0,
  currentStage: "",
  currentState: "",
  currentMessage: ""
};

const outputEl = document.getElementById("output");
const statusOutputEl = document.getElementById("statusOutput");
const statusHeadlineEl = document.getElementById("statusHeadline");
const statusDrawerEl = document.getElementById("statusDrawer");
const statusToggleBtnEl = document.getElementById("statusToggleBtn");
const rootViewEl = document.getElementById("rootView");
const projectViewEl = document.getElementById("projectView");
const projectGridEl = document.getElementById("projectGrid");
const artifactListEl = document.getElementById("artifactList");
const jobStatusEl = document.getElementById("jobStatus");
const settingsModalEl = document.getElementById("settingsModal");

function nowTime() {
  return new Date().toLocaleTimeString("en-US", { hour12: false });
}

function summarize(value) {
  if (typeof value === "string") {
    return value;
  }
  if (value && typeof value === "object") {
    if (typeof value.error === "string") {
      return value.error;
    }
    if (typeof value.action === "string" && typeof value.error === "string") {
      return `${value.action}: ${value.error}`;
    }
    return "Operation updated";
  }
  return String(value);
}

function pushStatus(message, level = "info") {
  const line = `[${nowTime()}] ${level.toUpperCase()} ${message}`;
  statusState.lines.unshift(line);
  if (statusState.lines.length > statusState.maxLines) {
    statusState.lines.length = statusState.maxLines;
  }
  if (statusOutputEl) {
    statusOutputEl.textContent = `${statusState.lines.join("\n")}\n`;
  }
  if (statusHeadlineEl) {
    statusHeadlineEl.textContent = line;
  }
}

function out(value, level = "info") {
  const line = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  if (outputEl) {
    outputEl.textContent = `${line}\n${outputEl.textContent}`;
  }
  if (typeof value === "string") {
    pushStatus(value, level);
  } else if (level === "error" || level === "warn") {
    pushStatus(summarize(value), level);
  }
}

function getErrorMessage(error) {
  if (!error) {
    return "Unknown error";
  }
  if (typeof error === "string") {
    return error;
  }
  if (typeof error.message === "string") {
    return error.message;
  }
  return JSON.stringify(error);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function initTauriRuntime(timeoutMs = 4000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const globals = Object.keys(window).filter((key) => key.includes("TAURI"));
    const tauri = window.__TAURI__;
    const internals = window.__TAURI_INTERNALS__;
    if (internals?.invoke) {
      runtime.invokeFn = (command, args = {}) => internals.invoke(command, args);
      runtime.event = tauri?.event ?? null;
      runtime.ready = true;
      runtime.mode = "__TAURI_INTERNALS__";
      pushStatus(`Tauri bridge connected via __TAURI_INTERNALS__ (${globals.join(", ") || "no globals"})`);
      return;
    }
    if (tauri?.core?.invoke) {
      runtime.invokeFn = (command, args = {}) => tauri.core.invoke(command, args);
      runtime.event = tauri.event ?? null;
      runtime.ready = true;
      runtime.mode = "__TAURI__.core";
      pushStatus(`Tauri bridge connected via __TAURI__.core (${globals.join(", ") || "no globals"})`);
      return;
    }
    await sleep(80);
  }
  runtime.ready = false;
  runtime.mode = "none";
  pushStatus("Tauri bridge not found. Run app with `pnpm tauri:dev`", "warn");
}

async function invoke(command, args = {}) {
  if (!runtime.invokeFn) {
    throw new Error("Tauri invoke unavailable in this runtime");
  }
  try {
    return await runtime.invokeFn(command, args);
  } catch (error) {
    const message = getErrorMessage(error);
    out({ command, error: message }, "error");
    throw new Error(message);
  }
}

function optionalText(id) {
  const element = document.getElementById(id);
  const value = element?.value?.trim?.() ?? "";
  return value.length > 0 ? value : undefined;
}

function compactObject(input) {
  const output = {};
  for (const [key, value] of Object.entries(input)) {
    if (value !== undefined) {
      output[key] = value;
    }
  }
  return output;
}

function showRootView() {
  rootViewEl?.classList.remove("hidden");
  projectViewEl?.classList.add("hidden");
}

function showProjectView() {
  rootViewEl?.classList.add("hidden");
  projectViewEl?.classList.remove("hidden");
}

function updateTopInfo() {
  const dataRootEl = document.getElementById("dataRootDisplay");
  const projectCountEl = document.getElementById("projectCount");
  const projectTitleEl = document.getElementById("projectTitle");
  if (dataRootEl) {
    dataRootEl.textContent = state.settings?.dataRoot ?? "-";
  }
  if (projectCountEl) {
    projectCountEl.textContent = `${state.projects.length} project(s)`;
  }
  if (projectTitleEl) {
    projectTitleEl.textContent = state.currentProject?.name ?? "-";
  }
  if (!state.currentJobId && jobStatusEl) {
    jobStatusEl.textContent = "No active job";
  }
}

function fillSettingsForm(settings) {
  document.getElementById("dataRoot").value = settings.dataRoot ?? "";
  document.getElementById("realMode").checked = !settings.usePlaceholders;
  document.getElementById("audioCliPath").value = settings.toolPaths?.audioCli ?? "";
  document.getElementById("demucsPath").value = settings.toolPaths?.demucs ?? "";
  document.getElementById("omnizartPath").value = settings.toolPaths?.omnizart ?? "";
  document.getElementById("basicPitchPath").value = settings.toolPaths?.basicPitch ?? "";
  document.getElementById("musescorePath").value = settings.toolPaths?.musescore ?? "";
  document.getElementById("ytdlpPath").value = settings.toolPaths?.ytDlp ?? "";
}

function settingsPayloadFromForm() {
  const toolPaths = compactObject({
    audioCli: optionalText("audioCliPath"),
    demucs: optionalText("demucsPath"),
    omnizart: optionalText("omnizartPath"),
    basicPitch: optionalText("basicPitchPath"),
    musescore: optionalText("musescorePath"),
    ytDlp: optionalText("ytdlpPath")
  });

  return compactObject({
    dataRoot: optionalText("dataRoot"),
    usePlaceholders: !document.getElementById("realMode").checked,
    toolPaths: Object.keys(toolPaths).length > 0 ? toolPaths : undefined
  });
}

async function loadSettings() {
  state.settings = await invoke("get_settings");
  fillSettingsForm(state.settings);
  updateTopInfo();
}

async function saveSettings() {
  const settings = settingsPayloadFromForm();
  state.settings = await invoke("update_settings", { settings });
  fillSettingsForm(state.settings);
  updateTopInfo();
  out({ settings: state.settings });
}

function renderProjects() {
  updateTopInfo();
  if (!projectGridEl) {
    return;
  }
  if (state.projects.length === 0) {
    projectGridEl.innerHTML = '<p class="muted">No projects yet. Create one above.</p>';
    return;
  }

  const cards = state.projects
    .map(
      (project) => `
      <article class="project-card" data-project-id="${project.id}">
        <h3>${project.name}</h3>
        <p class="muted path">${project.rootPath}</p>
        <p class="muted">Updated: ${new Date(project.updatedAt).toLocaleString()}</p>
        <button class="btn open-project" data-project-id="${project.id}">Open</button>
      </article>
    `
    )
    .join("");

  projectGridEl.innerHTML = cards;
}

async function refreshProjects() {
  state.projects = await invoke("list_projects");
  renderProjects();
}

function currentProjectId() {
  if (!state.currentProject?.id) {
    throw new Error("No project selected");
  }
  return state.currentProject.id;
}

async function openProject(projectId) {
  const found = state.projects.find((project) => project.id === projectId);
  if (!found) {
    out(`Project not found: ${projectId}`, "warn");
    return;
  }
  state.currentProject = found;
  state.currentJobId = null;
  updateTopInfo();
  showProjectView();
  await refreshArtifacts();
  pushStatus(`Opened project ${projectId}`);
}

async function refreshArtifacts() {
  if (!state.currentProject) {
    artifactListEl.innerHTML = "";
    return;
  }
  const artifacts = await invoke("list_artifacts", { projectId: currentProjectId() });
  if (artifacts.length === 0) {
    artifactListEl.innerHTML = '<li class="muted">No artifacts yet.</li>';
    return;
  }

  artifactListEl.innerHTML = artifacts
    .map((artifact) => `<li><span class="tag">${artifact.kind}</span> <span>${artifact.path}</span></li>`)
    .join("");
}

function pipelineOptions() {
  return {
    allowPartialSuccess: document.getElementById("allowPartialSuccess").checked,
    transcribeGuitar: document.getElementById("transcribeGuitar").checked,
    transcribeOther: document.getElementById("transcribeOther").checked,
    usePlaceholders: !document.getElementById("realMode").checked
  };
}

function openSettingsModal() {
  settingsModalEl.classList.remove("hidden");
}

function closeSettingsModal() {
  settingsModalEl.classList.add("hidden");
}

function updateJobStatus(text) {
  if (jobStatusEl) {
    jobStatusEl.textContent = text;
  }
}

function stageLabel(stage) {
  switch ((stage ?? "").toLowerCase()) {
    case "queued":
      return "queued";
    case "preflight":
      return "dependency check";
    case "separate":
      return "separation";
    case "transcribe":
      return "transcription";
    case "export":
      return "musicxml export";
    case "done":
      return "completed";
    default:
      return stage || "unknown stage";
  }
}

function formatElapsedSeconds(startedAtMs) {
  if (!startedAtMs) {
    return "0s";
  }
  const seconds = Math.max(0, Math.floor((Date.now() - startedAtMs) / 1000));
  return `${seconds}s`;
}

function renderLiveJobText() {
  if (!pollState.jobId) {
    return;
  }
  const stageText = stageLabel(pollState.currentStage);
  const elapsed = formatElapsedSeconds(pollState.startedAtMs);
  const state = (pollState.currentState ?? "").toLowerCase();
  let text = `Job ${pollState.jobId.slice(0, 8)}: ${stageText} (${elapsed})`;

  if (state === "queued") {
    text = `Job ${pollState.jobId.slice(0, 8)}: queued (${elapsed})`;
  } else if (state === "running") {
    text = `Running ${stageText} (${elapsed})`;
  } else if (state === "completed") {
    text = `Completed in ${elapsed}`;
  } else if (state === "failed") {
    const reason = pollState.currentMessage || "unknown reason";
    text = `Failed at ${stageText} (${elapsed}): ${reason}`;
  } else if (state === "canceled") {
    text = `Canceled at ${stageText} (${elapsed})`;
  }

  updateJobStatus(text);
  if (statusHeadlineEl) {
    statusHeadlineEl.textContent = text;
  }
}

function startJobTicker() {
  if (pollState.ticker) {
    clearInterval(pollState.ticker);
  }
  pollState.ticker = setInterval(() => {
    renderLiveJobText();
  }, 1000);
}

function beginJobTracking(job) {
  pollState.jobId = job.id;
  const parsed = job.startedAt ? Date.parse(job.startedAt) : NaN;
  pollState.startedAtMs = Number.isFinite(parsed) ? parsed : Date.now();
  pollState.currentStage = job.stage ?? "queued";
  pollState.currentState = job.state ?? "queued";
  pollState.currentMessage = job.message ?? "";
  if (pollState.currentState === "queued" || pollState.currentState === "running") {
    startJobTicker();
  }
  renderLiveJobText();
}

function applyJobSnapshot(job, source = "poll") {
  if (!job?.id) {
    return;
  }
  if (pollState.jobId !== job.id) {
    beginJobTracking(job);
    pushStatus(`Job ${job.id.slice(0, 8)} started: ${stageLabel(job.stage)}`);
  }

  const previousStage = pollState.currentStage;
  const previousState = pollState.currentState;
  const previousMessage = pollState.currentMessage;
  pollState.currentStage = job.stage ?? pollState.currentStage;
  pollState.currentState = job.state ?? pollState.currentState;
  pollState.currentMessage = job.message ?? pollState.currentMessage;

  if (previousStage && previousStage !== pollState.currentStage) {
    pushStatus(`${stageLabel(previousStage)} done, starting ${stageLabel(pollState.currentStage)}`);
  }

  if (previousState !== pollState.currentState) {
    if (pollState.currentState === "failed") {
      const reason = pollState.currentMessage || "unknown reason";
      pushStatus(`Job failed in ${stageLabel(pollState.currentStage)}: ${reason}`, "error");
      out(`Job failed: ${reason}`, "error");
    } else if (pollState.currentState === "completed") {
      pushStatus("Job completed");
      out("Job completed");
    } else if (pollState.currentState === "canceled") {
      pushStatus("Job canceled", "warn");
      out("Job canceled", "warn");
    } else if (pollState.currentState === "running" && source === "state-event") {
      pushStatus(`Job running: ${stageLabel(pollState.currentStage)}`);
    }
  } else if (
    pollState.currentState === "failed" &&
    pollState.currentMessage &&
    pollState.currentMessage !== previousMessage
  ) {
    pushStatus(`Failure reason: ${pollState.currentMessage}`, "error");
    out(`Job failed: ${pollState.currentMessage}`, "error");
  }

  renderLiveJobText();
}

function stopJobPolling(resetSnapshot = true) {
  if (pollState.timer) {
    clearInterval(pollState.timer);
    pollState.timer = null;
  }
  if (pollState.ticker) {
    clearInterval(pollState.ticker);
    pollState.ticker = null;
  }
  pollState.lastSignature = "";
  if (resetSnapshot) {
    pollState.jobId = null;
    pollState.startedAtMs = 0;
    pollState.currentStage = "";
    pollState.currentState = "";
    pollState.currentMessage = "";
  }
}

function startJobPolling(jobId) {
  stopJobPolling();
  pollState.timer = setInterval(async () => {
    if (!state.currentJobId || state.currentJobId !== jobId) {
      stopJobPolling();
      return;
    }
    try {
      const job = await invoke("get_job", { jobId });
      const signature = `${job.state}|${job.stage}|${Math.round((job.progress ?? 0) * 100)}|${job.message ?? ""}`;
      if (signature !== pollState.lastSignature) {
        pollState.lastSignature = signature;
        applyJobSnapshot(job, "poll");
      }
      if (job.state === "completed" || job.state === "failed" || job.state === "canceled") {
        stopJobPolling(false);
        await refreshArtifacts();
      }
    } catch (error) {
      out({ pollingError: getErrorMessage(error) }, "warn");
    }
  }, 1200);
}

async function startPipelineOnly() {
  await saveSettings();
  const result = await invoke("start_pipeline", {
    projectId: currentProjectId(),
    options: pipelineOptions()
  });
  state.currentJobId = result.id;
  beginJobTracking(result);
  out(`Pipeline started: ${result.id.slice(0, 8)}`);
  if (!runtime.event?.listen) {
    startJobPolling(result.id);
  }
}

async function importYoutubeOnly() {
  await saveSettings();
  const url = optionalText("youtubeUrl");
  if (!url) {
    out("youtubeUrl is required", "warn");
    return;
  }
  const imported = await invoke("import_youtube", { projectId: currentProjectId(), url });
  out(imported);
  await refreshArtifacts();
}

async function importYoutubeAndRunPipeline() {
  await importYoutubeOnly();
  await startPipelineOnly();
}

async function importLocal() {
  const filePath = optionalText("localPath");
  if (!filePath) {
    out("localPath is required", "warn");
    return;
  }
  const result = await invoke("import_local", { projectId: currentProjectId(), filePath });
  out(result);
  await refreshArtifacts();
}

function bindClick(id, handler) {
  const element = document.getElementById(id);
  if (!element) {
    pushStatus(`Missing element #${id}`, "error");
    return;
  }
  element.addEventListener("click", () => {
    Promise.resolve(handler()).catch((error) => out({ action: id, error: getErrorMessage(error) }, "error"));
  });
}

function setupStatusDrawer() {
  bindClick("statusToggleBtn", async () => {
    const collapsed = statusDrawerEl.classList.toggle("collapsed");
    statusToggleBtnEl.setAttribute("aria-expanded", String(!collapsed));
  });

  bindClick("statusClearBtn", async () => {
    statusState.lines = [];
    statusOutputEl.textContent = "";
    pushStatus("Status log cleared");
  });
}

function setupEventListeners() {
  bindClick("refreshProjectsBtn", async () => {
    await refreshProjects();
  });

  bindClick("createProjectBtn", async () => {
    const name = optionalText("newProjectName");
    if (!name) {
      out("Project name is required", "warn");
      return;
    }
    const created = await invoke("create_project", { name });
    out(created);
    document.getElementById("newProjectName").value = "";
    await refreshProjects();
    await openProject(created.id);
  });

  if (projectGridEl) {
    projectGridEl.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }
      const trigger = target.closest("[data-project-id]");
      const projectId = trigger?.getAttribute("data-project-id");
      if (!projectId) {
        return;
      }
      openProject(projectId).catch((error) => out({ action: "openProject", error: getErrorMessage(error) }, "error"));
    });
  }

  bindClick("backToRootBtn", async () => {
    state.currentProject = null;
    state.currentJobId = null;
    stopJobPolling();
    updateTopInfo();
    showRootView();
    await refreshProjects();
  });

  bindClick("refreshArtifactsBtn", async () => {
    await refreshArtifacts();
  });

  bindClick("importLocalBtn", async () => {
    await importLocal();
  });

  bindClick("importYoutubeBtn", async () => {
    await importYoutubeOnly();
  });

  bindClick("runYoutubePipelineBtn", async () => {
    await importYoutubeAndRunPipeline();
  });

  bindClick("startPipelineBtn", async () => {
    await startPipelineOnly();
  });

  bindClick("cancelPipelineBtn", async () => {
    if (!state.currentJobId) {
      out("No running job id", "warn");
      return;
    }
    const canceled = await invoke("cancel_job", { jobId: state.currentJobId });
    out(`Cancel requested: ${state.currentJobId.slice(0, 8)}`);
    applyJobSnapshot(canceled, "poll");
    stopJobPolling();
  });

  bindClick("openSettingsBtn", async () => {
    openSettingsModal();
  });

  bindClick("openSettingsBtnProject", async () => {
    openSettingsModal();
  });

  bindClick("closeSettingsBtn", async () => {
    closeSettingsModal();
  });

  bindClick("closeSettingsBtnFooter", async () => {
    closeSettingsModal();
  });

  settingsModalEl.addEventListener("click", (event) => {
    if (event.target === settingsModalEl) {
      closeSettingsModal();
    }
  });

  bindClick("saveSettingsBtn", async () => {
    await saveSettings();
    closeSettingsModal();
    await refreshProjects();
    if (state.currentProject) {
      const refreshedCurrent = state.projects.find((project) => project.id === state.currentProject.id);
      if (refreshedCurrent) {
        state.currentProject = refreshedCurrent;
        updateTopInfo();
      } else {
        state.currentProject = null;
        state.currentJobId = null;
        stopJobPolling();
        showRootView();
        updateTopInfo();
        out("Current project no longer exists in new dataRoot", "warn");
      }
    }
  });

  if (runtime.event?.listen) {
    runtime.event.listen("job:progress", (event) => {
      const payload = event.payload;
      if (payload.jobId === state.currentJobId) {
        const signature = `${payload.stage}|${Math.round((payload.percent ?? 0) * 100)}|${payload.message ?? ""}`;
        if (signature !== pollState.lastSignature) {
          pollState.lastSignature = signature;
          pollState.currentStage = payload.stage ?? pollState.currentStage;
          pollState.currentState = "running";
          renderLiveJobText();
          if (payload.message) {
            pushStatus(`${stageLabel(payload.stage)}: ${payload.message}`);
          }
        }
      }
    });

    runtime.event.listen("job:log", (event) => {
      const payload = event.payload;
      if (payload?.jobId !== state.currentJobId) {
        return;
      }
      const level = payload.level === "error" ? "error" : payload.level === "warn" ? "warn" : "info";
      pushStatus(`${stageLabel(payload.stage)}: ${payload.line}`, level);
    });

    runtime.event.listen("job:state", (event) => {
      const payload = event.payload;
      if (payload.jobId === state.currentJobId) {
        const baseSnapshot = {
          id: payload.jobId,
          state: payload.state,
          stage: payload.stage,
          message: pollState.currentMessage,
          startedAt: pollState.startedAtMs ? new Date(pollState.startedAtMs).toISOString() : undefined
        };
        applyJobSnapshot(baseSnapshot, "state-event");
        if (payload.state === "completed" || payload.state === "failed" || payload.state === "canceled") {
          stopJobPolling(false);
          invoke("get_job", { jobId: payload.jobId })
            .then((job) => {
              applyJobSnapshot(job, "poll");
            })
            .catch((error) => {
              out(`Failed to query final job details: ${getErrorMessage(error)}`, "warn");
            });
          refreshArtifacts().catch((error) => out({ refreshArtifactsError: getErrorMessage(error) }, "error"));
        }
      }
    });
  } else {
    pushStatus("Event bridge unavailable, fallback to polling get_job", "warn");
  }
}

async function bootstrap() {
  setupStatusDrawer();
  await initTauriRuntime();
  setupEventListeners();

  if (!runtime.ready) {
    const dataRootEl = document.getElementById("dataRootDisplay");
    if (dataRootEl) {
      dataRootEl.textContent = "Tauri bridge unavailable (open via pnpm tauri:dev)";
    }
    return;
  }

  await loadSettings();
  await refreshProjects();
  showRootView();
  pushStatus(`Root page ready (bridge: ${runtime.mode})`);
}

bootstrap().catch((error) => out({ bootstrapError: getErrorMessage(error) }, "error"));
