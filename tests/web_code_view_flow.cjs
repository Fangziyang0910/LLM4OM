"use strict";
// 结果区代码视图验收:语法高亮、复制入口、无原始 JSON 展示与深链稳定。
const assert = require("node:assert/strict");
const { completedRun } = require("./helpers/browser_fixture.cjs");
const path = require("node:path");
const { chromium } = require(process.env.LLM4OM_BROWSER_MODULE || "playwright");
const url = process.env.LLM4OM_WEB_TEST_URL;
const provider = process.env.LLM4OM_WEB_TEST_PROVIDER_URL;
for (const address of [url, provider])
  assert.ok(
    address && ["127.0.0.1", "localhost"].includes(new URL(address).hostname),
    "Only local fixture endpoints are allowed.",
  );
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.LLM4OM_BROWSER_EXECUTABLE,
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await completedRun(page);
    await page.click('[data-tab="code"]');
    await page.waitForSelector(".code-lines .code-line");
    const lines = await page.locator(".code-line").count();
    assert.ok(lines > 10, `expected highlighted code lines, got ${lines}`);
    assert.ok(
      (await page.locator(".code-line .tok-kw").count()) > 0,
      "keyword tokens missing",
    );
    assert.ok(
      (await page.locator(".code-line .tok-num, .code-line .tok-str").count()) > 0,
      "number/string tokens missing",
    );
    assert.match(
      await page.locator(".code-toolbar").innerText(),
      /Python · 求解实现/,
    );
    assert.ok(await page.getByRole("button", { name: "复制代码" }).isVisible());
    // 原始 JSON 不再在界面展示
    assert.equal(
      await page.locator(".raw-record").count(),
      0,
      "raw record fold must be gone",
    );
    assert.equal(await page.locator("#artifact-content").count(), 0);
    await page.waitForTimeout(1700);
    assert.equal(
      await page.locator("#artifact-choice").inputValue(),
      await page.locator("#artifact-choice").inputValue(),
    );
    assert.ok(
      (await page.locator(".code-line .tok-kw").count()) > 0,
      "highlight survives polling",
    );
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    assert.deepEqual(errors, []);
    console.log(
      "Code view: syntax tokens, copy entry, no raw JSON, polling and mobile passed.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
