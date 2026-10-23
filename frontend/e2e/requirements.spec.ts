import { expect, test } from "@playwright/test";

test("requesting prices with search off finishes instead of repeatedly updating the draft", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "通过对话整理需求" }).click();
  await page.waitForURL(/\/chat\//);
  const id = page.url().split("/").at(-1)!;
  await expect(page.getByRole("button", { name: "联网搜索", exact: true })).toContainText("联网搜索未开启");
  await page.getByLabel("发送给需求助手").fill("E2E_LOOP_DRAFT：常见的价格和来源你联网搜索得到，成本按每周算。");
  await page.getByLabel("发送给需求助手").press("Enter");
  await expect(page.getByRole("log")).toContainText("联网搜索未开启，请开启后再查询实时价格");
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeVisible();
  const state = (await (await page.request.get(`/threads/${id}`)).json()).values;
  expect(state.failure).toBeNull();
  expect(state.usage.llm_calls).toBe(2);
  expect(state.messages.filter((message: { name?: string }) => message.name === "update_draft")).toHaveLength(1);
});

test("Enter sends a streamed reply, Shift+Enter adds a line, and composition does not submit", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "通过对话整理需求" }).click();
  await page.waitForURL(/\/chat\//);
  const id = page.url().split("/").at(-1)!;
  await page.getByRole("button", { name: "门店排班", exact: true }).click();
  const input = page.getByLabel("发送给需求助手");
  await expect(input).toBeFocused();
  await input.fill("E2E_STREAM：帮我整理生产计划");
  await input.dispatchEvent("keydown", { key: "Enter", code: "Enter", isComposing: true });
  expect((await (await page.request.get(`/threads/${id}/runs`)).json()).length).toBe(0);
  await input.press("Shift+Enter");
  await expect(input).toHaveValue(/\n$/);
  await input.press("Enter");
  await expect(page.getByRole("log")).toContainText("这是逐字显示的回复。");
  await expect(input).toHaveValue("");
  await expect(input).toBeEditable();
  await expect(page.getByRole("button", { name: "停止", exact: true })).toBeVisible();
  await input.fill("下一条还没有发送的消息");
  await input.press("Enter");
  await expect(page.getByRole("log")).not.toContainText("流式回复已经完整输出");
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeVisible();
  await expect(input).toHaveValue("下一条还没有发送的消息");
  await expect(page.getByRole("log")).toContainText("流式回复已经完整输出");
  await page.reload();
  await expect(input).toHaveValue("下一条还没有发送的消息");
  await expect(page.getByRole("log").getByRole("article", { name: "需求助手" })).toHaveCount(1);
  expect((await (await page.request.get(`/threads/${id}`)).json()).values.messages).toHaveLength(4);
});

test("web search shows actual tool sources and preserves them on reload without solving", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "通过对话整理需求" }).click();
  await page.waitForURL(/\/chat\//);
  const id = page.url().split("/").at(-1)!;
  await page.getByRole("button", { name: "联网搜索", exact: true }).click();
  await page.getByLabel("发送给需求助手").fill("E2E_SEARCH：查一下门店排班有哪些公开资料。");
  await page.getByLabel("发送给需求助手").press("Enter");
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeVisible();
  const sources = page.getByRole("complementary", { name: "搜索来源" });
  await expect(sources.locator("details")).not.toHaveAttribute("open");
  await sources.locator("summary").click();
  await expect(sources.getByRole("link", { name: "排班参考" })).toHaveAttribute("href", "https://example.org/shift-guide");
  await expect(sources).toContainText("1 个来源");
  await expect(page.getByRole("log")).toContainText("请确认是否把这些建议用于你的门店");
  await page.reload();
  await sources.locator("summary").click();
  await expect(sources).toContainText("example.org");
  await expect(page.getByRole("button", { name: "联网搜索", exact: true })).toHaveAttribute("aria-pressed", "true");
  const state = (await (await page.request.get(`/threads/${id}`)).json()).values;
  expect(state.usage.solves).toBe(0);
  expect(state.messages.filter((message: { type: string }) => message.type === "human")).toHaveLength(1);
  expect(state.messages.find((message: { name?: string }) => message.name === "web_search").artifact.results).toHaveLength(1);
  expect(JSON.stringify(state)).not.toContain("e2e-search-key");
});

