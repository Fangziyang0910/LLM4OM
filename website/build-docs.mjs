import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import ReactMarkdown from "../frontend/node_modules/react-markdown/index.js";
import remarkGfm from "../frontend/node_modules/remark-gfm/index.js";

const require = createRequire(import.meta.url);
const React = require("../frontend/node_modules/react");
const { renderToStaticMarkup } = require("../frontend/node_modules/react-dom/server");
const hljs = require("../frontend/node_modules/highlight.js");
const directory = path.dirname(fileURLToPath(import.meta.url));
const root = path.dirname(directory);
const output = path.join(directory, "public/docs");
const manifest = JSON.parse(await fs.readFile(path.join(directory, "docs-manifest.json"), "utf8"));
const { groups, articles } = manifest;
const facts = JSON.parse(execFileSync(path.join(root, ".venv/bin/python"), ["-c", `
import json
from llm4om.methods import methods
from llm4om.languages import LANGUAGES
print(json.dumps({"methods": {k: {"parameters": v.parameters(), "linear_only": v.linear_only} for k,v in methods().items()}, "libraries": list(LANGUAGES)}))
`], { cwd: root, encoding: "utf8" }));
const escape = value => String(value).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const textOf = children => React.Children.toArray(children).map(child => typeof child === "object" ? textOf(child.props.children) : String(child)).join("");
const copy = {
  home: ["返回官网", "Product"], docs: ["文档中心", "Documentation"], search: ["搜索文档", "Search docs"],
  menu: ["目录", "Menu"], close: ["关闭", "Close"], toc: ["本页内容", "On this page"],
  previous: ["上一篇", "Previous"], next: ["下一篇", "Next"], source: ["相关实现与原始文档", "Implementation and source docs"],
  table: ["表格，可横向滚动", "Table, scroll horizontally"], skip: ["跳到文章", "Skip to article"],
  searchHint: ["搜索功能、方法或求解器，例如：调整条件、BIND、HiGHS", "Search features, methods or solvers: revisions, BIND, HiGHS"],
  searchEmpty: ["输入关键词查找文档", "Type to find a page"], searchHelp: ["↑ ↓ 选择 · Enter 打开 · Esc 关闭", "↑ ↓ select · Enter open · Esc close"],
  built: ["由 EIPI 团队开发", "Built by the EIPI team"], scope: ["当前平台实现", "Current platform implementation"]
};

if (new Set(articles.map(a => a.id)).size !== articles.length) throw new Error("Duplicate article ID");
for (const [key, present] of [["method", Object.keys(facts.methods)], ["library", facts.libraries]]) {
  const documented = articles.filter(a => a[key]).map(a => a[key]);
  if (JSON.stringify([...documented].sort()) !== JSON.stringify([...present].sort())) throw new Error(`Documentation does not cover the current ${key} registry`);
}
for (const article of articles) {
  if (!/^[a-z][a-z0-9-]*$/.test(article.id) || !groups.some(g => g.id === article.group)) throw new Error(`Invalid article: ${article.id}`);
  for (const file of article.sources) await fs.access(path.join(root, file));
}

