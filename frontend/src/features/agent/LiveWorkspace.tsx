import { useState } from "react";
import { Spinner } from "@/components/ui/spinner";
import type { ModelingTask } from "@/features/chat/Messages";
import { Outputs, type Tab } from "@/features/runs/Outputs";
import { Timeline } from "@/features/runs/Timeline";
import { phases } from "@/features/runs/steps";
import type { RunValues } from "@/features/runs/types";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";
import type { Options } from "@/types";

export default function LiveWorkspace({ task, data, options }: { task: ModelingTask; data: Record<string, string>; options: Options }) {
  const [view, setView] = useState<"steps" | "outputs">("steps");
  const [tab, setTab] = useState<Tab>("formulation");
  const [picked, setPicked] = useState<Partial<Record<"formulation" | "code", string>>>({});
  const values: RunValues = { data, ...Object.assign({}, ...task.steps.filter(step => step.type === "artifact").map(step => ({
    ...(step.formulation ? { formulation: step.formulation } : {}), ...(step.code ? { code: step.code } : {}),
  }))) };
  const all = phases(task.steps);
  const currentTitle = all.at(-1)?.step?.title;
  return <div className="flex h-full min-h-0 flex-col">
    <div className="flex shrink-0 items-center gap-2 border-b bg-primary/5 px-3.5 py-2 text-xs">
      <Spinner className="size-3.5 text-primary" />
      <span className="min-w-0 flex-1 truncate font-medium text-foreground">
        {currentTitle ? t("正在执行：{step}…", { step: t(currentTitle) }) : t("正在准备求解流程…")}
      </span>
      <div className="flex shrink-0 rounded-lg border bg-background p-0.5">
        <button type="button" onClick={() => setView("steps")}
          className={cn("rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors", view === "steps" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>
          {t("求解步骤")}
        </button>
        <button type="button" onClick={() => setView("outputs")}
          className={cn("rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors", view === "outputs" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>
          {t("模型与代码")}
        </button>
      </div>
    </div>
    <div className="min-h-0 flex-1">
      {view === "steps" ? <Timeline steps={task.steps} live={{}} active hideHeader onShow={(key, id) => { setPicked(current => ({ ...current, [key]: id })); setTab(key); setView("outputs"); }} />
        : <Outputs values={values} steps={task.steps} active tab={tab} setTab={setTab} picked={picked}
          setPicked={(key, id) => setPicked(current => ({ ...current, [key]: id }))}
          language={options.languages.find(item => item.id === task.language)} finished={false} onAdjust={() => undefined} />}
    </div>
  </div>;
}