test("a requirements conversation persists its editable draft and hands only the problem and files to modeling", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(String(error)));
  await page.goto("/");
  await page.getByRole("button", { name: "通过对话整理需求" }).click();
  await page.waitForURL(/\/chat\//);
  const chatUrl = page.url();
  const id = chatUrl.split("/").at(-1)!;
  const initial = await (await page.request.get(`/threads/${id}`)).json();
  expect(initial.metadata.kind).toBe("requirements");
  expect(initial.values.messages).toEqual([]);
  expect((await (await page.request.get(`/threads/${id}/runs`)).json()).length).toBe(0);
  await page.getByLabel("发送给需求助手").fill("我想安排工厂 A、B 两种产品的生产，希望利润高一些。CHAT_ONLY_MARKER");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("log")).toContainText("每件产品的利润和资源消耗是多少");
  await expect(page.getByLabel("问题描述")).toHaveValue(/待确认/);

  await page.getByLabel("添加附件").setInputFiles({ name: "costs.csv", mimeType: "text/csv", buffer: Buffer.from("product,profit\nA,3\nB,2\n") });
  await expect(page.getByText("costs.csv", { exact: true })).toBeVisible();
  await page.getByLabel("发送给需求助手").fill("A 利润 3，B 利润 2，A 消耗切割 2、加工 1；B 消耗切割 1、加工 2，两种资源各有 8 单位，数量必须为非负整数。");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("log")).toContainText("可以检查需求稿并用于建模");
  const edited = (await page.getByLabel("问题描述").inputValue()) + "\n\n产量按件计，利润按元计。";
  await page.getByLabel("问题描述").fill(edited);
  await page.getByRole("button", { name: "保存需求稿", exact: true }).click();
  await expect.poll(async () => (await (await page.request.get(`/threads/${id}`)).json()).values.description).toBe(edited);
  await page.reload();
  await expect(page.getByLabel("问题描述")).toHaveValue(edited);
  await expect(page.getByRole("log").getByText("需求助手", { exact: true })).toHaveCount(2);
  await expect(page.getByText("costs.csv", { exact: true })).toBeVisible();
  const saved = (await (await page.request.get(`/threads/${id}`)).json()).values;
  expect(saved.messages).toHaveLength(8);
  expect(saved.usage.solves).toBe(0);

  await page.getByRole("button", { name: "用于建模", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByLabel("问题描述")).toHaveValue(edited);
  expect((await (await page.request.get(`/threads/${id}/runs`)).json()).length).toBe(2);
  await page.getByRole("button", { name: "查看运行设置", exact: true }).click();
  await page.getByRole("radio", { name: "Feedback Repair", exact: true }).check();
  await page.getByRole("button", { name: "完成", exact: true }).click();
  await page.getByRole("button", { name: /^开始建模/ }).click();
  await page.waitForURL(/\/run\//);
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeVisible({ timeout: 60_000 });
  const runId = page.url().split("/").at(-1)!;
  expect(runId).not.toBe(id);
  const result = (await (await page.request.get(`/threads/${runId}`)).json()).values;
  expect(result.description).toBe(edited);
  expect(result.data).toEqual(saved.data);
  expect(result.solve.objective).toBe(13);
  expect(JSON.stringify(result)).not.toContain("CHAT_ONLY_MARKER");
  expect((await (await page.request.get(`/threads/${id}`)).json()).values).toEqual(saved);

  await page.getByLabel("搜索运行").fill("CHAT_ONLY_MARKER");
  await page.getByRole("navigation").getByRole("button", { name: /^我想安排.*CHAT_ONLY_MARKER.*需求对话/ }).click();
  await expect(page).toHaveURL(chatUrl);
  await expect(page.getByLabel("问题描述")).toHaveValue(edited);
  expect(errors).toEqual([]);
});

