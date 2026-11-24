import { expect, test, type Page } from "@playwright/test";

async function production(page: Page) {
  await page.goto("/model");
  await page.getByRole("main").getByRole("button", { name: /^生产计划/ }).click();
  await page.getByRole("button", { name: /^立即求解/ }).click();
  await page.waitForURL(/\/run\//);
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeVisible({ timeout: 60_000 });
  return page.url().split("/").at(-1)!;
}

test("a phone opens the requested conversation and shows a chosen plan immediately", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await production(page);
  const steps = page.getByRole("tab", { name: "求解步骤", exact: true });
  await expect(page.getByRole("button", { name: "求解步骤", exact: true })).toHaveCount(0);
  await steps.click();
  await expect(steps).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "模型与结果", exact: true }).click();
  await page.getByRole("button", { name: "对话追问", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "发送给方案助手" })).toBeVisible({ timeout: 2000 });
  await expect(page.getByLabel("相关方案", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "查看原方案", exact: true }).click();
  await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toBeVisible();
  await steps.click();
  await expect(page.getByRole("heading", { name: "求解步骤", exact: true })).toBeVisible();
});

test("a phone reviews the requirements draft before starting a modeling run", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/model");
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
  await expect(page.getByRole("button", { name: /^立即求解/ })).toBeInViewport();
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
  await page.getByRole("link", { name: "查看原方案", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`checkpoint=${state.checkpoint.checkpoint_id}`));
});

test("failed and infeasible revisions do not export a business plan or report removed decisions", async ({ page }) => {
  const original = await production(page);
  const { checkpoint, values } = await (await page.request.get(`/threads/${original}/state`)).json();
  const group = "unusable-" + Date.now();
  for (const status of ["optimal", "infeasible"]) {
    const failure = status === "optimal" ? "Candidate failed validation" : null;
    const created = await page.request.post("/threads", { data: {
      metadata: { graph_id: "direct", method: "direct", title: status, group,
        parent: { thread_id: original, checkpoint_id: checkpoint.checkpoint_id }, scenario: { name: status, instruction: "Limit capacity" } },
      supersteps: [{ updates: [{ as_node: "finish", values: { ...values, failure, explanation: null,
        revision: { instruction: "Limit capacity", description: values.description },
        solve: { ...values.solve, status, objective: failure ? 123 : null, variables: failure ? { candidate: 77 } : {} } } }] }],
    } });
    expect(created.ok()).toBe(true);
    const { thread_id } = await created.json();
    await page.goto(`/run/${thread_id}`);
    const pane = page.getByRole("tabpanel");
    await expect(pane).toContainText("前后方案指标对比");
    await expect(pane).toContainText("需要两个可用的求解方案才能比较决策。");
    await expect(pane.getByRole("table")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "导出 Excel" })).toHaveCount(0);
    await page.getByRole("tab", { name: "求解结果", exact: true }).click();
    if (failure) await expect(pane).not.toContainText("candidate");
    await page.getByRole("button", { name: "对话追问", exact: true }).click();
    const prompt = page.getByRole("button", { name: failure ? "排查失败原因" : "解释条件冲突" });
    await prompt.click();
    await expect(page.getByRole("textbox", { name: "发送给方案助手" })).toHaveValue(failure ? /失败/ : /冲突/);
    await expect(page.getByRole("button", { name: "解读关键决策" })).toHaveCount(0);
  }
  await page.goto("/compare/" + group);
  const failedRow = page.getByRole("row").filter({ hasText: "运行失败" }).first();
  await expect(failedRow.getByRole("cell").nth(3)).toHaveText("—");
  await expect(page.getByRole("main")).not.toContainText("candidate");
});

test("requirements keep conversation on the left and retain draft input across layout changes", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/model");
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
  await page.getByRole("tab", { name: "对话助手", exact: true }).click();
  await expect(input).toHaveValue("下一条尚未发送的想法");
});

test("the original row in a scenario comparison opens its frozen baseline", async ({ page }) => {
  const original = await production(page);
  const state = await (await page.request.get(`/threads/${original}/state`)).json();
  await page.getByRole("button", { name: "多场景对比", exact: true }).click();
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


test("requirements can be typed while an attachment is saved and the first turn uses that file", async ({ page }) => {
  await page.goto("/model");
  await page.getByRole("button", { name: "通过对话整理需求" }).click();
  await page.waitForURL(/\/chat\//);
  const threadId = page.url().split("/").at(-1)!;
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route(`**/threads/${threadId}/state`, async route => {
    if (route.request().method() === "POST") await pending;
    await route.continue();
  });
  const input = page.getByRole("textbox", { name: "发送给需求助手" });
  await page.getByLabel("添加附件", { exact: true }).setInputFiles({
    name: "costs.csv", mimeType: "text/csv", buffer: Buffer.from("产品,成本\nA,3"),
  });
  try {
    await input.fill("请根据我刚上传的成本表整理生产需求。", { timeout: 4_000 });
    await expect(page.getByRole("button", { name: "发送", exact: true })).toBeDisabled();
    await input.press("Enter");
    await expect(page.getByRole("log")).not.toContainText("请根据我刚上传");
  } finally { release(); }
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeEnabled();
  await input.press("Enter");
  await expect(page.getByRole("textbox", { name: "问题描述" })).toHaveValue(/costs.csv/);
  expect((await (await page.request.get(`/threads/${threadId}`)).json()).values.data["costs.csv"]).toContain("A,3");
});


test("limited runs distinguish verified decisions, an empty search and an old unchecked CVXPY result", async ({ page }) => {
  const original = await production(page);
  const { values } = await (await page.request.get(`/threads/${original}/state`)).json();
  for (const mode of ["verified", "unchecked", "empty"]) {
    const created = await page.request.post("/threads", { data: {
      metadata: { graph_id: "direct", method: "direct", title: "限时生产计划" },
      supersteps: [{ updates: [{ as_node: "finish", values: { ...values, explanation: null,
        spec: { ...values.spec, language: "cvxpy", cvxpy_limit_checked: mode !== "unchecked" },
        solve: { ...values.solve, status: "time_limit", objective: mode === "empty" ? null : 0,
          variables: mode === "empty" ? {} : { output: 0 } } } }] }],
    } });
    expect(created.ok()).toBe(true);
    await page.goto(`/run/${(await created.json()).thread_id}`);
    await expect(page.getByRole("main")).toContainText(
      mode === "empty" ? "尚未找到可行方案" : mode === "unchecked" ? "旧版记录没有核验" : "最优性尚未证明");
    await expect(page.getByRole("button", { name: "导出 Excel", exact: true })).toHaveCount(mode === "verified" ? 1 : 0);
    await page.getByRole("button", { name: "对话追问", exact: true }).click();
    await expect(page.getByRole("button", { name: mode === "verified" ? "核对目标值" : "解释求解状态", exact: true })).toBeVisible();
  }
});
