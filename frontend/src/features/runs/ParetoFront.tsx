import { useState } from "react";
import { ArrowDown, ArrowUp, Download, GitFork, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Plain, download } from "@/components/Content";
import { formatNumber } from "@/format";
import { t } from "@/i18n";
import { toCsv } from "@/lib/csv";
import { cn } from "@/lib/utils";
import type { ParetoFront as ParetoFrontData, ParetoObjective, ParetoSolution } from "@/features/runs/types";

/** Lightweight zero-dependency interactive 2D SVG trade-off plot synced with the Pareto table. */
function TradeoffPlot({
  objectives,
  solutions,
  activeIndex,
  onSelect,
}: {
  objectives: ParetoObjective[];
  solutions: ParetoSolution[];
  activeIndex: number;
  onSelect: (index: number) => void;
}) {
  const [xAxis, setXAxis] = useState(0);
  const [yAxis, setYAxis] = useState(1);
  if (objectives.length < 2 || solutions.length < 2) return null;

  const xi = xAxis < objectives.length ? xAxis : 0;
  const yi = yAxis < objectives.length && yAxis !== xi ? yAxis : (xi === 0 ? 1 : 0);
  const points = solutions
    .map((sol, idx) => ({ idx, x: sol.objectives[xi], y: sol.objectives[yi], knee: !!sol.knee }))
    .filter((pt): pt is { idx: number; x: number; y: number; knee: boolean } => pt.x != null && pt.y != null);
  if (points.length < 2) return null;

  const xMin = Math.min(...points.map(p => p.x));
  const xMax = Math.max(...points.map(p => p.x));
  const yMin = Math.min(...points.map(p => p.y));
  const yMax = Math.max(...points.map(p => p.y));
  const xSpan = xMax - xMin || 1;
  const ySpan = yMax - yMin || 1;

  const W = 520;
  const H = 190;
  const padL = 58;
  const padR = 18;
  const padT = 14;
  const padB = 34;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const sx = (v: number) => padL + ((v - xMin) / xSpan) * plotW;
  const sy = (v: number) => padT + plotH - ((v - yMin) / ySpan) * plotH;

  const xObj = objectives[xi];
  const yObj = objectives[yi];

  return <div className="rounded-xl border border-border/70 bg-background/80 p-3">
    <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span className="font-medium text-foreground/85">{t("目标权衡图")}</span>
      {objectives.length > 2 ? <div className="ml-auto flex items-center gap-1.5">
        <span>X</span>
        <Select value={String(xi)} onValueChange={v => setXAxis(Number(v))}>
          <SelectTrigger size="sm" aria-label={t("横轴目标")} className="h-7 min-w-28 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{objectives.map((obj, idx) => <SelectItem key={idx} value={String(idx)}>{obj.name}</SelectItem>)}</SelectContent>
        </Select>
        <span>Y</span>
        <Select value={String(yi)} onValueChange={v => setYAxis(Number(v))}>
          <SelectTrigger size="sm" aria-label={t("纵轴目标")} className="h-7 min-w-28 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{objectives.map((obj, idx) => <SelectItem key={idx} value={String(idx)} disabled={idx === xi}>{obj.name}</SelectItem>)}</SelectContent>
        </Select>
      </div> : null}
    </div>
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("目标权衡图")} className="h-44 w-full select-none">
      {/* Subtle gridlines */}
      {[0, 0.5, 1].map(frac => {
        const y = padT + plotH * (1 - frac);
        const val = yMin + ySpan * frac;
        return <g key={`y-${frac}`}>
          <line x1={padL} y1={y} x2={W - padR} y2={y} stroke="currentColor" strokeOpacity="0.1" strokeDasharray="3 3" />
          <text x={padL - 6} y={y + 3} textAnchor="end" fontSize="9.5" className="fill-muted-foreground font-mono">
            {formatNumber(Number(val.toPrecision(4)))}
          </text>
        </g>;
      })}
      {[0, 0.5, 1].map(frac => {
        const x = padL + plotW * frac;
        const val = xMin + xSpan * frac;
        return <g key={`x-${frac}`}>
          <line x1={x} y1={padT} x2={x} y2={padT + plotH} stroke="currentColor" strokeOpacity="0.08" strokeDasharray="3 3" />
          <text x={x} y={H - 17} textAnchor="middle" fontSize="9.5" className="fill-muted-foreground font-mono">
            {formatNumber(Number(val.toPrecision(4)))}
          </text>
        </g>;
      })}
      <line x1={padL} y1={padT + plotH} x2={W - padR} y2={padT + plotH} stroke="currentColor" strokeOpacity="0.25" />
      <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="currentColor" strokeOpacity="0.25" />
      <text x={padL + plotW / 2} y={H - 3} textAnchor="middle" fontSize="10" className="fill-muted-foreground font-medium">
        {xObj.name} ({xObj.sense === "max" ? "↑" : "↓"})
      </text>
      <text x={11} y={padT + plotH / 2} textAnchor="middle" fontSize="10" transform={`rotate(-90 11 ${padT + plotH / 2})`} className="fill-muted-foreground font-medium">
        {yObj.name} ({yObj.sense === "max" ? "↑" : "↓"})
      </text>
      {points.map(pt => {
        const isSel = pt.idx === activeIndex;
        const cx = sx(pt.x);
        const cy = sy(pt.y);
        return <g key={pt.idx} className="cursor-pointer" onClick={() => onSelect(pt.idx)}>
          <title>{`#${pt.idx + 1}${pt.knee ? ` (${t("推荐折中")})` : ""}: ${xObj.name}=${formatNumber(pt.x)}, ${yObj.name}=${formatNumber(pt.y)}`}</title>
          {isSel || pt.knee ? <circle cx={cx} cy={cy} r={isSel ? 8 : 6.5} fill="none" stroke="var(--primary)" strokeWidth={isSel ? 2 : 1.5} strokeOpacity={isSel ? 0.9 : 0.45} /> : null}
          <circle
            cx={cx}
            cy={cy}
            r={isSel ? 4.5 : pt.knee ? 4 : 3}
            fill={isSel || pt.knee ? "var(--primary)" : "currentColor"}
            fillOpacity={isSel ? 1 : pt.knee ? 0.9 : 0.45}
          />
        </g>;
      })}
    </svg>
  </div>;
}

