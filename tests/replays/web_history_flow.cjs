"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
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
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1100 },
    });
    const errors = [],
      mutations = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      if (request.method() === "POST") mutations.push(request.url());
    });
    await page.goto(url);
    await page.waitForSelector(".job");
    await page.locator(".job").first().click();
    await page.waitForSelector(".objective-result strong");
    const versions = await page.evaluate(() => snapshot.versions);
    assert.equal(versions.length, 2);
    const original = versions.find((version) => !version.parent_run_id);
    const child = versions.find(
      (version) => version.parent_run_id === original.run_id,
    );
    assert.equal(
      await page.locator(".objective-result strong").innerText(),
      "5",
    );
    await page.selectOption("#run-version", original.run_id);
    await page.waitForFunction(
      (id) => snapshot?.job?.run_id === id,
      original.run_id,
    );
    assert.equal(
      await page.locator(".objective-result strong").innerText(),
      "13",
    );
    assert.equal(await page.locator("#rerun").isVisible(), false);
    assert.match(
      await page.locator("#export").getAttribute("href"),
      new RegExp(original.run_id),
    );
    await page.click("#edit-run");
    await page.waitForSelector(".source-editor");
    await page.selectOption("#edit-operation", "problem");
    await page.waitForFunction(() =>
      document
        .querySelector("#revision-fields")
        .textContent.includes("完整问题描述"),
    );
    assert.equal(await page.evaluate(() => editParent.run), original.run_id);
    assert.match(
      await page.locator(".revision-summary").innerText(),
      /重新调用/,
    );
    await page.waitForTimeout(1600);
    assert.equal(
      await page.locator("#run-version").inputValue(),
      original.run_id,
    );
    if (process.env.LLM4OM_WEB_SCREENSHOTS)
      await page.screenshot({
        path: path.join(
          process.env.LLM4OM_WEB_SCREENSHOTS,
          "historical-parent.png",
        ),
        fullPage: true,
      });
    await page.selectOption("#run-version", child.run_id);
    await page.waitForFunction(
      (id) => snapshot?.job?.run_id === id,
      child.run_id,
    );
    assert.equal(await page.locator("#assisted-editor").isVisible(), false);
    assert.equal(
      await page.locator(".objective-result strong").innerText(),
      "5",
    );
    await page.selectOption("#run-version", "");
    await page.waitForFunction(
      () => snapshot && !selectedRun && !snapshot.historical,
    );
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    assert.deepEqual(errors, []);
    assert.deepEqual(mutations, []);
    console.log(
      "Historical13/current5, exact parent editor/export, polling selection, mobile layout: passed; zero POST/model calls.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
