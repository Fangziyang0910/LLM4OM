// 方法保存的表达式 → LaTeX 的有界转换,配 KaTeX 渲染。
// 输入两种形态:一是 ASCII 线性语法(sum_{p in S} a[i,j] * x[j] <= b[k]),
// 二是模型直接写出的 LaTeX($\min 2x_A \geq 8$ 这类带定界符与命令的文本)。
// 已是合法 LaTeX 的直接放行;混合写法先归一化记号再走 ASCII 转换;
// 任何无法安全转换的内容返回 null,由调用方回退纯文本,
// 因此自然语言描述与未知符号不会被误渲染。
import { useMemo } from "react";
import katex from "katex";
import "./vendor/katex.css";

const ident = /[A-Za-z_][A-Za-z0-9_]*/;

const mathy = (text: string) =>
 /^[\x20-\x7e]*$/.test(text) &&
 /[*<>=_[\]]|^\s*(maximize|minimize|sum_)/i.test(text.trim());

const word = (name: string) => {
  if (name.length === 1) return name;
  return `\\mathit{${name}}`;
};

// 标识符[索引,索引] → \mathit{名}_{索引…};标识符_后缀 → 下标;
// 无下划线的并写变量(xA)按 splitVarName 拆成字母+下标。
function identifier(token: string, rest: string): [string, string] {
  const underscore = token.indexOf("_");
  if (underscore > 0) {
    const name = token.slice(0, underscore);
    const tail = token.slice(underscore + 1);
    let latex = word(name);
    if (tail) latex += `_{${indexItem(tail)}}`;
    const indexMatch = rest.match(/^\[([^\]]*)\]/);
    if (indexMatch) {
      latex += `_{${indexMatch[1].split(",").map((item) => indexItem(item.trim())).join(",")}}`;
      rest = rest.slice(indexMatch[0].length);
    }
    return [latex, rest];
  }
  const [name, sub] = splitVarName(token);
  let latex = sub ? name : word(name);
  if (sub) latex += `_{${indexItem(sub)}}`;
  const indexMatch = rest.match(/^\[([^\]]*)\]/);
  if (indexMatch) {
    latex += `_{${indexMatch[1].split(",").map((item) => indexItem(item.trim())).join(",")}}`;
    rest = rest.slice(indexMatch[0].length);
  }
  return [latex, rest];
}

function indexItem(item: string): string {
  return ident.test(item) ? word(item) : item;
}

// 剥离成对的数学定界符:$$…$$、$…$、\(…\)、\[…\](可嵌套多层外包裹)。
function stripDelimiters(text: string): string {
  let current = text.trim();
  for (;;) {
    const next = current
      .replace(/^\$\$([\s\S]*)\$\$$/, "$1")
      .replace(/^\$([^$]*)\$$/, "$1")
      .replace(/^\\\(([\s\S]*)\\\)$/, "$1")
      .replace(/^\\\[([\s\S]*)\\\]$/, "$1")
      .trim();
    if (next === current) return current;
    current = next;
  }
}

// 混合写法里的 LaTeX 记号 → 等价 ASCII,统一交给 ASCII 转换。
const deLatex = (text: string) =>
  text
    .replace(/≥/g, ">=")
    .replace(/≤/g, "<=")
    .replace(/\\leq\b|\\le\b/g, "<=")
    .replace(/\\geq\b|\\ge\b/g, ">=")
    .replace(/\\cdot\b|\\times\b/g, "*")
    .replace(/\\min\b/gi, "minimize")
    .replace(/\\max\b/gi, "maximize")
    .replace(/\\sum_\{([^}]*)\}/g, "sum_{$1}")
    .replace(/\\[,; ]/g, " ");

// LLM 常按 JSON 字符串习惯把反斜杠写成两个(\\geq),或把下标转义为 x\_A;
// KaTeX 会把 \\ 当换行命令、geq 当变量名渲染,先归一成单反斜杠。
function normalizeEscapes(text: string): string {
  let current = text;
  for (;;) {
    const next = current.replace(/\\\\/g, "\\").replace(/\\_/g, "_");
    if (next === current) return current;
    current = next;
  }
}

// 变量名拆分:xA/x_A/x1/xAB → 字母 + 下标;普通单词(cut)与中文名不拆。
// 文本路径与结构化路径共用同一规则。
export function splitVarName(name: string): [string, string | null] {
  const text = String(name ?? "").trim();
  const match = /^([A-Za-z])_?([A-Z0-9]{1,3})$/.exec(text);
  if (match && (text.includes("_") || /^[\dA-Z]/.test(match[2]))) return [match[1], match[2]];
  return [text, null];
}

// 无下划线的变量并写(xA + xB ≥ 8)补成下标;含 \text 等文本命令的表达式
// 跳过,避免改动文字内容。
function withSubscripts(latex: string): string {
  if (/\\(text|math[a-z]*|operatorname)/.test(latex)) return latex;
  return latex.replace(/(?<![A-Za-z_\\])([A-Za-z])([A-Z0-9]{1,3})(?![A-Za-z_])/g, "$1_$2");
}

