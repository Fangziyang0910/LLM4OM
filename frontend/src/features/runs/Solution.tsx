import { useMemo, useState } from "react";
import { ChevronDown, Download, Grid3x3, List, Search, SearchX, TriangleAlert } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";
import { toCsv } from "@/lib/csv";
import { STATUS, formatNumber, tone } from "@/format";
import { t } from "@/i18n";
import { asMatrix, groupVariables, type VariableGroup } from "@/features/runs/tables";
import type { Diagnosis, Solve } from "@/features/runs/types";
import { Plain, download } from "@/components/Content";
import { StatusBadge } from "@/features/runs/status";

const value = (number: number) => <span className={cn("font-mono tabular", number === 0 && "text-muted-foreground/50")}>{formatNumber(number)}</span>;

/** A solve result: status and objective, the variables (grouped into matrices where they have two indices), and the log. */
export function Solution({ solve }: { solve: Solve }) {
  const [zeros, setZeros] = useState(false);
  const [filter, setFilter] = useState("");
  const [layout, setLayout] = useState<"grouped" | "list">("grouped");
  const [limit, setLimit] = useState(200);
  const entries = Object.entries(solve.variables);
  const nonzero = entries.filter(([, number]) => number !== 0).length;
  const groups = useMemo(() => groupVariables(solve.variables), [solve.variables]);
  const query = filter.trim().toLowerCase();
  const matches = (name: string) => !query || name.toLowerCase().includes(query);
  const shown = entries.filter(([name, number]) => (zeros || number !== 0) && matches(name));
  const shownGroups = groups.map(group => matches(group.base) ? group : {
    ...group, variables: group.variables.filter(variable => matches(variable.name)),
  }).filter(group => group.variables.length);

  return <div className="flex flex-col gap-5">
    <div className="grid grid-cols-3 gap-3">
      <Metric label={t("求解状态")}><StatusBadge status={solve.status} /></Metric>
      <Metric label={t("目标值")}><span className="text-xl font-semibold tracking-tight tabular">{solve.objective != null ? formatNumber(solve.objective) : "—"}</span></Metric>
      <Metric label={t("非零变量 / 变量")}><span className="text-xl font-semibold tracking-tight tabular">{nonzero}<span className="text-muted-foreground"> / {entries.length}</span></span></Metric>
    </div>

    {solve.status === "locally_optimal" ? <p className="text-sm text-muted-foreground">{t("已找到局部最优解；非凸问题仍可能存在更好的解。")}</p> : null}
    {solve.status === "locally_infeasible" ? <p className="text-sm text-muted-foreground">{t("本次局部搜索未找到可行解，不能据此断定整个问题不可行。")}</p> : null}
    {solve.status === "infeasible" && !solve.diagnosis?.items.length ? <p className="text-sm text-muted-foreground">
      {t("本次求解未提供具体冲突约束。可核对数学模型与原问题，或通过“调整条件”重新建模。")}</p> : null}
    {solve.error ? <Alert variant="destructive"><TriangleAlert /><AlertTitle>{t("代码执行出错")}</AlertTitle>
      <AlertDescription><Plain tone="bad" className="mt-1 w-full">{solve.error}</Plain></AlertDescription></Alert> : null}
    {solve.diagnosis ? <Conflict diagnosis={solve.diagnosis} /> : null}

    {entries.length ? <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input aria-label={t("筛选变量")} placeholder={t("按名称筛选")} value={filter} onChange={event => { setFilter(event.target.value); setLimit(200); }} className="h-8 w-44 pl-8 text-[13px]" />
        </div>
        <ToggleGroup type="single" size="sm" variant="outline" value={layout} onValueChange={next => next && setLayout(next as "grouped" | "list")} aria-label={t("显示方式")}>
          <ToggleGroupItem value="grouped" aria-label={t("按变量分组")}><Grid3x3 />{t("分组")}</ToggleGroupItem>
          <ToggleGroupItem value="list" aria-label={t("全部列表")}><List />{t("列表")}</ToggleGroupItem>
        </ToggleGroup>
        {layout === "list" ? <Label className="ml-1 gap-2 text-xs font-normal text-muted-foreground">
          <Switch size="sm" checked={zeros} onCheckedChange={setZeros} />{t("含取值为 0 的变量")}</Label> : null}
        <Button variant="ghost" size="sm" className="ml-auto text-muted-foreground" aria-label={t("下载变量取值 CSV")}
          onClick={() => download("solution.csv", toCsv([["variable", "value"], ...entries]))}>
          <Download />CSV</Button>
      </div>

      {layout === "grouped" ? <div className="flex flex-col gap-3">
        {shownGroups.slice(0, limit).map(group => <Group key={group.base} group={group} />)}
        {shownGroups.length > limit ? <Button variant="link" size="sm" onClick={() => setLimit(limit + 200)}>
          {t("再显示 {count} 个（共 {total} 个）", { count: Math.min(200, shownGroups.length - limit), total: shownGroups.length })}</Button> : null}
        {!shownGroups.length ? <p className="py-6 text-center text-sm text-muted-foreground">{t("没有匹配的变量。")}</p> : null}
      </div> : <div className="overflow-hidden rounded-lg border">
        <Table className="text-[13px]">
          <TableHeader className="bg-muted/50"><TableRow><TableHead className="h-8">{t("变量")}</TableHead><TableHead className="h-8 text-right">{t("取值")}</TableHead></TableRow></TableHeader>
          <TableBody>{shown.slice(0, limit).map(([name, number]) => <TableRow key={name}>
            <TableCell className="py-1.5 font-mono text-xs">{name}</TableCell><TableCell className="py-1.5 text-right">{value(number)}</TableCell>
          </TableRow>)}</TableBody>
        </Table>
        {!shown.length ? <p className="py-6 text-center text-sm text-muted-foreground">{t("没有匹配的变量。")}</p> : null}
        {shown.length > limit ? <Button variant="link" size="sm" className="w-full" onClick={() => setLimit(limit + 500)}>
          {t("再显示 {count} 个（共 {total} 个）", { count: Math.min(500, shown.length - limit), total: shown.length })}</Button> : null}
      </div>}
    </section> : null}

    {solve.output.trim() ? <Collapsible className="group/output">
      <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ChevronDown className="size-3.5 -rotate-90 transition-transform group-data-[state=open]/output:rotate-0" />{t("代码输出")}</CollapsibleTrigger>
      <CollapsibleContent className="pt-2"><Plain className="max-h-80 overflow-y-auto">{solve.output}</Plain></CollapsibleContent>
    </Collapsible> : null}
    {tone(solve.status) === "good" ? <p className="text-xs leading-relaxed text-muted-foreground">
      {t("求解器只保证这个数学模型的解是{status}。模型是否完整表达了问题，请在“数学模型”中核对。", { status: STATUS[solve.status] })}</p> : null}
  </div>;
}

