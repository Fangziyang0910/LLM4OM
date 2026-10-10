"use strict";
const assert = require("node:assert/strict");
const { chromium } = require(process.env.LLM4OM_BROWSER_MODULE || "playwright");
const url = process.env.LLM4OM_WEB_TEST_URL;
const providerUrl = process.env.LLM4OM_WEB_TEST_PROVIDER_URL;
assert.ok(url && ["127.0.0.1", "localhost"].includes(new URL(url).hostname));
assert.ok(
  providerUrl &&
    ["127.0.0.1", "localhost"].includes(new URL(providerUrl).hostname),
);
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.LLM4OM_BROWSER_EXECUTABLE,
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 390, height: 844 },
    });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(url);
    await page.waitForFunction(
      () => document.querySelector("#method").options.length > 0,
    );
    await page.click("#doctor");
    await page.waitForSelector("#doctor-result strong");
    assert.match(
      await page.locator("#doctor-result").innerText(),
      /未请求网络检查/,
    );
    const before = await (
      await page.request.get(providerUrl + "/requests")
    ).json();
    assert.equal(before.metadata_gets, 0);
    await page.check("#check-connectivity");
    await page.click("#doctor");
    await page.waitForFunction(() =>
      document.querySelector("#doctor-result").textContent.includes("接口可达"),
    );
    assert.match(
      await page.locator("#doctor-result").innerText(),
      /该页目录包含此模型/,
    );
    const after = await (
      await page.request.get(providerUrl + "/requests")
    ).json();
    assert.equal(after.metadata_gets, 1);
    assert.equal(after.generation_posts, 0);
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    assert.deepEqual(errors, []);
    console.log(
      "Web doctor: default zero HTTP, explicit one modelsGET, readable availability, zero generation/jobs, mobile passed.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
