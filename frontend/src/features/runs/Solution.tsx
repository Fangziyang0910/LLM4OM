import { memo, useMemo, useState } from "react";
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
import { formatNumber } from "@/format";
import { t } from "@/i18n";
import { asMatrix, groupVariables, type VariableGroup } from "@/features/runs/tables";
import type { Diagnosis, Solve } from "@/features/runs/types";
import { Plain, download } from "@/components/Content";

const value = (number: number | null) => number == null
  ? <span className="font-mono text-muted-foreground/50">—</span>
  : <span className={cn("font-mono tabular", number === 0 && "text-muted-foreground/50")}>{formatNumber(number)}</span>;

/** A solve result: status and objective, the variables (grouped into matrices where they have two indices), and the log. */
export function Solution({ solve }: { solve: Solve }) {
  const [zeros, setZeros] = useState(false);
  const [filter, setFilter] = useState("");
  const [layout, setLayout] = useState<"grouped" | "list">("grouped");
  const [limit, setLimit] = useState(200);
  const entries = useMemo(() => Object.entries(solve.variables), [solve.variables]);
  const groups = useMemo(() => groupVariables(solve.variables), [solve.variables]);
  const query = filter.trim().toLowerCase();
  const shown = useMemo(() => layout === "list" ? entries.filter(([name, number]) =>
    query ? name.toLowerCase().includes(query) : zeros || (number != null && number !== 0)) : [], [entries, layout, query, zeros]);
  const shownGroups = useMemo(() => !query || layout === "list" ? groups : groups.map(group =>
    group.base.toLowerCase().includes(query) ? group : {
      ...group, variables: group.variables.filter(variable => variable.name.toLowerCase().includes(query)),
    }).filter(group => group.variables.length), [groups, layout, query]);

  return <div className="flex flex-col gap-5">
    {solve.status === "locally_optimal" ? <p className="text-sm text-muted-foreground">{t("已找到高质量可行方案（局部最优）；复杂非线性场景下可能仍存在更优解。")}</p> : null}
    {solve.status === "locally_infeasible" ? <p className="text-sm text-muted-foreground">{t("当前局部搜索暂未找到可行方案，可尝试调整初始条件或重新求解。")}</p> : null}
    {solve.status === "infeasible" && !solve.diagnosis?.items.length ? <p className="text-sm text-muted-foreground">
      {t("当前条件之间存在冲突。建议核对原始数据或点击上方“调整条件”放宽限制后重试。")}</p> : null}
    {solve.error ? <Alert variant="destructive"><TriangleAlert /><AlertTitle>{t("模型计算出错")}</AlertTitle>
      <AlertDescription><Plain tone="bad" className="mt-1 w-full">{solve.error}</Plain></AlertDescription></Alert> : null}
    {solve.diagnosis ? <Conflict diagnosis={solve.diagnosis} /> : null}

    {entries.length ? <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input aria-label={t("筛选变量")} placeholder={t("搜索决策项…")} value={filter} onChange={event => { setFilter(event.target.value); setLimit(200); }} className="h-8 w-48 rounded-lg pl-8 text-[13px]" />
        </div>
        <ToggleGroup type="single" size="sm" variant="outline" value={layout} onValueChange={next => next && setLayout(next as "grouped" | "list")} aria-label={t("显示方式")}>
          <ToggleGroupItem value="grouped" aria-label={t("按变量分组")}><Grid3x3 />{t("分组视图")}</ToggleGroupItem>
          <ToggleGroupItem value="list" aria-label={t("全部列表")}><List />{t("列表视图")}</ToggleGroupItem>
        </ToggleGroup>
        {query ? <span className="text-xs text-muted-foreground">{t("搜索结果已包含零值项。")}</span> : layout === "list" ? <Label className="ml-1 gap-2 text-xs font-normal text-muted-foreground">
          <Switch size="sm" checked={zeros} onCheckedChange={setZeros} />{t("显示零值项")}</Label> : null}
        <Button variant="ghost" size="sm" className="ml-auto rounded-lg text-muted-foreground" aria-label={t("下载变量取值 CSV")}
          onClick={() => download("solution.csv", toCsv([["variable", "value"], ...entries]))}>
          <Download />{t("导出 CSV")}</Button>
      </div>

      {layout === "grouped" ? <div className="flex flex-col gap-3">
        {shownGroups.slice(0, limit).map(group => <Group key={group.base} group={group} includeZeros={!!query} />)}
        {shownGroups.length > limit ? <Button variant="link" size="sm" onClick={() => setLimit(limit + 200)}>
          {t("再显示 {count} 个（共 {total} 个）", { count: Math.min(200, shownGroups.length - limit), total: shownGroups.length })}</Button> : null}
        {!shownGroups.length ? <p className="py-6 text-center text-sm text-muted-foreground">{t("没有找到匹配的决策项。")}</p> : null}
      </div> : <div className="overflow-hidden rounded-xl border border-border/80">
        <Table className="text-[13px]">
          <TableHeader className="bg-muted/40"><TableRow><TableHead className="h-8">{t("决策变量")}</TableHead><TableHead className="h-8 text-right">{t("取值")}</TableHead></TableRow></TableHeader>
          <TableBody>{shown.slice(0, limit).map(([name, number]) => <TableRow key={name}>
            <TableCell className="py-1.5 font-mono text-xs">{name}</TableCell><TableCell className="py-1.5 text-right">{value(number)}</TableCell>
          </TableRow>)}</TableBody>
        </Table>
        {!shown.length ? <p className="py-6 text-center text-sm text-muted-foreground">{t("没有找到匹配的决策项。")}</p> : null}
        {shown.length > limit ? <Button variant="link" size="sm" className="w-full" onClick={() => setLimit(limit + 500)}>
          {t("再显示 {count} 个（共 {total} 个）", { count: Math.min(500, shown.length - limit), total: shown.length })}</Button> : null}
      </div>}
    </section> : null}

    {solve.output.trim() ? <Collapsible className="group/output">
      <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ChevronDown className="size-3.5 -rotate-90 transition-transform group-data-[state=open]/output:rotate-0" />{t("查看求解引擎日志")}</CollapsibleTrigger>
      <CollapsibleContent className="pt-2"><Plain>{solve.output}</Plain></CollapsibleContent>
    </Collapsible> : null}
  </div>;
}

