/** Rows as CSV; dates as ISO dates (or date-times), quoting only where needed. */
export function toCsv(rows: unknown[][]): string {
  const cell = (value: unknown) => {
    const text = value == null ? "" : value instanceof Date
      ? value.toISOString().replace(/T00:00:00\.000Z$/, "").replace(/\.000Z$/, "Z") : String(value);
    return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return rows.map(row => row.map(cell).join(",")).join("\n") + "\n";
}
