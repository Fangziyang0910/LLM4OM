import { expect, test } from "@playwright/test";

test.describe.configure({ timeout: 30000 });

test("a submitted conversation appears in history while its first reply is running", async ({ page }) => {
  const existing = await page.request.post("/threads", { data: {
    metadata: { graph_id: "optimization", kind: "optimization", title: "已有的当天对话" } } });
  expect(existing.ok()).toBe(true);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/agent");
  const title = "E2E_AGENT_PAUSE 请计算生产计划";
  await page.getByRole("textbox", { name: "发送给优化助手" }).fill(title);
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await page.waitForURL(/\/agent\//);
  const history = page.getByRole("navigation", { name: "运行记录" });
  const entry = history.getByRole("button", { name: title, exact: false }).first();
  await expect(entry).toBeVisible({ timeout: 2000 });
  await expect(entry).toHaveAttribute("aria-current", "page");
  await expect(entry).toContainText("正在求解");
  await page.getByRole("button", { name: "停止", exact: true }).click();
  await expect(entry).toContainText("已停止");
  await page.reload();
  await expect(entry).toContainText("已停止");
  await page.getByRole("textbox", { name: "发送给优化助手" }).fill("下一条尚未发送的消息");
  await page.getByRole("button", { name: "重试这一轮", exact: true }).click();
  await expect(entry).toContainText("正在求解");
  await expect(page.getByRole("log")).toContainText("实际求解结果：13", { timeout: 30000 });
  await expect(entry).not.toContainText("正在求解");
  await expect(page.getByRole("textbox", { name: "发送给优化助手" })).toHaveValue("下一条尚未发送的消息");
});

test("a completed conversation remains in history and reopens after navigating away and reloading", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/agent");
  const title = "E2E_GENERAL 历史保存检查";
  await page.getByRole("textbox", { name: "发送给优化助手" }).fill(title);
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await page.waitForURL(/\/agent\//);
  const url = page.url();
  await expect(page.getByRole("log")).toContainText("列表可以修改");
  const history = page.getByRole("navigation", { name: "运行记录" });
  const entry = history.getByRole("button", { name: title, exact: false }).first();
  await expect(entry).toBeVisible();
  await page.getByRole("button", { name: "多方案对比", exact: true }).click();
  await entry.click();
  await expect(page).toHaveURL(url);
  await expect(page.getByRole("log")).toContainText(title);
  await page.reload();
  await expect(entry).toBeVisible();
  await expect(entry).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("log")).toContainText("列表可以修改");
});

test("history discovers conversations created elsewhere even when this page has no active runs", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const loaded = page.waitForResponse(response => response.url().endsWith("/threads/search"));
  await page.goto("/");
  await loaded;
  const history = page.getByRole("navigation", { name: "运行记录" });
  await expect(page.getByRole("button", { name: "多方案对比", exact: true })).toBeVisible();
  const title = "其他页面新建的对话";
  const response = await page.request.post("/threads", { data: {
    metadata: { graph_id: "optimization", kind: "optimization", title } } });
  expect(response.ok()).toBe(true);
  const id = (await response.json()).thread_id;
  try {
    await expect(history.getByRole("button", { name: title, exact: false }).first()).toBeVisible({ timeout: 12000 });
  } finally { await page.request.delete(`/threads/${id}`); }
});

