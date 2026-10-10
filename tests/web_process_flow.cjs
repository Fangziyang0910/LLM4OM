"use strict";
const assert = require("node:assert/strict");
const { chromium } = require(process.env.LLM4OM_BROWSER_MODULE || "playwright");
const url = process.env.LLM4OM_WEB_TEST_URL;
assert.ok(url && ["localhost", "127.0.0.1"].includes(new URL(url).hostname));
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.LLM4OM_BROWSER_EXECUTABLE,
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1100 },
    });
    const errors = [];
    const posts = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      if (request.method() === "POST") posts.push(request.url());
    });
    await page.goto(url);
    await page.waitForFunction(
      () => document.querySelector("#method").options.length > 0,
    );
    for (const method of [
      "llm4om.methods.optimus_inline",
      "llm4om.methods.coe",
    ]) {
      await page.selectOption("#method", method);
      assert.deepEqual(
        await page
          .locator("#solver option")
          .evaluateAll((options) => options.map((option) => option.value)),
        ["llm4om.solvers.gurobi"],
      );
    }
    await page.selectOption("#method", "llm4om.methods.direct");
    assert.equal(await page.locator("#solver option").count(), 2);
    let config = JSON.parse(await page.locator("#config-json").inputValue());
    config.method.plugin_id = "llm4om.methods.coe";
    config.model_backend.plugin_id = "llm4om.model_backends.gurobipy";
    config.solver.plugin_id = "llm4om.solvers.highs";
    await page.locator(".settings-panel details summary").click();
    await page.locator("#config-json").fill(JSON.stringify(config));
    await page.click("#apply-config");
    assert.equal(await page.locator("#submit").isDisabled(), true);
    assert.match(
      await page.locator("#solver option:checked").innerText(),
      /当前配置不可用/,
    );
    assert.equal(
      JSON.parse(await page.locator("#config-json").inputValue()).solver
        .plugin_id,
      "llm4om.solvers.highs",
    );
    await page.selectOption("#solver", "llm4om.solvers.gurobi");
    assert.equal(await page.locator("#submit").isDisabled(), false);
    await page
      .locator(".job")
      .filter({ hasText: "OptiMUS" })
      .filter({ hasText: "已完成" })
      .first()
      .click();
    await page.waitForSelector(".timeline-step[data-artifact]");
    assert.equal(
      await page.locator(".timeline-step[data-artifact]").count(),
      6,
    );
    const states = [
      "state_1_params.json",
      "state_2_objective.json",
      "state_3_constraints.json",
      "state_4_constraints_modeled.json",
      "state_5_objective_modeled.json",
      "state_6_code.json",
    ];
    for (const name of states) {
      await page.locator('[data-artifact="method/' + name + '"]').click();
      assert.equal(
        await page.locator("#artifact-choice").inputValue(),
        "method/" + name,
      );
      if (name === states[0])
        assert.match(
          await page.locator("#model-view").innerText(),
          /此时尚未形成完整/,
        );
      if (name === states[5])
        assert.ok((await page.locator("#model-view .code-line").count()) > 0);
    }
    await page
      .locator('[data-artifact="method/state_2_objective.json"]')
      .click();
    await page.waitForTimeout(1800);
    assert.equal(
      await page.locator("#artifact-choice").inputValue(),
      "method/state_2_objective.json",
    );
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    assert.deepEqual(posts, []);
    assert.deepEqual(errors, []);
    if (process.env.LLM4OM_WEB_SCREENSHOTS)
      await page.screenshot({
        path: process.env.LLM4OM_WEB_SCREENSHOTS + "/process-mobile.png",
        fullPage: true,
      });
    console.log(
      "Manifest solver choices, explicit invalid selection, six saved states and stable historical selection passed; zero POST/model calls.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
