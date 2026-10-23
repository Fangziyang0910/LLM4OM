import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

const problem = "工厂生产 A、B 两种产品，产量是非负整数。每件 A 利润 3 元，B 利润 2 元。A 消耗切割 2、加工 1；B 消耗切割 1、加工 2。两种资源各有 8 单位。最大化总利润。";

async function production(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByLabel("问题描述").fill(problem);
  await page.getByRole("button", { name: /^开始建模/ }).click();
  await page.waitForURL(/\/run\//);
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeVisible({ timeout: 60_000 });
  return page.url().split("/").at(-1)!;
}

test("data can be reviewed and edited before modeling, with cancel and immutable saved inputs", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await page.getByLabel("问题描述").fill("根据 prices.csv 中的利润安排 A、B 的非负整数产量。A 消耗切割 2、加工 1；B 消耗切割 1、加工 2。两种资源各有 8 单位。最大化总利润。");
  await page.locator('input[type="file"]').setInputFiles({ name: "prices.csv", mimeType: "text/csv", buffer: Buffer.from("product,profit\nA,3\nB,2\n") });
  await page.getByRole("button", { name: "编辑 prices.csv", exact: true }).click();
  await page.getByLabel("第 1 行，第 2 列", { exact: true }).fill("9");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await page.getByRole("button", { name: "编辑 prices.csv", exact: true }).click();
  await expect(page.getByLabel("第 1 行，第 2 列", { exact: true })).toHaveValue("3");
  await page.getByLabel("第 2 列列名").fill("单件利润（元）");
  await page.getByLabel("第 1 行，第 2 列", { exact: true }).fill("5");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "保存数据", exact: true }).click();
  await page.getByRole("button", { name: /^开始建模/ }).click();
  await page.waitForURL(/\/run\//);
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeVisible({ timeout: 60_000 });
  const id = page.url().split("/").at(-1)!;
  const saved = (await (await page.request.get(`/threads/${id}`)).json()).values;
  expect(saved.data["prices.csv"]).toBe("product,单件利润（元）\nA,5\nB,2\n");
  expect(saved.solve.objective).toBe(20);
  await page.getByRole("button", { name: "更多操作", exact: true }).click();
  await page.getByRole("menuitem", { name: "修改后运行", exact: true }).click();
  await page.getByRole("button", { name: "编辑 prices.csv", exact: true }).click();
  await page.getByLabel("第 1 行，第 2 列", { exact: true }).fill("7");
  await page.getByRole("button", { name: "保存数据", exact: true }).click();
  expect((await (await page.request.get(`/threads/${id}`)).json()).values.data).toEqual(saved.data);
});

test("requirements file edits persist, and a rejected save can be cancelled without changing the attachment", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "通过对话整理需求" }).click();
  await page.waitForURL(/\/chat\//);
  const id = page.url().split("/").at(-1)!;
  await page.getByLabel("添加附件").setInputFiles({ name: "costs.csv", mimeType: "text/csv", buffer: Buffer.from("product,profit\nA,3\nB,2\n") });
  await page.getByRole("button", { name: "编辑 costs.csv", exact: true }).click();
  await page.getByLabel("第 1 行，第 2 列", { exact: true }).fill("5");
  await page.getByRole("button", { name: "保存数据", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.reload();
  await page.getByRole("button", { name: "编辑 costs.csv", exact: true }).click();
  await expect(page.getByLabel("第 1 行，第 2 列", { exact: true })).toHaveValue("5");
  await page.route(`**/threads/${id}/state`, route => route.request().method() === "POST"
    ? route.fulfill({ status: 400, contentType: "application/json", body: '{"detail":"save rejected"}' }) : route.continue());
  await page.getByLabel("第 1 行，第 2 列", { exact: true }).fill("9");
  await page.getByRole("button", { name: "保存数据", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("save rejected");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await page.getByRole("button", { name: "编辑 costs.csv", exact: true }).click();
  await expect(page.getByLabel("第 1 行，第 2 列", { exact: true })).toHaveValue("5");
});

test("a plan conversation explains actual values, computes changes and continues from the new plan with one server worker", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(String(error)));
  const sourceId = await production(page);
  const original = (await (await page.request.get(`/threads/${sourceId}`)).json()).values;
  await page.getByRole("button", { name: "讨论方案", exact: true }).click();
  await page.waitForURL(/\/discussion\//);
  const chatUrl = page.url(), id = chatUrl.split("/").at(-1)!;
  const input = page.getByLabel("发送给方案助手");
  await input.fill("请解释主要决策"); await input.press("Enter");
  await expect(page.getByRole("log")).toContainText("x[B] = 2");
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeVisible();
  expect((await (await page.request.get(`/threads/${id}`)).json()).values.plans).toHaveLength(0);
  await input.fill("B 至少生产 3 件，其他条件不变，帮我计算新方案。"); await input.press("Enter");
  await expect(page.getByRole("log")).toContainText("目标值 12", { timeout: 60_000 });
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeVisible();
  await expect(page.getByRole("log")).not.toContainText("def build_model");
  const state = (await (await page.request.get(`/threads/${id}`)).json()).values;
  expect(state.plans).toHaveLength(1);
  const derived = (await (await page.request.get(`/threads/${state.plans[0].source.thread_id}`)).json()).values;
  expect(derived.solve).toMatchObject({ objective: 12, status: "optimal", variables: { "x[A]": 2, "x[B]": 3 } });
  expect(derived.spec.method).toBe(original.spec.method);
  expect(derived.data).toEqual(original.data);
  expect((await (await page.request.get(`/threads/${sourceId}`)).json()).values).toEqual(original);
  await page.reload();
  await expect(page.getByRole("log")).toContainText("目标值 12");
  const assistant = page.getByRole("complementary", { name: "方案助手", exact: true });
  await assistant.getByText("相关方案 · 2", { exact: true }).click();
  await assistant.getByRole("button", { name: "打开原运行", exact: true }).click();
  await expect(page).toHaveURL(chatUrl);
  await expect(page.getByText("总利润", { exact: true }).locator("..")).toContainText("13");
  await expect(page.getByLabel("当前讨论方案", { exact: true })).toContainText("12");
  await input.fill("请查询现在的实际决策值"); await input.press("Enter");
  await expect(page.getByRole("log")).toContainText("x[B] = 3");
  await expect(page.getByLabel("当前讨论方案", { exact: true })).toContainText("12");
  await page.getByRole("button", { name: "更多操作", exact: true }).click();
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("menuitem", { name: "导出报告（Markdown）", exact: true }).click()]);
  const report = await readFile((await download.path())!, "utf8");
  expect(report).toContain(`/run/${state.plans[0].source.thread_id}`);
  expect(report).not.toContain(`/discussion/${id}`);
  await page.getByRole("complementary", { name: "方案助手", exact: true }).getByRole("button", { name: "收起方案助手", exact: true }).click();
  await page.waitForURL(/\/run\//);
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "更多操作", exact: true }).click();
  await page.getByRole("menuitem", { name: "返回方案对话", exact: true }).click();
  await expect(page).toHaveURL(chatUrl);
  expect(errors).toEqual([]);
});

