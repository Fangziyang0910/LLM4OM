"use strict";
// 键盘可达性验收:Tab 焦点环可见、无焦点陷阱,核心路径
// (打开运行 → 切换标签 → 故事卡打开产物 → 展开摘要)全部可用键盘完成。
const assert = require("node:assert/strict");
const { completedRun } = require("./helpers/browser_fixture.cjs");
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
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const seeded = await completedRun(page);
    await page.goto(url);
    await page.waitForSelector("#description");
    const focusable = await page.evaluate(() =>
      [...document.querySelectorAll('button,[href],input,select,textarea,[tabindex="0"]')]
        .filter((el) => el.offsetParent !== null && !el.disabled)
        .map((el) => el.tagName + (el.id ? "#" + el.id : el.className ? "." + String(el.className).split(" ")[0] : "")),
    );
    assert.ok(focusable.length >= 10, "应有充分的可聚焦控件: " + focusable.join(","));
    // Tab 进入页面后焦点环可见(全局 :focus-visible)
    await page.keyboard.press("Tab");
    const ring = await page.evaluate(() => {
      const el = document.activeElement;
      const style = getComputedStyle(el);
      return { tag: el.tagName, outline: style.outlineStyle, width: style.outlineWidth };
    });
    assert.ok(ring.tag !== "BODY", "Tab 后焦点应落在控件上");
    assert.notEqual(ring.outline, "none");
    assert.ok(parseFloat(ring.width) >= 2, "焦点环宽度应可见");
    // 无焦点陷阱:连按 Tab 可持续移动并回到起点
    const seen = new Set();
    for (let i = 0; i < 40; i += 1) {
      await page.keyboard.press("Tab");
      seen.add(await page.evaluate(() => document.activeElement?.tagName || ""));
    }
    assert.ok(seen.size >= 2, "Tab 应能移动焦点,而不是被拦截");
    // 原生弹窗限制 Tab 在窗口内，Escape 关闭并恢复触发按钮焦点。
    await page.locator("#choose-model").focus();
    await page.keyboard.press("Enter");
    await page.getByRole("dialog", { name: "选择模型", exact: true }).waitFor();
    for (let i = 0; i < 20; i++) {
      await page.keyboard.press("Tab");
      // Chrome also visits browser chrome (reported as BODY); background controls stay inert.
      assert.equal(await page.evaluate(() => document.activeElement === document.body ||
        Boolean(document.activeElement.closest("dialog:modal"))), true);
    }
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("dialog[open]").count(), 0);
    assert.equal(await page.evaluate(() => document.activeElement.id), "choose-model");
    // 核心路径 1:Enter 打开历史运行
    await page.locator("#open-history").focus();
    await page.keyboard.press("Enter");
    await page.locator(`[data-job-id="${seeded.job.job_id}"]`).focus();
    await page.keyboard.press("Enter");
    await page.waitForSelector(".objective-result strong");
    await page.getByLabel("更多运行操作").click();
    await page.locator("#edit-run").click();
    await page.getByRole("dialog", { name: "编辑新版本", exact: true }).waitFor();
    assert.equal(await page.locator(".run-tools").getAttribute("open"), null);
    await page.keyboard.press("Escape");
    assert.equal(await page.evaluate(() => document.activeElement.getAttribute("aria-label")), "更多运行操作");
    // 核心路径 2:Enter 切换到代码标签
    await page.locator('[data-tab="code"]').focus();
    await page.keyboard.press("Enter");
    await page.waitForSelector(".code-lines");
    assert.equal(
      await page.locator(".tab.active").getAttribute("data-tab"),
      "code",
    );
    await page.keyboard.press("ArrowRight");
    assert.equal(await page.getByRole("tab", { name: "求解结果" }).getAttribute("aria-selected"), "true");
    assert.equal(await page.locator(".decision-row").count(), 2);
    await page.keyboard.press("End");
    assert.equal(await page.locator(".tab.active").getAttribute("data-tab"), "code");
    await page.keyboard.press("Home");
    assert.equal(await page.locator(".tab.active").getAttribute("data-tab"), "result");
    // 核心路径 3:Enter 在带产物按钮的故事卡上打开对应产物
    await page.locator("#toggle-process").click();
    const artifactCard = page
      .locator(".timeline-step.story-card")
      .filter({ hasText: "数学表述已保存" })
      .first();
    await artifactCard.locator(".story-head").focus();
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => {
      const tab = document.querySelector(".tab.active")?.getAttribute("data-tab");
      return tab === "formulation" && document.querySelector("#artifact-choice")?.value;
    });
    // 核心路径 4:Enter 在求解完成卡上打开结果
    await page.locator("#toggle-process").click();
    const solved = page
      .locator(".timeline-step.story-card")
      .filter({ hasText: "求解完成" })
      .first();
    await solved.locator(".story-head").focus();
    await page.keyboard.press("Enter");
    await page.waitForFunction(
      () => document.querySelector(".tab.active")?.getAttribute("data-tab") === "result",
    );
    assert.deepEqual(errors, []);
    console.log(
      "Keyboard: visible focus ring, no trap, arrow/Home/End tab navigation and Enter artifact/result navigation: passed.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
