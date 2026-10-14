"use strict";
// Run against the local deterministic responder documented in s09-user-experience.md.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(process.env.LLM4OM_BROWSER_MODULE || "playwright");
const url = process.env.LLM4OM_WEB_TEST_URL;
const provider = process.env.LLM4OM_WEB_TEST_PROVIDER_URL;
const workspace = process.env.LLM4OM_WEB_TEST_WORKSPACE;
for (const address of [url, provider])
  assert.ok(
    address && ["127.0.0.1", "localhost"].includes(new URL(address).hostname),
    "Only local fixture endpoints are allowed.",
  );
assert.ok(workspace, "A disposable fixture workspace is required.");
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
    page.on("pageerror", (error) => errors.push(error.message));
    for (const revise of [false, true]) {
      await page.goto(url);
      await page.waitForFunction(
        () => document.querySelector("#method")?.options.length > 0,
      );
      await page.selectOption("#method", "llm4om.methods.feedback_repair");
      await page.click("#load-example");
      if (revise)
        await page
          .locator("#description")
          .fill(
            (await page.locator("#description").inputValue()) +
              " need-new-rule",
          );
      const problem = JSON.parse(
        fs.readFileSync(
          path.join(__dirname, "../examples/specs/problem.json"),
          "utf8",
        ),
      );
      problem.data_refs = [];
      problem.description = await page.locator("#description").inputValue();
      await page.locator(".problem-panel > details summary").click();
      await page.locator("#problem-json").fill(JSON.stringify(problem));
      await page.locator(".problem-panel > details summary").click();
      const config = JSON.parse(
        await page.locator("#config-json").inputValue(),
      );
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
      if (process.env.LLM4OM_WEB_TEST_LIVE_PROGRESS) {
        await page
          .locator(".live-modeling.running .modeling-detail")
          .waitFor({ timeout: 20000 });
        assert.match(
          await page.locator(".modeling-detail").innerText(),
          /Formulation/,
        );
        assert.equal(await page.locator(".stage.running").count(), 1);
        if (process.env.LLM4OM_WEB_SCREENSHOTS)
          await page
            .locator("#decision")
            .screenshot({
              path: path.join(
                process.env.LLM4OM_WEB_SCREENSHOTS,
                "live-modeling.png",
              ),
            });
      }
      await page.waitForSelector("#clarification:not([hidden])", {
        timeout: 20000,
      });
      assert.match(
        await page.locator(".live-modeling.needs_input").innerText(),
        /等待你补充/,
      );
      const before = await page.evaluate(() => ({
        job: snapshot.job.job_id,
        run: snapshot.job.run_id,
      }));
      const parent = path.join(
        workspace,
        before.job,
        "runs",
        before.run,
        "bundle.json",
      );
      const original = fs.readFileSync(parent);
      await page.click("#answer-submit");
      assert.match(await page.locator("#notice").innerText(), /请回答|请填写/);
      if (revise) {
        await page
          .locator("#clarification-questions textarea")
          .fill("产品 A 的生产数量最多为 2。");
        assert.equal(
          await page.locator("#clarification-preview").getAttribute("hidden"),
          null,
        );
        await page.locator("#clarification-preview summary").click();
        assert.match(
          await page.locator("#clarification-description").innerText(),
          /最多为 2/,
        );
      } else
        await page
          .locator("#clarification-questions select")
          .selectOption("confirm");
      if (process.env.LLM4OM_WEB_SCREENSHOTS)
        await page.screenshot({
          path: path.join(
            process.env.LLM4OM_WEB_SCREENSHOTS,
            revise ? "revision-form.png" : "confirmation-form.png",
          ),
          fullPage: true,
        });
      await page.click("#answer-submit");
      const objective = revise ? "12" : "13";
      await page.waitForFunction(
        (value) =>
          document.querySelector(".objective-result strong")?.textContent ===
          value,
        objective,
        { timeout: 30000 },
      );
      const after = await page.evaluate(() => ({
        run: snapshot.job.run_id,
        problem: snapshot.contents["public-problem.json"],
      }));
      if (revise) {
        assert.notEqual(before.run, after.run);
        assert.notEqual(after.problem.revision, problem.revision);
        assert.deepEqual(fs.readFileSync(parent), original);
      } else assert.equal(before.run, after.run);
      assert.equal(await page.locator(".check-row").count(), 5);
      assert.match(
        await page
          .locator(".check-row")
          .filter({ hasText: "原问题可行性" })
          .innerText(),
        /未提供/,
      );
      assert.equal(
        await page.locator("#clarification").getAttribute("hidden"),
        "",
      );
      console.log(
        JSON.stringify({
          action: revise ? "revise" : "confirm",
          objective: Number(objective),
          parent_preserved: revise ? true : null,
        }),
      );
    }
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    assert.deepEqual(errors, []);
    console.log("No page errors or mobile overflow.");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
