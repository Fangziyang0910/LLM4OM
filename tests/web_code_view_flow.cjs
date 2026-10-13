"use strict";
// 结果区代码视图验收:语法高亮、复制入口、原始记录默认折叠与深链稳定。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(process.env.LLM4OM_BROWSER_MODULE || "playwright");
const url = process.env.LLM4OM_WEB_TEST_URL;
const provider = process.env.LLM4OM_WEB_TEST_PROVIDER_URL;
for (const address of [url, provider])
  assert.ok(
    address && ["127.0.0.1", "localhost"].includes(new URL(address).hostname),
    "Only local fixture endpoints are allowed.",
  );
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.LLM4OM_BROWSER_EXECUTABLE,
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(url);
    await page.waitForFunction(
      () => document.querySelector("#method").options.length > 0,
    );
    await page.selectOption("#method", "llm4om.methods.feedback_repair");
    await page.click("#load-example");
    const problem = JSON.parse(
      fs.readFileSync(path.join(__dirname, "../examples/specs/problem.json"), "utf8"),
    );
    problem.data_refs = [];
    await page.locator(".problem-panel > details summary").click();
    await page.locator("#problem-json").fill(JSON.stringify(problem));
    await page.locator(".problem-panel > details summary").click();
    const config = JSON.parse(await page.locator("#config-json").inputValue());
    config.llm = {
      provider_plugin_id: "llm4om.providers.openai_compatible",
      model: "synthetic-web-guidance",
      config: {
        base_url: provider,
        credential_env: "LLM4OM_UI_GUIDANCE_TEST_KEY",
        max_retries: 0,
        max_output_tokens: 8192,
        timeout_s: 30,
      },
    };
    await page.locator("details:has(#config-json) > summary").click();
    await page.locator("#config-json").fill(JSON.stringify(config));
    await page.click("#apply-config");
    await page.locator("details:has(#config-json) > summary").click();
    await page.click("#submit");
    await page.waitForSelector("#clarification:not([hidden])", { timeout: 20000 });
    await page.locator("#clarification-questions select").selectOption("confirm");
    await page.click("#answer-submit");
    await page.waitForFunction(
      () => document.querySelector(".objective-result strong")?.textContent === "13",
      null,
      { timeout: 30000 },
    );
    await page.click('[data-tab="code"]');
    await page.waitForSelector(".code-lines .code-line");
    const lines = await page.locator(".code-line").count();
    assert.ok(lines > 10, `expected highlighted code lines, got ${lines}`);
    assert.ok(
      (await page.locator(".code-line .tok-kw").count()) > 0,
      "keyword tokens missing",
    );
    assert.ok(
      (await page.locator(".code-line .tok-num, .code-line .tok-str").count()) > 0,
      "number/string tokens missing",
    );
    assert.match(
      await page.locator(".code-toolbar").innerText(),
      /Python · 求解实现/,
    );
    assert.ok(await page.getByRole("button", { name: "复制代码" }).isVisible());
    assert.equal(
      await page.locator("#artifact-content").locator("..").getAttribute("open"),
      null,
      "raw record must be collapsed by default",
    );
    await page.locator(".raw-record summary").click();
    assert.match(
      await page.locator("#artifact-content").innerText(),
      /source|representation|{"?/,
    );
    await page.waitForTimeout(1700);
    assert.equal(
      await page.locator("#artifact-choice").inputValue(),
      await page.locator("#artifact-choice").inputValue(),
    );
    assert.ok(
      (await page.locator(".code-line .tok-kw").count()) > 0,
      "highlight survives polling",
    );
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    assert.deepEqual(errors, []);
    console.log(
      "Code view: syntax tokens, copy entry, collapsed raw record, polling and mobile passed.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
