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
      posts = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      if (request.method() === "POST") posts.push(request.url());
    });
    await page.goto(url);
    await page.locator(".job").first().click();
    const explorer = page.locator(".decision-explorer");
    await explorer.locator("summary").click();
    assert.equal(
      await explorer.locator(".explorer-objective strong").innerText(),
      "13",
    );
    assert.match(
      await explorer.locator(".explorer-constraint").first().innerText(),
      /8 ≤ 8[\s\S]*余量 0/,
    );
    assert.match(
      await explorer.locator(".explorer-constraint").nth(1).innerText(),
      /7 ≤ 8[\s\S]*余量 1/,
    );
    await explorer.locator('[data-decision-variable="x_A"]').fill("2");
    assert.equal(
      await explorer.locator(".explorer-objective strong").innerText(),
      "10",
    );
    await page.waitForTimeout(1600);
    assert.equal(
      await explorer.locator('[data-decision-variable="x_A"]').inputValue(),
      "2",
    );
    await explorer.locator('[data-decision-variable="x_A"]').fill("5");
    assert.equal(
      await explorer.locator(".explorer-objective strong").innerText(),
      "19",
    );
    assert.match(
      await explorer.locator(".explorer-constraint").first().innerText(),
      /12 ≤ 8[\s\S]*余量 -4/,
    );
    assert.equal(
      await page.locator(".objective-result strong").innerText(),
      "13",
    );
    assert.equal(
      await explorer.locator(".explorer-constraint.exceeded").count(),
      2,
    );
    if (process.env.LLM4OM_WEB_SCREENSHOTS)
      await page.screenshot({
        path: path.join(
          process.env.LLM4OM_WEB_SCREENSHOTS,
          "decision-desktop.png",
        ),
        fullPage: true,
      });
    await explorer.getByRole("button", { name: "恢复求解结果" }).click();
    assert.equal(
      await explorer.locator(".explorer-objective strong").innerText(),
      "13",
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
          "decision-mobile.png",
        ),
        fullPage: true,
      });
    assert.deepEqual(errors, []);
    assert.deepEqual(posts, []);
    console.log(
      "Decision explorer: actual saved13, changed10/19, constraint margins, reset, polling, mobile; zero POST/model/Solver calls.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
