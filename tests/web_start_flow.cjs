"use strict";
const { editorDialog, closeDialog } = require("./helpers/browser_fixture.cjs");
// 起点页体验验收:单一输入区、配置窗口、兼容性提示、预算与配置检查。
const assert = require("node:assert/strict");
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
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(url);
    await page.waitForFunction(
      () => document.querySelector("#method")?.options.length > 0,
    );
    const explainer = page.locator("#method-explainer");
    assert.equal(await page.locator(".advanced-controls").getAttribute("open"), null);
    assert.equal(await page.locator("dialog[open]").count(), 0);
    assert.equal(await page.locator("#submit").isDisabled(), true);
    assert.match(await page.locator("#choose-model").innerText(), /已配置/);
    const composer = await page.locator(".composer").boundingBox();
    const submit = await page.locator("#submit").boundingBox();
    assert.ok(submit.y + submit.height < 844 && submit.x >= composer.x);
    await page.locator("#load-example").click();
    await editorDialog(page, "options");
    await page.getByText("高级设置", { exact: true }).click();
    await page.selectOption("#method", "llm4om.methods.optimus");
    assert.equal(await page.locator("#method option:checked").innerText(), "OptiMUS");
    assert.match(await explainer.innerText(), /依次理解目标与约束/);
    assert.match(await explainer.innerText(), /已按该方法声明的能力切换/);
    assert.match(await page.locator("#budget-summary").innerText(), /模型请求 ≤\d+/);
    assert.match(await page.locator("#budget-summary").innerText(), /Token ≤[\d,]+/);
    assert.match(await page.locator("#budget-summary").innerText(), /时间 ≤[\d,]+ 秒/);
    assert.match(await page.locator("#budget-summary").innerText(), /真实请求与费用显著更高/);
    await page.selectOption("#method", "llm4om.methods.coe");
    assert.match(await page.locator("#method option:checked").innerText(), /CoE · 专家协作/);
    const config = JSON.parse(await page.locator("#config-json").inputValue());
    config.method.plugin_id = "llm4om.methods.coe";
    config.model_backend.plugin_id = "llm4om.model_backends.gurobipy";
    config.solver.plugin_id = "llm4om.solvers.highs";
    await page.locator("#config-json").fill(JSON.stringify(config));
    await page.click("#apply-config");
    assert.equal(await page.locator("#submit").isDisabled(), true);
    assert.match(await explainer.innerText(), /不兼容/);
    await closeDialog(page);
    await page.selectOption("#solver", "llm4om.solvers.gurobi");
    await editorDialog(page, "options");
    assert.equal(await page.locator("#submit").isDisabled(), false);
    assert.doesNotMatch(await explainer.innerText(), /不兼容/);
    const budgetInConfig = JSON.parse(await page.locator("#config-json").inputValue()).budget;
    const shown = await page.locator("#budget-summary").innerText();
    for (const [label, value] of [
      ["模型请求 ≤", budgetInConfig.max_llm_attempts],
      ["求解 ≤", budgetInConfig.max_solver_calls],
    ])
      assert.ok(
        shown.includes(`${label}${value}`),
        `budget chip ${label} ${value} missing`,
      );
    await page.click("#doctor");
    await page.waitForSelector("#doctor-result strong");
    assert.match(await page.locator("#doctor-result").innerText(), /未请求网络检查/);
    await page.check("#check-connectivity");
    await page.click("#doctor");
    // 当前确定性 Provider 只实现 POST,目录 GET 返回 501;分层呈现对
    // 失败态同样成立(通过/未通过计数与建议动作)。
    await page.waitForFunction(() =>
      /通过 \d+ 项 · 未通过 \d+ 项/.test(
        document.querySelector("#doctor-result").textContent,
      ),
    );
    const doctorText = await page.locator("#doctor-result").innerText();
    assert.match(doctorText, /HTTP 501|接口可达/);
    assert.match(doctorText, /建议检查服务地址与凭据后重试|可以提交运行/);
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
      false,
    );
    assert.deepEqual(errors, []);
    console.log(
      "Start page: method explainer cards, auto-switch note, invalid-solver warning, budget chips matching config, doctor layering and mobile passed.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
