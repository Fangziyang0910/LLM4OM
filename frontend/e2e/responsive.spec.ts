import { expect, test } from "@playwright/test";

const problem = "# 生产计划\n\n工厂生产 A、B 两种产品，数量必须是非负整数。\n\n" +
  "| 产品 | 利润 | 切割 | 加工 |\n| --- | --- | --- | --- |\n| A | $3 | 2 | 1 |\n| B | $2 | 1 | 2 |\n\n" +
  "两种资源各有 8 单位。最大化总利润。约束为 \\(2x_A+x_B\\le8\\) 和 \\(x_A+2x_B\\le8\\)。";

for (const [width, height] of [[320, 568], [390, 844], [768, 1024], [1024, 768], [1280, 720],
  [1366, 768], [1440, 600], [1440, 900], [1920, 1080], [2560, 1440], [3440, 1440]]) {
  test(`the composer fits ${width} × ${height} with a visible start action`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.goto("/");
    await page.getByRole("textbox", { name: "问题描述" }).fill(problem + "\n\n" + "请保留整数约束。\n\n".repeat(40));
    await page.getByRole("tab", { name: "预览", exact: true }).click();
    await expect(page.getByRole("heading", { name: "生产计划", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /^开始建模/ })).toBeInViewport();
    await page.getByRole("button", { name: "查看运行设置", exact: true }).click();
    await page.getByRole("switch", { name: "对比多个方法" }).click();
    await page.getByRole("button", { name: "完成", exact: true }).click();
    await expect(page.getByRole("button", { name: /^开始对比/ })).toBeInViewport();
    expect(await page.evaluate(() => {
      const main = document.querySelector("main")!;
      return main.scrollWidth <= main.clientWidth && document.documentElement.scrollWidth <= innerWidth;
    })).toBe(true);
    const editor = await page.getByRole("tablist", { name: "问题显示方式" }).locator('xpath=ancestor::*[@data-slot="card"]').boundingBox();
    expect(editor).not.toBeNull();
    if (width >= 1024) expect(editor!.width).toBeGreaterThan(Math.min(width - (width >= 1280 ? 256 : 0), 1152) * 0.9);
    await expect(page.getByRole("dialog", { name: "运行设置", exact: true })).toBeHidden();
    const navigation = page.getByRole("complementary", { name: "导航", exact: true });
    if (width >= 1280) await expect(navigation).toBeVisible();
    else {
      await expect(navigation).toBeHidden();
      await page.getByRole("button", { name: "打开菜单" }).click();
      await expect(page.getByRole("dialog").getByRole("button", { name: "新建建模", exact: true })).toBeVisible();
    }
  });
}

test("a phone can preview Markdown, submit its unchanged source and read the formatted run", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(String(error)));
  await page.goto("/");
  await page.getByRole("textbox", { name: "问题描述" }).fill(problem);
  await page.getByRole("tab", { name: "预览", exact: true }).click();
  await expect(page.getByRole("table")).toBeVisible();
  await expect(page.getByRole("cell", { name: "$3", exact: true })).toBeVisible();
  await expect(page.locator(".katex-mathml")).toHaveCount(2);
  await page.getByRole("tab", { name: "编辑", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "问题描述" })).toHaveValue(problem);
  await page.getByRole("tab", { name: "预览", exact: true }).click();
  await page.getByRole("button", { name: /^开始建模/ }).click();
  await page.waitForURL(/\/run\//);
  await page.getByRole("button", { name: "查看解", exact: true }).waitFor({ timeout: 60_000 });
  const thread = (await (await page.request.get(`/threads/${page.url().split("/").at(-1)}`)).json()).values;
  expect(thread.description).toBe(problem);
  expect(thread.solve.objective).toBe(13);
  await page.getByRole("tab", { name: "问题与数据", exact: true }).click();
  await expect(page.getByRole("tabpanel").getByRole("heading", { name: "生产计划", exact: true })).toBeVisible();
  await expect(page.getByRole("tabpanel").getByRole("cell", { name: "$3", exact: true })).toBeVisible();
  await expect(page.locator(".katex-error")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});
