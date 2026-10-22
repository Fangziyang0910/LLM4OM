/** Excel workbooks become CSV data files: generated code reads text, so a workbook is converted where it is added. */

import { toCsv } from "@/lib/csv";

/** A file name the server accepts: letters, digits, `_`, `-`, `.` and spaces. */
export const safeName = (name: string) => name.replace(/[^\p{L}\p{N}_\-. ]/gu, "_").replace(/^[. ]+/, "") || "sheet";

/** One CSV file per sheet that has data: `book.xlsx` becomes `book.csv`, or `book-Sheet2.csv` for each of several sheets. */
export async function excelToCsv(file: File): Promise<Record<string, string>> {
  const { default: readXlsxFile } = await import("read-excel-file/browser");
  const sheets = (await readXlsxFile(file)).filter(sheet => sheet.data.length);
  const base = safeName(file.name.replace(/\.xlsx$/i, ""));
  const files: Record<string, string> = {};
  for (const sheet of sheets) {
    const stem = sheets.length === 1 ? base : `${base}-${safeName(sheet.sheet)}`;
    let name = `${stem}.csv`, number = 2;
    while (name in files) name = `${stem}-${number++}.csv`;
    files[name] = toCsv(sheet.data);
  }
  return files;
}
