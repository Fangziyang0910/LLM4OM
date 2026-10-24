const assert = require("node:assert/strict");
const { spawn, execFileSync } = require("node:child_process");
const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium, expect } = require("../frontend/node_modules/@playwright/test");

const root = path.resolve(__dirname, "..");
const base = "http://127.0.0.1:8859";
const children = [];
const pauses = ms => new Promise(resolve => setTimeout(resolve, ms));

async function ready(url) {
  for (let i = 0; i < 240; i++) {
    try { if ((await fetch(url)).ok) return; } catch {}
    await pauses(250);
  }
  throw new Error(`Capture service did not start: ${url}`);
}

(async () => {
  const logs = path.join(root, "artifacts/website/capture.log");
  await fs.mkdir(path.dirname(logs), { recursive: true });
  await fs.writeFile(logs, "");
  function start(command, args, env = {}) {
    const child = spawn(command, args, { cwd: root, env: { ...process.env, ...env }, stdio: ["ignore", "pipe", "pipe"] });
    for (const stream of [child.stdout, child.stderr]) stream.on("data", data => fs.appendFile(logs, data).catch(() => {}));
    children.push(child);
    return child;
  }
  const python = path.join(root, ".venv/bin/python");
  start(python, ["website/capture_fixture.py", "8858"]);
  await ready("http://127.0.0.1:8858/v1/models");
  start(path.join(root, ".venv/bin/llm4om"), ["serve", "--sandbox", "local", "--jobs", "1", "--host", "127.0.0.1", "--port", "8859", "--workspace", path.join(root, "artifacts/website/capture-workspace")], {
    LLM4OM_LLM_PROVIDER: "openai_compatible", LLM4OM_LLM_MODEL: "demo-model", LLM4OM_LLM_API_KEY: "capture-not-a-key",
    LLM4OM_LLM_BASE_URL: "http://127.0.0.1:8858/v1", LLM4OM_LLM_NAME: "LLM4OM",
    LLM4OM_LLM_EXTRA_BODY: "{}", LANGSMITH_TRACING: "false", LANGCHAIN_TRACING_V2: "false",
  });
  await ready(`${base}/api/options`);
  const browser = await chromium.launch({ headless: true });
  try {
    for (const locale of ["zh", "en"]) {
      const en = locale === "en";
      const context = await browser.newContext({ viewport: { width: 1360, height: 850 }, deviceScaleFactor: 2, locale: en ? "en-US" : "zh-CN", colorScheme: "dark", reducedMotion: "reduce", recordVideo: { dir: path.join(root, "artifacts/website/recordings"), size: { width: 1360, height: 850 } } });
      await context.addInitScript(locale => { localStorage.setItem("theme", "dark"); localStorage.setItem("llm4om-locale", locale); }, locale);
      const page = await context.newPage();
      const video = page.video();
      const started = Date.now();
      const cues = [];
      const mark = (zh, english) => cues.push({ time: (Date.now() - started) / 1000, text: en ? english : zh });
      const prior = await (await page.request.post(`${base}/threads/search`, { data: { limit: 100 } })).json();
      for (const thread of prior) await page.request.delete(`${base}/threads/${thread.thread_id}`);
      const output = path.join(__dirname, "public/assets/screens", locale);
      await fs.mkdir(output, { recursive: true });
      const problem = en
        ? "Production plan for products A and B\nProduce nonnegative integer quantities. Profit is CNY 3 per A and CNY 2 per B. Each A uses 2 cutting units and 1 processing unit; each B uses 1 cutting unit and 2 processing units. Each resource has 8 units. Maximize total profit."
        : "A、B 两种产品的生产计划\n产量均为非负整数。A 每件利润 3 元，B 每件利润 2 元。每件 A 使用切割资源 2 单位、加工资源 1 单位；每件 B 使用切割资源 1 单位、加工资源 2 单位。两种资源各有 8 单位，求总利润最高的生产安排。";
      await page.goto(base);
      mark("填写生产需求，开始自动建模。", "Enter a production problem and start modeling.");
      assert.equal(await page.locator("html").evaluate(node => node.classList.contains("dark")), true);
      await page.getByLabel(en ? "Problem description" : "问题描述", { exact: true }).fill(problem);
      await pauses(1400);
      await page.getByRole("button", { name: en ? /^Start modeling/ : /^开始建模/ }).click();
      await page.waitForURL(/\/run\//);
      await page.getByRole("button", { name: en ? "Export Excel" : "导出 Excel", exact: true }).waitFor({ timeout: 60000 });
      const run = await (await page.request.get(`${base}/threads/${page.url().split("/").at(-1)}`)).json();
      assert.equal(run.values.solve.objective, 13);
      mark("查看实际方案：A 为 3，B 为 2，总利润 13。", "Review the computed plan: A = 3, B = 2, total profit 13.");
      await pauses(2400);
      await page.evaluate(() => document.fonts.ready);
      if (en) assert.doesNotMatch(await page.locator("body").innerText(), /[\u3400-\u9fff]/);
      const planBox = await page.getByRole("main").boundingBox();
      await page.screenshot({ path: path.join(output, "plan.png"), clip: { x: planBox.x, y: 0, width: planBox.width, height: 625 } });
      await page.getByRole("button", { name: en ? "Business scenario comparison" : "业务场景对比", exact: true }).click();
      for (const [i, amount] of [3, 4].entries()) {
        await page.getByLabel(en ? `Scenario ${i + 1} name` : `场景 ${i + 1} 名称`, { exact: true }).fill(en ? `At least ${amount} of B` : `B 至少生产 ${amount} 件`);
        await page.getByLabel(en ? `Scenario ${i + 1} changes` : `场景 ${i + 1} 调整要求`, { exact: true }).fill(en ? `Make at least ${amount} units of B, keeping all other conditions unchanged.` : `B 至少生产 ${amount} 件，其他条件保持不变。`);
      }
      mark("输入两个业务场景：B 至少 3 件，以及 B 至少 4 件。", "Enter two scenarios: at least 3 units of B, and at least 4.");
      await pauses(2000);
      await page.getByRole("button", { name: en ? "Calculate and compare" : "计算并对比", exact: true }).click();
      await page.waitForURL(/\/compare\//);
      await page.getByRole("heading", { name: en ? "Key decisions compared" : "关键决策对比", exact: true }).waitFor({ timeout: 60000 });
      await page.waitForFunction(() => !document.body.innerText.includes("…"));
      await expect(page.getByRole("row").filter({ hasText: en ? "At least 3 of B" : "B 至少生产 3 件" }).first()).toContainText("12", { timeout: 30000 });
      await expect(page.getByRole("row").filter({ hasText: en ? "At least 4 of B" : "B 至少生产 4 件" }).first()).toContainText("8", { timeout: 30000 });
      mark("同一基准下对比：原方案利润 13，两个场景分别为 12 和 8。", "Compare from one baseline: original profit 13; scenario profits 12 and 8.");
      await pauses(3000);
      if (en) assert.doesNotMatch(await page.locator("body").innerText(), /[\u3400-\u9fff]/);
      const scenarioBox = await page.getByRole("main").boundingBox();
      const tableBox = await page.getByRole("table").first().boundingBox();
      await page.screenshot({ path: path.join(output, "scenarios.png"), clip: { x: scenarioBox.x, y: 0, width: scenarioBox.width, height: tableBox.y + tableBox.height + 26 } });
      await page.goto(base);
      const filename = en ? "production.csv" : "生产数据.csv";
      const data = en ? "Product,Profit (CNY),Cutting units,Processing units\nA,3,2,1\nB,2,1,2\n" : "产品,单件利润（元）,切割资源（单位）,加工资源（单位）\nA,3,2,1\nB,2,1,2\n";
      await page.getByLabel(en ? "Problem description" : "问题描述", { exact: true }).fill(problem);
      await page.locator('input[type="file"]').first().setInputFiles({ name: filename, mimeType: "text/csv", buffer: Buffer.from(data) });
      await page.getByRole("button", { name: en ? `Edit ${filename}` : `编辑 ${filename}`, exact: true }).click();
      await page.getByRole("dialog").waitFor();
      mark("打开附件，检查字段和数据。", "Open an attachment and inspect its fields and values.");
      if (en) assert.doesNotMatch(await page.locator("body").innerText(), /[\u3400-\u9fff]/);
      const dataBox = await page.getByRole("dialog").boundingBox();
      await page.screenshot({ path: path.join(output, "data.png"), clip: { x: dataBox.x - 18, y: dataBox.y - 18, width: dataBox.width + 36, height: dataBox.height + 36 } });
      await pauses(1800);
      await page.getByLabel(en ? "Row 1, column 2" : "第 1 行，第 2 列", { exact: true }).fill("4");
      mark("修改 A 的单件利润并保存到需求稿。", "Edit A's unit profit and save the attachment to the draft.");
      await pauses(1800);
      await page.getByRole("button", { name: en ? "Save data" : "保存数据", exact: true }).click();
      await pauses(1800);
      const finished = (Date.now() - started) / 1000;
      console.log(`Captured ${locale}: dark workbench, computed plan (13), scenarios (12 / 8), editable data.`);
      await context.close();
      const media = path.join(__dirname, "public/assets/demos");
      await fs.mkdir(media, { recursive: true });
      const raw = await video.path();
      execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", raw, "-vf", "fps=24,format=yuv420p", "-c:v", "libx264", "-crf", "27", "-preset", "fast", "-an", "-movflags", "+faststart", path.join(media, `workbench-${locale}.mp4`)]);
      const timestamp = seconds => new Date(Math.round(seconds * 1000)).toISOString().slice(11, 23);
      const subtitles = "WEBVTT\n\n" + cues.map((cue, i) => `${timestamp(cue.time)} --> ${timestamp(cues[i + 1]?.time ?? finished)}\n${cue.text}\n`).join("\n");
      await fs.writeFile(path.join(media, `workbench-${locale}.vtt`), subtitles);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  for (const child of [...children].reverse()) child.kill("SIGTERM");
});
