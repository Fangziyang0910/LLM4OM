import { toast } from "sonner";
import { errorText } from "@/format";
import { t } from "@/i18n";
import { excelToCsv } from "./spreadsheet";

export const DATA_FILE_ACCEPT = ".csv,.json,.txt,.tsv,.xlsx";

/** Problem and conversation entries attach the same text files; Excel sheets become CSV. */
export async function readDataFiles(list: FileList | null): Promise<Record<string, string>> {
  const data: Record<string, string> = {};
  for (const file of Array.from(list ?? [])) {
    if (!DATA_FILE_ACCEPT.split(",").some(extension => file.name.toLowerCase().endsWith(extension))) {
      toast.error(t("不支持 {name}，请添加 CSV、TSV、JSON、TXT 或 XLSX 文件。", { name: file.name })); continue;
    }
    if (file.size > 2_000_000) { toast.error(t("{name} 超过 2 MB，没有添加。", { name: file.name })); continue; }
    try {
      if (/\.xlsx$/i.test(file.name)) {
        const sheets = await excelToCsv(file);
        const count = Object.keys(sheets).length;
        if (!count) { toast.error(t("{name} 没有可导入的数据，请先在工作表中填写数据。", { name: file.name })); continue; }
        Object.assign(data, sheets);
        toast.success(t("{name} 已转换为 {count} 个 CSV 文件。", { name: file.name, count }));
      } else data[file.name] = await file.text();
    } catch (error) { toast.error(t("无法读取 {name}：{error}", { name: file.name, error: errorText(error) })); }
  }
  return data;
}
