import { expect, test, type Page } from "@playwright/test";

async function production(page: Page) {
  await page.goto("/");
  await page.getByRole("main").getByRole("button", { name: /^生产计划/ }).click();
  await page.getByRole("button", { name: /^开始建模/ }).click();
  await page.waitForURL(/\/run\//);
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeVisible({ timeout: 60_000 });
  return page.url().split("/").at(-1)!;
}

test("a phone opens the requested conversation and shows a chosen plan immediately", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await production(page);
  await page.getByRole("button", { name: "讨论方案", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "发送给方案助手" })).toBeVisible({ timeout: 2000 });
  await page.getByLabel("已生成的方案").locator("summary").click();
  await page.getByRole("button", { name: "打开原运行", exact: true }).click();
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeVisible();
});

test("a phone reviews the requirements draft before starting a modeling run", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "通过对话整理需求" }).click();
  const input = page.getByRole("textbox", { name: "发送给需求助手" });
  await expect(page.getByRole("button", { name: "查看运行设置" })).toBeHidden();
  await expect(input).toBeInViewport();
  await input.fill("我想安排工厂 A、B 两种产品的生产。");
  await input.press("Enter");
  await expect(page.getByRole("log")).toContainText("每件产品的利润和资源消耗是多少");
  const count = await (await page.request.post("/threads/count", { data: {} })).json();
  await page.getByRole("button", { name: "检查需求稿", exact: true }).click({ timeout: 2000 });
  await expect(page.getByRole("textbox", { name: "问题描述" })).toBeVisible();
  await expect(page.getByRole("button", { name: "查看运行设置" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^开始建模/ })).toBeInViewport();
  expect(await (await page.request.post("/threads/count", { data: {} })).json()).toBe(count);
});

test("opening the original of a revised plan preserves the displayed baseline checkpoint", async ({ page }) => {
  const original = await production(page);
  const state = await (await page.request.get(`/threads/${original}/state`)).json();
  await page.getByRole("button", { name: "调整条件", exact: true }).click();
  await page.getByRole("textbox", { name: "要调整什么？" }).fill("B 至少生产 3 件，其他条件保持不变。");
  await page.getByRole("button", { name: "生成新方案", exact: true }).click();
  await page.waitForURL(url => !url.pathname.endsWith(original));
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeVisible({ timeout: 60_000 });
  await page.request.post(`/threads/${original}/state`, { data: { as_node: "finish", values: {
    solve: { ...state.values.solve, objective: 99 }, explanation: null,
  } } });
  await page.getByRole("tab", { name: "方案对比", exact: true }).click();
  await page.getByRole("link", { name: "打开原运行", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`checkpoint=${state.checkpoint.checkpoint_id}`));
});

test("requirements keep conversation on the left and retain draft input across layout changes", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "通过对话整理需求" }).click();
  const input = page.getByRole("textbox", { name: "发送给需求助手" });
  const draft = page.getByRole("textbox", { name: "问题描述" });
  await expect(input).toBeVisible();
  const before = (await input.boundingBox())!;
  expect(before.x).toBeLessThan((await draft.boundingBox())!.x);
  const divider = page.getByRole("separator", { name: "调整对话与需求稿的宽度" });
  await divider.focus();
  await divider.press("ArrowRight");
  await divider.press("ArrowRight");
  await expect.poll(async () => (await input.boundingBox())!.width).toBeGreaterThan(before.width + 20);
  const resized = (await input.boundingBox())!.width;
  await page.reload();
  await expect.poll(async () => Math.abs((await input.boundingBox())!.width - resized)).toBeLessThan(2);
  await input.fill("下一条尚未发送的想法");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("tab", { name: "当前需求稿", exact: true }).click();
  await expect(draft).toBeVisible();
  await page.getByRole("tab", { name: "需求助手", exact: true }).click();
  await expect(input).toHaveValue("下一条尚未发送的想法");
});

test("the original row in a scenario comparison opens its frozen baseline", async ({ page }) => {
  const original = await production(page);
  const state = await (await page.request.get(`/threads/${original}/state`)).json();
  await page.getByRole("button", { name: "业务场景对比", exact: true }).click();
  await page.getByRole("textbox", { name: "场景 1 调整要求" }).fill("B 至少生产 3 件");
  await page.getByRole("textbox", { name: "场景 2 调整要求" }).fill("B 至少生产 4 件");
  await page.getByRole("button", { name: "计算并对比" }).click();
  await page.waitForURL(/\/compare\//);
  const open = page.getByRole("button", { name: "打开方案：原方案", exact: true });
  await expect(open).toBeVisible();
  await page.request.post(`/threads/${original}/state`, { data: { as_node: "finish", values: {
    solve: { ...state.values.solve, objective: 99 }, explanation: null,
  } } });
  await open.click();
  await expect(page).toHaveURL(new RegExp(`checkpoint=${state.checkpoint.checkpoint_id}`));
});
