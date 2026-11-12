import { useState } from "react";
import { cleanup, createEvent, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ProblemEditor } from "./ProblemEditor";

afterEach(cleanup);

const source = "# 营养计划\n\n- 鸡肉 $4\n- 大米 $8\n\n| 食物 | 蛋白质 |\n| --- | --- |\n| 鸡肉 | 18 |\n\n约束：\\(x \\le 8\\)。\n\n$$x \\ge 0$$";

function Editor({ data = {} }: { data?: Record<string, string> }) {
  const [value, setValue] = useState(source);
  return <ProblemEditor value={value} data={data} onChange={setValue} onFiles={vi.fn()} onRemove={vi.fn()}
    onClear={() => setValue("")} onExamples={vi.fn()} onDataChange={vi.fn()} />;
}

test("Markdown preview renders the problem without changing its source or dollar prices", () => {
  const { container } = render(<Editor />);
  fireEvent.mouseDown(screen.getByRole("tab", { name: "预览" }));
  expect(screen.getByRole("heading", { name: "营养计划" })).toBeTruthy();
  expect(screen.getByRole("table")).toBeTruthy();
  expect(screen.getByText("鸡肉 $4")).toBeTruthy();
  expect(screen.getByText("大米 $8")).toBeTruthy();
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(2);
  expect(container.querySelector(".katex-error")).toBeNull();
  fireEvent.mouseDown(screen.getByRole("tab", { name: "编辑" }));
  const input = screen.getByRole("textbox", { name: "问题描述" }) as HTMLTextAreaElement;
  expect(input.value).toBe(source);
  fireEvent.change(input, { target: { value: source.replace("营养计划", "更新后的计划") } });
  fireEvent.mouseDown(screen.getByRole("tab", { name: "预览" }));
  expect(screen.getByRole("heading", { name: "更新后的计划" })).toBeTruthy();
});

test("clearing a preview returns to an empty editable problem", () => {
  render(<Editor />);
  fireEvent.mouseDown(screen.getByRole("tab", { name: "预览" }));
  fireEvent.click(screen.getByRole("button", { name: "清空" }));
  expect((screen.getByRole("textbox", { name: "问题描述" }) as HTMLTextAreaElement).value).toBe("");
});

test("attachment counts CSV records instead of physical lines in multiline cells", () => {
  render(<Editor data={{ "notes.csv": 'name,notes\nA,"first line\nsecond line"\n' }} />);
  expect(screen.getByText("2 行")).toBeTruthy();
});

test("text drags keep native editing available without showing the file overlay", () => {
  const attach = vi.fn();
  render(<ProblemEditor value={source} data={{}} onChange={vi.fn()} onFiles={attach} onRemove={vi.fn()}
    onClear={vi.fn()} onDataChange={vi.fn()} />);
  const input = screen.getByRole("textbox", { name: "问题描述" });
  const dataTransfer = { types: ["text/plain"], files: [] };
  const over = createEvent.dragOver(input, { dataTransfer });
  fireEvent(input, over);
  expect(over.defaultPrevented).toBe(false);
  expect(screen.queryByText("松开以添加数据文件")).toBeNull();
  const drop = createEvent.drop(input, { dataTransfer });
  fireEvent(input, drop);
  expect(drop.defaultPrevented).toBe(false);
  expect(attach).not.toHaveBeenCalled();
});

test("file drag feedback stays visible between editor children and clears when leaving", () => {
  render(<Editor />);
  const input = screen.getByRole("textbox", { name: "问题描述" });
  fireEvent.dragOver(input, { dataTransfer: { types: ["Files"] } });
  expect(screen.getByText("松开以添加数据文件")).toBeTruthy();
  fireEvent(input, new MouseEvent("dragleave", { bubbles: true, relatedTarget: screen.getByRole("button", { name: "清空" }) }));
  expect(screen.getByText("松开以添加数据文件")).toBeTruthy();
  fireEvent(input, new MouseEvent("dragleave", { bubbles: true, relatedTarget: document.body }));
  expect(screen.queryByText("松开以添加数据文件")).toBeNull();
});

test.each([false, true])("file drops are intercepted and respect disabled=%s", disabled => {
  const attach = vi.fn();
  render(<ProblemEditor value={source} data={{}} disabled={disabled} onChange={vi.fn()} onFiles={attach}
    onRemove={vi.fn()} onClear={vi.fn()} onDataChange={vi.fn()} />);
  const input = screen.getByRole("textbox", { name: "问题描述" });
  const files = [new File(["name,price\nA,3\n"], "prices.csv")];
  const dataTransfer = { types: ["Files"], files };
  const over = createEvent.dragOver(input, { dataTransfer });
  fireEvent(input, over);
  expect(over.defaultPrevented).toBe(true);
  expect(!!screen.queryByText("松开以添加数据文件")).toBe(!disabled);
  const drop = createEvent.drop(input, { dataTransfer });
  fireEvent(input, drop);
  expect(drop.defaultPrevented).toBe(true);
  expect(screen.queryByText("松开以添加数据文件")).toBeNull();
  if (disabled) expect(attach).not.toHaveBeenCalled();
  else expect(attach).toHaveBeenCalledWith(files);
});
