import "katex/dist/katex.min.css";
import { diffLines } from "diff";
import hljs from "highlight.js/lib/core";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import { fromMarkdown } from "mdast-util-from-markdown";
import type { Nodes } from "mdast";
import { Check, Copy } from "lucide-react";
import { memo, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { Button } from "@/components/ui/button";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";

hljs.registerLanguage("python", python);
hljs.registerLanguage("json", json);

// Convert LLM math delimiters outside code; use Markdown's parser to locate code spans and blocks.
function normalizeMath(text: string, singleDollarMath: boolean): string {
  if (!/\\[[(]/.test(text)) return text;
  const replace = (part: string) => part.replace(/\\\[([\s\S]*?)\\\]/g, (_, body) => `$$${body}$$`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_, body) => singleDollarMath ? `$${body}$` : `$$${body}$$`);
  const parts: string[] = [];
  let offset = 0;
  function visit(node: Nodes) {
    if (node.type === "code" || node.type === "inlineCode") {
      const start = node.position!.start.offset!, end = node.position!.end.offset!;
      parts.push(replace(text.slice(offset, start)), text.slice(start, end));
      offset = end;
    } else if ("children" in node) node.children.forEach(visit);
  }
  visit(fromMarkdown(text));
  return parts.join("") + replace(text.slice(offset));
}

/** Copies text; over plain HTTP the Clipboard API is missing, so a hidden text area is copied instead. */
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard) return navigator.clipboard.writeText(text);
  const area = Object.assign(document.createElement("textarea"), { value: text, readOnly: true });
  area.style.cssText = "position:fixed;opacity:0";
  document.body.append(area);
  area.select();
  const copied = document.execCommand("copy");
  area.remove();
  if (!copied) throw new Error("copy failed");
}

export function download(name: string, content: string | Blob) {
  const url = URL.createObjectURL(typeof content === "string" ? new Blob([content], { type: "text/plain;charset=utf-8" }) : content);
  const link = Object.assign(document.createElement("a"), { href: url, download: name });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function CopyButton({ text, label = t("复制"), className }: { text: string; label?: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  return <Button type="button" variant="ghost" size="icon-sm" aria-label={label} title={label} className={className}
    onClick={() => copyText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); }, () => undefined)}>
    {copied ? <Check className="text-success" /> : <Copy />}
  </Button>;
}

export const Markdown = memo(function Markdown({ text, className, singleDollarMath = true }: {
  // Problems contain dollar prices; explicit math delimiters keep those views unambiguous.
  text: string; className?: string; singleDollarMath?: boolean;
}) {
  return <div className={cn("markdown", className)}>
    <ReactMarkdown remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: singleDollarMath }]]} rehypePlugins={[rehypeKatex]}
      components={{ code: ({ className, children }) => {
        const language = /language-(python|py|json)/.exec(className ?? "")?.[1];
        const source = String(children ?? "");
        if (!className && !source.includes("\n")) return <code>{children}</code>;  // inline code
        return language ? <Code text={source.replace(/\n$/, "")} language={language === "json" ? "json" : "python"} className="not-prose" />
          : <Plain className="not-prose">{source.replace(/\n$/, "")}</Plain>;
      }, pre: ({ children }) => <>{children}</> }}>
      {normalizeMath(text, singleDollarMath)}
    </ReactMarkdown>
  </div>;
});

export const Code = memo(function Code({ text, language = "python", className }: {
  text: string; language?: "python" | "json"; className?: string;
}) {
  const html = useMemo(() => hljs.highlight(text, { language }).value, [text, language]);
  return <div className={cn("group relative rounded-lg border bg-muted/40", className)}>
    <CopyButton text={text} label={t("复制代码")} className="absolute top-1.5 right-1.5 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100" />
    <pre className="overflow-x-auto p-4 font-mono text-[12.5px] leading-relaxed"><code className="hljs" dangerouslySetInnerHTML={{ __html: html }} /></pre>
  </div>;
});

/** Preformatted text: solver logs, LLM replies, data files. */
export function Plain({ children, className, tone }: { children: React.ReactNode; className?: string; tone?: "bad" }) {
  return <pre className={cn("overflow-x-auto rounded-lg border bg-muted/40 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words",
    tone === "bad" && "border-destructive/25 bg-destructive/5 text-destructive", className)}>{children}</pre>;
}

/** Line changes from `before` to `after`, as a unified view. */
export function Diff({ before, after }: { before: string; after: string }) {
  const parts = useMemo(() => diffLines(before, after), [before, after]);
  const added = parts.filter(part => part.added).reduce((total, part) => total + (part.count ?? 0), 0);
  const removed = parts.filter(part => part.removed).reduce((total, part) => total + (part.count ?? 0), 0);
  return <div className="overflow-hidden rounded-lg border">
    <div className="flex gap-3 border-b bg-muted/40 px-3 py-1.5 text-xs">
      <span className="text-success">+{t("{count} 行", { count: added })}</span><span className="text-destructive">−{t("{count} 行", { count: removed })}</span>
    </div>
    <pre className="overflow-x-auto py-2 font-mono text-[12.5px] leading-relaxed">
      {parts.flatMap((part, index) => part.value.replace(/\n$/, "").split("\n").map((line, number) =>
        <div key={`${index}-${number}`} className={cn("px-3", part.added && "bg-success/10 text-success",
          part.removed && "bg-destructive/10 text-destructive")}>
          <span className="mr-3 inline-block w-3 text-muted-foreground select-none">{part.added ? "+" : part.removed ? "−" : " "}</span>{line || " "}
        </div>))}
    </pre>
  </div>;
}
