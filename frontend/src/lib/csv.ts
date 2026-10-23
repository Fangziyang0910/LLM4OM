/** Rows as CSV; dates as ISO dates (or date-times), quoting only where needed. */
export function toCsv(rows: unknown[][], delimiter = ","): string {
  const cell = (value: unknown) => {
    const text = value == null ? "" : value instanceof Date
      ? value.toISOString().replace(/T00:00:00\.000Z$/, "").replace(/\.000Z$/, "Z") : String(value);
    return /["\n\r]/.test(text) || text.includes(delimiter) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return rows.map(row => row.map(cell).join(delimiter)).join("\n") + "\n";
}

/** Parse without coercing values or dropping blank records; malformed quotes cannot be edited silently. */
export function parseCsv(source: string, delimiter = ","): string[][] {
  const text = source.replace(/^\uFEFF/, "");
  const rows: string[][] = [];
  let row: string[] = [], field = "", quoted = false, closed = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (char === '"') { quoted = false; closed = true; }
      else field += char;
    } else if (char === delimiter) { row.push(field); field = ""; closed = false; }
    else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i++;
      row.push(field); rows.push(row); row = []; field = ""; closed = false;
    } else if (char === '"' && !field && !closed) quoted = true;
    else if (char === '"' || closed) throw new Error("Unexpected text outside a quoted field.");
    else field += char;
  }
  if (quoted) throw new Error("Unclosed quoted field.");
  if (field || row.length || closed) { row.push(field); rows.push(row); }
  return rows;
}
