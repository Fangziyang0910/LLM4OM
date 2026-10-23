import { toast } from "sonner";
import { errorText } from "@/format";
import { t } from "@/i18n";
import { excelToCsv } from "./spreadsheet";

export const DATA_FILE_ACCEPT = ".csv,.json,.txt,.tsv,.xlsx";

/** Both problem entry points attach the same text files; Excel sheets become CSV. */
export async function readDataFiles(list: FileList | null): Promise<Record<string, string>> {
  const data: Record<string, string> = {};
  for (const file of Array.from(list ?? [])) {
    if (file.size > 2_000_000) { toast.error(t("{name} 超过 2 MB，没有添加。", { name: file.name })); continue; }
    try {
      if (/\.xlsx$/i.test(file.name)) {
        const sheets = await excelToCsv(file);
        Object.assign(data, sheets);
        toast.success(t("{name} 已转换为 {count} 个 CSV 文件。", { name: file.name, count: Object.keys(sheets).length }));
      } else data[file.name] = await file.text();
    } catch (error) { toast.error(t("无法读取 {name}：{error}", { name: file.name, error: errorText(error) })); }
  }
  return data;
}
