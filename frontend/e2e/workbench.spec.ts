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
  await page.getByRole("button", { name: /生产计划/ }).click();
  await expect(page.getByRole("textbox", { name: "问题描述" })).toHaveValue(PRODUCTION);
  await page.getByRole("button", { name: "开始建模" }).click();
  await page.waitForURL(/\/run\//);
  await page.getByRole("button", { name: "查看解" }).waitFor({ timeout: 60_000 });
  await expect(page.getByText("目标值").first().locator("..")).toContainText("13");

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
  expect(errors).toEqual([]);
});

test("a comparison runs several methods on one problem, also over plain HTTP", async ({ page }) => {
  // Over plain HTTP on a network address (not localhost) browsers leave out these secure-context APIs.
  await page.addInitScript(() => {
    Object.defineProperty(Crypto.prototype, "randomUUID", { value: undefined });
    Object.defineProperty(Navigator.prototype, "clipboard", { get: () => undefined });
  });
  const errors = await open(page);
  await page.getByRole("button", { name: /生产计划/ }).click();
  await page.getByRole("switch", { name: "对比多个方法" }).click();
  await page.locator("#compare-feedback_repair").click();
  await page.getByRole("button", { name: "开始对比（2 个运行）" }).click();
  await page.waitForURL(/\/compare\//);
  await expect(page.getByText("2 个有解的运行目标值一致")).toBeVisible({ timeout: 60_000 });
  const rows = page.getByRole("row");
  await expect(rows.filter({ hasText: "Direct" })).toContainText("13");
  await expect(rows.filter({ hasText: "Feedback Repair" })).toContainText("13");
  await rows.filter({ hasText: "Feedback Repair" }).click();
  await page.waitForURL(/\/run\//);
  await page.getByRole("button", { name: "更多操作", exact: true }).click();
  await page.getByRole("menuitem", { name: "复制链接" }).click();
  await page.locator("[data-sonner-toast]").filter({ hasText: "已复制链接。" }).waitFor();
  await page.getByRole("button", { name: "查看对比" }).click();
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
