"use strict";
const { editorDialog, closeDialog } = require("./helpers/browser_fixture.cjs");
// 垂直故事流验收:确定性 Provider 走 提交 → 澄清确认 → 完整求解,
// 检查真实步骤、阶段产物、折叠用量、产物跳转与轮询稳定性。
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
      () => document.querySelector("#method")?.options.length > 0,
    );
    await page.click("#load-example");
    await editorDialog(page, "options");
    await page.selectOption("#method", "llm4om.methods.feedback_repair");
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
    await closeDialog(page);
    await page.click("#submit");
    await page.waitForSelector("#clarification:not([hidden])", { timeout: 20000 });
    assert.equal(await page.locator("#toggle-process").getAttribute("aria-expanded"), "true");
    const waiting = page
      .locator(".timeline-step.story-card")
      .filter({ hasText: "等待补充信息" });
    await waiting.waitFor({ timeout: 10000 });
    assert.equal(await page.locator(".process-resources").getAttribute("open"), null);
    await page.locator(".process-resources > summary").click();
    assert.match(
      await page.locator(".story-consumption").innerText(),
      /模型请求/,
    );
    assert.match(await page.locator(".story-consumption").innerText(), /Token/);
    await page
      .locator("#clarification-questions select")
      .selectOption("confirm");
    await page.click("#answer-submit");
    await page.waitForFunction(
      () => document.querySelector(".objective-result strong")?.textContent === "13",
      null,
      { timeout: 30000 },
    );
    assert.equal(await page.locator("#process-panel").isVisible(), false);
    await page.locator("#toggle-process").click();
    const cards = page.locator(".timeline-step.story-card");
    const count = await cards.count();
    const labels = [];
    for (let index = 0; index < count; index++)
      labels.push(await cards.nth(index).locator(".step-content strong").innerText());
    assert.ok(count >= 4, `expected >= 4 milestone cards, got ${count}: ${JSON.stringify(labels)}`);
    for (const expected of ["联合生成数学表述与求解实现", "等待补充信息", "数学表述已保存", "求解完成"])
      assert.ok(
        labels.includes(expected),
        `story order missing ${expected}: ${JSON.stringify(labels)}`,
      );
    // 保留方法真实上报的步骤；没有上报的阶段和已结束的启动标记不补造。
    for (const dropped of ["读取问题与数据", "调用求解器"])
      assert.ok(
        !labels.includes(dropped),
        `contentless step should not be a card: ${JSON.stringify(labels)}`,
      );
    assert.equal(await page.locator(".story-attempts").count(), 0, "attempt pills must be gone");
    assert.equal(await page.locator(".story-code").count(), 0, "code fragments must be gone");
    assert.equal(await page.locator(".raw-record").count(), 0, "raw JSON must not be displayed");
    const ending = cards.last();
    assert.match(await ending.innerText(), /建模完成/);
    assert.match(await ending.innerText(), /目标值 13/);
    const formulationCard = cards.filter({ hasText: "数学表述已保存" }).first();
    await formulationCard.locator(".story-artifact-button").click();
    assert.equal(
      await page.locator("#artifact-choice").inputValue(),
      "checks/001/formulation.json",
    );
    assert.ok((await page.locator("#model-view").innerText()).length > 0);
    await page.waitForTimeout(1700);
    assert.equal(
      await page.locator("#artifact-choice").inputValue(),
      "checks/001/formulation.json",
    );
    assert.match(
      await page.locator(".story-consumption").textContent(),
      /模型请求 \d+/,
    );
    // 独立页面 fixture：核心 code_saved 引用 ModelArtifact，跳转须读取其 Code 产物。
    const codeEventSnapshot = await page.evaluate(() => window.snapshot);
    codeEventSnapshot.events.push({ kind: "code_saved", sequence_no: 100,
      artifact_ref: codeEventSnapshot.bundle.model_artifact_ref });
    await page.route("**/api/jobs/" + codeEventSnapshot.job.job_id,
      route => route.fulfill({ json: codeEventSnapshot }));
    await page.reload();
    await page.locator("#toggle-process").click();
    await page.locator(".story-card").filter({ hasText: "求解实现已保存" }).locator(".story-head").click();
    assert.equal(await page.locator(".tab.active").getAttribute("data-tab"), "code");
    await page.locator(".code-lines").waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    assert.deepEqual(errors, []);
    console.log(
      "Story flow: real method steps, milestones, disclosed consumption, artifact jump, polling stability and mobile passed.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
