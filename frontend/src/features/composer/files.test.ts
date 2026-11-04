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

test("replacing existing attachments or a file from the same selection reports the affected name", async () => {
  vi.mocked(excelToCsv).mockResolvedValue({ "prices.csv": "name,price\nA,9\n" });
  const files = [{ name: "prices.csv", size: 12, text: async () => "name,price\nA,3\n" }, new File([], "prices.xlsx")];
  const existing = { "prices.csv": "name,price\nA,1\n", "notes.txt": "keep" };
  expect(await readDataFiles(files as unknown as FileList, existing)).toEqual({ "prices.csv": "name,price\nA,9\n" });
  expect(toast.success).toHaveBeenCalledWith("已替换同名数据文件：prices.csv");
  expect(existing).toEqual({ "prices.csv": "name,price\nA,1\n", "notes.txt": "keep" });
  vi.clearAllMocks();
  await readDataFiles(files as unknown as FileList);
  expect(toast.success).toHaveBeenCalledWith("已替换同名数据文件：prices.csv");
});

test("a failed replacement does not report success or replace existing data", async () => {
  const files = [{ name: "prices.csv", size: 12, text: async () => { throw new Error("read failed"); } }];
  expect(await readDataFiles(files as unknown as FileList, { "prices.csv": "old" })).toEqual({});
  expect(toast.success).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledWith("无法读取 prices.csv：read failed");
});
