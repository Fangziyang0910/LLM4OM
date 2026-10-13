// 极简 Python 语法高亮:无依赖的字符级扫描器,支持跨三引号字符串的
// 行拆分。只做展示着色,不解析语义。

export interface Token {
  text: string;
  type: "kw" | "str" | "num" | "com" | "bi" | "dec" | "def" | "plain";
}

const keywords = new Set([
  "def", "class", "return", "if", "elif", "else", "for", "while", "in", "not",
  "and", "or", "import", "from", "as", "with", "try", "except", "finally",
  "raise", "pass", "break", "continue", "lambda", "yield", "global",
  "nonlocal", "assert", "del", "is", "None", "True", "False",
]);
const builtins = new Set([
  "range", "len", "print", "int", "float", "str", "list", "dict", "set",
  "tuple", "sum", "min", "max", "abs", "enumerate", "zip", "round", "sorted",
  "any", "all", "open", "isinstance", "type", "super", "property",
  "staticmethod", "classmethod", "self", "value", "Var", "Objective",
  "Constraint", "ConcreteModel", "SolverFactory", "positive_integers",
  "Binary", "Integers", "NonNegativeIntegers", "Reals", "minimize", "maximize",
]);

const isWord = (char: string) => /[A-Za-z_]/.test(char);

export function tokenizePython(source: string): Token[] {
  const tokens: Token[] = [];
  let index = 0;
  let plain = "";
  const flush = () => {
    if (plain) {
      tokens.push({ text: plain, type: "plain" });
      plain = "";
    }
  };
  while (index < source.length) {
    const char = source[index];
    if (char === "#") {
      flush();
      const end = source.indexOf("\n", index);
      const stop = end === -1 ? source.length : end;
      tokens.push({ text: source.slice(index, stop), type: "com" });
      index = stop;
      continue;
    }
    if (char === '"' || char === "'") {
      flush();
      const triple = source.slice(index, index + 3);
      const quote = triple === '"""' || triple === "'''" ? triple : char;
      let end = index + quote.length;
      while (end < source.length) {
        if (source[end] === "\\") {
          end += 2;
          continue;
        }
        if (source.startsWith(quote, end)) break;
        end += 1;
      }
      const stop = Math.min(source.length, end + quote.length);
      tokens.push({ text: source.slice(index, stop), type: "str" });
      index = stop;
      continue;
    }
    if (/[0-9]/.test(char) && !isWord(plain.slice(-1) || " ")) {
      flush();
      const match = /^[0-9][0-9_.eE]*/.exec(source.slice(index));
      const text = match ? match[0] : char;
      tokens.push({ text, type: "num" });
      index += text.length;
      continue;
    }
    if (isWord(char)) {
      const word = /^[A-Za-z_][A-Za-z0-9_]*/.exec(source.slice(index))![0];
      const previous = tokens.at(-1)?.text ?? "";
      flush();
      if (previous === "def" || previous === "class")
        tokens.push({ text: word, type: "def" });
      else if (keywords.has(word)) tokens.push({ text: word, type: "kw" });
      else if (builtins.has(word)) tokens.push({ text: word, type: "bi" });
      else plain += word;
      index += word.length;
      continue;
    }
    plain += char;
    index += 1;
  }
  flush();
  return tokens;
}

/** 把 token 序列拆成行;跨行 token(三引号字符串)按行切开。 */
export function tokenizeLines(source: string): Token[][] {
  const tokens = tokenizePython(source);
  const lines: Token[][] = [[]];
  for (const token of tokens) {
    const pieces = token.text.split("\n");
    pieces.forEach((piece, position) => {
      if (position > 0) lines.push([]);
      if (piece) lines[lines.length - 1].push({ text: piece, type: token.type });
    });
  }
  return lines;
}
