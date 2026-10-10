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
    await page.locator('[data-tab="candidates"]').click();
    assert.equal(await page.locator(".candidate-card").count(), 2);
    assert.match(
      await page.locator('[data-candidate-id="001"]').innerText(),
      /未通过检查/,
    );
    const selected = page.locator('[data-candidate-id="002"]');
    assert.match(await selected.innerText(), /最终选择[\s\S]*修正自 001/);
    assert.match(
      await selected.locator(".candidate-result").innerText(),
      /候选目标 13/,
    );
    assert.match(
      await page.locator(".candidate-selection").innerText(),
      /Selected 002/,
    );
    await selected.locator(".candidate-changes summary").click();
    assert.match(
      await selected.locator(".candidate-changes").innerText(),
      /R-CUTTING[\s\S]*R-FINISHING/,
    );
    await page.waitForTimeout(1600);
    assert.equal(
      await selected.locator(".candidate-changes").getAttribute("open"),
      "",
    );
    if (process.env.LLM4OM_WEB_SCREENSHOTS)
      await page.screenshot({
        path: path.join(
          process.env.LLM4OM_WEB_SCREENSHOTS,
          "candidates-desktop.png",
        ),
        fullPage: true,
      });
    await selected.getByRole("button", { name: "查看数学模型" }).click();
    assert.equal(
      await page.locator("#artifact-choice").inputValue(),
      "candidates/002/formulation.json",
    );
    assert.equal(await page.locator(".variable-card").count(), 2);
    await page.locator('[data-tab="candidates"]').click();
    await page.selectOption(
      "#artifact-choice",
      "candidates/001/assessment.json",
    );
    assert.equal(await page.locator(".candidate-card").count(), 2);
    await selected.getByRole("button", { name: "查看求解代码" }).click();
    assert.equal(
      await page.locator("#artifact-choice").inputValue(),
      "candidates/002/model.py",
    );
    assert.ok((await page.locator(".code-line").count()) > 0);
    await page.locator('[data-tab="candidates"]').click();
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
          "candidates-mobile.png",
        ),
        fullPage: true,
      });
    const referenceCheck = await page.evaluate(async () => {
      const { jobs } = await (await fetch("/api/jobs")).json();
      const snapshot = await (
        await fetch("/api/jobs/" + jobs[0].job_id)
      ).json();
      const reference = snapshot.bundle.model_artifact_ref;
      return {
        completed: UI.artifactKey(snapshot, reference),
        progress: UI.artifactKey({ ...snapshot, bundle: null }, reference),
        mismatch: UI.artifactKey(snapshot, {
          ...reference,
          sha256: "0".repeat(64),
        }),
      };
    });
    assert.equal(referenceCheck.completed, "candidates/002/artifact.json");
    assert.equal(referenceCheck.progress, "candidates/002/artifact.json");
    assert.equal(referenceCheck.mismatch, undefined);
    assert.deepEqual(errors, []);
    assert.deepEqual(posts, []);
    console.log(
      "Saved real repair: two candidates, final selection, changes, model/code navigation, full-list isolation, polling and mobile; zero POST/model/Solver calls.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
