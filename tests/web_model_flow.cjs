"use strict";
const assert = require("node:assert/strict");
const { completedRun } = require("./helpers/browser_fixture.cjs");
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
    await completedRun(page);
    const profit = page
      .locator(".requirement-link")
      .filter({ hasText: "R-PROFIT" })
      .first();
    await profit.locator("summary").click();
    assert.match(await profit.innerText(), /最大化按单位利润计算的总利润/);
    const domain = page
      .locator(".requirement-link")
      .filter({ hasText: "R-DOMAIN" })
      .first();
    await domain.locator("summary").click();
    assert.match(await domain.innerText(), /非负整数/);
    await page.waitForTimeout(1600);
    assert.equal(await profit.getAttribute("open"), "");
    await page.selectOption(
      "#artifact-choice",
      "checks/001/formulation-snapshot.json",
    );
    assert.match(
      await page.locator("#model-view .objective-card").innerText(),
      /3/,
    );
    assert.equal(await page.locator("#model-view .variable-card").count(), 2);
    const coverage = page.locator(".model-coverage");
    await coverage.locator("summary").click();
    await page.locator(".model-notes summary").click();
    assert.match(await coverage.innerText(), /R-FINISHING/);
    assert.match(await coverage.innerText(), /方法声明/);
    assert.match(
      await page.locator("#model-view").innerText(),
      /未记录模型假设/,
    );
    if (process.env.LLM4OM_WEB_SCREENSHOTS)
      await page.screenshot({
        path: path.join(
          process.env.LLM4OM_WEB_SCREENSHOTS,
          "model-requirements.png",
        ),
        fullPage: true,
      });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    const fixture = await page.evaluate(() => {
      const host = document.createElement("div");
      document.body.append(host);
      const formulation = {
        formulation_id: "f1",
        representation: {
          variables: [{ id: "x", domain: "integer" }],
          objective: {
            sense: "max",
            expression_text: "x",
            requirement_ids: ["R-MISSING"],
          },
          constraints: [],
        },
      };
      const metadata = {
        formulation_ref: { artifact_id: "f1" },
        assumptions: [
          {
            id: "A1",
            text: "<img src=x onerror=alert(1)>",
            origin: "model",
            status: "proposed",
          },
        ],
        warnings: ["review this model"],
        requirement_traces: [],
      };
      UI.records(host, formulation, "formulation", {
        "public-problem.json": {
          requirements: [{ id: "R-UNMAPPED", text: "Unmapped rule." }],
        },
        "checks/002/artifact.json": {
          formulation_ref: { artifact_id: "f2" },
          assumptions: [],
          warnings: ["OTHER-CANDIDATE"],
        },
        "checks/001/artifact.json": metadata,
      });
      host.querySelector(".model-coverage").open = true;
      const result = {
        text: host.innerText,
        images: host.querySelectorAll("img").length,
      };
      UI.records(
        host,
        {
          formulation_ref: null,
          assumptions: [],
          warnings: ["public_reflection_exhausted"],
          requirement_traces: [],
        },
        "formulation",
        {
          "checks/002/structured-ir.json": {
            objective: { expression: { terms: [] } },
            variables: [{ id: "OTHER" }],
          },
        },
      );
      result.nativeText = host.innerText;
      host.remove();
      return result;
    });
    assert.match(fixture.text, /待确认/);
    assert.match(fixture.text, /review this model/);
    assert.match(fixture.text, /原问题未声明此需求/);
    assert.match(fixture.text, /未记录关联/);
    assert.ok(!fixture.text.includes("OTHER-CANDIDATE"));
    assert.equal(fixture.images, 0);
    assert.match(fixture.nativeText, /没有独立的数学表述/);
    assert.match(fixture.nativeText, /公开检查/);
    assert.deepEqual(errors, []);
    assert.deepEqual(mutations, []);
    console.log(
      "Actual requirement disclosures and mobile layout; UI fixture assumptions/warnings/missing mappings/candidate isolation/native availability/safe text: passed; read-only view after independent local fixture setup.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
