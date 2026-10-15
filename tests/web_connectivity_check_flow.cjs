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
      () => document.querySelector("#method")?.options.length > 0,
    );
    await page.locator('#llm-model-list').waitFor();
    assert.match(await page.locator('#llm-model-list option:checked').innerText(), /Fixture Model v2.*fixture-model/);
    await page.selectOption('#llm-model-list', 'alternate-model');
    assert.equal(await page.locator('#model').inputValue(), 'alternate-model');
    await page.locator('#model').fill('manual-model-id');
    assert.equal(await page.locator('#llm-model-list').inputValue(), '');
    await page.selectOption('#llm-model-list', 'fixture-model');
    await page.click("#doctor");
    await page.waitForSelector("#doctor-result strong");
    assert.match(
      await page.locator("#doctor-result").innerText(),
      /未请求网络检查/,
    );
    const before = await (
      await page.request.get(providerUrl + "/requests")
    ).json();
    assert.equal(before.metadata_gets, 1);
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
    assert.equal(after.metadata_gets, 2);
    assert.equal(after.generation_posts, 0);
    await page.route('**/api/llm-models', route => route.fulfill({ status: 400, json: { error: { message: '目录暂不可用' } } }));
    await page.locator('#fetch-models').click();
    await page.waitForFunction(() => document.querySelector('#model-directory-status')?.textContent?.includes('目录暂不可用'));
    await page.locator('#model').fill('manual-after-failure');
    assert.equal(await page.locator('#model').inputValue(), 'manual-after-failure');
    await page.unroute('**/api/llm-models');
    let releaseOld, oldStarted;
    const oldGate = new Promise(resolve => { releaseOld = resolve; });
    const oldRequest = new Promise(resolve => { oldStarted = resolve; });
    await page.route('**/api/llm-models', async route => {
      if (route.request().postDataJSON().llm.config.base_url.includes('127.0.0.1')) {
        oldStarted();
        await oldGate;
        await route.fulfill({ json: { models: [{ id: 'old-model', name: 'Old Vendor Model' }] } });
      } else {
        assert.equal(route.request().headers()['x-llm4om-provider-key'], 'synthetic-google-directory-key');
        assert.ok(!route.request().postData().includes('synthetic-google-directory-key'));
        await route.fulfill({ json: { models: [{ id: 'new-model', name: 'New Vendor Model' }] } });
      }
    });
    await page.locator('#fetch-models').click();
    await oldRequest;
    await page.locator('#provider').selectOption('google');
    await page.locator('#llm-api-key').fill('synthetic-google-directory-key');
    await page.locator('#fetch-models').click();
    await page.locator('#llm-model-list option[value="new-model"]').waitFor({ state: 'attached' });
    const oldResponse = page.waitForResponse(response => response.url().endsWith('/api/llm-models') &&
      response.request().postDataJSON().llm.config.base_url.includes('127.0.0.1'));
    releaseOld();
    await oldResponse;
    await page.locator('#llm-model-list').selectOption('new-model');
    assert.equal(await page.locator('#model').inputValue(), 'new-model');
    assert.equal(await page.locator('#llm-model-list option[value="old-model"]').count(), 0);
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    assert.deepEqual(errors, []);
    console.log(
      "Automatic model directory, display name/API ID selection, manual fallback, stale-response isolation, explicit doctor and zero generation passed.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
