import { expect, test, type Page } from "@playwright/test";

async function production(page: Page) {
  await page.goto("/");
  await page.getByRole("main").getByRole("button", { name: /^生产计划/ }).click();
  await page.getByRole("button", { name: /^开始建模/ }).click();
  await page.waitForURL(/\/run\//);
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeVisible({ timeout: 60_000 });
  return page.url();
}

test("desktop results keep modeling central and present adjustment actions together", async ({ page }) => {
  await production(page);
  for (const width of [1024, 1366, 1440, 1920]) {
    await page.setViewportSize({ width, height: 812 });
    const actions = page.getByRole("group", { name: "运行操作", exact: true });
    const buttons = await actions.getByRole("button").all();
    const boxes = await Promise.all(buttons.map(button => button.boundingBox()));
    expect(new Set(boxes.map(box => box!.y)).size).toBe(1);
    expect((await page.locator("main header").boundingBox())!.height).toBeLessThan(150);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.getByText("运行信息", { exact: true }).click();
  await expect(page.locator("main header")).toContainText("deepseek-v4.1 flash-1017");
  await page.getByText("完整变量取值（2 个）", { exact: true }).click();
  await expect(page.getByLabel("筛选变量")).toBeVisible();
  await expect(page.getByRole("button", { name: "业务场景对比", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "更多操作", exact: true }).click();
  await expect(page.getByRole("menuitem", { name: "再运行一次", exact: true })).toBeVisible();
});

test("desktop configuration is compact by default and retains the selected method", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "查看运行设置", exact: true })).toBeInViewport();
  await page.getByRole("button", { name: "查看运行设置", exact: true }).click();
  const settings = page.getByRole("complementary", { name: "运行设置", exact: true });
  await expect(settings).toBeInViewport();
  await page.getByRole("radio", { name: "OptiMind", exact: true }).check();
  await page.reload();
  await page.getByRole("button", { name: "查看运行设置", exact: true }).click();
  const selected = page.getByRole("radio", { name: "OptiMind", exact: true });
  await expect(selected).toBeChecked();
  const box = (await selected.boundingBox())!, list = (await page.getByRole("radiogroup", { name: "建模方法", exact: true }).boundingBox())!;
  expect(box.y).toBeGreaterThanOrEqual(list.y);
  expect(box.y + box.height).toBeLessThanOrEqual(list.y + list.height);
});

test("clearing the problem can be undone with its attachments", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("问题描述").fill("需要保留的生产计划");
  await page.locator('input[type="file"]').setInputFiles({ name: "costs.csv", mimeType: "text/csv", buffer: Buffer.from("name,cost\nA,3\n") });
  await page.getByRole("button", { name: "清空", exact: true }).click();
  await expect(page.getByLabel("问题描述")).toHaveValue("");
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(page.getByLabel("问题描述")).toHaveValue("需要保留的生产计划");
  await expect(page.getByRole("button", { name: "编辑 costs.csv", exact: true })).toBeVisible();
});

test("desktop editing retains the cursor through preview and respects composition before Ctrl+Enter", async ({ page }) => {
  await page.goto("/");
  const input = page.getByLabel("问题描述");
  await expect(input).toBeFocused();
  await input.fill("# 生产计划\n\n" + Array.from({ length: 35 }, (_, i) => `第 ${i + 1} 项业务条件。`).join("\n"));
  await input.evaluate(node => { const field = node as HTMLTextAreaElement; field.setSelectionRange(14, 20); field.scrollTop = 80; });
  await page.getByRole("tab", { name: "预览", exact: true }).click();
  await page.getByRole("tab", { name: "编辑", exact: true }).click();
  expect(await input.evaluate(node => [(node as HTMLTextAreaElement).selectionStart, (node as HTMLTextAreaElement).selectionEnd, node.scrollTop])).toEqual([14, 20, 80]);
  await input.dispatchEvent("keydown", { key: "Enter", ctrlKey: true, isComposing: true });
  await expect(page).toHaveURL(/\/$/);
  await input.press("Control+Enter");
  await page.waitForURL(/\/run\//);
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeVisible({ timeout: 60_000 });
});

test("desktop panel widths can be adjusted with the keyboard and survive reopening a run", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const url = await production(page);
  await page.getByRole("button", { name: "建模过程", exact: true }).click();
  const panels = page.locator('[data-slot="resizable-panel"]');
  const before = (await panels.first().boundingBox())!.width;
  expect((await panels.last().boundingBox())!.width).toBeGreaterThan(before);
  const divider = page.getByRole("separator", { name: "调整过程与结果的宽度", exact: true });
  await divider.focus();
  await divider.press("ArrowRight");
  await divider.press("ArrowRight");
  await expect.poll(async () => (await panels.first().boundingBox())!.width).toBeGreaterThan(before + 20);
  const resized = (await panels.first().boundingBox())!.width;
  await page.goto("/");
  await page.goto(url);
  await page.getByRole("button", { name: "建模过程", exact: true }).click();
  await expect.poll(async () => Math.abs((await panels.first().boundingBox())!.width - resized)).toBeLessThan(2);
});

