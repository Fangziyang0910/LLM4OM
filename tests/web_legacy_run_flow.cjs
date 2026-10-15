"use strict";
// 早于 ADR-0006 保存的候选布局运行仍可只读浏览。
const assert = require("node:assert/strict");
const { chromium } = require(process.env.LLM4OM_BROWSER_MODULE || "playwright");
const { completedRun } = require("./helpers/browser_fixture.cjs");

const legacy = [
  ['"checks/', '"candidates/'],
  ["/record-snapshot.json", "/candidate-snapshot.json"],
  ["/record.json", "/candidate.json"],
  ["/check.json", "/assessment.json"],
  ['"selection.json"', '"candidate-selection.json"'],
  ['"selected_check_id"', '"final_candidate_id"'],
  ['"check_id"', '"candidate_id"'],
  ['"check_ref"', '"assessment_ref"'],
  ['"check_finished"', '"candidate_assessed"'],
  ['"checks":', '"candidates":'],
  ['"max_checks"', '"max_candidates"'],
];

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.LLM4OM_BROWSER_EXECUTABLE, args: ["--no-sandbox"] });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const result = await completedRun(page, { descriptionSuffix: " need-repair" });
    await page.route(new RegExp("/api/jobs/" + result.job.job_id + "(\\?|$)"), async (route) => {
      const response = await route.fetch();
      const value = await response.json();
      value.events = value.events.filter((event) => event.kind !== "selection_saved");
      let text = JSON.stringify(value);
      for (const [current, earlier] of legacy) text = text.split(current).join(earlier);
      assert.ok(text.includes('"final_candidate_id"') && !text.includes('"checks/'));
      await route.fulfill({ response, body: text, headers: { ...response.headers(), "content-type": "application/json" } });
    });
    await page.reload();
    await page.waitForSelector(".objective-result strong");
    assert.equal(await page.locator(".objective-result strong").innerText(), "13");
    await page.click('[data-tab="formulation"]');
    const versions = page.locator(".stage-history li");
    assert.equal(await versions.count(), 2);
    assert.match(await versions.nth(1).innerText(), /第 2 版 · 检查 002 · 最终选择[\s\S]*修正自检查 001/);
    await page.locator("#toggle-process").click();
    const titles = await page.locator("#method-timeline .story-card .step-content strong").allInnerTexts();
    assert.equal(titles.filter((title) => title === "公开检查").length, 2);
    assert.deepEqual(errors, []);
    console.log("Legacy candidate-layout run renders through the current views: passed");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
