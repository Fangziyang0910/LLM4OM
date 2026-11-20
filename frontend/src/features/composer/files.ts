import { toast } from "sonner";
import { errorText } from "@/format";
import { t } from "@/i18n";
import { toCsv } from "@/lib/csv";

export const DATA_FILE_ACCEPT = ".csv,.json,.txt,.tsv,.xlsx";

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

/** Problem and conversation entries attach the same text files; Excel sheets become CSV. */
export async function readDataFiles(list: FileList | null, existing: Record<string, string> = {}): Promise<Record<string, string>> {
  const data: Record<string, string> = {};
  const add = (files: Record<string, string>) => {
    for (const [name, content] of Object.entries(files)) {
      if (Object.hasOwn(existing, name) || Object.hasOwn(data, name))
        toast.success(t("已替换同名数据文件：{name}", { name }));
      data[name] = content;
    }
  };
  for (const file of Array.from(list ?? [])) {
    if (!DATA_FILE_ACCEPT.split(",").some(extension => file.name.toLowerCase().endsWith(extension))) {
      toast.error(t("不支持 {name}，请添加 CSV、TSV、JSON、TXT 或 XLSX 文件。", { name: file.name })); continue;
    }
    if (file.size > 2_000_000) { toast.error(t("{name} 超过 2 MB，没有添加。", { name: file.name })); continue; }
    try {
      if (/\.xlsx$/i.test(file.name)) {
        const sheets = await excelToCsv(file);
        if (!Object.keys(sheets).length) { toast.error(t("{name} 没有可导入的数据，请先在工作表中填写数据。", { name: file.name })); continue; }
        const valid: Record<string, string> = {};
        for (const [name, content] of Object.entries(sheets)) {
          if (new Blob([content]).size > 2_000_000) toast.error(t("{name} 超过 2 MB，没有添加。", { name }));
          else valid[name] = content;
        }
        const count = Object.keys(valid).length;
        if (!count) continue;
        add(valid);
        toast.success(t("{name} 已转换为 {count} 个 CSV 文件。", { name: file.name, count }));
      } else add({ [file.name]: await file.text() });
    } catch (error) { toast.error(t("无法读取 {name}：{error}", { name: file.name, error: errorText(error) })); }
  }
  return data;
}
