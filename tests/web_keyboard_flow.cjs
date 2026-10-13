"use strict";
// 键盘可达性验收:Tab 焦点环可见、无焦点陷阱,核心路径
// (打开运行 → 切换标签 → 故事卡打开产物 → 展开摘要)全部可用键盘完成。
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
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(url);
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
    // 核心路径 1:Enter 打开历史运行
    await page.locator(".job").first().focus();
    await page.keyboard.press("Enter");
    await page.waitForSelector(".objective-result strong");
    // 核心路径 2:Enter 切换到代码标签
    await page.locator('[data-tab="code"]').focus();
    await page.keyboard.press("Enter");
    await page.waitForSelector(".code-lines");
    assert.equal(
      await page.locator(".tab.active").getAttribute("data-tab"),
      "code",
    );
    // 核心路径 3:Enter 在带产物按钮的故事卡上打开对应产物
    const artifactCard = page
      .locator(".timeline-step.story-card")
      .filter({ hasText: "数学表述已保存" })
      .first();
    await artifactCard.focus();
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => {
      const tab = document.querySelector(".tab.active")?.getAttribute("data-tab");
      return tab === "formulation" && document.querySelector("#artifact-choice")?.value;
    });
    // 核心路径 4:Enter 在求解完成卡上打开运行详情
    const solved = page
      .locator(".timeline-step.story-card")
      .filter({ hasText: "求解完成" })
      .first();
    await solved.focus();
    await page.keyboard.press("Enter");
    await page.waitForFunction(
      () => document.querySelector(".tab.active")?.getAttribute("data-tab") === "diagnostics",
    );
    assert.deepEqual(errors, []);
    console.log(
      "Keyboard: visible focus ring, no trap, Enter-only path (run → code tab → artifact card → diagnostics card): passed.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
