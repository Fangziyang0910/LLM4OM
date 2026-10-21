import hljs from "highlight.js/lib/core";
import python from "highlight.js/lib/languages/python";
import json from "highlight.js/lib/languages/json";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { memo, useMemo, useState } from "react";
import { Check, Copy } from "lucide-react";

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

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return <div className="markdown">
    <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}
      components={{ code: ({ className, children }) => {
        const language = /language-(python|py|json)/.exec(className ?? "")?.[1];
        const source = String(children ?? "");
        if (!className && !source.includes("\n")) return <code>{children}</code>;  // inline code
        return language ? <Code text={source.replace(/\n$/, "")} language={language === "json" ? "json" : "python"} />
          : <pre className="plain"><code>{source.replace(/\n$/, "")}</code></pre>;
      }, pre: ({ children }) => <>{children}</> }}>
      {normalizeMath(text)}
    </ReactMarkdown>
  </div>;
});

export const Code = memo(function Code({ text, language = "python" }: { text: string; language?: "python" | "json" }) {
  const html = useMemo(() => hljs.highlight(text, { language }).value, [text, language]);
  const [copied, setCopied] = useState(false);
  return <div className="code-block">
    <button type="button" className="icon-button copy" aria-label="复制代码" title="复制"
      onClick={() => copyText(text)?.then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); })}>
      {copied ? <Check size={14} /> : <Copy size={14} />}
    </button>
    <pre><code className="hljs" dangerouslySetInnerHTML={{ __html: html }} /></pre>
  </div>;
});
