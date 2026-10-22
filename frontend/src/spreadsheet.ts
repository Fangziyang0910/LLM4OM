/** Excel workbooks become CSV data files: generated code reads text, so a workbook is converted where it is added. */

type Cell = string | number | boolean | Date | null | unknown;

/** Rows as CSV; dates as ISO dates (or date-times), quoting only where needed. */
export function toCsv(rows: Cell[][]): string {
  const cell = (value: Cell) => {
    const text = value == null ? "" : value instanceof Date
      ? value.toISOString().replace(/T00:00:00\.000Z$/, "").replace(/\.000Z$/, "Z") : String(value);
    return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return rows.map(row => row.map(cell).join(",")).join("\n") + "\n";
}

/** A file name the server accepts: letters, digits, `_`, `-`, `.` and spaces. */
export const safeName = (name: string) => name.replace(/[^\p{L}\p{N}_\-. ]/gu, "_").replace(/^[. ]+/, "") || "sheet";

/** One CSV file per sheet that has data: `book.xlsx` becomes `book.csv`, or `book-Sheet2.csv` for each of several sheets. */
export async function excelToCsv(file: File): Promise<Record<string, string>> {
  const { default: readXlsxFile } = await import("read-excel-file/browser");
  const sheets = (await readXlsxFile(file)).filter(sheet => sheet.data.length);
  const base = safeName(file.name.replace(/\.xlsx$/i, ""));
  return Object.fromEntries(sheets.map(sheet =>
    [sheets.length === 1 ? `${base}.csv` : `${base}-${safeName(sheet.sheet)}.csv`, toCsv(sheet.data)]));
}
