import { expect, test } from "@playwright/test";
import readXlsxFile from "read-excel-file/node";

test("downloads an Excel business plan with actual values and the source problem", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.getByRole("main").getByRole("button", { name: /^生产计划/ }).click();
  await page.getByRole("button", { name: /^开始建模/ }).click();
  await page.waitForURL(/\/run\//);
  const exportButton = page.getByRole("button", { name: "导出 Excel", exact: true });
  await expect(exportButton).toBeVisible({ timeout: 60_000 });
  const downloading = page.waitForEvent("download");
  await exportButton.click();
  const file = await downloading;
  expect(file.suggestedFilename()).toMatch(/\.xlsx$/);
  const path = testInfo.outputPath("solution.xlsx");
  await file.saveAs(path);
  const [plan, problem] = await readXlsxFile(path);
  expect(plan.data).toContainEqual(["总利润", 13, "元", null]);
  expect(plan.data).toContainEqual(["x[A] 的生产数量", 3, "件", "x[A]"]);
  expect(plan.data).toContainEqual(["x[B] 的生产数量", 2, "件", "x[B]"]);
  expect(problem.data.flat().join("\n")).toContain("使总利润最大");
});

test("an unverified conflict suggestion opens an editable change request and solves a new plan", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(String(error)));
  await page.goto("/");
  await page.getByRole("textbox", { name: "问题描述" }).fill(
    "工厂生产 A、B 两种产品。合同要求 A、B 各至少生产 5 件。A 消耗 2 单位切割资源，B 消耗 1 单位，切割资源共 8 单位。使利润 3A+2B 最大。");
  await page.getByRole("button", { name: /^开始建模/ }).click();
  await page.waitForURL(/\/run\//);
  await expect(page.getByText("为什么无解", { exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("建议尚未验证。选择后可编辑调整要求，再重新建模验证。", { exact: true })).toBeVisible();
  const sourceId = page.url().split("/").at(-1)!;
  const original = (await (await page.request.get(`/threads/${sourceId}`)).json()).values;
  expect(original.solve.status).toBe("infeasible");
  expect(original.solve.diagnosis.items.length).toBeGreaterThan(0);
  expect(original.usage.solves).toBe(1);
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "尝试这个调整", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "调整条件", exact: true });
  await expect(dialog.getByLabel("要调整什么？")).toHaveValue("将切割资源提高至 15 单位，其他条件保持不变。");
  expect(page.url()).toMatch(new RegExp(`${sourceId}$`));
  await dialog.getByRole("button", { name: "生成新方案", exact: true }).click();
  await expect(page).not.toHaveURL(new RegExp(`${sourceId}$`));
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeVisible({ timeout: 60_000 });
  const child = await (await page.request.get(`/threads/${page.url().split("/").at(-1)}`)).json();
  expect(child.values.solve.status).toBe("optimal");
  expect(child.values.solve.objective).toBe(25);
  expect(child.values.description).toContain("切割资源共 15 单位");
  expect(child.values.description).not.toContain("切割资源共 8 单位");
  expect(child.values.infeasibility).toBeNull();
  expect(child.metadata.parent.thread_id).toBe(sourceId);
  expect((await (await page.request.get(`/threads/${sourceId}`)).json()).values).toEqual(original);
  expect(errors).toEqual([]);
});
