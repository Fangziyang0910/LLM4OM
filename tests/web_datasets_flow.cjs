"use strict";
// 数据集浏览验收:侧栏入口 → 数据集列表 → 条目表 → 单条公开输入与
// 结构化参考答案;界面不出现原始 JSON,窄屏无横向溢出。
const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const path = require("node:path");
const { chromium } = require(process.env.LLM4OM_BROWSER_MODULE || "playwright");
const url = process.env.LLM4OM_WEB_TEST_URL;
const workspaceEnv = process.env.LLM4OM_WEB_TEST_WORKSPACE;
assert.ok(
  url && ["127.0.0.1", "localhost"].includes(new URL(url).hostname),
  "Only local fixture endpoints are allowed.",
);
assert.ok(workspaceEnv, "LLM4OM_WEB_TEST_WORKSPACE is required.");
const repo = path.join(__dirname, "..");
// guidance 伺服器把 serve_web 的工作区设在 LLM4OM_WEB_TEST_WORKSPACE(即 <ws>/jobs),
// 冻结数据集需落在该工作区的 tasks/ 下才会被发现。
const workspace = workspaceEnv;
(async () => {
  // 冻结一个确定性数据集到工作区 tasks/(服务器按请求重新扫描)。
  execFileSync(
    "uv",
    ["run", "--locked", "llm4om", "import", "--config", "examples/specs/import-checker.json",
     "--output", path.join(workspace, "tasks", "micro")],
    { cwd: repo, stdio: "pipe" },
  );
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.LLM4OM_BROWSER_EXECUTABLE,
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(url);
    await page.locator("#open-datasets").click();
    const row = page.locator(".dataset-row").filter({ hasText: "original-production-micro-fixture" });
    await row.waitFor({ timeout: 10000 });
    assert.match(await row.innerText(), /v1/);
    await row.click();
    await page.locator("#dataset-detail .dataset-row").filter({ hasText: "fixture-production-milp-001" })
      .waitFor({ timeout: 10000 });
    await page.locator("#dataset-detail .dataset-row").first().click();
    const caseView = page.locator("#dataset-case");
    await caseView.waitFor({ timeout: 5000 });
    assert.match(await caseView.innerText(), /问题描述/);
    assert.match(await caseView.innerText(), /生产数量/);
    assert.match(await caseView.innerText(), /参考目标值/);
    assert.match(await caseView.innerText(), /13/);
    assert.match(await caseView.innerText(), /qty_A/);
    // 界面不展示原始 JSON
    assert.equal(await page.locator(".raw-record").count(), 0);
    assert.doesNotMatch(await caseView.innerText(), /\{/, "参考答案不得以原始 JSON 呈现");
    await page.locator("#back-to-datasets").click();
    await page.locator("#datasets").waitFor({ timeout: 5000 });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator("#open-datasets").click();
    await page.locator(".dataset-row").first().waitFor({ timeout: 5000 });
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
      false,
    );
    assert.deepEqual(errors, []);
    console.log(
      "Datasets: sidebar entry → dataset list → case table → structured problem + reference answer (no raw JSON) and mobile passed.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
