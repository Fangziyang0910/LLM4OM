import { useState } from "react";
import { ArrowRight, BookOpen, CalendarClock, Factory, MessageSquareText, Sparkles, Truck } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { errorText } from "@/format";
import { t } from "@/i18n";
import { ProblemEditor } from "@/features/composer/ProblemEditor";
import { DRAFT_KEY, type ModelingConfigProps, useRunLauncher } from "@/features/composer/RunSettings";
import { readDataFiles } from "@/features/composer/files";
import { normalizeTarget } from "@/features/runs/target";
import type { Draft } from "@/types";

const STARTERS = [
  {
    icon: Factory,
    title: "生产计划",
    tag: "提升利润",
    summary: "在有限设备与工序额度下，合理安排多种产品的产量，让总利润最高。",
    description: "工厂生产 A、B 两种产品，数量必须是非负整数。每件 A 利润为 3，每件 B 利润为 2。A 消耗 2 单位切割资源和 1 单位加工资源，" +
      "B 消耗 1 单位切割资源和 2 单位加工资源。两种资源各有 8 单位。请确定生产数量，使总利润最大。",
  },
  {
    icon: Truck,
    title: "运输问题",
    tag: "附数据表",
    summary: "三个仓库向四个客户发货，自动读取表格算出总运费最低的调拨方案。",
    description: "三个仓库向四个客户运送同一种货物。各仓库的供应量、各客户的需求量和单位运费见数据文件 transport.csv：" +
      "前三行是仓库到客户的单位运费，supply 列是仓库供应量，最后一行 demand 是客户需求量。每个客户的需求必须恰好满足，" +
      "仓库发货不能超过供应量。请制定运输方案，使总运费最小。",
    data: { "transport.csv": "from,C1,C2,C3,C4,supply\nW1,4,6,9,5,120\nW2,7,3,4,8,150\nW3,6,5,7,3,100\ndemand,80,90,110,70,\n" },
  },
  {
    icon: CalendarClock,
    title: "任务指派",
    tag: "缩短工时",
    summary: "根据每位员工处理各项任务的耗时差异，安排一对一指派使总耗时最短。",
    description: "把 4 名员工分配到 4 项任务，每人恰好做一项，每项恰好由一人完成。完成时间（小时）如下：" +
      "员工 1：9、2、7、8；员工 2：6、4、3、7；员工 3：5、8、1、8；员工 4：7、6、9、4（依次对应任务 1–4）。" +
      "请给出总完成时间最短的分配方案。",
  },
];

export function initialDraft(): Draft {
  let saved: Partial<Draft> = {};
  try { saved = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "{}") ?? {}; } catch { /* storage may be unavailable */ }
  const target = normalizeTarget(saved.language, saved.solver);
  return { description: saved.description ?? "", data: saved.data ?? {}, method: saved.method ?? "direct",
    language: target.language, preset: saved.preset ?? null, solver: target.solver, origin: saved.origin,
    comparing: saved.comparing ?? false, methods: saved.methods ?? [], presets: saved.presets ?? [] };
}

export type ComposerProps = ModelingConfigProps & {
  openExamples: () => void;
  onDiscuss?: () => Promise<void>;
};

