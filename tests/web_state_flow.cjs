"use strict";
const assert = require("node:assert/strict");
const { chromium } = require(process.env.LLM4OM_BROWSER_MODULE || "playwright");
const url = process.env.LLM4OM_WEB_TEST_URL;
assert.ok(url && ["127.0.0.1", "localhost"].includes(new URL(url).hostname));

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.LLM4OM_BROWSER_EXECUTABLE,
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    const jobs = ["a", "b"].map(letter => ({
      job_id: letter.repeat(32), created_at: 1, status: "completed", run_id: letter.repeat(32),
      description: `Problem ${letter}`, method: "llm4om.methods.direct", model: "fixture",
    }));
    const historicalRun = "c".repeat(32);
    const snapshot = (job, runId) => ({
      job: { ...job, run_id: runId || job.run_id }, bundle: null, events: [], artifacts: [], contents: {},
      versions: [job.run_id, historicalRun].map(run_id => ({ run_id, status: "completed", parent_run_id: null,
        operation: null, assisted: false, saved_at: 1 })),
      latest_run_id: job.run_id, historical: Boolean(runId), data_previews: {},
    });
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    let started;
    const delayed = new Promise(resolve => { started = resolve; });
    let hold = true;
    let fail = false;
    let failStarted, releaseFailure;
    const failureStarted = new Promise(resolve => { failStarted = resolve; });
    const failureGate = new Promise(resolve => { releaseFailure = resolve; });
    await page.route("**/api/jobs", route => route.fulfill({ json: { jobs } }));
    await page.route("**/api/jobs/*", async route => {
      const job = jobs.find(item => new URL(route.request().url()).pathname.endsWith(item.job_id));
      assert.ok(job);
      if (job === jobs[0] && fail) {
        failStarted();
        await failureGate;
        await route.fulfill({ status: 400, json: { error: { message: "late-old-run-error" } } });
        return;
      }
      if (job === jobs[0] && hold) { started(); await gate; }
      await route.fulfill({ json: snapshot(job, new URL(route.request().url()).searchParams.get("run_id")) });
    });
    await page.goto(url);
    await page.waitForFunction(() => document.querySelector("#model")?.value);
    await page.locator("#model").fill("edited-model");
    await page.locator("#solver").selectOption("llm4om.solvers.gurobi");
    assert.equal(await page.locator("#model").inputValue(), "edited-model");
    assert.equal(JSON.parse(await page.locator("#config-json").inputValue()).llm.model, "edited-model");
    await page.locator("details:has(#config-json) > summary").click();
    await page.locator("#config-json").fill("{}");
    await page.locator("#apply-config").click();
    assert.match(await page.locator("#notice").innerText(), /完整的运行配置/);
    assert.equal(await page.locator("#model").inputValue(), "edited-model");
    await page.locator("#solver").selectOption("llm4om.solvers.highs");
    assert.equal(await page.locator("#config-json").inputValue(), "{}");

    await page.locator("#jobs button").nth(0).click();
    await delayed;
    await page.locator("#jobs button").nth(1).click();
    await page.waitForFunction(id => window.snapshot?.job.job_id === id, jobs[1].job_id);
    hold = false;
    release();
    await page.waitForTimeout(200);
    assert.deepEqual(await page.evaluate(() => ({ selected: window.currentJob, shown: window.snapshot.job.job_id })),
      { selected: jobs[1].job_id, shown: jobs[1].job_id });
    await page.waitForTimeout(1700);
    assert.equal(await page.evaluate(() => window.snapshot.job.job_id), jobs[1].job_id);
    await page.locator("#run-version").selectOption(historicalRun);
    await page.waitForFunction(id => window.snapshot?.job.run_id === id, historicalRun);
    await page.locator('[data-tab="diagnostics"]').click();
    assert.equal(new URL(page.url()).searchParams.get("run"), historicalRun);
    assert.equal(new URL(page.url()).searchParams.get("tab"), "diagnostics");
    await page.reload();
    await page.waitForFunction(id => window.snapshot?.job.run_id === id, historicalRun);
    assert.equal(await page.locator(".tab.active").getAttribute("data-tab"), "diagnostics");
    fail = true;
    await page.locator("#jobs button").nth(0).click();
    await failureStarted;
    await page.locator("#jobs button").nth(1).click();
    await page.waitForFunction(id => window.snapshot?.job.job_id === id, jobs[1].job_id);
    releaseFailure();
    await page.waitForTimeout(200);
    assert.ok(!(await page.locator("#notice").innerText()).includes("late-old-run-error"));
    assert.deepEqual(errors, []);
    console.log("Configuration/draft edits survive selection; late responses, polling and historical links preserve the selected run.");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
