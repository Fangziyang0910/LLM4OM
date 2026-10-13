// ASCII 数学表达式 → LaTeX 的有界转换,配 KaTeX 渲染。
// 表达式来自方法保存的 expression_text:sum_{p in S} a[i,j] * x[j] <= b[k]
// 这类线性语法。任何超出该语法的内容返回 null,由调用方回退纯文本,
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

// 标识符[索引,索引] → \mathit{名}_{索引…};标识符_后缀 → 下标。
function identifier(token: string, rest: string): [string, string] {
  const underscore = token.indexOf("_");
  const name = underscore > 0 ? token.slice(0, underscore) : token;
  const tail = underscore > 0 ? token.slice(underscore + 1) : "";
  let latex = word(name);
  if (tail) latex += `_{${indexItem(tail)}}`;
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

export function toLatex(text: string): string | null {
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

export function MathTex({ text, display }: { text: string; display?: boolean }) {
  const html = useMemo(() => {
    const latex = toLatex(text);
    if (latex == null) return null;
    try {
      return katex.renderToString(latex, {
        throwOnError: true,
        strict: "ignore",
        displayMode: !!display,
      });
    } catch {
      return null;
    }
  }, [text, display]);
  if (html == null) return <span className="math-fallback">{text}</span>;
  return <span className="math-tex" dangerouslySetInnerHTML={{ __html: html }} />;
}
