import { useMemo, useState } from "react";
import { ChevronDown, Download, Grid3x3, List, Search, TriangleAlert } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";
import { STATUS, formatNumber, tone } from "@/format";
import { asMatrix, groupVariables, type VariableGroup } from "@/tables";
import type { Solve } from "@/types";
import { Plain, download } from "./Content";
import { StatusBadge } from "./status";

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
  const shownGroups = groups.filter(group => matches(group.base) || group.variables.some(variable => matches(variable.name)));

  return <div className="flex flex-col gap-5">
    <div className="grid grid-cols-3 gap-3">
      <Metric label="求解状态"><StatusBadge status={solve.status} /></Metric>
      <Metric label="目标值"><span className="text-xl font-semibold tracking-tight tabular">{solve.objective != null ? formatNumber(solve.objective) : "—"}</span></Metric>
      <Metric label="非零变量 / 变量"><span className="text-xl font-semibold tracking-tight tabular">{nonzero}<span className="text-muted-foreground"> / {entries.length}</span></span></Metric>
    </div>

    {solve.error ? <Alert variant="destructive"><TriangleAlert /><AlertTitle>代码执行出错</AlertTitle>
      <AlertDescription><Plain tone="bad" className="mt-1 w-full">{solve.error}</Plain></AlertDescription></Alert> : null}

    {entries.length ? <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input aria-label="筛选变量" placeholder="按名称筛选" value={filter} onChange={event => setFilter(event.target.value)} className="h-8 w-44 pl-8 text-[13px]" />
        </div>
        <ToggleGroup type="single" size="sm" variant="outline" value={layout} onValueChange={next => next && setLayout(next as "grouped" | "list")} aria-label="显示方式">
          <ToggleGroupItem value="grouped" aria-label="按变量分组"><Grid3x3 />分组</ToggleGroupItem>
          <ToggleGroupItem value="list" aria-label="全部列表"><List />列表</ToggleGroupItem>
        </ToggleGroup>
        {layout === "list" ? <Label className="ml-1 gap-2 text-xs font-normal text-muted-foreground">
          <Switch size="sm" checked={zeros} onCheckedChange={setZeros} />含取值为 0 的变量</Label> : null}
        <Button variant="ghost" size="sm" className="ml-auto text-muted-foreground" aria-label="下载变量取值 CSV"
          onClick={() => download("solution.csv", "variable,value\n" + entries.map(([name, number]) => `"${name.replace(/"/g, '""')}",${number}`).join("\n"))}>
          <Download />CSV</Button>
      </div>

      {layout === "grouped" ? <div className="flex flex-col gap-3">
        {shownGroups.map(group => <Group key={group.base} group={group} />)}
        {!shownGroups.length ? <p className="py-6 text-center text-sm text-muted-foreground">没有匹配的变量。</p> : null}
      </div> : <div className="overflow-hidden rounded-lg border">
        <Table className="text-[13px]">
          <TableHeader className="bg-muted/50"><TableRow><TableHead className="h-8">变量</TableHead><TableHead className="h-8 text-right">取值</TableHead></TableRow></TableHeader>
          <TableBody>{shown.slice(0, limit).map(([name, number]) => <TableRow key={name}>
            <TableCell className="py-1.5 font-mono text-xs">{name}</TableCell><TableCell className="py-1.5 text-right">{value(number)}</TableCell>
          </TableRow>)}</TableBody>
        </Table>
        {!shown.length ? <p className="py-6 text-center text-sm text-muted-foreground">没有匹配的变量。</p> : null}
        {shown.length > limit ? <Button variant="link" size="sm" className="w-full" onClick={() => setLimit(limit + 500)}>
          再显示 {Math.min(500, shown.length - limit)} 个（共 {shown.length} 个）</Button> : null}
      </div>}
    </section> : null}

    {solve.output.trim() ? <Collapsible className="group/output">
      <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ChevronDown className="size-3.5 -rotate-90 transition-transform group-data-[state=open]/output:rotate-0" />代码输出</CollapsibleTrigger>
      <CollapsibleContent className="pt-2"><Plain className="max-h-80 overflow-y-auto">{solve.output}</Plain></CollapsibleContent>
    </Collapsible> : null}
    {tone(solve.status) === "good" ? <p className="text-xs leading-relaxed text-muted-foreground">
      求解器只保证这个数学模型的解是{STATUS[solve.status]}。模型是否完整表达了问题，请在“数学模型”中核对。</p> : null}
  </div>;
}

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="flex flex-col gap-1.5 rounded-lg border bg-muted/30 px-3 py-2.5">
    <span className="text-[11px] text-muted-foreground">{label}</span><div className="flex h-7 items-center">{children}</div>
  </div>;
}

/** One base name: a matrix for two indices, otherwise index → value rows. */
function Group({ group }: { group: VariableGroup }) {
  const matrix = asMatrix(group);
  const nonzero = group.variables.filter(variable => variable.value !== 0).length;
  const shape = matrix ? `${matrix.rows.length} × ${matrix.columns.length}` : group.dims ? `${group.dims} 个下标` : "标量";
  const rows = group.variables.filter(variable => variable.value !== 0);
  return <div className="overflow-hidden rounded-lg border">
    <div className="flex items-center gap-2 border-b bg-muted/40 px-3 py-1.5 text-xs">
      <span className="font-mono font-semibold">{group.base || "标量变量"}</span>
      <span className="text-muted-foreground">{shape}</span>
      <span className="ml-auto text-muted-foreground tabular">{nonzero} / {group.variables.length} 非零</span>
    </div>
    {matrix ? <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead><tr className="border-b">
          <th className="sticky left-0 bg-card px-3 py-1.5" />
          {matrix.columns.map(column => <th key={column} className="px-3 py-1.5 text-right font-mono text-xs font-medium text-muted-foreground">{column}</th>)}
        </tr></thead>
        <tbody>{matrix.rows.map(row => <tr key={row} className="border-b last:border-0">
          <th className="sticky left-0 bg-card px-3 py-1.5 text-left font-mono text-xs font-medium text-muted-foreground">{row}</th>
          {matrix.columns.map(column => {
            const cell = matrix.cell(row, column);
            return <td key={column} className={cn("px-3 py-1.5 text-right", cell && "bg-primary/5 font-medium")}>{cell == null ? "" : value(cell)}</td>;
          })}
        </tr>)}</tbody>
      </table>
    </div> : rows.length ? <div className="-mr-px -mb-px grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))]">
      {rows.map(variable => <div key={variable.name} className="flex items-center justify-between gap-2 border-r border-b px-3 py-1.5 text-[13px]">
        <span className="truncate font-mono text-xs text-muted-foreground" title={variable.name}>{group.dims ? variable.indices.join(", ") : variable.name}</span>
        {value(variable.value)}
      </div>)}
    </div> : <p className="px-3 py-2 text-xs text-muted-foreground">全部取值为 0。</p>}
  </div>;
}
