import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import writeExcelFile from "write-excel-file/node";

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
