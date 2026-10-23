import { expect, test } from "@playwright/test";

test("the result tab strip does not create a vertical scrollbar", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("main").getByRole("button", { name: /^生产计划/ }).click();
  await page.getByRole("button", { name: /^开始建模/ }).click();
  await page.waitForURL(/\/run\//);
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeVisible({ timeout: 60_000 });
  const list = page.getByRole("tablist", { name: "运行产物", exact: true });
  for (const size of [{ width: 1366, height: 768 }, { width: 1920, height: 1080 }, { width: 1024, height: 600 }]) {
    await page.setViewportSize(size);
    for (const name of ["解", "数学模型", "求解代码", "问题与数据"]) {
      const tab = list.getByRole("tab", { name, exact: true });
      await tab.click();
      await expect(tab).toHaveAttribute("aria-selected", "true");
      const sizes = await list.evaluate(node => ({ height: node.clientHeight, content: node.scrollHeight }));
      expect(sizes.content, JSON.stringify({ size, ...sizes })).toBeLessThanOrEqual(sizes.height);
      await expect(page.getByRole("tabpanel", { name, exact: true })).toBeInViewport();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "建模过程", exact: true }).click();
  const divider = page.getByRole("separator", { name: "调整过程与结果的宽度" });
  await divider.focus();
  await divider.press("End");
  const last = list.getByRole("tab", { name: "问题与数据", exact: true });
  await last.focus();
  await expect(last).toHaveAttribute("aria-selected", "true");
  await expect.poll(() => list.evaluate(node => node.scrollLeft)).toBeGreaterThan(0);
  expect(await list.evaluate(node => node.scrollHeight - node.clientHeight)).toBe(0);
});

test("the data editor has one scroll viewport and keeps its column headers visible", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("/");
  const csv = [Array.from({ length: 12 }, (_, i) => `column${i}`),
    ...Array.from({ length: 60 }, (_, row) => Array.from({ length: 12 }, (_, column) => `${row}-${column}`))]
    .map(row => row.join(",")).join("\n");
  await page.locator('input[type="file"]').setInputFiles({ name: "wide.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "编辑 wide.csv", exact: true }).click();
  const dialog = page.getByRole("dialog");
  const viewport = dialog.locator('[data-slot="table-container"]');
  const sizes = await viewport.evaluate(node => ({ height: node.clientHeight, content: node.scrollHeight }));
  expect(sizes.content).toBeGreaterThan(sizes.height);
  for (const height of [768, 600, 450]) {
    await page.setViewportSize({ width: 1366, height });
    await viewport.evaluate(node => { node.scrollTop = 200; node.scrollLeft = 200; });
    await expect.poll(() => viewport.evaluate(node => Math.abs(node.querySelector("thead")!.getBoundingClientRect().top - node.getBoundingClientRect().top))).toBeLessThanOrEqual(1);
    expect(await dialog.evaluate(node => node.scrollHeight - node.clientHeight)).toBe(0);
    await expect(dialog.getByRole("button", { name: "保存数据", exact: true })).toBeInViewport();
    await dialog.getByRole("tab", { name: "原文", exact: true }).click();
    await expect(dialog.getByRole("textbox", { name: "数据文件原文" })).toBeInViewport();
    await expect(dialog.getByRole("button", { name: "取消", exact: true })).toBeInViewport();
    expect(await dialog.evaluate(node => node.scrollHeight - node.clientHeight)).toBe(0);
    await dialog.getByRole("tab", { name: "表格", exact: true }).click();
  }
});

test("settings scroll as one form and reveal the saved method", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 600 });
  await page.goto("/");
  await page.getByRole("button", { name: "查看运行设置", exact: true }).click();
  const methods = page.getByRole("radiogroup", { name: "建模方法", exact: true });
  expect(await methods.evaluate(node => node.scrollHeight - node.clientHeight)).toBe(0);
  const selected = methods.getByRole("radio", { name: "OptiMind", exact: true });
  await selected.check();
  await page.getByRole("button", { name: "完成", exact: true }).click();
  await page.getByRole("button", { name: "查看运行设置", exact: true }).click();
  await expect(selected).toBeChecked();
  await expect(selected).toBeInViewport();
  await expect(page.getByRole("button", { name: "完成", exact: true })).toBeInViewport();
  expect(await page.getByRole("dialog").evaluate(node => node.scrollHeight - node.clientHeight)).toBe(0);
});

test("long catalog names wrap within the desktop navigation", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 600 });
  await page.route("**/api/options", async route => {
    const response = await route.fetch();
    const options = await response.json();
    options.datasets[0].title = "LongCatalogName".repeat(12);
    options.datasets[0].license = "LongLicenseIdentifier".repeat(8);
    await route.fulfill({ json: options });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "示例题库", exact: true }).click();
  const nav = page.getByRole("navigation", { name: "题库", exact: true });
  expect(await nav.evaluate(node => node.scrollWidth - node.clientWidth)).toBe(0);
  await expect(page.getByRole("button", { name: "下一页", exact: true })).toBeInViewport();
});