for (const [index, locale] of ["zh", "en"].entries()) {
  const t = key => copy[key][index];
  const title = item => item.title[index];
  const summary = item => item.summary[index];
  const search = [];
  const navigation = groups.map(group => `<details open class="nav-group"><summary>${escape(title(group))}<span>${articles.filter(a => a.group === group.id).length}</span></summary><ul>${articles.filter(a => a.group === group.id).map(a => `<li><a href="../${a.id}/" data-article="${a.id}">${escape(title(a))}</a></li>`).join("")}</ul></details>`).join("");
  for (const [position, article] of articles.entries()) {
    let markdown = await fs.readFile(path.join(directory, "content", locale, `${article.id}.md`), "utf8");
    if (markdown.trim().length < 250) throw new Error(`Incomplete content: ${locale}/${article.id}`);
    if (article.method) {
      const parameters = Object.entries(facts.methods[article.method].parameters);
      markdown += `\n## ${index ? "Current parameters" : "当前参数"}\n\n`;
      markdown += index ? "Parameters come from the deployed method preset. They are saved with each run and cannot be changed per run in the UI, CLI or Python API.\n\n" : "参数来自部署时的方法预设，随每次运行记录保存。页面、命令行和 Python 接口均不提供单次运行的参数修改。\n\n";
      markdown += parameters.length ? `| ${index ? "Parameter" : "参数"} | ${index ? "Value" : "取值"} |\n|---|---|\n${parameters.map(([key, value]) => `| \`${key}\` | \`${JSON.stringify(value).replaceAll("|", "\\|")}\` |`).join("\n")}\n` : index ? "Direct has no method-specific preset parameters.\n" : "Direct 没有方法专属的预设参数。\n";
      markdown += `\n[${index ? "Parameter definitions" : "查看参数定义"}](https://github.com/Fangziyang0910/LLM4OM/blob/main/src/llm4om/methods/presets.py)\n`;
    }
    const headings = [];
    const heading = level => ({ children }) => {
      const id = `section-${headings.length + 1}`;
      const label = textOf(children);
      headings.push({ id, label, level });
      return React.createElement(`h${level}`, { id }, children, React.createElement("a", { href: `#${id}`, className: "heading-anchor", "aria-label": `${label} — ${index ? "link to section" : "章节链接"}` }, "#"));
    };
    const html = renderToStaticMarkup(React.createElement(ReactMarkdown, {
      remarkPlugins: [remarkGfm], skipHtml: true,
      components: {
        h2: heading(2), h3: heading(3),
        table: ({ children }) => React.createElement("div", { className: "table-scroll", tabIndex: 0, role: "region", "aria-label": t("table") }, React.createElement("table", {}, children)),
        code: ({ children, className }) => {
          const language = className?.replace("language-", "");
          if (language && hljs.getLanguage(language)) return React.createElement("code", { className, dangerouslySetInnerHTML: { __html: hljs.highlight(String(children), { language }).value } });
          return React.createElement("code", { className }, children);
        }
      }
    }, markdown));
    if (!headings.length) throw new Error(`No sections: ${locale}/${article.id}`);
    const group = groups.find(g => g.id === article.group);
    const nav = navigation.replaceAll(`data-article="${article.id}"`, `data-article="${article.id}" aria-current="page"`);
    const cards = article.id === "introduction" ? groups.map(g => {
      const first = articles.find(a => a.group === g.id && a.id !== "introduction");
      return `<a class="doc-card" href="../${first.id}/"><span class="card-arrow" aria-hidden="true">↗</span><strong>${escape(title(g))}</strong><span>${escape(g.description[index])}</span></a>`;
    }).join("") : ["methods", "solvers"].includes(article.id) ? articles.filter(a => a.group === article.group && a.id !== article.id).map(a => `<a class="doc-card" href="../${a.id}/"><span class="card-arrow" aria-hidden="true">↗</span><strong>${escape(title(a))}</strong><span>${escape(summary(a))}</span></a>`).join("") : "";
    const pageLink = (item, direction) => item ? `<a href="../${item.id}/" class="pagination-${direction}"><span>${t(direction)}</span><strong>${direction === "previous" ? "← " : ""}${escape(title(item))}${direction === "next" ? " →" : ""}</strong></a>` : "<span></span>";
    const counterpart = `../../${index ? "zh" : "en"}/${article.id}/`;
    const tocLinks = headings.map(h => `<a href="#${h.id}" class="toc-level-${h.level}">${escape(h.label)}</a>`).join("");
    const page = `<!doctype html>
<html lang="${index ? "en" : "zh-CN"}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#101014"><meta name="description" content="${escape(summary(article))}"><title>${escape(title(article))} · LLM4OM Docs</title><meta property="og:title" content="${escape(title(article))} · LLM4OM Docs"><meta property="og:description" content="${escape(summary(article))}"><link rel="canonical" href="https://fangziyang0910.github.io/LLM4OM/docs/${locale}/${article.id}/"><link rel="alternate" hreflang="zh-CN" href="../../zh/${article.id}/"><link rel="alternate" hreflang="en" href="../../en/${article.id}/"><link rel="icon" href="../../../assets/llm4om.svg" type="image/svg+xml"><link rel="preload" href="../../../assets/inter-latin-wght-normal.woff2" as="font" type="font/woff2" crossorigin><link rel="stylesheet" href="../../../styles.css"><link rel="stylesheet" href="../../docs.css"><script src="../../docs.js" defer></script></head>
<body class="docs-page" data-locale="${locale}"><a class="skip-link" href="#article">${t("skip")}</a>
<header class="site-header docs-header"><div class="docs-header-inner"><a class="brand" href="../../../?lang=${locale}"><img src="../../../assets/llm4om.svg" width="29" height="29" alt=""><span>LLM4OM</span></a><a class="docs-wordmark" href="../introduction/">Docs</a><button class="docs-search-button" id="search-open" type="button" aria-haspopup="dialog"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="10" cy="10" r="6.5"/><path d="m15 15 6 6"/></svg><span>${t("search")}</span><kbd>⌘ K</kbd></button><nav class="docs-header-links" aria-label="${t("menu")}"><a class="docs-product-link" href="../../../?lang=${locale}">${t("home")}</a><a id="docs-language" class="language-button" href="${counterpart}" lang="${index ? "zh-CN" : "en"}" aria-label="${index ? "切换到中文" : "Switch to English"}">${index ? "中文" : "EN"}</a><a class="docs-github" href="https://github.com/Fangziyang0910/LLM4OM" aria-label="GitHub"><img src="../../../assets/github.svg" width="20" height="20" alt=""></a></nav></div></header>
<div class="docs-mobile-bar"><button id="mobile-menu" type="button" aria-haspopup="dialog"><span aria-hidden="true">☰</span> ${t("menu")}</button><span>${escape(title(group))}</span></div>
<div class="docs-layout"><aside class="docs-sidebar"><nav aria-label="${t("docs")}">${nav}</nav><a class="sidebar-team" href="https://scut-eipi.github.io/">EIPI <span>↗</span></a></aside>
<main class="docs-main" id="article" tabindex="-1"><div class="doc-breadcrumb"><span>${escape(title(group))}</span><span aria-hidden="true">/</span><span>${escape(title(article))}</span></div><header class="article-heading"><h1>${escape(title(article))}</h1><p>${escape(summary(article))}</p></header>${cards && article.id === "introduction" ? `<div class="doc-card-grid intro-cards">${cards}</div>` : ""}<details class="docs-inline-toc"><summary>${t("toc")}</summary><nav aria-label="${t("toc")}">${tocLinks}</nav></details><article class="doc-prose">${html}</article>${cards && article.id !== "introduction" ? `<div class="doc-card-grid">${cards}</div>` : ""}<details class="doc-sources"><summary>${t("source")}</summary><ul>${article.sources.map(file => `<li><a href="https://github.com/Fangziyang0910/LLM4OM/blob/main/${escape(file)}">${escape(file)}</a></li>`).join("")}</ul></details><nav class="doc-pagination" aria-label="${index ? "Article navigation" : "文章导航"}">${pageLink(articles[position - 1], "previous")}${pageLink(articles[position + 1], "next")}</nav><footer class="doc-footer"><a href="https://scut-eipi.github.io/">${t("built")} ↗</a><span>LLM4OM Docs</span></footer></main>
<aside class="docs-toc"><p>${t("toc")}</p><nav aria-label="${t("toc")}">${tocLinks}</nav><a class="toc-top" href="#article">${index ? "Back to top ↑" : "回到顶部 ↑"}</a></aside></div>
<dialog id="mobile-nav" class="docs-nav-dialog"><div class="dialog-header"><span>${t("docs")}</span><button type="button" data-close="mobile-nav" aria-label="${t("close")}">×</button></div><nav aria-label="${t("docs")}">${nav}</nav></dialog>
<dialog id="docs-search" class="docs-search-dialog" aria-labelledby="search-title"><div class="search-field"><label id="search-title" class="sr-only" for="search-input">${t("search")}</label><input id="search-input" type="search" autocomplete="off" placeholder="${t("searchHint")}"><button type="button" data-close="docs-search" aria-label="${t("close")}">Esc</button></div><p id="search-status" role="status">${t("searchEmpty")}</p><ol id="search-results"></ol><div class="search-help">${t("searchHelp")}</div></dialog>
</body></html>\n`;
    await fs.mkdir(path.join(output, locale, article.id), { recursive: true });
    await fs.writeFile(path.join(output, locale, article.id, "index.html"), page);
    search.push({ id: article.id, title: title(article), description: summary(article), group: title(group), text: html.replace(/<a[^>]*class="heading-anchor"[^>]*>.*?<\/a>/g, "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " "), headings });
  }
  await fs.writeFile(path.join(output, `search-${locale}.json`), JSON.stringify(search) + "\n");
}
await fs.writeFile(path.join(output, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
await fs.writeFile(path.join(output, "index.html"), `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LLM4OM Docs</title><meta name="description" content="LLM4OM 中英文使用文档 / LLM4OM documentation in Chinese and English"><link rel="stylesheet" href="../styles.css"><script>let language=new URLSearchParams(location.search).get('lang');try{language=language||localStorage.getItem('llm4om-site-language')}catch{}location.replace('./'+(language==='en'?'en':'zh')+'/introduction/')</script></head><body><main style="padding:60px"><h1>LLM4OM Docs</h1><p><a href="zh/introduction/">中文文档 →</a></p><p><a href="en/introduction/">English documentation →</a></p></main></body></html>\n`);
console.log(`Built ${articles.length} articles × 2 languages, with ${Object.keys(facts.methods).length} methods and ${facts.libraries.length} libraries.`);
