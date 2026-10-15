"use strict";
const { editorDialog, closeDialog } = require("./helpers/browser_fixture.cjs");
const assert = require("node:assert/strict");
const { chromium } = require(process.env.LLM4OM_BROWSER_MODULE || "playwright");
const url = process.env.LLM4OM_WEB_TEST_URL;
assert.ok(url && ["127.0.0.1", "localhost"].includes(new URL(url).hostname));

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.LLM4OM_BROWSER_EXECUTABLE, args: ["--no-sandbox"] });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    const job = { job_id: "d".repeat(32), run_id: "d".repeat(32), created_at: 1, status: "completed",
      description: "Natural-language fixture", method: "llm4om.methods.optitree", model: "fixture" };
    await page.route("**/api/jobs", route => route.fulfill({ json: { jobs: [job] } }));
    await page.route("**/api/jobs/*", route => route.fulfill({ json: { job, bundle: null, events: [], artifacts: [],
      versions: [{ run_id: job.run_id, status: "completed", parent_run_id: null, assisted: false }], latest_run_id: job.run_id,
      contents: { "formulation.json": { formulation_id: "native-fixture", representation_kind: "native_formulation",
        representation: { schema: "optitree/0.1.0", state: { mathematical_model: "maximize 3A + 2B\n2A + B <= 8", retrieved_type: "Production planning" } } } },
      data_previews: {}, budget_ledger: {}, saved_edits: {} } }));
    await page.goto(url);
    const bootstrap = await page.request.get(url + "/api/bootstrap").then(response => response.json());
    await editorDialog(page, "options");
    await page.waitForSelector("#method");
    assert.equal(await page.locator('#method option[value="llm4om.methods.optimus_inline"]').count(), 0);
    for (const method of ["direct", "feedback_repair", "optimus", "coe", "optitree", "or_llm_agent", "autoformulation"]) {
      await editorDialog(page, "options");
      await page.selectOption("#method", "llm4om.methods." + method);
      const config = JSON.parse(await page.locator("#config-json").inputValue());
      assert.ok(!("params_data_id" in config.method.config));
      assert.ok(!("labels_data_id" in config.method.config));
      const solvers = await page.locator("#solver option").evaluateAll(options => options.map(option => option.value));
      assert.deepEqual(solvers.slice().sort(), ["llm4om.solvers.gurobi", "llm4om.solvers.highs", "llm4om.solvers.ortools"]);
      await closeDialog(page);
      for (const solver of solvers) {
        await page.selectOption("#solver", solver);
        const selected = JSON.parse(await page.locator("#config-json").inputValue());
        assert.equal(selected.solver.plugin_id, solver);
        assert.equal(selected.model_backend.plugin_id, "llm4om.model_backends.pyomo_factory");
        const response = await page.request.post(url + "/api/doctor", {
          headers: { "X-LLM4OM-Token": bootstrap.token }, data: { config: selected, check_connectivity: false },
        });
        const report = await response.json();
        assert.equal(response.status(), 200, JSON.stringify({ method, solver, error: report.error }));
        assert.equal(report.preflight_ok, true, JSON.stringify({ method, solver, error: report.error }));
      }
    }
    await page.selectOption("#solver", "llm4om.solvers.ortools");
    assert.match(await page.locator("#solver option:checked").innerText(), /OR-Tools.*SCIP/);
    await page.locator("#open-history").click();
    await page.locator("#jobs button").click();
    await page.locator('[data-tab="formulation"]').click();
    await page.getByText("maximize 3A + 2B", { exact: false }).waitFor();
    await page.getByText("检索类型：Production planning", { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log("All seven method × three solver UI configurations pass real backend preflight; natural input and native Formulation rendering passed without model generation.");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
