import { useState } from "react";
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip as RechartsTooltip, XAxis, YAxis } from "recharts";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatNumber } from "@/format";
import { t } from "@/i18n";
import type { ParetoObjective, ParetoSolution } from "./types";

type PlotPoint = { idx: number; x: number; y: number; knee: boolean };

/** Interactive 2D Pareto trade-off scatter chart powered by Recharts, synced with the table selection. */
export default function TradeoffPlot({
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
  const points: PlotPoint[] = solutions
    .map((sol, idx) => ({ idx, x: sol.objectives[xi], y: sol.objectives[yi], knee: !!sol.knee }))
    .filter((pt): pt is PlotPoint => pt.x != null && pt.y != null);
  if (points.length < 2) return null;

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
    <div role="img" aria-label={t("目标权衡图")} className="h-56 w-full select-none">
      <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 520, height: 224 }}>
        <ScatterChart margin={{ top: 10, right: 16, bottom: 22, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" strokeOpacity={0.1} />
          <XAxis
            type="number"
            dataKey="x"
            name={xObj.name}
            domain={["auto", "auto"]}
            tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
            tickFormatter={v => formatNumber(Number(Number(v).toPrecision(4)))}
            label={{ value: `${xObj.name} (${xObj.sense === "max" ? "↑" : "↓"})`, position: "insideBottom", offset: -14, fontSize: 11, fill: "var(--muted-foreground)" }}
          />
          <YAxis
            type="number"
            dataKey="y"
            name={yObj.name}
            domain={["auto", "auto"]}
            width={56}
            tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
            tickFormatter={v => formatNumber(Number(Number(v).toPrecision(4)))}
            label={{ value: `${yObj.name} (${yObj.sense === "max" ? "↑" : "↓"})`, angle: -90, position: "insideLeft", offset: 4, style: { textAnchor: "middle" }, fontSize: 11, fill: "var(--muted-foreground)" }}
          />
          <RechartsTooltip
            cursor={{ strokeDasharray: "3 3", strokeOpacity: 0.35 }}
            content={({ active: show, payload }) => {
              const pt = payload?.[0]?.payload as PlotPoint | undefined;
              if (!show || !pt) return null;
              return <div className="rounded-xl border border-border/80 bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md">
                <div className="mb-1 flex items-center gap-1.5 font-semibold">
                  <span>#{pt.idx + 1}</span>
                  {pt.knee ? <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">{t("推荐折中")}</span> : null}
                </div>
                <div className="space-y-0.5 font-mono text-[11px] tabular">
                  <div>{xObj.name}: <strong>{formatNumber(pt.x)}</strong></div>
                  <div>{yObj.name}: <strong>{formatNumber(pt.y)}</strong></div>
                </div>
              </div>;
            }}
          />
          <Scatter
            data={points}
            isAnimationActive={false}
            onClick={entry => {
              const pt = (entry?.payload ?? entry) as PlotPoint | undefined;
              if (pt && typeof pt.idx === "number") onSelect(pt.idx);
            }}
            shape={(props: unknown) => {
              const { cx, cy, payload } = props as { cx?: number; cy?: number; payload?: PlotPoint };
              if (cx == null || cy == null || !payload) return <g />;
              const isSel = payload.idx === activeIndex;
              return <g className="cursor-pointer" onClick={() => onSelect(payload.idx)}>
                {isSel || payload.knee ? <circle cx={cx} cy={cy} r={isSel ? 8.5 : 6.5} fill="none" stroke="var(--primary)" strokeWidth={isSel ? 2 : 1.5} strokeOpacity={isSel ? 0.9 : 0.45} /> : null}
                <circle
                  cx={cx}
                  cy={cy}
                  r={isSel ? 4.8 : payload.knee ? 4.2 : 3.4}
                  fill={isSel || payload.knee ? "var(--primary)" : "currentColor"}
                  fillOpacity={isSel ? 1 : payload.knee ? 0.9 : 0.48}
                />
              </g>;
            }}
          />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  </div>;
}
