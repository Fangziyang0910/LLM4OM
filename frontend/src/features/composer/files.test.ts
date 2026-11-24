import { afterEach, expect, test, vi } from "vitest";
import readXlsxFile from "read-excel-file/browser";
import { toast } from "sonner";
import { toCsv } from "@/lib/csv";
import { excelToCsv, readDataFiles, safeName } from "./files";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("read-excel-file/browser", () => ({ default: vi.fn() }));
afterEach(() => vi.clearAllMocks());

test("quotes CSV cells only where needed, sanitizes names and deduplicates colliding sheet names", async () => {
  expect(toCsv([["name", "cost", "note"], ["W1", 4.5, 'a "big", one'], ["W2", null, new Date(Date.UTC(2026, 0, 2))]]))
    .toBe('name,cost,note\nW1,4.5,"a ""big"", one"\nW2,,2026-01-02\n');
  expect(safeName("运费 (2026)/表")).toBe("运费 _2026__表");
  expect(safeName(".hidden")).toBe("hidden");
  vi.mocked(readXlsxFile).mockResolvedValue([
    { sheet: "a&b", data: [["first"]] }, { sheet: "a_b", data: [["second"]] },
  ] as never);
  expect(await excelToCsv(new File([], "book.xlsx"))).toEqual({ "book-a_b.csv": "first\n", "book-a_b-2.csv": "second\n" });
});

test("an empty workbook reports missing data while other selected files remain attached", async () => {
  vi.mocked(readXlsxFile).mockResolvedValue([] as never);
  const files = [new File([], "empty.xlsx"), { name: "data.csv", size: 12, arrayBuffer: async () => new TextEncoder().encode("name,price\nA,003\n").buffer }];
  expect(await readDataFiles(files as unknown as FileList)).toEqual({ "data.csv": "name,price\nA,003\n" });
  expect(toast.error).toHaveBeenCalledWith("empty.xlsx 没有可导入的数据，请先在工作表中填写数据。");
  expect(toast.success).not.toHaveBeenCalled();
});

test("a corrupt workbook leaves other attachments available and reports the read failure", async () => {
  vi.mocked(readXlsxFile).mockRejectedValue(new Error("Invalid workbook"));
  const files = [new File([], "broken.xlsx"), { name: "notes.txt", size: 5, arrayBuffer: async () => new TextEncoder().encode("notes").buffer }];
  expect(await readDataFiles(files as unknown as FileList)).toEqual({ "notes.txt": "notes" });
  expect(toast.error).toHaveBeenCalledWith("无法读取 broken.xlsx：Invalid workbook");
  expect(toast.success).not.toHaveBeenCalled();
});

test("replacing existing attachments or a file from the same selection reports the affected name", async () => {
  vi.mocked(readXlsxFile).mockResolvedValue([{ sheet: "Sheet1", data: [["name", "price"], ["A", 9]] }] as never);
  const files = [{ name: "prices.csv", size: 12, arrayBuffer: async () => new TextEncoder().encode("name,price\nA,3\n").buffer }, new File([], "prices.xlsx")];
  const existing = { "prices.csv": "name,price\nA,1\n", "notes.txt": "keep" };
  expect(await readDataFiles(files as unknown as FileList, existing)).toEqual({ "prices.csv": "name,price\nA,9\n" });
  expect(toast.success).toHaveBeenCalledWith("已替换同名数据文件：prices.csv");
  expect(existing).toEqual({ "prices.csv": "name,price\nA,1\n", "notes.txt": "keep" });
  vi.clearAllMocks();
  vi.mocked(readXlsxFile).mockResolvedValue([{ sheet: "Sheet1", data: [["name", "price"], ["A", 9]] }] as never);
  await readDataFiles(files as unknown as FileList);
  expect(toast.success).toHaveBeenCalledWith("已替换同名数据文件：prices.csv");
});

test("a failed replacement does not report success or replace existing data", async () => {
  const files = [{ name: "prices.csv", size: 12, arrayBuffer: async () => { throw new Error("read failed"); } }];
  expect(await readDataFiles(files as unknown as FileList, { "prices.csv": "old" })).toEqual({});
  expect(toast.success).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledWith("无法读取 prices.csv：read failed");
});
