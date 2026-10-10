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
    await page.locator('[data-tab="diagnostics"]').click();
    const usage = page
      .locator(".runtime-card")
      .filter({ has: page.locator("h3", { hasText: /^资源使用$/ }) });
    assert.equal(await usage.locator(".metric strong").nth(0).innerText(), "1");
    assert.equal(await usage.locator(".metric strong").nth(3).innerText(), "2");
    assert.match(await usage.innerText(), /7,299/);
    assert.match(
      await usage.locator("tr").filter({ hasText: "费用" }).innerText(),
      /未提供/,
    );
    const solve = page.locator(".runtime-card").filter({
      has: page.locator("h3", { hasText: /^最终候选的求解与执行$/ }),
    });
    assert.match(
      await solve.locator("tr").filter({ hasText: "Best bound" }).innerText(),
      /7/,
    );
    assert.match(
      await solve.locator("tr").filter({ hasText: "报告Gap" }).innerText(),
      /0/,
    );
    assert.match(await solve.innerText(), /CPU时间[\s\S]*峰值内存/);
    const calls = page
      .locator(".runtime-card")
      .filter({ has: page.locator("h3", { hasText: /^已保存的模型调用$/ }) });
    assert.match(await calls.innerText(), /父版本[\s\S]*deepseek-v4-pro-0813/);
    assert.match(
      await page.locator("#process-summary").innerText(),
      /人工辅助修订/,
    );
    if (process.env.LLM4OM_WEB_SCREENSHOTS)
      await page.screenshot({
        path: path.join(
          process.env.LLM4OM_WEB_SCREENSHOTS,
          "runtime-desktop.png",
        ),
        fullPage: true,
      });
    const original = await page.evaluate(async () => {
      const { jobs } = await (await fetch("/api/jobs")).json();
      const result = await (await fetch("/api/jobs/" + jobs[0].job_id)).json();
      return result.versions.find((item) => !item.parent_run_id).run_id;
    });
    await page.selectOption("#run-version", original);
    await page.waitForFunction(
      () =>
        document.querySelector(".objective-result strong")?.textContent ===
        "13",
    );
    assert.equal(await usage.locator(".metric strong").nth(3).innerText(), "1");
    assert.match(
      await solve.locator("tr").filter({ hasText: "Best bound" }).innerText(),
      /13/,
    );
    assert.match(
      await calls.innerText(),
      /当前版本[\s\S]*deepseek-v4-pro-0813/,
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
          "runtime-mobile.png",
        ),
        fullPage: true,
      });
    const unknown = await page.evaluate(() => {
      const host = document.createElement("div");
      document.body.append(host);
      UI.runtimeDetails(host, {
        contents: {
          "budget-ledger.json": {
            llm_attempts: 1,
            external_llm_requests: 1,
            total_tokens: null,
            known_total_tokens: 0,
            reserved_tokens: 37,
            cost: null,
          },
          "llm-trace.json": {
            attempts: [
              {
                role: "formulation",
                status: "response_unknown",
                reservation: 37,
                usage: { total_tokens: null },
              },
            ],
          },
        },
      });
      const result = {
        text: host.innerText,
        solverCards: [...host.querySelectorAll("h3")].filter((item) =>
          item.textContent.includes("求解与执行"),
        ).length,
      };
      host.remove();
      return result;
    });
    assert.match(unknown.text, /总Token\s+未知/);
    assert.match(unknown.text, /已知Token\s+0/);
    assert.match(unknown.text, /未知用量预留\s+37/);
    assert.match(unknown.text, /费用\s+未提供/);
    assert.match(unknown.text, /响应未确认/);
    assert.equal(unknown.solverCards, 0);
    assert.deepEqual(errors, []);
    assert.deepEqual(posts, []);
    console.log(
      "Runtime summary: actual13/7 version scope, usage/budgets, bound/gap/CPU/memory, unknown tokens/reservations/cost, mobile; zero POST/model/Solver calls.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
