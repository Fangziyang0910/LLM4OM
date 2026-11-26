/** Tables the run page builds from solver output and data files. */

import { parseCsv } from "@/lib/csv";

const natural = new Intl.Collator("en", { numeric: true }).compare;

/** One variable of a solution: `x[W1,C2]` has the base `x` and the indices `W1`, `C2`. */
export type Variable = { name: string; indices: string[]; value: number | null };
/** The variables that share a base name; scalars (no indices) share the base "". */
export type VariableGroup = { base: string; dims: number; variables: Variable[] };
/** A two-index group laid out as rows (first index) by columns (second index). */
export type Matrix = { rows: string[]; columns: string[]; cell: (row: string, column: string) => number | null | undefined };

function splitIndexList(source: string): string[] {
  const parts: string[] = [];
  let start = 0;
  let quote = "";
  for (let position = 0; position < source.length; position++) {
    const character = source[position];
    if (quote) {
      if (character === "\\") position++;
      else if (character === quote) quote = "";
    } else if ((character === "'" || character === '"') && !source.slice(start, position).trim()) {
      quote = character;
    } else if (character === ",") {
      parts.push(source.slice(start, position));
      start = position + 1;
    }
  }
  parts.push(source.slice(start));
  return parts.map(part => {
    const index = part.trim();
    const delimiter = index[0];
    if (index.length < 2 || (delimiter !== "'" && delimiter !== '"') || index.at(-1) !== delimiter) return index;
    return index.slice(1, -1).replace(/\\([\\'"])/g, (escape, character: string) => character === delimiter || character === "\\" ? character : escape);
  });
}

function splitIndexedName(name: string): { base: string; indices: string[] } | null {
  const trimmed = name.trim();
  const spans: { start: number; end: number; content: string }[] = [];
  let position = 0;
  while (position < trimmed.length) {
    const open = trimmed[position];
    if (open !== "[" && open !== "(") { position++; continue; }
    const close = open === "[" ? "]" : ")";
    let cursor = position + 1;
    let tokenStart = cursor;
    let quote = "";
    let depth = 1;
    while (cursor < trimmed.length && depth > 0) {
      const ch = trimmed[cursor];
      if (quote) {
        if (ch === "\\") cursor += 2;
        else {
          if (ch === quote) quote = "";
          cursor++;
        }
        continue;
      }
      if ((ch === "'" || ch === '"') && !trimmed.slice(tokenStart, cursor).trim()) {
        quote = ch;
        cursor++;
        continue;
      }
      if (ch === open) depth++;
      else if (ch === close) {
        depth--;
        if (depth === 0) break;
      } else if (ch === "," && depth === 1) {
        tokenStart = cursor + 1;
      }
      cursor++;
    }
    if (depth !== 0) return null;
    spans.push({ start: position, end: cursor, content: trimmed.slice(position + 1, cursor) });
    position = cursor + 1;
  }
  if (!spans.length || spans.at(-1)!.end !== trimmed.length - 1) return null;
  let first = spans.length - 1;
  while (first > 0 && spans[first - 1].end + 1 === spans[first].start) first--;
  const trailing = spans.slice(first);
  const base = trimmed.slice(0, trailing[0].start);
  if (!base || trailing.some(span => !span.content.trim())) return null;
  return { base, indices: trailing.flatMap(span => splitIndexList(span.content)) };
}

function compareVariables(a: Variable, b: Variable): number {
  const shared = Math.min(a.indices.length, b.indices.length);
  for (let i = 0; i < shared; i++) {
    const diff = natural(a.indices[i], b.indices[i]);
    if (diff !== 0) return diff;
  }
  return a.indices.length - b.indices.length || natural(a.name, b.name);
}

export function groupVariables(values: Record<string, number | null>): VariableGroup[] {
  const groups = new Map<string, VariableGroup>();
  for (const [name, value] of Object.entries(values)) {
    const parsed = splitIndexedName(name);
    const variable: Variable = parsed ? { name, indices: parsed.indices, value } : { name, indices: [], value };
    const base = parsed ? parsed.base : "";
    const group = groups.get(base) ?? { base, dims: variable.indices.length, variables: [] };
    // Mixed index counts under one base name cannot form a matrix; keep the largest so callers fall back to a list.
    group.dims = Math.max(group.dims, variable.indices.length);
    group.variables.push(variable);
    groups.set(base, group);
  }
  for (const group of groups.values()) group.variables.sort(compareVariables);
  return [...groups.values()].sort((a, b) => (a.base === "") === (b.base === "") ? natural(a.base, b.base) : a.base === "" ? 1 : -1);
}

/** The group as a matrix, or null when it is not a two-index group of reasonable width. */
export function asMatrix(group: VariableGroup, maxColumns = 24): Matrix | null {
  if (group.dims !== 2 || group.variables.some(variable => variable.indices.length !== 2)) return null;
  const rows = [...new Set(group.variables.map(variable => variable.indices[0]))].sort(natural);
  const columns = [...new Set(group.variables.map(variable => variable.indices[1]))].sort(natural);
  if (columns.length > maxColumns) return null;
  const cells = new Map<string, Map<string, number | null>>();
  let uniqueCount = 0;
  for (const variable of group.variables) {
    const [row, column] = variable.indices;
    let rowMap = cells.get(row);
    if (!rowMap) { rowMap = new Map(); cells.set(row, rowMap); }
    if (rowMap.has(column)) return null;
    rowMap.set(column, variable.value);
    uniqueCount++;
  }
  if (uniqueCount !== group.variables.length) return null;
  return { rows, columns, cell: (row, column) => cells.get(row)?.get(column) };
}

/** Rows of a CSV or TSV file, or null when it is not a rectangular table worth showing as one. */
export function parseDelimited(text: string, delimiter = ","): string[][] | null {
  try {
    const table = parseCsv(text, delimiter).filter(cells => cells.some(cell => cell.trim()));
    return table.length >= 2 && table[0].length >= 2 && table.every(cells => cells.length === table[0].length) ? table : null;
  } catch { return null; }
}

/** Added and removed variables stay distinct from variables whose actual value is zero. */
/** The indices a variable is known by across models: `x[W1,C2]` → `W1,C2`; a scalar is known by its own name. */
function indexKey(name: string): string {
  const parsed = splitIndexedName(name);
  return parsed ? parsed.indices.join(",") : name.trim();
}

/**
 * Line up the variables of separately generated models, one row per decision with each model's variable name.
 * Exact names match first. A variable without an exact match joins the one earlier variable with the same indices
 * (`A` ↔ `x[A]`), so a renamed variable family stays on one row; ambiguous indices keep their own rows.
 */
export function alignVariables(solutions: Record<string, number | null>[]): (string | undefined)[][] {
  const rows: (string | undefined)[][] = [];
  const exact = new Map<string, number>();
  solutions.forEach((variables, column) => {
    const byIndex = new Map<string, number[]>();
    rows.forEach((row, at) => {
      if (row[column] !== undefined) return;
      const known = row.find(name => name !== undefined)!;
      byIndex.set(indexKey(known), [...(byIndex.get(indexKey(known)) ?? []), at]);
    });
    const pending: string[] = [];
    for (const name of Object.keys(variables)) {
      const at = exact.get(name);
      if (at !== undefined && rows[at][column] === undefined) rows[at][column] = name;
      else pending.push(name);
    }
    const counts = new Map<string, number>();
    for (const name of pending) counts.set(indexKey(name), (counts.get(indexKey(name)) ?? 0) + 1);
    for (const name of pending) {
      const candidates = (byIndex.get(indexKey(name)) ?? []).filter(at => rows[at][column] === undefined);
      const at = counts.get(indexKey(name)) === 1 && candidates.length === 1 ? candidates[0] : undefined;
      if (at !== undefined) { rows[at][column] = name; continue; }
      const row: (string | undefined)[] = Array(solutions.length).fill(undefined);
      row[column] = name;
      rows.push(row);
      if (!exact.has(name)) exact.set(name, rows.length - 1);
    }
  });
  return rows;
}

/** Decisions whose values differ between two solutions, aligned as in {@link alignVariables}. */
export function variableChanges(before: Record<string, number | null>, after: Record<string, number | null>) {
  return alignVariables([before, after])
    .map(([previous, next]) => ({ name: (previous ?? next)!, ...(previous !== undefined && next !== undefined && next !== previous ? { renamed: next } : {}),
      before: previous !== undefined ? before[previous] : undefined, after: next !== undefined ? after[next] : undefined }))
    .filter(item => item.before !== item.after);
}
