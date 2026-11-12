import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import writeExcelFile from "write-excel-file/node";

test("data rows can be added, saved and cancelled without editing CSV syntax", async ({ page }) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({ name: "demand.csv", mimeType: "text/csv", buffer: Buffer.from("客户,需求量\n门店A,003\n") });
  await page.getByRole("button", { name: "编辑 demand.csv", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "添加数据行", exact: true }).click();
  await dialog.getByLabel("第 2 行，第 1 列", { exact: true }).fill("门店B");
  await dialog.getByLabel("第 2 行，第 2 列", { exact: true }).fill("004");
  await dialog.getByRole("button", { name: "保存数据", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await page.reload();
  await page.getByRole("button", { name: "编辑 demand.csv", exact: true }).click();
  await expect(dialog.getByLabel("第 1 行，第 2 列", { exact: true })).toHaveValue("003");
  await expect(dialog.getByLabel("第 2 行，第 2 列", { exact: true })).toHaveValue("004");
  await dialog.getByRole("button", { name: "添加数据行", exact: true }).click();
  await dialog.getByLabel("第 3 行，第 1 列", { exact: true }).fill("不保存的门店");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(dialog.getByRole("button", { name: "保存数据", exact: true })).toBeInViewport();
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  await page.getByRole("button", { name: "编辑 demand.csv", exact: true }).click();
  await expect(dialog.getByLabel("第 3 行，第 1 列", { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("llm4om-draft")!).data["demand.csv"]))
    .toBe("客户,需求量\n门店A,003\n门店B,004\n");
});

test("dragging text into the problem preserves native insertion and file imports", async ({ page }) => {
  await page.goto("/");
  const input = page.getByRole("textbox", { name: "问题描述", exact: true });
  await input.fill("");
  await input.evaluate(node => {
    const source = document.createElement("p");
    source.id = "text-drag-source";
    source.textContent = "每位客户最多分配 3 辆车。";
    source.draggable = true;
    source.addEventListener("dragstart", event => event.dataTransfer!.setData("text/plain", source.textContent!));
    node.before(source);
  });
  await page.locator("#text-drag-source").dragTo(input, { targetPosition: { x: 30, y: 30 } });
  await expect(input).toHaveValue("每位客户最多分配 3 辆车。");
  await expect(page.getByText("松开以添加数据文件", { exact: true })).toHaveCount(0);
  const dropped = await page.evaluateHandle(() => {
    const transfer = new DataTransfer();
    transfer.items.add(new File(["name,price\nA,003\n"], "prices.csv", { type: "text/csv" }));
    return transfer;
  });
  await input.dispatchEvent("dragover", { dataTransfer: dropped });
  await expect(page.getByText("松开以添加数据文件", { exact: true })).toBeVisible();
  await input.dispatchEvent("drop", { dataTransfer: dropped });
  await dropped.dispose();
  await expect(page.getByRole("button", { name: "编辑 prices.csv", exact: true })).toBeVisible();
  await expect(input).toHaveValue("每位客户最多分配 3 辆车。");
  await page.reload();
  await expect(input).toHaveValue("每位客户最多分配 3 辆车。");
  await expect(page.getByRole("button", { name: "编辑 prices.csv", exact: true })).toBeVisible();
});

for (const language of ["zh", "en"]) {
  test(`invalid imports explain rejected files and keep valid data (${language})`, async ({ page }) => {
    await page.addInitScript(language => localStorage.setItem("llm4om-locale", language), language);
    await page.goto("/");
    const input = page.getByRole("textbox", { name: language === "zh" ? "问题描述" : "Problem description", exact: true });
    const dropped = await page.evaluateHandle(() => {
      const files = new DataTransfer();
      files.items.add(new File(["%PDF-1.7 binary contents"], "report.pdf", { type: "application/pdf" }));
      files.items.add(new File(["name,price\nA,003\n"], "prices.CSV", { type: "text/csv" }));
      return files;
    });
    await input.dispatchEvent("drop", { dataTransfer: dropped });
    await dropped.dispose();
    const rejected = language === "zh" ? "不支持 report.pdf，请添加 CSV、TSV、JSON、TXT 或 XLSX 文件。"
      : "report.pdf is not supported. Add a CSV, TSV, JSON, TXT or XLSX file.";
    await expect(page.getByText(rejected, { exact: true })).toBeVisible();
    const files = page.getByRole("list", { name: language === "zh" ? "数据文件" : "Data files", exact: true });
    await expect(files.getByText("prices.CSV", { exact: true })).toBeVisible();
    await expect(files.getByText("report.pdf", { exact: true })).toHaveCount(0);

    const empty = await writeExcelFile([]).toBuffer();
    await page.locator('input[type="file"]').setInputFiles({ name: "empty.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: empty });
    const noData = language === "zh" ? "empty.xlsx 没有可导入的数据，请先在工作表中填写数据。"
      : "empty.xlsx has no data to import. Add data to a worksheet first.";
    await expect(page.getByText(noData, { exact: true })).toBeVisible();
    await expect(files.getByText("empty.csv", { exact: true })).toHaveCount(0);
    await page.locator('input[type="file"]').setInputFiles(fileURLToPath(new URL("fixtures/transport.xlsx", import.meta.url)));
    await expect(files.getByText("transport-costs.csv", { exact: true })).toBeVisible();
    await expect(files.getByText("transport-notes.csv", { exact: true })).toBeVisible();
    await page.reload();
    await expect(files.getByText("prices.CSV", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem("llm4om-draft")!).data)).toEqual({
      "prices.CSV": "name,price\nA,003\n", "transport-costs.csv": expect.any(String), "transport-notes.csv": expect.any(String),
    });
  });
}
