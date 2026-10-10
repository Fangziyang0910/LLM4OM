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
      viewport: { width: 1440, height: 1000 },
    });
    const errors = [],
      mutations = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      if (request.method() === "POST") mutations.push(request.url());
    });
    await page.goto(url);
    await page.waitForFunction(
      () => !document.querySelector("#data-files").disabled,
    );
    const jobsBefore = await page.evaluate(
      async () => (await (await fetch("/api/jobs")).json()).jobs.length,
    );
    await page.locator("#data-files").setInputFiles([
      {
        name: "notes.csv",
        mimeType: "text/csv",
        buffer: Buffer.from(
          'label,note,amount\n"A, special","first\nsecond",003\n' +
            Array.from(
              { length: 24 },
              (_, index) =>
                `item${index},<img src=x onerror=alert(1)>,${index}\n`,
            ).join(""),
        ),
      },
      {
        name: "settings.json",
        mimeType: "application/json",
        buffer: Buffer.from(
          '{"capacity":8,"costs":[3,2],"enabled":false,"unknown":null}',
        ),
      },
    ]);
    await page.locator(".upload-preview").nth(1).waitFor();
    const uploadCards = page.locator(".upload-card");
    assert.deepEqual(
      await uploadCards.first().locator("th").allTextContents(),
      ["label", "note", "amount"],
    );
    assert.deepEqual(
      await uploadCards
        .first()
        .locator("tbody tr")
        .first()
        .locator("td")
        .allTextContents(),
      ["A, special", "first\nsecond", "003"],
    );
    assert.equal(await uploadCards.first().locator("tbody tr").count(), 20);
    assert.match(await uploadCards.first().innerText(), /20 \/ 25/);
    assert.equal(await uploadCards.locator("img").count(), 0);
    assert.deepEqual(
      await uploadCards
        .nth(1)
        .locator("tbody tr")
        .nth(2)
        .locator("td")
        .allTextContents(),
      ["enabled", "false"],
    );
    assert.deepEqual(
      await uploadCards
        .nth(1)
        .locator("tbody tr")
        .nth(3)
        .locator("td")
        .allTextContents(),
      ["unknown", "null"],
    );
    assert.equal(
      await page.evaluate(
        async () => (await (await fetch("/api/jobs")).json()).jobs.length,
      ),
      jobsBefore,
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
          "upload-mobile.png",
        ),
        fullPage: true,
      });
    await uploadCards
      .first()
      .getByRole("button", { name: "移除", exact: true })
      .click();
    assert.equal(await uploadCards.count(), 1);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.waitForSelector(".job");
    await page.locator(".job").first().click();
    await page.waitForSelector(".objective-result strong");
    await page.click('[data-tab="data"]');
    const products = page
      .locator(".model-card")
      .filter({ has: page.locator("h3", { hasText: /^products$/ }) });
    await products.waitFor();
    assert.deepEqual(
      await products.locator("table").first().locator("th").allTextContents(),
      ["product_id", "profit", "cutting", "finishing"],
    );
    assert.deepEqual(
      await products
        .locator("tbody tr")
        .first()
        .locator("td")
        .allTextContents(),
      ["A", "3", "2", "1"],
    );
    assert.deepEqual(
      await products.locator("tbody tr").nth(1).locator("td").allTextContents(),
      ["B", "2", "1", "2"],
    );
    assert.match(
      await products.locator(".data-view-meta").innerText(),
      /完整模型数据视图/,
    );
    assert.match(
      await products.locator(".data-view-meta").innerText(),
      /原始 2 行 · 视图 2 行/,
    );
    await products.locator("summary").click();
    assert.match(
      await products.locator(".data-provenance").innerText(),
      /74ad23f699830b8bbf6d32948c9ff9209fc39ff9ddbaa5c64c97140850249064/,
    );
    const capacities = page
      .locator(".model-card")
      .filter({ has: page.locator("h3", { hasText: /^capacities$/ }) });
    assert.deepEqual(
      await capacities
        .locator("tbody tr")
        .first()
        .locator("td")
        .allTextContents(),
      ["cutting", "8"],
    );
    assert.equal(
      await page
        .locator("#artifact-content")
        .locator("..")
        .getAttribute("open"),
      null,
    );
    if (process.env.LLM4OM_WEB_SCREENSHOTS)
      await page.screenshot({
        path: path.join(process.env.LLM4OM_WEB_SCREENSHOTS, "model-data.png"),
        fullPage: true,
      });
    await page.waitForTimeout(1600);
    assert.equal(
      await page.locator(".tab.active").getAttribute("data-tab"),
      "data",
    );
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    assert.deepEqual(errors, []);
    assert.deepEqual(
      mutations.map((address) => new URL(address).pathname),
      ["/api/data-preview", "/api/data-preview"],
    );
    console.log(
      "Upload CSV/JSON previews and saved tables, bounded display, safe text/values, no new jobs, polling and mobile: passed; only two local preview POSTs, zero model/Solver calls.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
