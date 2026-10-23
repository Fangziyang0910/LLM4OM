import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

// Each test starts runs on the shared server: a scripted LLM writes the model, the local sandbox solves it.

const PRODUCTION = /工厂生产 A、B 两种产品/;

async function open(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(String(error)));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.getByRole("textbox", { name: "问题描述" }).waitFor();
  return errors;
}

test("a run shows the solution, keeps a note and tags, and exports a report", async ({ page }) => {
  const errors = await open(page);
  await page.getByRole("main").getByRole("button", { name: /^生产计划/ }).click();
  await expect(page.getByRole("textbox", { name: "问题描述" })).toHaveValue(PRODUCTION);
  await page.getByRole("button", { name: "开始建模" }).click();
  await page.waitForURL(/\/run\//);
  await page.getByRole("button", { name: "查看解" }).waitFor({ timeout: 60_000 });
  await expect(page.getByText("总利润", { exact: true }).locator("..")).toContainText("13");
  const threadId = page.url().split("/").at(-1)!;
  const before = (await (await page.request.get(`/threads/${threadId}`)).json()).values.timing;

  await page.getByRole("button", { name: "更多操作", exact: true }).click();
  await page.getByRole("menuitem", { name: "备注与标签" }).click();
  const dialog = page.getByRole("dialog", { name: "备注与标签" });
  await dialog.getByLabel("备注").fill("整数约束已核对");
  await dialog.getByLabel("标签").fill("e2e, 已核对");
  await dialog.getByRole("button", { name: "保存" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText("整数约束已核对")).toBeVisible();

  // The tag filters the history after a reload, so the server kept it.
  await page.reload();
  await page.getByRole("button", { name: "查看解" }).waitFor();
  const after = (await (await page.request.get(`/threads/${threadId}`)).json()).values.timing;
  expect(after).toEqual(before);
  await page.getByRole("textbox", { name: "搜索运行" }).fill("#e2e");
  await expect(page.getByRole("navigation", { name: "运行记录" }).getByText(/工厂生产/)).toHaveCount(1);
  await page.getByRole("textbox", { name: "搜索运行" }).fill("#nosuch");
  await expect(page.getByRole("navigation", { name: "运行记录" }).getByText(/工厂生产/)).toHaveCount(0);

  await page.getByRole("button", { name: "更多操作", exact: true }).click();
  const [download] = await Promise.all([page.waitForEvent("download"),
    page.getByRole("menuitem", { name: "导出报告（Markdown）" }).click()]);
  const report = await readFile(await download.path(), "utf-8");
  expect(download.suggestedFilename()).toMatch(/\.md$/);
  expect(report).toMatch(/目标值：13/);
  expect(report).toContain("整数约束已核对");
  expect(report).toContain("build_model");
  expect(report).toContain("运行配置");
  expect(report).not.toContain("e2e-not-a-key");
  expect(errors).toEqual([]);
});

test("a cancelled method keeps its draft after reloading without an event stream", async ({ page }) => {
  const errors = await open(page);
  await page.getByRole("textbox", { name: "问题描述" }).fill("E2E_PAUSE_REPAIR 工厂生产计划");
  await page.getByRole("button", { name: "查看运行设置", exact: true }).click();
  await page.locator("#method-feedback_repair").click();
  await page.getByRole("button", { name: "完成", exact: true }).click();
  await page.getByRole("button", { name: "开始建模" }).click();
  await page.waitForURL(/\/run\//);
  await expect(page.getByText(/LLM 正在处理：repair/)).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "停止", exact: true }).click();
  await expect(page.getByText("运行已停止", { exact: true })).toBeVisible();
  let streamRequests = 0;
  await page.route(/\/runs\/[^/]+\/stream/, route => { streamRequests++; return route.abort(); });
  await page.reload();
  await expect(page.getByText("停止前已保存的过程和产物仍可查看。", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "求解代码", exact: true }).click();
  await expect(page.getByRole("tabpanel")).toContainText("return m.missing");
  expect(streamRequests).toBe(0);
  expect(errors).toEqual([]);
});

test("a named DeepSeek preset keeps its native provider, custom endpoint and actual model ID", async ({ page }) => {
  const errors = await open(page);
  await page.getByRole('button', { name: /预设模型/ }).click();
  const dialog = page.getByRole('dialog', { name: '预设模型', exact: true });
  await expect(dialog.getByRole('heading', { name: 'deepseek-v4.1 flash-1017' })).toBeVisible();
  await expect(dialog.getByText('mock-model', { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: '添加预设', exact: true }).click();
  await dialog.getByRole('combobox', { name: '服务商', exact: true }).click();
  await page.getByRole('option', { name: 'DeepSeek', exact: true }).click();
  await dialog.getByLabel('接口地址', { exact: true }).fill('http://127.0.0.1:8796/v1');
  await dialog.getByLabel('API 密钥', { exact: true }).fill('e2e-not-a-key');
  await dialog.getByLabel('预设名称', { exact: true }).fill('DeepSeek native test');
  await dialog.getByLabel('模型 ID', { exact: true }).fill('mock-model');
  await dialog.getByRole('button', { name: '添加预设', exact: true }).last().click();
  await expect(dialog.getByRole('heading', { name: 'DeepSeek native test' })).toBeVisible();
  const saved = (await (await page.request.get('/api/presets')).json()).presets.at(-1);
  expect(saved).toMatchObject({ name: 'DeepSeek native test', model: 'mock-model', provider: 'deepseek', base_url: 'http://127.0.0.1:8796/v1' });
  expect(saved.api_key).toBeUndefined();
  await dialog.getByRole('button', { name: '删除这个预设' }).click();
  await dialog.getByRole('button', { name: '确认删除？' }).click();
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  expect(errors).toEqual([]);
});

test("new methods expose supported solver choices and BIND runs through the workbench", async ({ page }) => {
  const errors = await open(page);
  await page.getByRole("button", { name: "查看运行设置", exact: true }).click();
  await page.locator("#method-sac_opt").click();
  await expect(page.locator("#language-pyomo")).toBeChecked();
  await expect(page.locator("#language-gurobipy")).toBeEnabled();
  await page.locator("#method-optimind").click();
  await expect(page.locator("#language-pyscipopt")).toBeEnabled();
  await expect(page.locator("#language-cpmpy")).toBeEnabled();
  await page.locator("#method-bind").click();
  await expect(page.locator("#language-casadi")).toBeEnabled();
  await expect(page.locator("#language-cvxpy")).toBeEnabled();
  await expect(page.locator('[id^="language-"]')).toHaveCount(9);
  await page.locator('label[for="language-ortools"]').click();
  await page.locator('label[for="language-pyomo"]').click();
  await page.getByRole("button", { name: "完成", exact: true }).click();
  await page.getByRole("main").getByRole("button", { name: /^生产计划/ }).click();
  await page.getByRole("button", { name: "开始建模" }).click();
  await page.waitForURL(/\/run\//);
  await page.getByRole("button", { name: "查看解" }).waitFor({ timeout: 60_000 });
  await expect(page.getByText("总利润", { exact: true }).locator("..")).toContainText("13");
  const state = (await (await page.request.get(`/threads/${page.url().split("/").at(-1)}`)).json()).values;
  expect(state.spec.method).toBe("bind");
  expect(state.failure).toBeNull();
  expect(errors).toEqual([]);
});

test("native APIs run without an interface setting and a library can use different backends", async ({ page }) => {
  const errors = await open(page);
  await page.getByRole("button", { name: "查看运行设置", exact: true }).click();
  await page.locator('label[for="language-ortools"]').click();
  await expect(page.getByRole('combobox', { name: '建模接口', exact: true })).toHaveCount(0);
  await page.getByRole('combobox', { name: '求解后端', exact: true }).click();
  await page.getByRole('option', { name: 'CP_SAT', exact: true }).click();
  await page.getByRole("button", { name: "完成", exact: true }).click();
  await page.getByRole('main').getByRole('button', { name: /^生产计划/ }).click();
  await page.getByRole('button', { name: '开始建模' }).click();
  await page.waitForURL(/\/run\//);
  await page.getByRole('button', { name: '查看解' }).waitFor({ timeout: 60_000 });
  let state = (await (await page.request.get(`/threads/${page.url().split('/').at(-1)}`)).json()).values;
  expect(state.spec).toMatchObject({ language: 'ortools', solver: 'CP_SAT' });
  expect(state.solve.objective).toBe(13);

  for (const solver of ['OSQP', 'SCS']) {
    await page.goto('/');
    await page.getByRole('textbox', { name: '问题描述' }).fill('连续变量 x,y>=0，x+y<=2。最小化(x-1)^2+(y-2)^2。');
    await page.getByRole("button", { name: "查看运行设置", exact: true }).click();
    await page.locator('label[for="language-cvxpy"]').click();
    await expect(page.locator('[id^="language-"]')).toHaveCount(9);
    await page.getByRole('combobox', { name: '求解后端', exact: true }).click();
    await page.getByRole('option', { name: solver, exact: true }).click();
    await page.getByRole("button", { name: "完成", exact: true }).click();
    await page.getByRole('button', { name: '开始建模' }).click();
    await page.waitForURL(/\/run\//);
    await page.getByRole('button', { name: '查看解' }).waitFor({ timeout: 60_000 });
    state = (await (await page.request.get(`/threads/${page.url().split('/').at(-1)}`)).json()).values;
    expect(state.spec).toMatchObject({ language: 'cvxpy', solver });
    expect(state.solve.solver).toBe(solver);
    expect(state.solve.objective).toBeCloseTo(0.5, 4);
  }
  expect(errors).toEqual([]);
});

test("history can load records beyond the first two hundred", async ({ page }) => {
  const ids: string[] = [];
  try {
    for (let index = 0; index < 205; index++) {
      const response = await page.request.post("/threads", { data: { metadata: {
        title: index === 0 ? "pagination-first" : `pagination-${index}`, method: "direct", language: "pyomo", model: "mock-model",
      } } });
      expect(response.ok()).toBeTruthy();
      ids.push((await response.json()).thread_id);
    }
    await open(page);
    await page.getByRole("textbox", { name: "搜索运行" }).fill("pagination-first");
    const history = page.getByRole("navigation", { name: "运行记录" });
    await expect(history.getByText("pagination-first", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "加载更早的运行" }).click();
    await page.getByRole("button", { name: "加载更早的运行" }).click();
    await expect(history.getByText("pagination-first", { exact: true })).toBeVisible();
    // Opening an old record directly does not load its row into the first history page.
    await page.goto(`/run/${ids[1]}`);
    await expect(history.getByText("pagination-1", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "更多操作", exact: true }).click();
    await page.getByRole("menuitem", { name: "删除这次运行" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "删除", exact: true }).click();
    await page.waitForURL("/");
    expect((await page.request.get(`/threads/${ids[1]}`)).status()).toBe(404);
  } finally {
    await Promise.all(ids.map(id => page.request.delete(`/threads/${id}`)));
  }
});

test("a comparison runs several methods on one problem, also over plain HTTP", async ({ page }) => {
  // Over plain HTTP on a network address (not localhost) browsers leave out these secure-context APIs.
  await page.addInitScript(() => {
    Object.defineProperty(Crypto.prototype, "randomUUID", { value: undefined });
    Object.defineProperty(Navigator.prototype, "clipboard", { get: () => undefined });
  });
  const errors = await open(page);
  await page.getByRole("main").getByRole("button", { name: /^生产计划/ }).click();
  await page.getByRole("button", { name: "查看运行设置", exact: true }).click();
  await page.getByRole("switch", { name: "对比多个方法" }).click();
  await page.locator("#compare-feedback_repair").click();
  await page.getByRole("button", { name: "完成", exact: true }).click();
  await page.getByRole("button", { name: "开始对比（2 个运行）" }).click();
  await page.waitForURL(/\/compare\//);
  await expect(page.getByText("2 个有解的运行目标值一致")).toBeVisible({ timeout: 60_000 });
  const rows = page.getByRole("row");
  await expect(rows.filter({ hasText: "Direct" })).toContainText("13");
  await expect(rows.filter({ hasText: "Feedback Repair" })).toContainText("13");
  await rows.filter({ hasText: "Feedback Repair" }).click();
  await page.waitForURL(/\/run\//);
  await page.setViewportSize({ width: 320, height: 740 });
  await page.getByRole("button", { name: "更多操作", exact: true }).click();
  await expect(page.getByRole("menuitem", { name: "查看对比", exact: true })).toBeInViewport();
  await page.keyboard.press("Escape");
  expect(await page.getByRole("main").evaluate(main => main.scrollWidth <= main.clientWidth)).toBe(true);
  for (const viewport of [{ width: 320, height: 568 }, { width: 844, height: 390 }]) {
    await page.setViewportSize(viewport);
    const panel = page.getByRole("tabpanel");
    await panel.scrollIntoViewIfNeeded();
    await expect(panel).toBeInViewport();
    expect((await panel.boundingBox())!.height).toBeGreaterThan(240);
  }
  await page.getByRole("button", { name: "更多操作", exact: true }).click();
  await page.getByRole("menuitem", { name: "复制链接" }).click();
  await page.locator("[data-sonner-toast]").filter({ hasText: "已复制链接。" }).waitFor();
  await page.getByRole("button", { name: "更多操作", exact: true }).click();
  await page.getByRole("menuitem", { name: "查看对比", exact: true }).click();
  await page.waitForURL(/\/compare\//);
  expect(errors).toEqual([]);
});

test("an infeasible model shows the constraints that conflict", async ({ page }) => {
  const errors = await open(page);
  await page.getByRole("textbox", { name: "问题描述" }).fill(
    "工厂生产 A、B 两种产品。合同要求 A、B 各至少生产 5 件。A 消耗 2 单位切割资源，B 消耗 1 单位，切割资源共 8 单位。使利润 3A+2B 最大。");
  await page.getByRole("button", { name: "开始建模" }).click();
  await page.waitForURL(/\/run\//);
  await expect(page.getByText("求解器判定模型不可行", { exact: false })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: /查看解|查看详情/ }).first().click();
  const conflict = page.getByRole("heading", { name: /不能同时满足的约束/ }).locator("..");
  await expect(conflict).toContainText("cutting");
  await expect(conflict).toContainText("contract");
  expect(errors).toEqual([]);
});

test("an Excel workbook becomes one CSV file per sheet", async ({ page }) => {
  await open(page);
  await page.locator("input[type=file]").setInputFiles(fileURLToPath(new URL("fixtures/transport.xlsx", import.meta.url)));
  const files = page.getByRole("list", { name: "数据文件" });
  await expect(files.getByText("transport-costs.csv")).toBeVisible();
  await expect(files.getByText("transport-notes.csv")).toBeVisible();
});

test("the workbench switches to English and stays in English", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "外观与语言" }).last().click();
  await page.getByRole("menuitemradio", { name: "English" }).click();
  await expect(page.getByRole("heading", { name: "Describe an optimization problem" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Start modeling" })).toBeVisible();
  await expect(page.getByText("建模方法")).toHaveCount(0);
});
