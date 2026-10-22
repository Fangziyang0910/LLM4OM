/** Tables the run page builds from solver output and data files. */

const natural = new Intl.Collator("en", { numeric: true }).compare;

/** One variable of a solution: `x[W1,C2]` has the base `x` and the indices `W1`, `C2`. */
export type Variable = { name: string; indices: string[]; value: number };
/** The variables that share a base name; scalars (no indices) share the base "". */
export type VariableGroup = { base: string; dims: number; variables: Variable[] };
/** A two-index group laid out as rows (first index) by columns (second index). */
export type Matrix = { rows: string[]; columns: string[]; cell: (row: string, column: string) => number | undefined };

export function parseVariable(name: string, value: number): Variable {
  const match = /^(.+?)[[(](.*)[\])]$/.exec(name.trim());
  if (!match) return { name, indices: [], value };
  const indices = match[2].split(",").map(index => index.trim().replace(/^['"]|['"]$/g, ""));
  return { name, indices, value };
}

export function groupVariables(values: Record<string, number>): VariableGroup[] {
  const groups = new Map<string, VariableGroup>();
  for (const [name, value] of Object.entries(values)) {
    const variable = parseVariable(name, value);
    const base = variable.indices.length ? /^(.+?)[[(]/.exec(name.trim())![1] : "";
    const group = groups.get(base) ?? { base, dims: variable.indices.length, variables: [] };
    // Mixed index counts under one base name cannot form a matrix; keep the largest so callers fall back to a list.
    group.dims = Math.max(group.dims, variable.indices.length);
    group.variables.push(variable);
    groups.set(base, group);
  }
  for (const group of groups.values()) group.variables.sort((a, b) => natural(a.indices.join("\u0000"), b.indices.join("\u0000")));
  return [...groups.values()].sort((a, b) => (a.base === "") === (b.base === "") ? natural(a.base, b.base) : a.base === "" ? 1 : -1);
}

/** The group as a matrix, or null when it is not a two-index group of reasonable width. */
export function asMatrix(group: VariableGroup, maxColumns = 24): Matrix | null {
  if (group.dims !== 2 || group.variables.some(variable => variable.indices.length !== 2)) return null;
  const rows = [...new Set(group.variables.map(variable => variable.indices[0]))].sort(natural);
  const columns = [...new Set(group.variables.map(variable => variable.indices[1]))].sort(natural);
  if (columns.length > maxColumns) return null;
  const cells = new Map(group.variables.map(variable => [variable.indices.join("\u0000"), variable.value]));
  return { rows, columns, cell: (row, column) => cells.get(row + "\u0000" + column) };
}

/** Rows of a CSV or TSV file, or null when it is not a rectangular table worth showing as one. */
export function parseDelimited(text: string, delimiter = ","): string[][] | null {
  const rows: string[][] = [];
  let row: string[] = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (char === '"') quoted = false;
      else field += char;
    } else if (char === '"' && field === "") quoted = true;
    else if (char === delimiter) { row.push(field); field = ""; }
    else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i++;
      row.push(field); rows.push(row); row = []; field = "";
    } else field += char;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  const table = rows.filter(cells => cells.some(cell => cell.trim()));
  if (table.length < 2 || table[0].length < 2 || table.some(cells => cells.length !== table[0].length)) return null;
  return table;
}
