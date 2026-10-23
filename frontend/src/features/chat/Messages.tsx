import type { Message } from "@langchain/langgraph-sdk";
import { ArrowUpRight, Globe, Sparkles } from "lucide-react";
import { CopyButton, Markdown } from "@/components/Content";
import { Spinner } from "@/components/ui/spinner";
import { t } from "@/i18n";

export function messageText(message: Message): string {
  return typeof message.content === "string" ? message.content : (message.content ?? [])
    .filter(block => block.type === "text").map(block => block.text).join("\n");
}

/** Tool results provide the sources; model-written links are never turned into source cards. */
export function ChatMessages({ messages, loading, label }: { messages: Message[]; loading: boolean; label: string }) {
  const completed = new Set(messages.filter(message => message.type === "tool").map(message => message.tool_call_id));
  return <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 py-4">
    {messages.map((message, index) => {
      if (message.type === "tool") {
        if (message.name !== "web_search") return null;
        const artifact = message.artifact as { query?: string; error?: string; results?: { title: string; url: string; snippet?: string; date?: string }[] } | undefined;
        const sources = (artifact?.results ?? []).filter(source => typeof source.title === "string" && /^https?:\/\//i.test(source.url) && URL.canParse(source.url));
        return <aside key={message.id ?? index} aria-label={t("搜索来源")} className="ml-9 rounded-xl border bg-card px-4 py-3 text-sm">
          <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground"><Globe className="size-3.5" />
            <span className="min-w-0 break-words">{artifact?.query || t("联网搜索")}</span>
            <span className="ml-auto shrink-0">{t("{count} 个来源", { count: sources.length })}</span>
          </div>
          {artifact?.error ? <p role="alert" className="text-destructive">{artifact.error}</p>
            : sources.length ? <ul className="flex flex-col divide-y">{sources.map((source, sourceIndex) => <li key={`${source.url}-${sourceIndex}`} className="py-2 first:pt-0 last:pb-0">
              <a href={source.url} target="_blank" rel="noopener noreferrer" className="flex items-start gap-2 font-medium text-foreground hover:text-primary">
                <span className="line-clamp-2 min-w-0 break-words">{source.title}</span><ArrowUpRight className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
              </a>
              <p className="mt-0.5 truncate text-xs text-muted-foreground">{new URL(source.url).hostname}{source.date ? ` · ${source.date.slice(0, 10)}` : ""}</p>
            </li>)}</ul> : <p className="text-xs text-muted-foreground">{t("没有找到相关网页。")}</p>}
        </aside>;
      }
      if (message.type !== "human" && message.type !== "ai") return null;
      const text = messageText(message);
      const pending = message.type === "ai" && loading && index === messages.length - 1 ? message.tool_calls?.filter(call => !completed.has(call.id ?? "")) ?? [] : [];
      if (!text && !pending.length) return null;
      return <article key={message.id ?? index} aria-label={message.type === "human" ? t("你") : label}
        className={message.type === "human" ? "group ml-auto max-w-[92%] rounded-2xl rounded-tr-sm bg-muted px-4 py-3 sm:max-w-[85%]" : "group min-w-0"}>
        {message.type === "ai" ? <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <span className="grid size-7 place-items-center rounded-lg bg-primary/10 text-primary"><Sparkles className="size-3.5" /></span>{label}</div> : null}
        {text ? <div className={message.type === "ai" ? "pl-9" : ""}><Markdown text={text} singleDollarMath={false} /></div> : null}
        {pending.map(call => <p key={call.id ?? call.name} role="status" className="mt-2 flex items-center gap-2 pl-9 text-xs text-muted-foreground">
          <Spinner />{call.name === "web_search" ? t("正在联网搜索……") : call.name === "solve_scenarios" ? t("正在重新建模求解……")
            : call.name === "lookup_variables" ? t("正在查询实际决策值……") : t("正在更新需求稿……")}</p>)}
        {text && message.type === "ai" ? <div className="mt-1 pl-8 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:focus-within:opacity-100">
          <CopyButton text={text} label={t("复制回复")} />
        </div> : null}
      </article>;
    })}
    {loading ? <div role="status" className="flex items-center gap-2 pl-9 text-xs text-muted-foreground"><Spinner />{t("正在回复……")}</div> : null}
  </div>;
}
