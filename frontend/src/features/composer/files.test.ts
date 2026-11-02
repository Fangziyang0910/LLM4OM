import { afterEach, expect, test, vi } from "vitest";
import { toast } from "sonner";
import { readDataFiles } from "./files";
import { excelToCsv } from "./spreadsheet";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("./spreadsheet", () => ({ excelToCsv: vi.fn() }));
afterEach(() => vi.clearAllMocks());

test("an empty workbook reports missing data while other selected files remain attached", async () => {
  vi.mocked(excelToCsv).mockResolvedValue({});
  const files = [new File([], "empty.xlsx"), { name: "data.csv", size: 12, text: async () => "name,price\nA,003\n" }];
  expect(await readDataFiles(files as unknown as FileList)).toEqual({ "data.csv": "name,price\nA,003\n" });
  expect(toast.error).toHaveBeenCalledWith("empty.xlsx 没有可导入的数据，请先在工作表中填写数据。");
  expect(toast.success).not.toHaveBeenCalled();
});

test("a corrupt workbook leaves other attachments available and reports the read failure", async () => {
  vi.mocked(excelToCsv).mockRejectedValue(new Error("Invalid workbook"));
  const files = [new File([], "broken.xlsx"), { name: "notes.txt", size: 5, text: async () => "notes" }];
  expect(await readDataFiles(files as unknown as FileList)).toEqual({ "notes.txt": "notes" });
  expect(toast.error).toHaveBeenCalledWith("无法读取 broken.xlsx：Invalid workbook");
  expect(toast.success).not.toHaveBeenCalled();
});