/** Dedicated multi-objective Pareto front table card with 2D scatter plot, knee-point highlight, CSV export and row inspection. */
export function ParetoFront({ pareto }: { pareto: ParetoFrontData }) {
  const defaultIndex = Math.max(0, pareto.solutions.findIndex(item => item.knee));
  const [selected, setSelected] = useState(defaultIndex);
  if (!pareto.solutions.length) return null;

  const activeIndex = selected < pareto.solutions.length ? selected : defaultIndex;
  const active = pareto.solutions[activeIndex];
  const activeVars = Object.entries(active?.variables ?? {}).filter(([, val]) => val != null && val !== 0);

  const exportCsv = () => {
    const headers = [
      "index",
      "knee",
      ...pareto.objectives.map(obj => `${obj.name} (${obj.sense})`),
    ];
    const rows = pareto.solutions.map((sol, idx) => [
      idx + 1,
      sol.knee ? "yes" : "",
      ...sol.objectives.map(val => val ?? ""),
    ]);
    download("pareto_front.csv", toCsv([headers, ...rows]));
  };

  return <Card className="gap-4 rounded-2xl border-primary/20 bg-gradient-to-br from-primary/[0.03] via-card to-card py-4 shadow-xs">
    <CardHeader className="flex flex-wrap items-center gap-2 px-5">
      <CardTitle className="flex items-center gap-2 text-sm font-semibold">
        <span className="grid size-6 place-items-center rounded-lg bg-primary/10 text-primary">
          <GitFork className="size-3.5" />
        </span>
        {t("多目标 Pareto 前沿")}
      </CardTitle>
      <Badge variant="secondary" className="h-5 font-normal tabular">
        {t("共 {total} 个非支配解", { total: pareto.total })}
      </Badge>
      {pareto.total > pareto.solutions.length ? <span className="text-xs text-muted-foreground">
        {t("已展示 {shown} 个代表解", { shown: pareto.solutions.length })}
      </span> : null}
      <Button variant="ghost" size="sm" className="ml-auto rounded-lg text-muted-foreground" aria-label={t("导出 Pareto CSV")} onClick={exportCsv}>
        <Download />{t("导出 Pareto CSV")}
      </Button>
      <p className="w-full text-xs leading-relaxed text-muted-foreground">
        {t("以下为多目标权衡的非支配解集，带“推荐折中”标记的为归一化拐点方案；点击任意一行可查看对应决策明细。")}
      </p>
    </CardHeader>
    <CardContent className="flex min-w-0 flex-col gap-3.5 px-5">
      <TradeoffPlot objectives={pareto.objectives} solutions={pareto.solutions} activeIndex={activeIndex} onSelect={setSelected} />
      <Table className="text-[13px]" containerClassName="max-h-80 rounded-xl border border-border/80 bg-background/80">
        <TableHeader className="sticky top-0 z-10 bg-muted/80 backdrop-blur-xs">
          <TableRow>
            <TableHead className="h-9 w-28">{t("方案编号")}</TableHead>
            {pareto.objectives.map((obj, idx) => <TableHead key={`${obj.name}-${idx}`} className="h-9 text-right">
              <span className="inline-flex items-center justify-end gap-1 font-medium">
                <span>{obj.name}</span>
                <span className="inline-flex items-center rounded bg-muted px-1 py-0.5 font-mono text-[10px] font-normal text-muted-foreground">
                  {obj.sense === "max" ? <ArrowUp className="mr-0.5 size-2.5" /> : <ArrowDown className="mr-0.5 size-2.5" />}
                  {obj.sense}
                </span>
              </span>
            </TableHead>)}
          </TableRow>
        </TableHeader>
        <TableBody>
          {pareto.solutions.map((sol, idx) => {
            const isSelected = idx === activeIndex;
            return <TableRow
              key={idx}
              onClick={() => setSelected(idx)}
              aria-selected={isSelected}
              className={cn(
                "cursor-pointer transition-colors",
                isSelected ? "bg-primary/10 hover:bg-primary/12" : sol.knee ? "bg-primary/[0.04] hover:bg-primary/[0.08]" : "hover:bg-muted/40",
              )}
            >
              <TableCell className="py-2 font-mono text-xs">
                <span className="inline-flex items-center gap-1.5">
                  <span className={cn("font-semibold", isSelected && "text-primary")}>#{idx + 1}</span>
                  {sol.knee ? <Badge variant="secondary" className="h-4.5 gap-0.5 px-1.5 text-[10px] font-medium text-primary">
                    <Sparkles className="size-2.5" />{t("推荐折中")}
                  </Badge> : null}
                </span>
              </TableCell>
              {pareto.objectives.map((_, objIdx) => {
                const val = sol.objectives[objIdx];
                return <TableCell key={objIdx} className={cn("py-2 text-right font-mono tabular", isSelected && "font-semibold")}>
                  {val == null ? "—" : formatNumber(val)}
                </TableCell>;
              })}
            </TableRow>;
          })}
        </TableBody>
      </Table>

      {active && (active.decoded != null || activeVars.length > 0) ? <div className="rounded-xl border border-border/70 bg-muted/20 p-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-medium text-foreground/85">
          <span>{t("方案 #{index} 决策明细", { index: activeIndex + 1 })}</span>
          {active.knee ? <Badge variant="outline" className="h-4.5 px-1.5 text-[10px] font-normal text-primary">{t("推荐折中")}</Badge> : null}
        </div>
        {active.decoded != null ? <Plain className="max-h-56 overflow-auto">{JSON.stringify(active.decoded, null, 2)}</Plain>
          : <div className="grid grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-1.5">
            {activeVars.slice(0, 60).map(([name, val]) => <div key={name} className="flex items-center justify-between gap-2 rounded-lg border bg-background px-2.5 py-1 text-xs">
              <span className="truncate font-mono text-muted-foreground" title={name}>{name}</span>
              <span className="font-mono font-medium tabular">{val == null ? "—" : formatNumber(val)}</span>
            </div>)}
          </div>}
      </div> : null}
    </CardContent>
  </Card>;
}
