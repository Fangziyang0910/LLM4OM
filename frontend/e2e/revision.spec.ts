import { expect, test } from "@playwright/test";

test("business explanation and a revised plan preserve the original checkpoint", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(String(error)));
  await page.goto("/");
  await page.getByRole("main").getByRole("button", { name: /^生产计划/ }).click();
  await page.getByRole("button", { name: /^开始建模/ }).click();
  await page.waitForURL(/\/run\//);
  await page.getByRole("button", { name: "查看解", exact: true }).waitFor({ timeout: 60_000 });
  await expect(page.getByText("方案解读", { exact: true })).toBeVisible();
  const sourceId = page.url().split("/").at(-1)!;
  const original = (await (await page.request.get(`/threads/${sourceId}`)).json()).values;
  expect(original.solve.objective).toBe(13);
  expect(original.explanation.decisions.length).toBeGreaterThan(0);

  await page.getByRole("button", { name: "调整条件", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "调整条件", exact: true });
  await dialog.getByLabel("要调整什么？").fill("B 至少生产 3 件");
  await dialog.getByRole("button", { name: "生成新方案", exact: true }).click();
  await expect(page).not.toHaveURL(new RegExp(`${sourceId}$`));
  await expect(page.getByRole("tab", { name: "方案对比", exact: true })).toHaveAttribute("data-state", "active", { timeout: 60_000 });
  await expect(page.getByText("目标值差（新 − 原）", { exact: true }).locator("..")).toContainText("-1");
  const child = await (await page.request.get(`/threads/${page.url().split("/").at(-1)}`)).json();
  expect(child.metadata.parent.thread_id).toBe(sourceId);
  expect(child.metadata.parent.checkpoint_id).toBeTruthy();
  expect(child.values.solve.objective).toBe(12);
  expect(child.values.spec.method).toBe(original.spec.method);
  expect(child.values.spec.language).toBe(original.spec.language);
  expect(child.values.spec.preset).toBe(original.spec.preset);
  expect(child.values.revision.description).toBe(original.description);
  expect(child.values.description).toContain("B 至少生产 3 件");
  expect(child.values.data).toEqual(original.data);
  expect((await (await page.request.get(`/threads/${sourceId}`)).json()).values).toEqual(original);

  const later = await page.request.post(`/threads/${sourceId}/state`, { data: {
    values: { description: "原线程后来换了一道题", solve: { ...original.solve, objective: 999 } }, as_node: "finish",
  } });
  expect(later.ok()).toBe(true);
  await page.reload();
  await expect(page.getByText("目标值差（新 − 原）", { exact: true }).locator("..")).toContainText("-1");
  await page.getByText("查看题面变化", { exact: true }).click();
  await expect(page.getByRole("tabpanel")).toContainText("B 至少生产 3 件");
  for (const viewport of [{ width: 320, height: 568 }, { width: 844, height: 390 }]) {
    await page.setViewportSize(viewport);
    expect(await page.getByRole("main").evaluate(main => main.scrollWidth <= main.clientWidth)).toBe(true);
  }
  await page.getByRole("tab", { name: "解", exact: true }).click();
  await expect(page.getByText("方案解读", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