test("the requirements assistant retries a failed turn and keeps the editable problem without starting a solve", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByLabel("问题描述").fill("保留原需求稿");
  await page.getByRole("button", { name: "通过对话整理需求" }).click();
  await page.waitForURL(/\/chat\//);
  const id = page.url().split("/").at(-1)!;
  await page.getByLabel("发送给需求助手").fill("E2E_CHAT_RETRY：请帮我整理生产计划");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  const retry = page.getByRole("button", { name: "重试这一轮", exact: true });
  await expect(retry).toBeVisible();
  const failed = (await (await page.request.get(`/threads/${id}`)).json()).values;
  expect(failed.description).toBe("保留原需求稿");
  expect(failed.messages).toHaveLength(1);
  await retry.click();
  await expect(page.getByRole("log")).toContainText("可以检查需求稿并用于建模");
  const result = (await (await page.request.get(`/threads/${id}`)).json()).values;
  expect(result.messages).toHaveLength(4);
  expect(result.usage.solves).toBe(0);
  for (const [width, height] of [[1024, 768], [1366, 768], [1440, 900], [1920, 1080], [3440, 1440]]) {
    await page.setViewportSize({ width, height });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const send = await page.getByRole("button", { name: "发送", exact: true }).boundingBox();
    expect(send).not.toBeNull();
    expect(send!.y + send!.height).toBeLessThanOrEqual(height);
  }
  await page.setViewportSize({ width: 375, height: 812 });
  await page.getByRole("tab", { name: "问题与数据", exact: true }).click();
  await expect(page.getByLabel("问题描述")).toHaveValue(result.description);
  await page.getByRole("tab", { name: "预览", exact: true }).click();
  await expect(page.getByRole("tabpanel", { name: "预览", exact: true })).toContainText("总利润最大");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("tab", { name: "需求助手", exact: true }).click();
  await page.getByRole("button", { name: "用于建模", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByLabel("问题描述")).toHaveValue(result.description);
  expect((await (await page.request.get(`/threads/${id}/runs`)).json()).length).toBe(2);
});

test("a failed draft save keeps the user's edit and prevents handing off stale text", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("问题描述").fill("原需求稿");
  await page.getByRole("button", { name: "通过对话整理需求" }).click();
  await page.waitForURL(/\/chat\//);
  const url = page.url(), id = url.split("/").at(-1)!;
  await expect(page.getByLabel("问题描述")).toBeEnabled();
  await page.route(`**/threads/${id}/state`, async route => {
    if (route.request().method() === "POST") await route.fulfill({ status: 400, contentType: "application/json", body: '{"detail":"save rejected"}' });
    else await route.continue();
  });
  await page.getByLabel("问题描述").fill("人工修改：晚班至少 3 人，不得放宽。");
  await page.getByRole("button", { name: "用于建模", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("需求稿未保存");
  await expect(page).toHaveURL(url);
  await expect(page.getByLabel("问题描述")).toHaveValue("人工修改：晚班至少 3 人，不得放宽。");
  expect((await (await page.request.get(`/threads/${id}`)).json()).values.description).toBe("原需求稿");
  await page.unroute(`**/threads/${id}/state`);
  await page.getByRole("button", { name: "保存需求稿", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel("问题描述")).toHaveValue("人工修改：晚班至少 3 人，不得放宽。");
});

test("stopping a requirements turn keeps the question and draft available after reload", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("问题描述").fill("原需求稿：整数生产计划");
  await page.getByRole("button", { name: "通过对话整理需求" }).click();
  await page.waitForURL(/\/chat\//);
  const id = page.url().split("/").at(-1)!;
  await page.getByLabel("发送给需求助手").fill("E2E_PAUSE_CHAT：继续整理");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect.poll(async () => (await (await page.request.get(`/threads/${id}/state`)).json()).values.messages?.length).toBe(1);
  await page.getByRole("button", { name: "停止", exact: true }).click();
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("问题描述")).toHaveValue("原需求稿：整数生产计划");
  await expect(page.getByRole("log")).toContainText("E2E_PAUSE_CHAT：继续整理");
  await expect(page.getByRole("log")).toContainText("这轮回复已停止，可以重新回答。");
  const input = page.getByLabel("发送给需求助手");
  await input.fill("下一轮尚未发送的想法");
  await page.getByRole("button", { name: "重试这一轮", exact: true }).click();
  await expect(page.getByRole("log")).toContainText("每件产品的利润和资源消耗是多少");
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeVisible();
  await expect(input).toHaveValue("下一轮尚未发送的想法");
  const state = (await (await page.request.get(`/threads/${id}`)).json()).values;
  expect(state.messages).toHaveLength(4);
  expect(state.messages.filter((message: { type: string }) => message.type === "human")).toHaveLength(1);
  await expect(page.getByRole("button", { name: "重试这一轮", exact: true })).toHaveCount(0);
});

test("refreshing during a reply reconnects the same run and keeps the next unsent message", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "通过对话整理需求" }).click();
  await page.waitForURL(/\/chat\//);
  const id = page.url().split("/").at(-1)!;
  const input = page.getByLabel("发送给需求助手");
  await input.fill("E2E_STREAM：帮我整理生产计划"); await input.press("Enter");
  await expect(page.getByRole("log")).toContainText("这是逐字显示的回复。");
  await input.fill("刷新时也要保留这条草稿");
  await page.reload();
  await expect(input).toHaveValue("刷新时也要保留这条草稿");
  await expect(page.getByRole("log")).toContainText("流式回复已经完整输出");
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeVisible();
  expect((await (await page.request.get(`/threads/${id}/runs`)).json()).length).toBe(1);
  const state = (await (await page.request.get(`/threads/${id}`)).json()).values;
  expect(state.messages).toHaveLength(4);
});

test("stopping a queued conversation keeps the question before its first input checkpoint", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "通过对话整理需求" }).click();
  await page.waitForURL(/\/chat\//);
  const id = page.url().split("/").at(-1)!;
  const blocker = await (await page.request.post("/threads", { data: {} })).json();
  const run = await (await page.request.post(`/threads/${blocker.thread_id}/runs`, { data: {
    assistant_id: "requirements", input: { description: "", messages: [{ type: "human", content: "E2E_HOLD_CHAT：占用一个执行槽" }] },
    context: { preset: "env", locale: "zh" },
  } })).json();
  try {
    await expect.poll(async () => (await (await page.request.get(`/threads/${blocker.thread_id}/runs/${run.run_id}`)).json()).status).toBe("running");
    const input = page.getByLabel("发送给需求助手");
    const question = "这条排队中的问题还没有保存，不应该被清空。";
    await input.fill(question); await input.press("Enter");
    await expect.poll(async () => (await (await page.request.get(`/threads/${id}/runs`)).json())[0]?.status).toBe("pending");
    await expect(input).toHaveValue(question);
    await page.getByRole("button", { name: "停止", exact: true }).click();
    await expect(page.getByRole("button", { name: "发送", exact: true })).toBeVisible({ timeout: 30_000 });
    await page.reload();
    await expect(input).toHaveValue("");
    await expect(page.getByRole("button", { name: "重试这一轮", exact: true })).toBeVisible();
    const messages = (await (await page.request.get(`/threads/${id}`)).json()).values.messages;
    expect(messages).toHaveLength(1);
    expect(messages[0].content).toBe(question);
  } finally {
    await page.request.post(`/threads/${blocker.thread_id}/runs/${run.run_id}/cancel?wait=true`);
    await page.request.delete(`/threads/${blocker.thread_id}`);
  }
});
