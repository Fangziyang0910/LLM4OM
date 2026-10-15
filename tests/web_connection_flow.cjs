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
      viewport: { width: 390, height: 844 },
    });
    const errors = [],
      posts = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      if (request.method() === "POST") posts.push(request.url());
    });
    await page.goto(url);
    const result = await page.evaluate(() => {
      const host = document.createElement("div");
      host.className = "decision-card";
      document.querySelector("main").append(host);
      const snapshot = {
        job: { status: "failed" },
        bundle: { error: { code: "provider_connection_error" } },
        contents: {
          "llm-trace.json": {
            attempts: [
              {
                diagnostic: "provider_connection_error",
                connection_diagnostic: "tls_interrupted",
              },
            ],
          },
        },
      };
      UI.decision(host, null, null, null, snapshot);
      const result = { tls: host.innerText };
      snapshot.contents = {};
      UI.decision(host, null, null, null, snapshot);
      result.legacy = host.innerText;
      snapshot.contents = {
        "llm-trace.json": {
          attempts: [
            {
              diagnostic: "provider_connection_error",
              connection_diagnostic: "tls_certificate",
            },
          ],
        },
      };
      snapshot.bundle.error.code = "budget_exhausted";
      UI.decision(host, null, null, null, snapshot);
      result.budget = host.innerText;
      UI.decision(host, { termination: "optimal", has_primal_solution: true, objective_value: 13,
        solver_id: "llm4om.solvers.highs" }, { variables: { qty_A: 3 } }, null, snapshot);
      result.partialObjective = host.querySelector(".objective-result strong")?.textContent;
      result.partialFailure = Boolean(host.querySelector(".failure-summary"));
      result.emptyAnalysis = host.querySelectorAll(".result-analysis").length;
      host.remove();
      return result;
    });
    assert.match(result.tls, /TLS 连接被中断/);
    assert.match(result.tls, /用量可能未知/);
    assert.match(result.legacy, /暂时无法连接/);
    assert.match(result.budget, /预算上限/);
    assert.ok(!result.budget.includes("证书"));
    assert.equal(result.partialObjective, "13");
    assert.equal(result.partialFailure, true);
    assert.equal(result.emptyAnalysis, 0);
    assert.deepEqual(errors, []);
    assert.deepEqual(posts, []);
    console.log(
      "TLS diagnostic, unknown usage notice, legacy fallback and unrelated failure preserved: passed; zero POST/model calls.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
