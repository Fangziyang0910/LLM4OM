"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(process.env.LLM4OM_BROWSER_MODULE || "playwright");
const url = process.env.LLM4OM_WEB_TEST_URL,
  workspace = process.env.LLM4OM_WEB_TEST_WORKSPACE;
assert.ok(url && ["127.0.0.1", "localhost"].includes(new URL(url).hostname));
assert.ok(workspace, "Use a disposable workspace with a copied completed run.");
(async () => {
  const b = await chromium.launch({
    headless: true,
    executablePath: process.env.LLM4OM_BROWSER_EXECUTABLE,
    args: ["--no-sandbox"],
  });
  try {
    const p = await b.newPage({ viewport: { width: 1440, height: 1100 } });
    const errors = [];
    p.on("pageerror", (e) => errors.push(e.message));
    await p.goto(url);
    await p.waitForSelector(".job");
    await p.locator(".job").first().click();
    await p.waitForSelector(".objective-result strong");
    const before = await p.evaluate(() => ({
      job: currentJob,
      run: snapshot.job.run_id,
      ledger: snapshot.contents["budget-ledger.json"],
    }));
    const parent = path.join(
        workspace,
        before.job,
        "runs",
        before.run,
        "bundle.json",
      ),
      bytes = fs.readFileSync(parent);
    await p.click("#edit-run");
    await p.waitForSelector(".source-editor");
    assert.equal(
      await p.locator("#revision-advanced").getAttribute("open"),
      null,
    );
    await p.click("#submit-edit");
    await p.waitForFunction(() =>
      document.querySelector("#notice").textContent.includes("修改原因"),
    );
    assert.match(await p.locator("#notice").innerText(), /修改原因/);
    await p.selectOption("#edit-operation", "problem");
    await p.waitForFunction(() =>
      document
        .querySelector("#revision-fields")
        .textContent.includes("完整问题描述"),
    );
    assert.match(await p.locator(".revision-summary").innerText(), /重新调用/);
    const problem = JSON.parse(
      await p.locator("#assisted-document").inputValue(),
    );
    assert.notEqual(problem.problem.revision, "1");
    await p.selectOption("#edit-operation", "code");
    await p.waitForSelector(".source-editor");
    const source = await p.locator(".source-editor").inputValue();
    assert.ok(source.includes('"upper_bound": null'));
    await p
      .locator(".source-editor")
      .fill(source.replaceAll('"upper_bound": null', '"upper_bound": 1'));
    await p
      .locator(".revision-field")
      .filter({ hasText: "修改原因" })
      .locator("textarea")
      .fill("将两个决策变量上界设为1，验证人工代码修订。");
    if (process.env.LLM4OM_WEB_SCREENSHOTS)
      await p.screenshot({
        path: path.join(
          process.env.LLM4OM_WEB_SCREENSHOTS,
          "revision-editor.png",
        ),
        fullPage: true,
      });
    await p.click("#submit-edit");
    await p.waitForFunction(
      (old) =>
        snapshot?.job?.run_id !== old && snapshot?.job?.status === "completed",
      before.run,
      { timeout: 40000 },
    );
    assert.equal(await p.locator(".objective-result strong").innerText(), "5");
    assert.deepEqual(fs.readFileSync(parent), bytes);
    const after = await p.evaluate(() => ({
      assisted: snapshot.bundle.assisted,
      ledger: snapshot.contents["budget-ledger.json"],
    }));
    assert.equal(after.assisted, true);
    assert.equal(
      after.ledger.external_llm_requests,
      before.ledger.external_llm_requests,
    );
    assert.equal(after.ledger.solver_calls, before.ledger.solver_calls + 1);
    await p.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await p.evaluate(() => document.documentElement.scrollWidth > innerWidth),
      false,
    );
    assert.deepEqual(errors, []);
    console.log(
      "Readable revision UI → real container HiGHS5; old bundle unchanged, no new LLM request, assisted=true, no page errors or mobile overflow.",
    );
  } finally {
    await b.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
