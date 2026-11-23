export const SELECTORS = {
  projectGrid: '[data-testid="project-grid"]',
  openProject: (projectId) => `button.open-project[data-project-id="${projectId}"]`,
  openSettingsRoot: '[data-testid="open-settings-root"]',
  settingsModal: "#settingsModal",
  saveSettings: "#saveSettingsBtn",
  realModeToggle: '[data-testid="real-mode-toggle"]',
  startPipeline: '[data-testid="start-pipeline"]',
  jobStatus: '[data-testid="job-status"]',
  artifactList: '[data-testid="artifact-list"]',
  outputLog: '[data-testid="output-log"]',
  projectTitle: "#projectTitle"
};
