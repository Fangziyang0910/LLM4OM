"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(process.env.LLM4OM_BROWSER_MODULE || "playwright");
const url = process.env.LLM4OM_WEB_TEST_URL;
const workspace = process.env.LLM4OM_WEB_TEST_WORKSPACE;
assert.ok(url && ["127.0.0.1", "localhost"].includes(new URL(url).hostname));
assert.ok(workspace, "Use a disposable guidance workspace after web_story_flow.");
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.LLM4OM_BROWSER_EXECUTABLE,
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1100 },
    });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(url);
    await page.locator(".job").first().click();
    await page.waitForSelector(".objective-result strong");
    const before = await page.evaluate(async () => {
      const { jobs } = await (await fetch("/api/jobs")).json();
      return (await fetch("/api/jobs/" + jobs[0].job_id)).json();
    });
    const parent = path.join(
      workspace,
      before.job.job_id,
      "runs",
      before.job.run_id,
      "bundle.json",
    );
    const bytes = fs.readFileSync(parent);
    await page.click("#edit-run");
    await page.selectOption("#edit-operation", "formulation");
    await page.getByLabel("qty_A · 上界", { exact: true }).waitFor();
    assert.equal(
      await page.locator("#revision-advanced").getAttribute("open"),
      null,
    );
    for (const [label, value] of [
      ["qty_A · 上界", "1"],
      ["qty_B · 上界", "1"],
      ["目标 · 常数", "1"],
      ["目标 · A 系数", "4"],
      ["capacity_cutting · 右侧值", "3"],
      ["capacity_finishing · 右侧值", "3"],
      ["候选总上限", "2"],
      ["求解次数总上限", "2"],
    ])
      await page.getByLabel(label, { exact: true }).fill(value);
    await page
      .getByLabel("修改原因", { exact: true })
      .fill("调整已有数值，并新增 qty_A ≤ 0 约束，检查普通表单的结构修订。");
    await page
      .getByRole("button", { name: "＋ 添加约束", exact: true })
      .click();
    await page.getByLabel("C_USER_1 · A 系数", { exact: true }).fill("1");
    await page
      .getByRole("button", { name: "＋ 添加约束", exact: true })
      .click();
    await page
      .getByRole("button", { name: "移除约束 C_USER_2", exact: true })
      .click();
    await page.waitForFunction(() => {
      const draft = JSON.parse(document.querySelector("#assisted-document").value);
      return draft.structured_ir.constraints.length === 3;
    });
    assert.match(
      await page.locator(".revision-field").filter({ hasText: "修改原因" }).locator("textarea").inputValue(),
      /新增/,
    );
    const draft = JSON.parse(
      await page.locator("#assisted-document").inputValue(),
    );
    assert.equal(draft.structured_ir.variables[0].upper_bound, 1);
    assert.equal(draft.formulation.representation.variables[0].upper_bound, 1);
    assert.match(
      draft.formulation.representation.objective.expression_text,
      /4\*qty_A/,
    );
    assert.match(
      draft.formulation.representation.constraints[0].expression_text,
      /<= 3$/,
    );
    assert.deepEqual(
      draft.structured_ir.constraints.map((item) => item.id),
      ["capacity_cutting", "capacity_finishing", "C_USER_1"],
    );
    assert.match(
      draft.formulation.representation.constraints.at(-1).expression_text,
      /1\*qty_A.*<= 0$/,
    );
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    if (process.env.LLM4OM_WEB_SCREENSHOTS)
      await page.screenshot({
        path: path.join(
          process.env.LLM4OM_WEB_SCREENSHOTS,
          "model-editor-mobile.png",
        ),
        fullPage: true,
      });
    await page.setViewportSize({ width: 1440, height: 1100 });
    if (process.env.LLM4OM_WEB_SCREENSHOTS)
      await page.screenshot({
        path: path.join(
          process.env.LLM4OM_WEB_SCREENSHOTS,
          "model-editor-desktop.png",
        ),
        fullPage: true,
      });
    await page.click("#submit-edit");
    await page.waitForFunction(
      async ({ id, run }) => {
        const response = await fetch("/api/jobs/" + id);
        const result = await response.json();
        return (
          result.job.run_id !== run &&
          result.job.status === "completed" &&
          result.bundle?.assisted
        );
      },
      { id: before.job.job_id, run: before.job.run_id },
      { timeout: 40000, polling: 500 },
    );
    await page.waitForFunction(
      () =>
        document.querySelector(".objective-result strong")?.textContent === "3",
      null,
      { timeout: 20000 },
    );
    assert.deepEqual(fs.readFileSync(parent), bytes);
    const after = await page.evaluate(
      async (id) => (await fetch("/api/jobs/" + id)).json(),
      before.job.job_id,
    );
    assert.notEqual(after.job.run_id, before.job.run_id);
    assert.equal(
      after.contents["budget-ledger.json"].external_llm_requests,
      before.contents["budget-ledger.json"].external_llm_requests,
    );
    assert.equal(
      after.contents["budget-ledger.json"].solver_calls,
      before.contents["budget-ledger.json"].solver_calls + 1,
    );
    assert.deepEqual(errors, []);
    console.log(
      "Readable strictIR constraint add/remove → real container HiGHS3, synchronized Formulation, preserved edits/reason, immutable parent13, assisted result, zero new model requests, mobile passed.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
