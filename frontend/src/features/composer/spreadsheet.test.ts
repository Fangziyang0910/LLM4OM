import { describe, expect, it, vi } from "vitest";
import { excelToCsv, safeName } from "@/features/composer/spreadsheet";
import { toCsv } from "@/lib/csv";

vi.mock("read-excel-file/browser", () => ({ default: async () => [
  { sheet: "a&b", data: [["first"]] }, { sheet: "a_b", data: [["second"]] },
] }));

describe("Excel sheets as CSV", () => {
  it("quotes cells only where needed and writes dates as ISO dates", () => {
    expect(toCsv([["name", "cost", "note"], ["W1", 4.5, 'a "big", one'], ["W2", null, new Date(Date.UTC(2026, 0, 2))]]))
      .toBe('name,cost,note\nW1,4.5,"a ""big"", one"\nW2,,2026-01-02\n');
  });

  it("keeps names the server accepts", () => {
    expect(safeName("运费 (2026)/表")).toBe("运费 _2026__表");
    expect(safeName(".hidden")).toBe("hidden");
  });

  it("keeps both sheets when sanitizing their names produces the same name", async () => {
    expect(await excelToCsv(new File([], "book.xlsx"))).toEqual({ "book-a_b.csv": "first\n", "book-a_b-2.csv": "second\n" });
  });
});
