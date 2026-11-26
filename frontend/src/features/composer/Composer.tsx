import { useLayoutEffect, useRef, useState } from "react";
import { ArrowRight, Factory, GitFork, MessageSquareText, Truck } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { errorText } from "@/format";
import { t } from "@/i18n";
import { ProblemEditor } from "@/features/composer/ProblemEditor";
import { type ModelingConfigProps, useRunLauncher } from "@/features/composer/RunSettings";
import { readDataFiles } from "@/features/composer/files";
import { saveDraft } from "./draft";
export { initialDraft } from "./draft";
import type { Draft } from "@/types";

const STARTERS: {
  icon: typeof Factory;
  title: string;
  tag: string;
  summary: string;
  description: string;
  data?: Record<string, string>;
  method?: string;
}[] = [
  {
    icon: Factory,
    title: "生产计划",
    tag: "精确求解",
    summary: "在有限设备与工序额度下，合理安排多种产品的产量，让总利润最高。",
    description: "工厂生产 A、B 两种产品，数量必须是非负整数。每件 A 利润为 3，每件 B 利润为 2。A 消耗 2 单位切割资源和 1 单位加工资源，" +
      "B 消耗 1 单位切割资源和 2 单位加工资源。两种资源各有 8 单位。请确定生产数量，使总利润最大。",
    method: "direct",
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
    method: "direct",
  },
  {
    icon: GitFork,
    title: "多目标 GPU 调度",
    tag: "AutoCO · 多目标",
    summary: "把 12 个 AI 训练任务分到 4 个集群，同时权衡总电费与故障风险，自动生成 Pareto 前沿。",
    description: "将 12 个 AI 计算任务（编号 0 到 11）分配到 4 个异构 GPU 集群（编号 0 到 3），每个任务只能分配到一个集群。" +
      "任务算力需求为 [18, 25, 14, 30, 22, 16, 28, 19, 24, 15, 27, 20]；" +
      "各集群算力上限为 [80, 90, 75, 85]，单位电费系数为 [1.0, 1.2, 0.9, 1.3]，故障风险系数为 [0.08, 0.04, 0.11, 0.02]。" +
      "硬约束：每个集群承担的总算力不能超过其上限，且互斥任务对 (0, 1)、(3, 6)、(5, 10) 不能分在同一集群。" +
      "请同时最小化两个冲突目标（求 Pareto 非支配解集）：1）总电费 = sum(任务算力 * 所在集群电费系数）；2）总故障风险 = sum(任务算力 * 所在集群风险系数）。",
    method: "autoco",
  },
];

export type ComposerProps = ModelingConfigProps & {
  openExamples: () => void;
  onDiscuss?: () => Promise<void>;
};

export function Composer({ onDiscuss, ...modeling }: ComposerProps) {
  const { draft, setDraft, options } = modeling;
  const [reading, setReading] = useState(false);
  const latestDraft = useRef(draft);
  useLayoutEffect(() => { latestDraft.current = draft; }, [draft]);
  const set = (change: Partial<Draft>) => setDraft(current => ({ ...current, ...change }));
  const { busy, setBusy, settingsTrigger, startButton, settingsDialog } = useRunLauncher({
    ...modeling,
    problem: { description: draft.description, data: draft.data, origin: draft.origin },
    reading,
  });

  const applyFiles = async (files: Record<string, string>) => {
    if (!Object.keys(files).length) return;
    const current = latestDraft.current;
    const data = { ...current.data, ...files };
    try { await saveDraft({ ...current, data }); }
    catch (error) { toast.error(t("草稿未保存到浏览器：{error}", { error: errorText(error) }), { id: "draft-save" }); }
    setDraft(latest => ({ ...latest, data }));
  };
  const attach = async (list: FileList | null) => {
    setReading(true);
    try { await applyFiles(await readDataFiles(list, draft.data)); }
    finally { setReading(false); }
  };

  return <div className="flex h-full flex-col">
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex min-h-full max-w-5xl flex-col gap-4 p-4 sm:px-6 sm:py-5 lg:h-full">
        <header className="animate-fade-up flex shrink-0 flex-col gap-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h1 className="text-lg font-semibold tracking-tight sm:text-xl">{draft.comparing ? t("多方案对比") : t("单次求解")}</h1>
            {onDiscuss ? <Button type="button" variant="ghost" size="sm" disabled={busy || reading}
              className="text-xs text-muted-foreground" onClick={async () => {
                setBusy(true);
                try { await onDiscuss(); } catch (error) { toast.error(errorText(error)); } finally { setBusy(false); }
              }}><MessageSquareText />{t("通过对话整理需求")}</Button> : null}
          </div>
          <p className="text-xs text-muted-foreground sm:text-[13px]">{t("同一问题可指定或并排对比多种建模方法、AI 模型与求解器。")}</p>
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-5">
          <ProblemEditor autoFocus value={draft.description} data={draft.data} reading={reading} onChange={description => set({ description })}
            onFiles={list => void attach(list)}
            toolbarExtra={settingsTrigger}
            primaryAction={startButton}
            onClear={() => {
              const previous = { description: draft.description, data: draft.data, origin: draft.origin }; set({ description: "", data: {}, origin: undefined });
              toast.success(t("已清空问题和附件。"), { action: { label: t("撤销"), onClick: () => set(previous) } });
            }}
            onDataChange={(name, content) => applyFiles({ [name]: content })}
            onRemove={name => setDraft(current => {
              const data = { ...current.data }; delete data[name]; return { ...current, data };
            })} />

          {!draft.description && !Object.keys(draft.data).length ? <section className="animate-fade-up flex shrink-0 flex-col gap-2">
            <h2 className="px-0.5 text-xs font-medium text-muted-foreground">{t("快速示例")}</h2>
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
              {STARTERS.map(item => {
                const Icon = item.icon;
                const targetMethod = item.method && options.methods.some(m => m.id === item.method) ? item.method : undefined;
                return <button key={item.title} type="button" onClick={() => set({
                  description: t(item.description), data: item.data ?? {}, origin: undefined,
                  ...(!draft.comparing && targetMethod ? { method: targetMethod } : {}),
                })}
                  className="group flex min-w-0 flex-col gap-2 rounded-xl border bg-card/90 p-3.5 text-left transition-all duration-150 hover:border-primary/40 hover:bg-card hover:shadow-xs">
                  <span className="flex items-center gap-2 text-sm">
                    <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                      <Icon className="size-3.5" />
                    </span>
                    <span className="truncate font-medium text-foreground">{t(item.title)}</span>
                    <Badge variant="secondary" className="h-4.5 shrink-0 rounded px-1.5 text-[10px] font-normal">{t(item.tag)}</Badge>
                    <ArrowRight className="ml-auto size-3.5 shrink-0 text-muted-foreground/60 opacity-0 transition-all group-hover:translate-x-0.5 group-hover:text-primary group-hover:opacity-100" />
                  </span>
                  <span className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{t(item.summary)}</span>
                </button>;
              })}
            </div>
          </section> : null}
        </div>
      </div>
    </div>
    {settingsDialog}
  </div>;
}
