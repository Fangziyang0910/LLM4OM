import "katex/dist/katex.min.css";
import { diffLines } from "diff";
import hljs from "highlight.js/lib/core";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import { Check, Copy } from "lucide-react";
import { memo, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

hljs.registerLanguage("python", python);
hljs.registerLanguage("json", json);

// LLMs often write \( \) and \[ \]; remark-math understands $ and $$.
const normalizeMath = (text: string) =>
  text.replace(/\\\[([\s\S]*?)\\\]/g, (_, body) => `$$${body}$$`).replace(/\\\(([\s\S]*?)\\\)/g, (_, body) => `$${body}$`);

export const copyText = (text: string) => navigator.clipboard?.writeText(text).catch(() => undefined);

export function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = Object.assign(document.createElement("a"), { href: url, download: name });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function CopyButton({ text, label = "复制", className }: { text: string; label?: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  return <Button type="button" variant="ghost" size="icon-sm" aria-label={label} title={label} className={className}
    onClick={() => copyText(text)?.then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); })}>
    {copied ? <Check className="text-success" /> : <Copy />}
  </Button>;
}

export const Markdown = memo(function Markdown({ text, className }: { text: string; className?: string }) {
  return <div className={cn("markdown", className)}>
    <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}
      components={{ code: ({ className, children }) => {
        const language = /language-(python|py|json)/.exec(className ?? "")?.[1];
        const source = String(children ?? "");
        if (!className && !source.includes("\n")) return <code>{children}</code>;  // inline code
        return language ? <Code text={source.replace(/\n$/, "")} language={language === "json" ? "json" : "python"} className="not-prose" />
          : <Plain className="not-prose">{source.replace(/\n$/, "")}</Plain>;
      }, pre: ({ children }) => <>{children}</> }}>
      {normalizeMath(text)}
    </ReactMarkdown>
  </div>;
});

export const Code = memo(function Code({ text, language = "python", className }: {
  text: string; language?: "python" | "json"; className?: string;
}) {
  const html = useMemo(() => hljs.highlight(text, { language }).value, [text, language]);
  return <div className={cn("group relative rounded-lg border bg-muted/40", className)}>
    <CopyButton text={text} label="复制代码" className="absolute top-1.5 right-1.5 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100" />
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
      <span className="text-success">+{added} 行</span><span className="text-destructive">−{removed} 行</span>
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
