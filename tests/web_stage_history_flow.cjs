"use strict";
// 修正历史属于两阶段产物与建模过程，不再有独立的候选页。
const assert = require("node:assert/strict");
const { chromium } = require(process.env.LLM4OM_BROWSER_MODULE || "playwright");
const { completedRun } = require("./helpers/browser_fixture.cjs");

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.LLM4OM_BROWSER_EXECUTABLE, args: ["--no-sandbox"] });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const result = await completedRun(page, { descriptionSuffix: " need-repair" });
    assert.equal(result.bundle.selected_check_id, "002");
    assert.equal(await page.locator('[data-tab="candidates"], [data-tab="checks"]').count(), 0);

    await page.click('[data-tab="formulation"]');
    const history = page.locator(".stage-history");
    assert.match(await history.locator("h3").innerText(), /数学表述修正历史/);
    const versions = history.locator("li");
    assert.equal(await versions.count(), 2);
    assert.match(await versions.nth(0).innerText(), /第 1 版 · 检查 001[\s\S]*初始生成/);
    assert.match(await versions.nth(1).innerText(), /第 2 版 · 检查 002 · 最终选择[\s\S]*修正自检查 001：修正变量引用/);
    await versions.nth(0).getByRole("button").click();
    assert.equal(await page.locator("#artifact-choice").inputValue(), "checks/001/formulation.json");
    assert.equal(await versions.nth(0).getByRole("button").getAttribute("aria-pressed"), "true");
    await versions.nth(1).getByRole("button").click();
    await page.locator(".story-card").filter({ hasText: "数学表述已保存" }).first().locator(".story-head").click();
    assert.match(await page.locator("#artifact-choice").inputValue(), /^checks\/001\/formulation/);

    // 检查 001 在编译前失败，没有代码阶段产物，因此代码页没有修正历史。
    await page.click('[data-tab="code"]');
    assert.equal(await page.locator(".stage-history").count(), 0);
    await page.locator(".story-card").filter({ hasText: "公开检查" }).first().locator(".story-head").click();
    assert.equal(await page.locator(".tab.active").getAttribute("data-tab"), "code");
    assert.ok(await page.locator(".story-body .model-warning").first().isVisible());

    const titles = await page.locator("#method-timeline .story-card .step-content strong").allInnerTexts();
    assert.equal(titles.filter((title) => title === "公开检查").length, 2);
    assert.ok(titles.indexOf("最终选择") > titles.lastIndexOf("公开检查"));
    await page.getByText("选择依据", { exact: true }).click();
    assert.match(await page.locator("#method-timeline").innerText(), /最终选择[\s\S]*检查 002 · Selected 002/);
    assert.deepEqual(errors, []);
    console.log("Stage history and modeling process steps: passed");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
