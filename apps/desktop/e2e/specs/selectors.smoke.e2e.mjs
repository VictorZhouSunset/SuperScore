import assert from "node:assert/strict";

describe("SuperScore desktop smoke selectors", () => {
  it("shows stable hooks for the real pipeline flow", async () => {
    await browser.waitUntil(async () => (await $('[data-testid="project-grid"]').isExisting()) === true, {
      timeout: 10000,
      interval: 250,
      timeoutMsg: "project-grid did not appear in the SuperScore window"
    });

    assert.equal(await $('[data-testid="project-grid"]').isExisting(), true);
    assert.equal(await $('[data-testid="open-settings-root"]').isExisting(), true);
    assert.equal(await $('[data-testid="open-settings-project"]').isExisting(), true);
    assert.equal(await $('[data-testid="start-pipeline"]').isExisting(), true);
    assert.equal(await $('[data-testid="real-mode-toggle"]').isExisting(), true);
    assert.equal(await $('[data-testid="job-status"]').isExisting(), true);
    assert.equal(await $('[data-testid="artifact-list"]').isExisting(), true);
    assert.equal(await $('[data-testid="output-log"]').isExisting(), true);
  });
});