function toLatexAscii(text: string): string | null {
  if (!mathy(text)) return null;
  try {
    let out = "";
    let rest = text.replace(/\s+/g, " ").trim().replace(/^subject to:?\s*/i, "");
    const sense = rest.match(/^(maximize|minimize)\s+/i);
    if (sense) {
      out += `\\mathrm{${sense[1].toLowerCase()}}\\;`;
      rest = rest.slice(sense[0].length);
    }
    let previous = "";
    while (rest.length) {
      const sum = rest.match(/^sum_\{([^}]*)\}/);
      if (sum) {
        const [bound] = sum[1].split(/\bin\b/).map((part) => part.trim());
        const set = sum[1].match(/\bin\s+(\w+)$/);
        out += `\\sum_{${indexItem(bound)}${set ? ` \\in ${word(set[1])}` : ""}}`;
        rest = rest.slice(sum[0].length);
        previous = "}";
        continue;
      }
      const rel = rest.match(/^(<=|>=|=)/);
      if (rel) {
        out += ` ${rel[1] === "<=" ? "\\le" : rel[1] === ">=" ? "\\ge" : "="} `;
        rest = rest.slice(rel[1].length);
        previous = "rel";
        continue;
      }
      const number = rest.match(/^\d+(?:\.\d+)?/);
      if (number) {
        out += number[0];
        rest = rest.slice(number[0].length);
        previous = "num";
        continue;
      }
      const name = rest.match(new RegExp(`^${ident.source}`));
      if (name && name[0] !== "sum") {
        const [latex, next] = identifier(name[0], rest.slice(name[0].length));
        out += latex;
        rest = next;
        previous = "id";
        continue;
      }
      const operator = rest.match(/^[+\-*/^()[\],]/);
      if (operator) {
        const token = operator[0];
        if (token === "*") out += previous === "num" ? "" : " \\cdot ";
        else if (token === "^") {
          const power = rest.slice(1).match(/^\{?(\w+)\}?/);
          if (!power) return null;
          out += `^{${indexItem(power[1])}}`;
          rest = rest.slice(1 + power[0].length);
          previous = "id";
          continue;
        } else if (token === "[") return null; // 索引只跟在标识符后
        else out += token === "," ? ",\\," : token;
        rest = rest.slice(1);
        previous = "op";
        continue;
      }
      if (rest.startsWith(" ")) {
        rest = rest.slice(1);
        continue;
      }
      return null; // 语法外字符
    }
    return out;
  } catch {
    return null;
  }
}

// 判断文本是否是"裸公式":可打印数学字符、含运算符、没有自然语言词。
// 方法的 description 字段有时被写成 ASCII 公式,据此避免公式显示两遍。
export const isBareFormula = (value: unknown): boolean => {
  const text = String(value ?? "").trim();
  return (
    !!text &&
    /^[\x20-\x7e\\$^_{}]*$/.test(text) &&
    /[*<>=_[\]\\]|\\(?:geq|leq|ge|le|cdot|times|min|max|sum)/.test(text) &&
    !/[A-Za-z]{4,}/.test(text)
  );
};

export function toLatex(text: string): string | null {
  const stripped = normalizeEscapes(stripDelimiters(String(text ?? "")));
  if (!stripped) return null;
  // 已是 LaTeX(含命令且无 ASCII 关系符):补变量下标后直接交给 KaTeX,先验证可解析。
  if (/\\[A-Za-z]+/.test(stripped) && !/<=|>=/.test(stripped)) {
    const latex = withSubscripts(stripped);
    try {
      katex.renderToString(latex, { throwOnError: true, strict: "ignore" });
      return latex;
    } catch {
      // 含未知命令时落到归一化后的 ASCII 转换
    }
  }
  return toLatexAscii(deLatex(stripped));
}

// 顶层二元运算与关系符处切分为片段;.math-expression 是 flex-wrap 容器,
// 片段作为独立子项自然换行,长公式不再被横向滚动条裁切。
// 花括号内的内容(上下标、参数)不切;一元正负号(前界是运算符/开头)不切。
function splitLatexParts(latex: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let start = 0;
  let index = 0;
  const binary = (position: number) => {
    const before = latex.slice(0, position).trimEnd().at(-1);
    return !!before && /[\w}\])]/.test(before);
  };
  const relations = /^(\\le|\\leq|\\leqslant|\\ge|\\geq|\\geqslant|\\ne|\\neq|\\equiv|\\approx)$/;
  while (index < latex.length) {
    const char = latex[index];
    if (char === "{") depth += 1;
    else if (char === "}") depth = Math.max(0, depth - 1);
    else if (char === "\\") {
      const command = /^\\[A-Za-z]+/.exec(latex.slice(index))?.[0] || "";
      if (depth === 0 && relations.test(command) && binary(index)) {
        if (index > start) parts.push(latex.slice(start, index));
        parts.push(command);
        index += command.length;
        start = index;
        continue;
      }
      index += command.length || 2;
      continue;
    } else if (depth === 0 && (char === "+" || char === "-" || char === "=") && binary(index)) {
      if (index > start) parts.push(latex.slice(start, index));
      parts.push(char);
      start = index + 1;
      index += 1;
      continue;
    }
    index += 1;
  }
  if (start < latex.length) parts.push(latex.slice(start));
  return parts.filter((part) => part.trim().length > 0);
}

export function MathTex({ text }: { text: string }) {
  const parts = useMemo(() => {
    const latex = toLatex(text);
    if (latex == null) return null;
    try {
      return splitLatexParts(latex).map((part) =>
        katex.renderToString(part, { throwOnError: true, strict: "ignore" }),
      );
    } catch {
      return null;
    }
  }, [text]);
  if (parts == null) return <span className="math-fallback">{text}</span>;
  return (
    <span className="math-tex">
      {parts.map((html, index) => (
        <span className="math-part" key={index} dangerouslySetInnerHTML={{ __html: html }} />
      ))}
    </span>
  );
}
