import { expect, test } from "@playwright/test";

let presetId = "";
test.beforeAll(async ({ request }) => {
  const response = await request.post("/api/presets", { data: { name: "Polish DeepSeek", provider: "deepseek", model: "polish-model",
    api_key: "e2e-not-a-key", base_url: "http://127.0.0.1:8796/v1", extra_body: { thinking: { type: "disabled" } } } });
  expect(response.ok()).toBe(true);
  presetId = (await response.json()).presets.find((preset: { name: string }) => preset.name === "Polish DeepSeek").id;
});
test.afterAll(async ({ request }) => { if (presetId) await request.delete(`/api/presets/${presetId}`); });

test("the agent keeps following after the workspace changes the rendered message height", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/agent");
  await page.getByRole("combobox", { name: "对话模型", exact: true }).click();
  await page.getByRole("option", { name: "Polish DeepSeek", exact: true }).click();
  const input = page.getByRole("textbox", { name: "发送给优化助手" });
  await input.fill("E2E_POLISH_STREAM：请解释生产计划的资源约束。");
  await input.press("Enter");
  const log = page.getByRole("log");
  await expect(log).toContainText("流式公式回复已完成。");
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeVisible();
  for (const open of [true, false, true]) {
    await page.getByRole("button", { name: open ? "建模工作区" : "收起建模工作区", exact: true }).click();
    await expect.poll(() => log.evaluate(node => node.scrollHeight - node.scrollTop - node.clientHeight)).toBeLessThan(2);
    await expect(page.getByRole("button", { name: "回到最新消息", exact: true })).toHaveCount(0);
  }
  await log.hover();
  await page.mouse.wheel(0, -await log.evaluate(node => node.scrollHeight / 2));
  await expect(page.getByRole("button", { name: "回到最新消息", exact: true })).toBeVisible();
  for (const open of [false, true]) {
    await page.getByRole("button", { name: open ? "建模工作区" : "收起建模工作区", exact: true }).click();
    await expect.poll(() => log.evaluate(node => node.scrollTop)).toBeGreaterThan(100);
    await expect(page.getByRole("button", { name: "回到最新消息", exact: true })).toBeVisible();
  }
});

for (const kind of ["optimization", "requirements", "solution_chat"]) {
  test(`${kind} streams formulas smoothly, respects scrolling, and sends the actual thinking choice`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(String(error)));
    let label = "发送给优化助手";
    if (kind === "optimization") await page.goto("/agent");
    else if (kind === "requirements") {
      await page.goto("/");
      await page.getByRole("button", { name: "通过对话整理需求" }).click();
      label = "发送给需求助手";
    } else {
      await page.goto("/");
      await page.getByRole("main").getByRole("button", { name: /^生产计划/ }).click();
      await page.getByRole("button", { name: /^开始建模/ }).click();
      await page.waitForURL(/\/run\//);
      await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeVisible({ timeout: 60_000 });
      await page.getByRole("button", { name: "讨论方案", exact: true }).click();
      label = "发送给方案助手";
    }
    await page.getByRole("combobox", { name: "对话模型", exact: true }).click();
    await page.getByRole("option", { name: "Polish DeepSeek", exact: true }).click();
    const toggle = page.getByRole("button", { name: "深度思考", exact: true });
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await toggle.click();
    const input = page.getByRole("textbox", { name: label });
    await input.fill("E2E_POLISH_STREAM：请解释生产计划的资源约束。");
    await input.press("Enter");
    const log = page.getByRole("log");
    await expect(log).toContainText("思考已开启。");
    await expect.poll(() => log.evaluate(node => node.scrollHeight > node.clientHeight * 2)).toBe(true);
    await log.hover();
    await page.mouse.wheel(0, -2000);
    const latest = page.getByRole("button", { name: "回到最新消息", exact: true });
    await expect(latest).toBeVisible();
    const before = await log.evaluate(node => node.scrollTop);
    await expect(log).toContainText("流式公式回复已完成。");
    expect(await log.evaluate(node => node.scrollTop)).toBeLessThanOrEqual(before + 2);
    await latest.click();
    await expect.poll(() => log.evaluate(node => node.scrollHeight - node.scrollTop - node.clientHeight)).toBeLessThan(2);
    const assistant = log.getByRole("article", { name: kind === "optimization" ? "优化助手" : kind === "requirements" ? "需求助手" : "方案助手" });
    await expect(assistant.locator(".katex-display")).toHaveCount(24);
    await expect(assistant.locator(".katex-error")).toHaveCount(0);
    expect(await assistant.locator(".katex-mathml").count()).toBe(72);
    await expect(assistant).toContainText("A costs $4 and B costs $8.");
    await assistant.getByText("思考过程", { exact: true }).click();
    await expect(assistant).toContainText("先核对实际资源。");
    if (await latest.isVisible()) await latest.click();
    await expect.poll(() => log.evaluate(node => node.scrollHeight - node.scrollTop - node.clientHeight)).toBeLessThan(2);
    await page.setViewportSize({ width: 1440, height: 768 });
    await expect.poll(() => log.evaluate(node => node.scrollHeight - node.scrollTop - node.clientHeight)).toBeLessThan(2);
    await page.reload();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await toggle.click();
    await input.fill("E2E_POLISH_STREAM：关闭思考后，再解释一次。");
    await input.press("Enter");
    await expect(log).toContainText("思考已关闭。");
    await expect(page.getByRole("button", { name: "发送", exact: true })).toBeVisible();
    const second = log.getByRole("article", { name: kind === "optimization" ? "优化助手" : kind === "requirements" ? "需求助手" : "方案助手" }).last();
    await expect(second.locator("details")).toHaveCount(0);
    await expect(second.locator(".katex-display")).toHaveCount(24);
    await page.reload();
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    const saved = (await (await page.request.get("/api/presets")).json()).presets.find((preset: { id: string }) => preset.id === presetId);
    expect(saved.extra_body.thinking.type).toBe("disabled");
    expect(errors).toEqual([]);
  });
}
