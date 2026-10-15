"use strict";
// 平台内置样例 → 查看问题 → 复制公开输入 → 带入建模；不要求用户导入数据集。
const assert = require("node:assert/strict");
const { chromium } = require(process.env.LLM4OM_BROWSER_MODULE || "playwright");
const url = process.env.LLM4OM_WEB_TEST_URL;
assert.ok(url && ["127.0.0.1", "localhost"].includes(new URL(url).hostname));
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.LLM4OM_BROWSER_EXECUTABLE, args: ["--no-sandbox"] });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ["clipboard-read", "clipboard-write"] });
    const page = await context.newPage();
    await page.addInitScript(() => {
      const write = navigator.clipboard.writeText.bind(navigator.clipboard);
      navigator.clipboard.writeText = async (text) => { window.__copiedText = text; await write(text); };
    });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(url);
    await page.locator('#method').selectOption('llm4om.methods.optitree');
    await page.locator('#solver').selectOption('llm4om.solvers.ortools');
    const configBefore = await page.locator('#config-json').inputValue();
    await page.locator("#open-datasets").click();
    await page.locator("#datasets .dataset-row").filter({ hasText: "NL4Opt" }).waitFor();
    assert.equal(await page.locator("#datasets .dataset-row").count(), 9);
    assert.doesNotMatch(await page.locator("#datasets").innerText(), /已导入|冻结导入|上传数据集|已选|适配器/);
    const titles = await page.locator('#datasets .benchmark-card h3').allTextContents();
    assert.equal(titles.length, 9);
    for (const title of titles) {
      await page.locator('#datasets .benchmark-card').filter({ has: page.getByRole('heading', { name: title, exact: true }) }).click();
      await page.locator('#dataset-detail .dataset-row').first().click();
      assert.ok((await page.locator('#dataset-case .problem-text').innerText()).length > 0);
      await page.locator('#back-to-datasets').click();
    }
    await page.locator("#datasets .dataset-row").filter({ hasText: "NL4Opt" }).click();
    await page.locator("#dataset-detail .dataset-row").first().click();
    const description = await page.locator("#dataset-case .problem-text").innerText();
    await page.locator("#copy-benchmark-problem").click();
    await page.waitForFunction(() => document.querySelector('#notice')?.textContent?.includes('问题已复制'));
    assert.equal(await page.evaluate(() => window.__copiedText), description);
    await page.locator("#try-benchmark-problem").click();
    await page.waitForFunction(value => document.querySelector('#description')?.value === value, description);
    assert.equal(await page.locator("#description").inputValue(), description);
    assert.equal(await page.locator("#config-json").inputValue(), configBefore);
    await page.locator("#open-datasets").click();
    await page.locator("#datasets .dataset-row").filter({ hasText: "MAMO Easy" }).click();
    await page.locator("#dataset-detail .dataset-row").first().waitFor();
    await page.getByRole("button", { name: "下一页 →" }).click();
    await page.locator("#dataset-detail .dataset-row").first().waitFor();
    assert.match(await page.locator(".dataset-pager").innerText(), /第 2/);
    await page.locator("#back-to-datasets").click();
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.setViewportSize({ width: 1440, height: 1000 });

    // 独立工程 fixture 验证携带业务参数，保留其 fixture 身份。
    const listing = await page.evaluate(async () => (await fetch('/api/datasets')).json());
    const nlp = listing.datasets.find(item => item.dataset_id === 'nl4lp');
    const raw = JSON.stringify({ Capacity: 4, Count: "5" });
    const problem = { schema_version: "0.3.0", problem_id: "public-parameter-fixture", revision: "1",
      description: "Choose a nonnegative integer quantity at most Capacity.", language: "en", problem_type_hint: "milp",
      requirements: [], assumptions: [], data_refs: [{ data_id: "parameters", path: "parameters.json", format: "json", schema: { type: "object" } }],
      source: { kind: "builtin_benchmark", dataset_id: "parameter-fixture" } };
    const data = [{ name: "parameters.json", data_id: "parameters", format: "json", size: Buffer.byteLength(raw),
      base64: Buffer.from(raw).toString("base64"), schema: { type: "object" } }];
    await page.route(`**/api/datasets/${nlp.task_id}?*`, route => route.fulfill({ json: {
      dataset: { ...nlp, N_cases: 1 }, total: 1, cases: [{ case_id: "public-case", sample_id: "1",
        problem, input: { title: "Parameter fixture", problem, data }, copy_text: problem.description + "\n\n" + raw,
        reference: { private_annotation: "PRIVATE-REFERENCE-SENTINEL", expected_objective: 123456789 } }] } }));
    await page.locator("#datasets .dataset-row").filter({ hasText: "NL4LP" }).click();
    await page.locator("#dataset-detail .dataset-row").first().click();
    await page.locator("#copy-benchmark-problem").click();
    await page.waitForFunction(() => document.querySelector('#notice')?.textContent?.includes('问题已复制'));
    const copied = await page.evaluate(() => window.__copiedText);
    assert.ok(copied.includes(raw)); assert.ok(!copied.includes("PRIVATE-"));
    await page.locator("#try-benchmark-problem").click();
    await page.waitForFunction(value => document.querySelector('#description')?.value === value, problem.description);
    assert.equal(await page.locator("#description").inputValue(), problem.description);
    assert.equal(await page.locator("#config-json").inputValue(), configBefore);
    let submitted;
    await page.route("**/api/jobs", async route => {
      if (route.request().method() === "POST") {
        submitted = route.request().postDataJSON();
        await route.fulfill({ status: 400, json: { error: { message: "Fixture captured the modeling input." } } });
      } else await route.continue();
    });
    await page.locator("#submit").click();
    await page.waitForFunction(() => document.querySelector('#notice')?.textContent?.includes('Fixture captured'));
    assert.equal(submitted.problem.source.dataset_id, "parameter-fixture");
    assert.equal(Buffer.from(submitted.data[0].base64, "base64").toString(), raw);
    assert.ok(!JSON.stringify(submitted).includes("PRIVATE-"));
    assert.deepEqual(errors, []);
    console.log("Built-in benchmarks, pagination, copy, modeling handoff with public data, retained method configuration and narrow-screen layout passed.");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
