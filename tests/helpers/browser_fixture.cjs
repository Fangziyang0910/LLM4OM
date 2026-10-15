"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

// Each view/edit test creates its own run through the public HTTP interface.
async function completedRun(page, { descriptionSuffix = "" } = {}) {
  const url = process.env.LLM4OM_WEB_TEST_URL;
  const provider = process.env.LLM4OM_WEB_TEST_PROVIDER_URL;
  for (const address of [url, provider])
    assert.ok(address && ["127.0.0.1", "localhost"].includes(new URL(address).hostname));
  const bootstrap = await (await page.request.get(url + "/api/bootstrap")).json();
  const config = bootstrap.config;
  config.method = { plugin_id: "llm4om.methods.feedback_repair", config: bootstrap.method_presets["llm4om.methods.feedback_repair"].config };
  config.llm = { provider_plugin_id: "llm4om.providers.openai_compatible", model: "synthetic-web-guidance",
    config: { base_url: provider, credential_env: "LLM4OM_UI_GUIDANCE_TEST_KEY", max_retries: 0,
      max_output_tokens: 8192, timeout_s: 30 } };
  const problem = JSON.parse(fs.readFileSync(path.join(__dirname, "../../examples/specs/problem.json"), "utf8"));
  problem.data_refs = [];
  problem.description += descriptionSuffix;
  const headers = { "X-LLM4OM-Token": bootstrap.token };
  const created = await page.request.post(url + "/api/jobs", { headers, data: { config, problem, data: [] } });
  assert.ok(created.ok(), await created.text());
  const job = await created.json();
  const wait = async wanted => {
    const deadline = Date.now() + 40000;
    while (Date.now() < deadline) {
      const value = await (await page.request.get(url + "/api/jobs/" + job.job_id)).json();
      assert.ok(!value.error, JSON.stringify(value.error));
      assert.ok(!["failed", "cancelled", "unresolved"].includes(value.job.status), JSON.stringify(value.job.error || value.bundle?.error));
      if (value.job.status === wanted) return value;
      await new Promise(resolve => setTimeout(resolve, 200));
    }
    throw new Error("Fixture run did not reach " + wanted);
  };
  const waiting = await wait("needs_input");
  const reference = waiting.bundle.clarification_request_ref;
  const key = Object.keys(waiting.contents).find(name => reference.relative_path.endsWith("/" + name));
  const request = waiting.contents[key];
  const resumed = await page.request.post(url + "/api/jobs/" + job.job_id + "/resume", {
    headers, data: { answers: { schema_version: "0.1.0", request_id: request.request_id, action: "confirm",
      answers: request.questions.map(question => ({ question_id: question.question_id, value: true })) } },
  });
  assert.ok(resumed.ok(), await resumed.text());
  const result = await wait("completed");
  await page.goto(url + "/?job=" + job.job_id);
  await page.waitForSelector(".objective-result strong");
  assert.equal(await page.locator(".objective-result strong").innerText(), "13");
  return result;
}

// Navigate the same native dialogs as a user; changing settings never bypasses the UI.
async function closeDialog(page) {
  if (await page.locator("dialog[open]").count()) await page.keyboard.press("Escape");
}

async function editorDialog(page, kind) {
  const title = kind === "model" ? "选择模型" : "建模选项";
  if (await page.getByRole("dialog", { name: title, exact: true }).isVisible()) return;
  await closeDialog(page);
  await page.locator(kind === "model" ? "#choose-model" : "#open-options").click();
  await page.getByRole("dialog", { name: title, exact: true }).waitFor();
}

module.exports = { completedRun, editorDialog, closeDialog };