/** The actual solver evidence, separate from the platform's business explanation and candidate changes. */
function Conflict({ diagnosis }: { diagnosis: Diagnosis }) {
  return <section className="flex flex-col gap-2 rounded-xl border border-destructive/25 bg-destructive/5 p-3.5">
    <h3 className="flex items-center gap-2 text-sm font-medium"><SearchX className="size-4 text-destructive" />{t("冲突约束定位")}
      <span className="text-xs font-normal text-muted-foreground">{diagnosis.tool}</span></h3>
    {diagnosis.error ? <p className="text-xs text-muted-foreground">{t("未能自动提取冲突明细：{error}", { error: diagnosis.error })}</p> : <>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {t("求解引擎定位到以下约束条件无法同时满足，请对照业务规则核对：")}</p>
      <ul className="flex flex-col gap-1">{diagnosis.items.map(item => <li key={item}
        className="rounded-lg border bg-background px-2.5 py-1.5 font-mono text-xs break-all">{item}</li>)}</ul>
      {diagnosis.total > diagnosis.items.length ? <p className="text-xs text-muted-foreground">
        {t("仅展示前 {shown} 条，共 {total} 条。", { shown: diagnosis.items.length, total: diagnosis.total })}</p> : null}
      <p className="text-[11px] text-muted-foreground">{t("点击上方“调整条件”将基于原问题生成新方案，原记录仍会保留。")}</p>
    </>}
  </section>;
}

/** One base name: a matrix for two indices, otherwise index → value rows. */
const Group = memo(function Group({ group, includeZeros }: { group: VariableGroup; includeZeros: boolean }) {
  const [limit, setLimit] = useState(200);
  const matrix = useMemo(() => asMatrix(group), [group]);
  const nonzero = useMemo(() => group.variables.reduce((n, item) => n + Number(item.value != null && item.value !== 0), 0), [group]);
  const shape = matrix ? `${matrix.rows.length} × ${matrix.columns.length}` : group.dims ? t("{count} 维组合", { count: group.dims }) : t("单项指标");
  const rows = useMemo(() => matrix || includeZeros ? group.variables
    : group.variables.filter(variable => variable.value != null && variable.value !== 0), [group, includeZeros, matrix]);
  return <div className="overflow-hidden rounded-xl border border-border/80 bg-card shadow-2xs">
    <div className="flex items-center gap-2 border-b border-border/60 bg-muted/35 px-3.5 py-2 text-xs">
      <span className="font-mono font-semibold">{group.base || t("单项决策")}</span>
      <span className="text-muted-foreground">{shape}</span>
      <span className="ml-auto text-muted-foreground tabular">{t("{nonzero} / {total} 项生效", { nonzero, total: group.variables.length })}</span>
    </div>
    {matrix ? <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead><tr className="border-b">
          <th className="sticky left-0 bg-card px-3 py-1.5" />
          {matrix.columns.map(column => <th key={column} scope="col" className="px-3 py-1.5 text-right font-mono text-xs font-medium text-muted-foreground">{column}</th>)}
        </tr></thead>
        <tbody>{matrix.rows.slice(0, limit).map(row => <tr key={row} className="border-b last:border-0">
          <th scope="row" className="sticky left-0 bg-card px-3 py-1.5 text-left font-mono text-xs font-medium text-muted-foreground">{row}</th>
          {matrix.columns.map(column => {
            const cell = matrix.cell(row, column);
            return <td key={column} className={cn("px-3 py-1.5 text-right", cell != null && cell !== 0 && "bg-primary/5 font-medium")}>{cell === undefined ? "" : value(cell)}</td>;
          })}
        </tr>)}</tbody>
      </table>
    </div> : rows.length ? <div className="-mr-px -mb-px grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))]">
      {rows.slice(0, limit).map(variable => <div key={variable.name} className="flex items-center justify-between gap-2 border-r border-b px-3 py-1.5 text-[13px]">
        <span className="truncate font-mono text-xs text-muted-foreground" title={variable.name}>{group.dims ? variable.indices.join(", ") : variable.name}</span>
        {value(variable.value)}
      </div>)}
    </div> : <p className="px-3.5 py-2.5 text-xs text-muted-foreground">{t("全部取值为 0。")}</p>}
    {(matrix?.rows.length ?? rows.length) > limit ? <Button variant="link" size="sm" className="w-full" onClick={() => setLimit(limit + 200)}>
      {t("再显示 {count} 个（共 {total} 个）", { count: Math.min(200, (matrix?.rows.length ?? rows.length) - limit), total: matrix?.rows.length ?? rows.length })}</Button> : null}
  </div>;
});
