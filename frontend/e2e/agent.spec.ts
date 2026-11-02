import { expect, test } from "@playwright/test";

test("attachments finish reading and saving before the agent can send, while the next message stays editable", async ({ page }) => {
  await page.addInitScript(() => {
    const read = File.prototype.text;
    File.prototype.text = function () {
      if (this.name === "delayed.csv") return new Promise<string>(resolve => {
        window.addEventListener("finish-file-read", () => resolve("name,price\nA,003\n"), { once: true });
      });
      return read.call(this);
    };
  });
  await page.goto("/agent");
  const input = page.getByRole("textbox", { name: "发送给优化助手" });
  const send = page.getByRole("button", { name: "发送", exact: true });
  const attach = page.getByRole("button", { name: "添加数据文件", exact: true });
  await input.fill("E2E_GENERAL 列表和元组有什么区别？");
  await page.getByLabel("数据文件", { exact: true }).setInputFiles({ name: "delayed.csv", mimeType: "text/csv", buffer: Buffer.from("name,price\nA,003\n") });
  await expect(send).toBeDisabled();
  await expect(attach).toBeDisabled();
  await expect(attach).toHaveAttribute("title", "正在读取数据……");
  await input.fill("E2E_GENERAL 列表和元组有什么区别？请简要说明。");
  await input.press("Enter");
  await expect(page).toHaveURL(/\/agent$/);
  await page.evaluate(() => window.dispatchEvent(new Event("finish-file-read")));
  await expect(page.getByRole("button", { name: "delayed.csv", exact: true })).toBeVisible();
  await expect(send).toBeEnabled();
  await input.press("Enter");
  await page.waitForURL(/\/agent\//);
  await expect(page.getByRole("log")).toContainText("列表可以修改");
  const threadId = page.url().split("/").at(-1)!;
  expect((await (await page.request.get(`/threads/${threadId}`)).json()).values.data).toEqual({ "delayed.csv": "name,price\nA,003\n" });

  let finishSave!: () => void;
  const waiting = new Promise<void>(resolve => { finishSave = resolve; });
  await page.route(`**/threads/${threadId}/state`, async route => {
    if (route.request().method() === "POST") await waiting;
    await route.continue();
  });
  await input.fill("E2E_GENERAL 谢谢，请再解释一次。");
  await page.locator('input[type="file"]').setInputFiles({ name: "second.csv", mimeType: "text/csv", buffer: Buffer.from("value\n2\n") });
  await expect(send).toBeDisabled();
  await expect(page.getByRole("button", { name: "移除 delayed.csv", exact: true })).toBeDisabled();
  await input.fill("E2E_GENERAL 谢谢，请用一句话解释。");
  await input.press("Enter");
  finishSave();
  await expect(send).toBeEnabled();
  await expect(input).toHaveValue("E2E_GENERAL 谢谢，请用一句话解释。");
  await expect(page.getByRole("button", { name: "second.csv", exact: true })).toBeVisible();
  expect((await (await page.request.get(`/threads/${threadId}`)).json()).values.data).toEqual({
    "delayed.csv": "name,price\nA,003\n", "second.csv": "value\n2\n",
  });
  await page.unroute(`**/threads/${threadId}/state`);
  await page.route(`**/threads/${threadId}/state`, async route => {
    if (route.request().method() === "POST") await route.fulfill({ status: 400, json: { detail: "attachment save failed" } });
    else await route.continue();
  });
  const third = { name: "third.csv", mimeType: "text/csv", buffer: Buffer.from("value\n3\n") };
  await page.locator('input[type="file"]').setInputFiles(third);
  await expect(page.getByText("attachment save failed", { exact: false })).toBeVisible();
  await expect(send).toBeEnabled();
  await expect(attach).toBeEnabled();
  await expect(input).toHaveValue("E2E_GENERAL 谢谢，请用一句话解释。");
  await expect(page.getByRole("button", { name: "third.csv", exact: true })).toHaveCount(0);
  await page.unroute(`**/threads/${threadId}/state`);
  await page.locator('input[type="file"]').setInputFiles(third);
  await expect(page.getByRole("button", { name: "third.csv", exact: true })).toBeVisible();
  expect((await (await page.request.get(`/threads/${threadId}`)).json()).values.data).toEqual({
    "delayed.csv": "name,price\nA,003\n", "second.csv": "value\n2\n", "third.csv": "value\n3\n",
  });
});

test("the mobile conversation keeps navigation, composer controls and keyboard sending accessible", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto("/agent");
  await expect(page.getByRole("heading", { name: "优化对话", exact: true })).toHaveCount(1);
  await page.getByRole("button", { name: "打开菜单" }).click();
  await expect(page.getByRole("dialog").getByRole("button", { name: "新建建模", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  const input = page.getByRole("textbox", { name: "发送给优化助手" });
  await page.getByRole("button", { name: "建模偏好" }).click();
  for (const size of [{ width: 320, height: 568 }, { width: 844, height: 390 }]) {
    await page.setViewportSize(size);
    await expect(page.getByRole("combobox", { name: "固定建模方法" })).toBeInViewport();
    await expect(input).toBeInViewport();
  }
  await page.getByRole("button", { name: "建模偏好" }).click();
  await page.setViewportSize({ width: 320, height: 568 });
  await input.fill("E2E_GENERAL 列表和元组有什么区别？");
  await input.press("Shift+Enter");
  await input.pressSequentially("谢谢");
  await expect(input).toHaveValue("E2E_GENERAL 列表和元组有什么区别？\n谢谢");
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeInViewport();
  await input.press("Control+Enter");
  await expect(page.getByRole("log")).toContainText("列表可以修改");
  for (const size of [{ width: 320, height: 568 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(size);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(input).toBeInViewport();
  }
});

test("the independent agent discusses an idea, models it, and calculates changes without leaving the conversation", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(String(error)));
  await page.goto("/agent");
  const input = page.getByRole("textbox", { name: "发送给优化助手" });
  await input.fill("E2E_AGENT_IDEA 帮我排班");
  await input.press("Enter");
  await page.waitForURL(/\/agent\//);
  const chat = page.url().split("/").at(-1)!;
  await expect(page.getByRole("log")).toContainText("每班至少需要几个人");
  expect((await (await page.request.get(`/threads/${chat}`)).json()).values.plans).toEqual([]);
  await input.fill("请计算工厂的生产计划");
  await input.press("Enter");
  await expect(page.getByRole("log")).toContainText("实际求解结果：13", { timeout: 60_000 });
  let saved = await (await page.request.get(`/threads/${chat}`)).json();
  expect(saved.metadata.kind).toBe("optimization");
  expect(saved.values.plans).toHaveLength(1);
  expect(saved.values.messages.find((message: { name?: string }) => message.name === "model_and_solve").artifact.type).toBe("plans");
  const first = saved.values.source;
  const original = await (await page.request.get(`/threads/${first.thread_id}`)).json();
  expect(original.values.solve.objective).toBe(13);
  expect(original.values.spec.method).toBe("direct");
  const workspace = page.getByRole("complementary", { name: "建模工作区" });
  await expect(workspace).toBeVisible();
  await workspace.getByRole("tab", { name: /数学模型/ }).click();
  await expect(workspace.getByRole("tabpanel")).toContainText("max");
  await input.fill("B 至少生产 3 件，请重新计算");
  await input.press("Enter");
  await expect(page.getByRole("log")).toContainText("目标值 12", { timeout: 60_000 });
  saved = await (await page.request.get(`/threads/${chat}`)).json();
  expect(saved.values.source).toEqual(first);
  expect(saved.values.current.thread_id).not.toBe(first.thread_id);
  expect(saved.values.plans).toHaveLength(2);
  expect((await (await page.request.get(`/threads/${first.thread_id}`)).json()).values).toEqual(original.values);
  await workspace.getByRole("combobox", { name: "查看计算方案", exact: true }).click();
  await page.getByRole("option", { name: saved.values.plans[0].name, exact: true }).click();
  await expect(workspace.getByLabel("方案上下文", { exact: true })).toContainText("正在查看历史方案");
  expect((await (await page.request.get(`/threads/${chat}`)).json()).values.current).toEqual(saved.values.current);
  await workspace.getByRole("button", { name: "查看讨论中的方案", exact: true }).click();
  await expect(workspace.getByLabel("方案上下文", { exact: true })).toHaveCount(0);
  await expect(workspace.getByRole("combobox", { name: "查看计算方案", exact: true })).toContainText("当前讨论方案");
  const conversation = page.locator('[data-slot="resizable-panel"][id="conversation"]');
  const before = (await conversation.boundingBox())!.width;
  const divider = page.getByRole("separator", { name: "调整对话与建模工作区的宽度", exact: true });
  await divider.focus();
  await divider.press("ArrowRight");
  await divider.press("ArrowRight");
  await expect.poll(async () => (await conversation.boundingBox())?.width ?? 0).toBeGreaterThan(before + 20);
  const resized = (await conversation.boundingBox())!.width;
  await page.reload();
  await expect(conversation).toBeVisible();
  await expect.poll(async () => Math.abs(((await conversation.boundingBox())?.width ?? 0) - resized)).toBeLessThan(2);
  await input.fill("E2E_AGENT_BATCH 从原方案比较两种条件");
  await input.press("Enter");
  await expect(page.getByRole("button", { name: "对比本轮方案" })).toBeVisible({ timeout: 60_000 });
  await page.reload();
  await expect(page.getByRole("log")).toContainText("目标值 12");
  await input.fill("E2E_SELECT_ORIGINAL 回到原方案，先不重新计算");
  await input.press("Enter");
  await expect(page.getByRole("button", { name: "已选择：生产计划", exact: true })).toBeVisible();
  expect((await (await page.request.get(`/threads/${chat}`)).json()).values.current).toEqual(first);
  await input.fill("E2E_CHECK_CAPACITY 核对原方案的剩余切割能力");
  await input.press("Enter");
  const calculation = page.getByLabel("计算核对", { exact: true });
  await expect(calculation.locator("strong")).toHaveText("0");
  await calculation.locator("summary").click();
  await expect(calculation.locator("code")).toContainText("v['x[A]']");
  await page.reload();
  await expect(calculation.locator("strong")).toHaveText("0");
  expect((await (await page.request.get(`/threads/${chat}`)).json()).values.current).toEqual(first);
  await page.getByRole("button", { name: "对比本轮方案" }).click();
  await page.waitForURL(/\/compare\//);
  expect(errors).toEqual([]);
});

test("ordinary questions and arithmetic work without creating a modeling plan", async ({ page }) => {
  await page.goto("/agent");
  const input = page.getByRole("textbox", { name: "发送给优化助手" });
  await input.fill("E2E_GENERAL 列表和元组有什么区别？");
  await input.press("Enter");
  await page.waitForURL(/\/agent\//);
  await expect(page.getByRole("log")).toContainText("列表可以修改");
  const id = page.url().split("/").at(-1)!;
  await input.fill("E2E_ARITHMETIC 计算 23789 * 47 - 18635");
  await input.press("Enter");
  const calculation = page.getByLabel("计算核对", { exact: true });
  await expect(calculation.locator("strong")).toHaveText("1,099,448");
  await page.reload();
  await expect(calculation.locator("strong")).toHaveText("1,099,448");
  const saved = await (await page.request.get(`/threads/${id}`)).json();
  expect(saved.values.plans).toEqual([]);
  expect(saved.values.current).toBeNull();
  await expect(page.getByRole("complementary", { name: "建模工作区", exact: true })).toHaveCount(0);
});

test("pinned choices, data edits, retries and saved plans survive reload", async ({ page }) => {
  await page.goto("/agent");
  await page.getByRole("button", { name: "添加数据文件" }).click();
  await page.getByLabel("数据文件", { exact: true }).setInputFiles({ name: "capacity.csv", mimeType: "text/csv", buffer: Buffer.from("capacity\n8\n") });
  await page.getByRole("button", { name: "capacity.csv", exact: true }).click();
  const editor = page.getByRole("dialog", { name: "编辑数据：capacity.csv" });
  await editor.getByRole("textbox", { name: "第 1 列列名" }).fill("capacity（单位）");
  await editor.getByRole("button", { name: "保存数据" }).click();
  await page.getByRole("button", { name: "建模偏好" }).click();
  await page.getByRole("combobox", { name: "固定建模方法" }).click();
  await page.getByRole("option", { name: "Direct", exact: true }).click();
  await page.getByRole("combobox", { name: "固定建模求解器" }).click();
  await page.getByRole("option", { name: "OR-Tools", exact: true }).click();
  const input = page.getByRole("textbox", { name: "发送给优化助手" });
  await input.fill("E2E_AGENT_REPLY_RETRY 请计算生产计划");
  await input.press("Enter");
  await page.waitForURL(/\/agent\//);
  await expect(page.getByText("这轮回复未完成，可以重试。", { exact: true })).toBeVisible({ timeout: 60_000 });
  const id = page.url().split("/").at(-1)!;
  const before = await (await page.request.get(`/threads/${id}`)).json();
  const plan = await (await page.request.get(`/threads/${before.values.current.thread_id}`)).json();
  expect(plan.values.spec.language).toBe("ortools");
  expect(plan.values.solve.objective).toBe(13);
  expect(plan.values.data["capacity.csv"]).toContain("capacity（单位）");
  await input.fill("下一条还没发送的草稿");
  await page.getByRole("button", { name: "重试这一轮" }).click();
  await expect(page.getByRole("log")).toContainText("没有重复求解");
  await expect(input).toHaveValue("下一条还没发送的草稿");
  await page.reload();
  const after = await (await page.request.get(`/threads/${id}`)).json();
  expect(after.values.plans).toHaveLength(1);
  expect(after.values.messages.filter((m: { type: string }) => m.type === "human")).toHaveLength(1);
  await page.getByRole("button", { name: "建模偏好" }).click();
  await expect(page.getByRole("combobox", { name: "固定建模求解器" })).toContainText("OR-Tools");
});

test("an in-flight modeling task shows real steps and can be stopped and retried", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/agent");
  const input = page.getByRole("textbox", { name: "发送给优化助手" });
  await input.fill("E2E_AGENT_PAUSE 请计算生产计划");
  await input.press("Enter");
  await page.waitForURL(/\/agent\//);
  await expect(page.getByText("正在建模求解……", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "查看正在生成的产物" })).toBeVisible();
  await page.getByRole("button", { name: "停止", exact: true }).click();
  await expect(page.getByText("这轮回复已停止，可以重新回答。", { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "重试这一轮" }).click();
  await expect(page.getByRole("log")).toContainText("实际求解结果：13", { timeout: 60_000 });
  await expect(page.getByRole("complementary", { name: "建模工作区" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("search and manual modeling remain available from the agent entry", async ({ page }) => {
  await page.goto("/agent");
  await page.getByRole("button", { name: "联网搜索", exact: true }).click();
  await page.getByRole("textbox", { name: "发送给优化助手" }).fill("E2E_AGENT_SEARCH 请查公开排班参考");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await page.waitForURL(/\/agent\//);
  await expect(page.getByRole("log")).toContainText("公开排班参考");
  await page.getByRole("complementary", { name: "搜索来源" }).locator("summary").click();
  await expect(page.getByRole("link", { name: "排班参考", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "手动建模", exact: true }).click();
  await page.waitForURL(/\/$/);
  await expect(page.getByRole("textbox", { name: "问题描述" })).toBeVisible();
});


test("the original workbench and agent have independent entry points and preserve the manual draft", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("textbox", { name: "问题描述" }).fill("原有工作台的未发送问题");
  await page.getByRole("button", { name: "优化对话", exact: true }).click();
  await page.waitForURL(/\/agent$/);
  await expect(page.getByRole("textbox", { name: "发送给优化助手" })).toBeVisible();
  await page.getByRole("textbox", { name: "发送给优化助手" }).fill("Agent 里另一份未发送草稿");
  await page.getByRole("button", { name: "手动建模", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "问题描述" })).toHaveValue("原有工作台的未发送问题");
  await page.getByRole("button", { name: "优化对话", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "发送给优化助手" })).toHaveValue("Agent 里另一份未发送草稿");
  await page.getByRole("button", { name: "新建建模", exact: true }).click();
  await page.waitForURL(/\/$/);
  await expect(page.getByRole("textbox", { name: "问题描述" })).toHaveValue("原有工作台的未发送问题");
  await page.reload();
  await expect(page.getByRole("textbox", { name: "问题描述" })).toHaveValue("原有工作台的未发送问题");
});

test("the agent entry works on a windowed desktop in English and dark mode", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.addInitScript(() => { localStorage.setItem("llm4om-locale", "en"); localStorage.setItem("theme", "dark"); });
  await page.goto("/agent");
  await expect(page.getByRole("heading", { name: "What would you like to optimize?" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message the optimization assistant" })).toBeVisible();
  await expect(page.locator("html")).toHaveClass(/dark/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