test("unsent messages survive navigation and reload and stay separate for each conversation", async ({ page }) => {
  const runUrl = await production(page);
  await page.getByRole("button", { name: "讨论方案", exact: true }).click();
  await page.waitForURL(/\/discussion\//);
  const discussion = page.url();
  await page.getByLabel("发送给方案助手").fill("方案对话还没发送的条件");
  await page.goto("/");
  await page.getByRole("button", { name: "通过对话整理需求", exact: true }).click();
  await page.waitForURL(/\/chat\//);
  const chat = page.url();
  await expect(page.getByLabel("发送给需求助手")).toHaveValue("");
  await page.getByLabel("发送给需求助手").fill("需求对话还没发送的想法");
  await page.goto(discussion);
  await expect(page.getByLabel("发送给方案助手")).toHaveValue("方案对话还没发送的条件");
  await page.reload();
  await expect(page.getByLabel("发送给方案助手")).toHaveValue("方案对话还没发送的条件");
  await page.goto(chat);
  await expect(page.getByLabel("发送给需求助手")).toHaveValue("需求对话还没发送的想法");
  const id = chat.split("/").at(-1)!;
  expect((await (await page.request.get(`/threads/${id}`)).json()).values.messages).toEqual([]);
  await page.goto(runUrl);
  await page.getByRole("button", { name: "讨论方案", exact: true }).click();
  await expect(page).toHaveURL(discussion);
});

test("example navigation stays visible without scrolling through the whole page", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await page.getByRole("button", { name: "从题库选题", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "示例题库", exact: true });
  await expect(dialog.getByRole("button", { name: "下一页", exact: true })).toBeInViewport();
  await dialog.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(dialog).toContainText("21–40");
  await expect(dialog.getByRole("button", { name: "上一页", exact: true })).toBeInViewport();
});

test("a preset can be added with Enter and its submission cannot be interrupted or duplicated", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "查看运行设置", exact: true }).click();
  await page.getByRole("button", { name: "管理", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "预设模型", exact: true });
  await dialog.getByRole("button", { name: "添加预设", exact: true }).click();
  await page.getByLabel("接口地址", { exact: true }).fill("http://127.0.0.1:8796/v1");
  await page.getByLabel("API 密钥", { exact: true }).fill("test-key");
  await page.getByLabel("预设名称", { exact: true }).fill("Usability test");
  await page.getByLabel("模型 ID", { exact: true }).fill("mock-model");
  await page.getByRole("button", { name: "高级参数", exact: true }).click();
  let writes = 0;
  await page.route("**/api/presets", async route => {
    if (route.request().method() === "POST") { writes++; await new Promise(resolve => setTimeout(resolve, 1000)); }
    await route.continue();
  });
  await page.getByLabel("模型 ID", { exact: true }).press("Enter");
  await expect(page.getByLabel("模型 ID", { exact: true })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Usability test", exact: true })).toBeVisible();
  expect(writes).toBe(1);
  const saved = (await (await page.request.get("/api/presets")).json()).presets.find((preset: { name: string }) => preset.name === "Usability test");
  await page.request.delete(`/api/presets/${saved.id}`);
});

test("a preset loading error can be retried without opening an empty configuration form", async ({ page }) => {
  let failed = true;
  await page.route("**/api/presets", route => failed
    ? route.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"temporarily unavailable"}' }) : route.continue());
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("预设模型加载失败", { timeout: 15_000 });
  await expect(page.getByText("还没有预设模型。", { exact: true })).toHaveCount(0);
  failed = false;
  await page.getByRole("alert").getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "查看运行设置", exact: true })).toContainText("deepseek-v4.1 flash-1017");
});

