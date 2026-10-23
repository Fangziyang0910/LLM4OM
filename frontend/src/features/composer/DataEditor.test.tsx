import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { parseCsv, toCsv } from "@/lib/csv";
import { DataEditor } from "./DataEditor";

afterEach(cleanup);

test("cell and header edits preserve every page, leading zeros, empty values and multiline text", async () => {
  const rows = [["name", "price"], ...Array.from({ length: 55 }, (_, i) => [i === 0 ? "001" : `item ${i}`, i === 1 ? 'two\n"lines"' : ""])];
  const save = vi.fn();
  render(<DataEditor name="prices.csv" content={toCsv(rows)} onSave={save} onClose={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("第 2 列列名"), { target: { value: "单价（元）" } });
  fireEvent.click(screen.getByRole("button", { name: "下一页" }));
  fireEvent.change(screen.getByLabelText("第 51 行，第 2 列"), { target: { value: "4.50" } });
  fireEvent.click(screen.getByRole("button", { name: "保存数据" }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  const updated = parseCsv(save.mock.calls[0][0]);
  expect(updated).toHaveLength(56);
  expect(updated[0][1]).toBe("单价（元）");
  expect(updated[1]).toEqual(["001", ""]);
  expect(updated[2][1]).toBe('two\n"lines"');
  expect(updated[51][1]).toBe("4.50");
  expect(updated[55]).toEqual(rows[55]);
});

test("cancel does not save edited data and a failed save keeps the editor open", async () => {
  const save = vi.fn().mockRejectedValue(new Error("save rejected")), close = vi.fn();
  render(<DataEditor name="prices.tsv" content={"name\tprice\nA\t003\n"} onSave={save} onClose={close} />);
  fireEvent.change(screen.getByLabelText("第 1 行，第 2 列"), { target: { value: "004" } });
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(close).toHaveBeenCalledOnce(); expect(save).not.toHaveBeenCalled();
  close.mockClear();
  fireEvent.click(screen.getByRole("button", { name: "保存数据" }));
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("save rejected"));
  expect(close).not.toHaveBeenCalled();
  expect(save.mock.calls[0][0]).toBe("name\tprice\nA\t004\n");
});

test("raw editing can repair malformed CSV without silently discarding it", async () => {
  const save = vi.fn();
  render(<DataEditor name="broken.csv" content={'name,price\nA,"broken'} onSave={save} onClose={vi.fn()} />);
  expect(screen.getByRole("alert").textContent).toContain("Unclosed");
  expect((screen.getByRole("button", { name: "保存数据" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("数据文件原文"), { target: { value: "name,price\nA,2\n" } });
  fireEvent.click(screen.getByRole("button", { name: "保存数据" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith("name,price\nA,2\n"));
});

test("JSON syntax errors keep the file open without saving", async () => {
  const save = vi.fn(), close = vi.fn();
  render(<DataEditor name="data.json" content='{"price":3}' onSave={save} onClose={close} />);
  fireEvent.change(screen.getByLabelText("数据文件原文"), { target: { value: "{" } });
  fireEvent.click(screen.getByRole("button", { name: "保存数据" }));
  await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  expect(save).not.toHaveBeenCalled(); expect(close).not.toHaveBeenCalled();
});

test("wide tables use raw editing and keep every column", () => {
  const content = toCsv([Array.from({ length: 80 }, (_, i) => `column ${i}`), Array(80).fill("001")]);
  render(<DataEditor name="wide.csv" content={content} onSave={vi.fn()} onClose={vi.fn()} />);
  expect((screen.getByLabelText("数据文件原文") as HTMLTextAreaElement).value).toBe(content);
});

test("CSV parsing preserves records and rejects malformed quoting", () => {
  const rows = [["code", "value"], ["001", "a,b"], ["", 'x\n"y"'], [""]];
  expect(parseCsv("\uFEFF" + toCsv(rows))).toEqual(rows);
  expect(parseCsv(toCsv(rows, "\t"), "\t")).toEqual(rows);
  expect(() => parseCsv('a,b\n"x"oops,1')).toThrow();
  expect(() => parseCsv('a,b\nx"y,1')).toThrow();
});