/** The actual solver evidence, separate from the platform's business explanation and candidate changes. */
function Conflict({ diagnosis }: { diagnosis: Diagnosis }) {
  return <section className="flex flex-col gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3">
    <h3 className="flex items-center gap-2 text-sm font-medium"><SearchX className="size-4 text-destructive" />{t("不能同时满足的约束")}
      <span className="text-xs font-normal text-muted-foreground">{diagnosis.tool}</span></h3>
    {diagnosis.error ? <p className="text-xs text-muted-foreground">{t("没有找到冲突：{error}", { error: diagnosis.error })}</p> : <>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {t("求解器在这组约束和变量界限中定位到了冲突。请对照原问题核对它们。")}</p>
      <ul className="flex flex-col gap-1">{diagnosis.items.map(item => <li key={item}
        className="rounded-md border bg-background px-2 py-1 font-mono text-xs break-all">{item}</li>)}</ul>
      {diagnosis.total > diagnosis.items.length ? <p className="text-xs text-muted-foreground">
        {t("只显示前 {shown} 条，共 {total} 条。", { shown: diagnosis.items.length, total: diagnosis.total })}</p> : null}
      <p className="text-[11px] text-muted-foreground">{t("调整条件会创建新方案，保留本次模型和结果。")}</p>
    </>}
  </section>;
}

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="flex flex-col gap-1.5 rounded-lg border bg-muted/30 px-3 py-2.5">
    <span className="text-[11px] text-muted-foreground">{label}</span><div className="flex h-7 items-center">{children}</div>
  </div>;
}

/** One base name: a matrix for two indices, otherwise index → value rows. */
function Group({ group }: { group: VariableGroup }) {
  const [limit, setLimit] = useState(200);
  const matrix = asMatrix(group);
  const nonzero = group.variables.filter(variable => variable.value !== 0).length;
  const shape = matrix ? `${matrix.rows.length} × ${matrix.columns.length}` : group.dims ? t("{count} 个下标", { count: group.dims }) : t("标量");
  const rows = group.variables.filter(variable => variable.value !== 0);
  return <div className="overflow-hidden rounded-lg border">
    <div className="flex items-center gap-2 border-b bg-muted/40 px-3 py-1.5 text-xs">
      <span className="font-mono font-semibold">{group.base || t("标量变量")}</span>
      <span className="text-muted-foreground">{shape}</span>
      <span className="ml-auto text-muted-foreground tabular">{nonzero} / {group.variables.length} {t("非零")}</span>
    </div>
    {matrix ? <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead><tr className="border-b">
          <th className="sticky left-0 bg-card px-3 py-1.5" />
          {matrix.columns.map(column => <th key={column} className="px-3 py-1.5 text-right font-mono text-xs font-medium text-muted-foreground">{column}</th>)}
        </tr></thead>
        <tbody>{matrix.rows.slice(0, limit).map(row => <tr key={row} className="border-b last:border-0">
          <th className="sticky left-0 bg-card px-3 py-1.5 text-left font-mono text-xs font-medium text-muted-foreground">{row}</th>
          {matrix.columns.map(column => {
            const cell = matrix.cell(row, column);
            return <td key={column} className={cn("px-3 py-1.5 text-right", cell && "bg-primary/5 font-medium")}>{cell == null ? "" : value(cell)}</td>;
          })}
        </tr>)}</tbody>
      </table>
    </div> : rows.length ? <div className="-mr-px -mb-px grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))]">
      {rows.slice(0, limit).map(variable => <div key={variable.name} className="flex items-center justify-between gap-2 border-r border-b px-3 py-1.5 text-[13px]">
        <span className="truncate font-mono text-xs text-muted-foreground" title={variable.name}>{group.dims ? variable.indices.join(", ") : variable.name}</span>
        {value(variable.value)}
      </div>)}
    </div> : <p className="px-3 py-2 text-xs text-muted-foreground">{t("全部取值为 0。")}</p>}
    {(matrix?.rows.length ?? rows.length) > limit ? <Button variant="link" size="sm" className="w-full" onClick={() => setLimit(limit + 200)}>
      {t("再显示 {count} 个（共 {total} 个）", { count: Math.min(200, (matrix?.rows.length ?? rows.length) - limit), total: matrix?.rows.length ?? rows.length })}</Button> : null}
  </div>;
}