test.describe("windowed desktop navigation", () => {
  test.use({ viewport: { width: 1024, height: 768 } });
  test("history search and row actions work through nested menus and drawer reopening", async ({ page }) => {
    await production(page);
    await page.getByRole("button", { name: "打开菜单", exact: true }).click();
    const drawer = page.getByRole("dialog", { name: "导航", exact: true });
    await drawer.getByLabel("搜索运行").fill("Direct");
    await drawer.getByRole("navigation").getByRole("button", { name: /^工厂生产/ }).first().click();
    await page.getByRole("button", { name: "打开菜单", exact: true }).click();
    await expect(drawer.getByLabel("搜索运行")).toHaveValue("Direct");
    const more = drawer.getByRole("button", { name: /^更多操作：/ }).first();
    await more.hover();
    await more.click();
    await expect(page.getByRole("menuitem", { name: "删除", exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(drawer).toBeVisible();
    await drawer.getByRole("button", { name: "清除搜索", exact: true }).click();
    await expect(drawer.getByLabel("搜索运行")).toHaveValue("");
    await drawer.getByRole("button", { name: "Close", exact: true }).click();
    await expect(drawer).toBeHidden();
    await page.getByRole("button", { name: "打开菜单", exact: true }).click();
    await expect(drawer.getByLabel("搜索运行")).toHaveValue("");
  });
});

test("a failed page chunk offers a reload and preserves the saved problem", async ({ page }) => {
  await page.route("**/assets/Requirements-*.js", route => route.fulfill({ status: 503, body: "temporarily unavailable" }));
  await page.goto("/");
  await page.getByLabel("问题描述").fill("已经写好的需求不能因为页面加载失败而丢失");
  await page.getByRole("button", { name: "通过对话整理需求", exact: true }).click();
  await page.waitForURL(/\/chat\//);
  await expect(page.getByRole("alert")).toContainText("页面未能加载");
  await page.unroute("**/assets/Requirements-*.js");
  await page.getByRole("button", { name: "重新加载", exact: true }).click();
  await expect(page.getByLabel("问题描述")).toHaveValue("已经写好的需求不能因为页面加载失败而丢失");
});

test("the requirements draft runs in the modeling workbench and related history retains its source", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "通过对话整理需求", exact: true }).click();
  await page.waitForURL(/\/chat\//);
  const chat = page.url().split("/").at(-1)!;
  const input = page.getByLabel("发送给需求助手");
  await input.fill("两种资源各有 8 单位，A、B 利润 3 和 2，产量是整数。CHAT_WORKSPACE_ONLY");
  await input.press("Control+Enter");
  await expect(page.getByRole("log")).toContainText("可以检查需求稿并用于建模");
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/chat/${chat}$`));
  expect((await (await page.request.get(`/threads/${chat}/runs`)).json()).length).toBe(1);
  await page.getByRole("button", { name: "收起需求助手", exact: true }).click();
  const problem = "# 工作区关联验证\n\n" + await page.getByLabel("问题描述").inputValue();
  await page.getByLabel("问题描述").fill(problem);
  await page.getByRole("button", { name: /^开始建模/ }).click();
  await page.waitForURL(/\/run\//);
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeVisible({ timeout: 60_000 });
  const saved = await (await page.request.get(`/threads/${page.url().split("/").at(-1)}`)).json();
  expect(saved.metadata.origin).toBe(chat);
  expect(saved.values.description).toBe(problem);
  expect(saved.values.solve.objective).toBe(13);
  expect(JSON.stringify(saved.values)).not.toContain("CHAT_WORKSPACE_ONLY");
  const navigation = page.getByRole("navigation", { name: "运行记录", exact: true });
  const related = navigation.getByRole("button", { name: "相关记录：工作区关联验证", exact: true });
  await expect(related).toHaveAttribute("aria-expanded", "false");
  await related.click();
  await expect(navigation.getByRole("button", { name: /CHAT_WORKSPACE_ONLY.*需求对话/ })).toBeVisible();
  await related.click();
  await expect(navigation.getByRole("button", { name: /CHAT_WORKSPACE_ONLY.*需求对话/ })).toHaveCount(0);
});
