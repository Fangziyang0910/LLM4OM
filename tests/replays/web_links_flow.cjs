"use strict";
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
    await page.waitForSelector(".objective-result strong");
    assert.equal(
      await page.locator(".objective-result strong").innerText(),
      "7",
    );
    const latestLink = new URL(
      await page.locator("#run-link").getAttribute("href"),
    );
    assert.ok(latestLink.searchParams.get("run"));
    assert.equal(new URL(page.url()).searchParams.get("run"), null);
    const versions = await page.evaluate(async () => {
      const { jobs } = await (await fetch("/api/jobs")).json();
      const result = await (await fetch("/api/jobs/" + jobs[0].job_id)).json();
      return result.versions;
    });
    const original = versions.find((item) => !item.parent_run_id);
    await page.selectOption("#run-version", original.run_id);
    await page.waitForFunction(
      () =>
        document.querySelector(".objective-result strong")?.textContent ===
        "13",
    );
    await page.locator('[data-tab="code"]').click();
    await page.selectOption("#artifact-choice", "checks/001/model.py");
    const bookmark = page.url();
    assert.equal(new URL(bookmark).searchParams.get("run"), original.run_id);
    assert.equal(new URL(bookmark).searchParams.get("tab"), "code");
    assert.equal(
      new URL(bookmark).searchParams.get("artifact"),
      "checks/001/model.py",
    );
    await page.reload();
    await page.waitForSelector(".code-lines");
    assert.equal(
      await page.locator(".objective-result strong").innerText(),
      "13",
    );
    assert.equal(
      await page.locator("#run-version").inputValue(),
      original.run_id,
    );
    assert.equal(
      await page.locator("#artifact-choice").inputValue(),
      "checks/001/model.py",
    );
    assert.ok((await page.locator(".code-line").count()) > 0);
    assert.match(
      await page.locator("#export").getAttribute("href"),
      new RegExp(original.run_id),
    );
    await page.waitForTimeout(1600);
    assert.equal(
      new URL(page.url()).searchParams.get("artifact"),
      "checks/001/model.py",
    );
    await page.click("#new-run");
    assert.equal(new URL(page.url()).search, "");
    assert.equal(await page.locator("#editor").isVisible(), true);
    await page.goto(latestLink.href);
    await page.waitForSelector(".objective-result strong");
    assert.equal(
      await page.locator(".objective-result strong").innerText(),
      "7",
    );
    assert.equal(
      await page.locator("#run-version").inputValue(),
      latestLink.searchParams.get("run"),
    );
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    assert.deepEqual(errors, []);
    assert.deepEqual(posts, []);
    console.log(
      "Run links: latest7 permalink, original13/code bookmark after reload, selected export, polling, new problem and mobile; zero POST/model/Solver calls.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