test("a business scenario comparison keeps one frozen baseline and shows actual decisions", async ({ page }) => {
  const sourceId = await production(page);
  const original = (await (await page.request.get(`/threads/${sourceId}`)).json()).values;
  await page.getByRole("button", { name: "业务场景对比", exact: true }).click();
  await page.getByLabel("场景 1 名称", { exact: true }).fill("B 至少 3 件");
  await page.getByLabel("场景 1 调整要求", { exact: true }).fill("B 至少生产 3 件");
  await page.getByLabel("场景 2 名称", { exact: true }).fill("B 至少 4 件");
  await page.getByLabel("场景 2 调整要求", { exact: true }).fill("B 至少生产 4 件");
  await page.getByRole("button", { name: "计算并对比", exact: true }).click();
  await page.waitForURL(/\/compare\//);
  await expect(page.getByRole("heading", { name: "关键决策对比", exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("row").filter({ hasText: "B 至少 3 件" }).first()).toContainText("12");
  await expect(page.getByRole("row").filter({ hasText: "B 至少 4 件" }).first()).toContainText("8");
  await expect(page.getByRole("row").filter({ hasText: "原方案" }).first()).toContainText("13");
  expect((await (await page.request.get(`/threads/${sourceId}`)).json()).values).toEqual(original);
  for (const [width, height] of [[320, 568], [375, 812], [768, 1024], [1440, 900]]) {
    await page.setViewportSize({ width, height });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});

test("several scenarios can also be calculated from chat and remain available after deleting the conversation", async ({ page }) => {
  await production(page);
  await page.getByRole("button", { name: "讨论方案", exact: true }).click();
  await page.waitForURL(/\/discussion\//);
  const id = page.url().split("/").at(-1)!;
  await page.getByLabel("发送给方案助手").fill("E2E_SOLUTION_BATCH：计算 B 至少生产 3 件和至少生产 4 件两个方案");
  await page.getByLabel("发送给方案助手").press("Enter");
  await expect(page.getByRole("log")).toContainText("目标值 8", { timeout: 60_000 });
  await page.getByText("相关方案 · 3", { exact: true }).click();
  await expect(page.getByRole("button", { name: "查看场景对比 1", exact: true })).toBeVisible();
  const state = (await (await page.request.get(`/threads/${id}`)).json()).values;
  expect(state.plans).toHaveLength(2);
  await page.getByRole("button", { name: "查看场景对比 1", exact: true }).click();
  await expect(page.getByRole("heading", { name: "关键决策对比", exact: true })).toBeVisible();
  await page.request.delete(`/threads/${id}`);
  for (const plan of state.plans) expect((await page.request.get(`/threads/${plan.source.thread_id}`)).ok()).toBe(true);
});

test("retrying a failed chat explanation reuses the already computed plan", async ({ page }) => {
  await production(page);
  await page.getByRole("button", { name: "讨论方案", exact: true }).click();
  await page.waitForURL(/\/discussion\//);
  const id = page.url().split("/").at(-1)!;
  await page.getByLabel("发送给方案助手").fill("E2E_SOLUTION_REPLY_RETRY：B 至少生产 3 件，重新计算");
  await page.getByLabel("发送给方案助手").press("Enter");
  await expect(page.getByRole("button", { name: "重试这一轮", exact: true })).toBeVisible({ timeout: 60_000 });
  const before = (await (await page.request.get(`/threads/${id}`)).json()).values;
  expect(before.plans).toHaveLength(1);
  await page.getByRole("button", { name: "重试这一轮", exact: true }).click();
  await expect(page.getByRole("log")).toContainText("没有重复计算");
  const after = (await (await page.request.get(`/threads/${id}`)).json()).values;
  expect(after.plans).toEqual(before.plans);
  expect(after.messages.filter((message: { type: string }) => message.type === "human")).toHaveLength(1);
});