test("requirements history follows the first message and keeps an active conversation and draft when reopening", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const data = { "demand.csv": "customer,demand\nA,003\n" };
  const response = await page.request.post("/threads", { data: {
    metadata: { graph_id: "requirements", kind: "requirements", title: "新需求对话", preset: "env" },
    supersteps: [{ updates: [{ as_node: "discuss", values: { description: "原需求稿", data, messages: [] } }] }] } });
  expect(response.ok()).toBe(true);
  const id = (await response.json()).thread_id;
  await page.goto(`/chat/${id}`);
  const input = page.getByRole("textbox", { name: "发送给需求助手" });
  const title = "E2E_PAUSE_CHAT 需求历史同步检查";
  await input.fill(title);
  const submitted = page.waitForRequest(request => request.method() === "POST" && request.url().endsWith("/runs/stream"));
  await input.press("Enter");
  expect((await submitted).postDataJSON().input).not.toHaveProperty("data");
  const entry = page.getByRole("navigation", { name: "运行记录" }).getByRole("button", { name: title, exact: false }).first();
  await expect(entry).toContainText("正在梳理");
  await input.fill("下一条需求草稿");
  await page.getByRole("button", { name: "多方案对比", exact: true }).click();
  await entry.click();
  await expect(page).toHaveURL(new RegExp(`/chat/${id}$`));
  await expect(input).toHaveValue("下一条需求草稿");
  await expect(page.getByRole("log")).toContainText("每件产品的利润和资源消耗是多少", { timeout: 15000 });
  await expect(entry).not.toContainText("正在梳理");
  await page.reload();
  await expect(input).toHaveValue("下一条需求草稿");
  await expect(page.getByRole("log")).toContainText(title);
  const saved = await (await page.request.get(`/threads/${id}/state`)).json();
  expect(saved.values.data).toEqual(data);
});

test("a failed reply stays in history and retry updates the same conversation without duplicating its question", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/agent");
  const title = "E2E_AGENT_REPLY_RETRY 历史中的回复失败检查";
  await page.getByRole("textbox", { name: "发送给优化助手" }).fill(title);
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await page.waitForURL(/\/agent\//);
  const id = page.url().split("/").at(-1)!;
  const entry = page.getByRole("navigation", { name: "运行记录" }).getByRole("button", { name: title, exact: false }).first();
  await expect(page.getByText("这轮回复未完成，可以重试。", { exact: true })).toBeVisible({ timeout: 30000 });
  await expect(entry).toContainText("对话中断");
  await page.reload();
  await expect(entry).toContainText("对话中断");
  await page.getByRole("button", { name: "重试这一轮", exact: true }).click();
  await expect(page.getByRole("log")).toContainText("没有重复求解");
  await expect(entry).toContainText("最优 · 13");
  const thread = await (await page.request.get(`/threads/${id}`)).json();
  expect(thread.values.messages.filter((message: { type: string }) => message.type === "human")).toHaveLength(1);
  expect(thread.values.plans).toHaveLength(1);
});

test("queued conversations show the queue state and keep their saved question after cancellation", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const blocker = await (await page.request.post("/threads", { data: {} })).json();
  const run = await (await page.request.post(`/threads/${blocker.thread_id}/runs`, { data: {
    assistant_id: "requirements", input: { description: "", messages: [{ type: "human", content: "E2E_HOLD_CHAT 占用执行槽" }] },
    context: { preset: "env", locale: "zh" },
  } })).json();
  try {
    await expect.poll(async () => (await (await page.request.get(`/threads/${blocker.thread_id}/runs/${run.run_id}`)).json()).status).toBe("running");
    await page.goto("/agent");
    const title = "E2E_GENERAL 排队中保存问题";
    await page.getByRole("textbox", { name: "发送给优化助手" }).fill(title);
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await page.waitForURL(/\/agent\//);
    const id = page.url().split("/").at(-1)!;
    const entry = page.getByRole("navigation", { name: "运行记录" }).getByRole("button", { name: title, exact: false }).first();
    await expect(entry).toContainText("排队中");
    await expect(page.getByRole("log")).toContainText(title);
    await page.getByRole("button", { name: "停止", exact: true }).click();
    await expect(entry).toContainText("已停止");
    await page.reload();
    await expect(entry).toContainText("已停止");
    const thread = await (await page.request.get(`/threads/${id}`)).json();
    expect(thread.values.messages).toHaveLength(1);
    expect(thread.values.messages[0].content).toBe(title);
  } finally {
    await page.request.post(`/threads/${blocker.thread_id}/runs/${run.run_id}/cancel?wait=true`);
    await page.request.delete(`/threads/${blocker.thread_id}`);
  }
});