export function Composer({ openExamples, onDiscuss, ...modeling }: ComposerProps) {
  const { draft, setDraft } = modeling;
  const [reading, setReading] = useState(false);
  const set = (change: Partial<Draft>) => setDraft(current => ({ ...current, ...change }));
  const { busy, setBusy, settingsTrigger, startButton, settingsDialog } = useRunLauncher({
    ...modeling,
    problem: { description: draft.description, data: draft.data, origin: draft.origin },
    reading,
  });

  const attach = async (list: FileList | null) => {
    setReading(true);
    try {
      const data = await readDataFiles(list, draft.data);
      setDraft(current => ({ ...current, data: { ...current.data, ...data } }));
    } finally { setReading(false); }
  };

  const discussTrigger = onDiscuss ? <Button type="button" variant="ghost" size="sm"
    className="h-8 rounded-xl px-2.5 text-xs font-normal text-muted-foreground hover:text-foreground"
    disabled={busy || reading} onClick={async () => {
      setBusy(true);
      try { await onDiscuss(); } catch (error) { toast.error(errorText(error)); } finally { setBusy(false); }
    }}>
    <MessageSquareText className="size-3.5 text-primary/80" />{t("边聊边梳理")}
  </Button> : null;

  return <div className="flex h-full flex-col">
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex min-h-full max-w-5xl flex-col gap-4 p-4 sm:px-6 sm:py-5 lg:h-full">
        <header className="animate-fade-up flex shrink-0 flex-col gap-2">
          <div className="hidden flex-wrap items-center gap-2 text-xs text-muted-foreground sm:flex" aria-label={t("使用步骤")}>
            <span className="inline-flex items-center gap-1.5 rounded-full border bg-card/80 px-2.5 py-0.5 font-medium text-foreground/85 shadow-2xs">
              <span className="grid size-4 place-items-center rounded-full bg-primary/15 text-[10px] font-semibold text-primary">1</span>{t("描述目标与条件")}
            </span>
            <span className="text-muted-foreground/50">→</span>
            <span className="inline-flex items-center gap-1.5 rounded-full border bg-card/80 px-2.5 py-0.5">
              <span className="grid size-4 place-items-center rounded-full bg-muted text-[10px] font-semibold">2</span>{t("上传表格（可选）")}
            </span>
            <span className="text-muted-foreground/50">→</span>
            <span className="inline-flex items-center gap-1.5 rounded-full border bg-card/80 px-2.5 py-0.5">
              <span className="grid size-4 place-items-center rounded-full bg-muted text-[10px] font-semibold">3</span>{t("自动求得最优方案")}
            </span>
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{t("你想解决什么优化问题？")}</h1>
            <p className="mt-1 hidden text-[13px] leading-relaxed text-muted-foreground sm:block">{t("无需编写公式或代码：用日常语言说明目标（如降低成本、提高利润、合理排班）与限制条件，系统将自动完成数学建模并算出最优方案。")}</p>
          </div>
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-5">
          <ProblemEditor autoFocus value={draft.description} data={draft.data} reading={reading} onChange={description => set({ description })}
            onFiles={list => void attach(list)}
            toolbarExtra={<>{settingsTrigger}{discussTrigger}</>}
            primaryAction={startButton}
            onClear={() => {
              const previous = { description: draft.description, data: draft.data, origin: draft.origin }; set({ description: "", data: {}, origin: undefined });
              toast.success(t("已清空问题和附件。"), { action: { label: t("撤销"), onClick: () => set(previous) } });
            }}
            onDataChange={(name, content) => setDraft(current => ({ ...current, data: { ...current.data, [name]: content } }))}
            onRemove={name => setDraft(current => {
              const data = { ...current.data }; delete data[name]; return { ...current, data };
            })} />

          {!draft.description ? <section className="animate-fade-up flex shrink-0 flex-col gap-2.5">
            <div className="flex items-center justify-between gap-2 px-0.5">
              <h2 className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><Sparkles className="size-3.5 text-primary/80" />{t("不知道怎么写？点选常见场景立即体验")}</h2>
            </div>
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              {STARTERS.map(item => {
                const Icon = item.icon;
                return <button key={item.title} type="button" onClick={() => set({ description: t(item.description), data: item.data ?? {}, origin: undefined })}
                  className="group flex min-w-0 items-start gap-3 rounded-2xl border bg-card/90 p-3.5 text-left shadow-2xs transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:bg-card hover:shadow-sm">
                  <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                    <Icon className="size-4.5" />
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="flex items-center gap-2 text-sm">
                      <span className="font-semibold text-foreground">{t(item.title)}</span>
                      <Badge variant="secondary" className="h-5 rounded-md px-1.5 text-[11px] font-normal">{t(item.tag)}</Badge>
                      <ArrowRight className="ml-auto size-3.5 text-muted-foreground/60 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-primary" />
                    </span>
                    <span className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{t(item.summary)}</span>
                  </span>
                </button>;
              })}
              <button type="button" onClick={openExamples}
                className="group flex min-w-0 items-start gap-3 rounded-2xl border border-dashed bg-card/50 p-3.5 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:bg-card hover:shadow-sm">
                <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl bg-accent text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                  <BookOpen className="size-4.5" />
                </span>
                <span className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <span>{t("浏览案例模板库")}</span>
                    <ArrowRight className="ml-auto size-3.5 text-muted-foreground/60 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-primary" />
                  </span>
                  <span className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{t("涵盖生产制造、仓储配送、排班调度等真实优化场景，一键填入修改。")}</span>
                </span>
              </button>
            </div>
          </section> : null}
        </div>
      </div>
    </div>
    {settingsDialog}
  </div>;
}
