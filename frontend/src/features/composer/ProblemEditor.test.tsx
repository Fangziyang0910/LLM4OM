import { useState } from "react";
import { cleanup, createEvent, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ProblemEditor } from "./ProblemEditor";

afterEach(cleanup);

const source = "# 营养计划\n\n- 鸡肉 $4\n- 大米 $8\n\n| 食物 | 蛋白质 |\n| --- | --- |\n| 鸡肉 | 18 |\n\n约束：\\(x \\le 8\\)。\n\n$$x \\ge 0$$";

function Editor({ initial = source, data = {}, onChangeSpy }: {
  initial?: string; data?: Record<string, string>; onChangeSpy?: (value: string) => void;
}) {
  const [value, setValue] = useState(initial);
  const update = (next: string) => { setValue(next); onChangeSpy?.(next); };
  return <ProblemEditor value={value} data={data} onChange={update} onFiles={vi.fn()} onRemove={vi.fn()}
    onClear={() => update("")} onDataChange={vi.fn()} />;
}

test("renders Markdown, tables and math live in one box without edit/preview buttons or altering dollar prices", () => {
  const spy = vi.fn();
  const { container } = render(<Editor onChangeSpy={spy} />);
  expect(screen.queryByRole("tab", { name: "编辑" })).toBeNull();
  expect(screen.queryByRole("tab", { name: "预览" })).toBeNull();
  expect(screen.getByRole("heading", { name: "营养计划" })).toBeTruthy();
  expect(screen.getByRole("table")).toBeTruthy();
  expect(screen.getByText("鸡肉 $4")).toBeTruthy();
  expect(screen.getByText("大米 $8")).toBeTruthy();
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(2);
  expect(container.querySelector(".katex-error")).toBeNull();

  // Clicking a rendered block reveals only its Markdown source borderlessly while keeping other blocks rendered.
  fireEvent.mouseDown(screen.getByText("鸡肉 $4"));
  const input = screen.getByRole("textbox", { name: "问题描述" }) as HTMLTextAreaElement;
  expect(input.value).toBe("- 鸡肉 $4");
  expect(input.className).toContain("border-0");
  expect(input.className).toContain("bg-transparent");
  expect(screen.getByText("大米 $8")).toBeTruthy();

  fireEvent.mouseDown(screen.getByRole("heading", { name: "营养计划" }));
  expect(input.value).toBe("# 营养计划");
  expect(screen.queryByRole("heading", { name: "营养计划" })).toBeNull();
  expect(screen.getByRole("table")).toBeTruthy();
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(2);

  fireEvent.change(input, { target: { value: "# 更新后的计划", selectionStart: 8 } });
  expect(spy).toHaveBeenLastCalledWith(source.replace("营养计划", "更新后的计划"));

  // Moving focus out immediately renders the edited block and exposes the full lossless source on the textbox.
  fireEvent.blur(input);
  expect(screen.getByRole("heading", { name: "更新后的计划" })).toBeTruthy();
  expect(input.value).toBe(source.replace("营养计划", "更新后的计划"));
});

test("typing a heading and pressing Enter renders the completed block live above the cursor", () => {
  render(<Editor initial="" />);
  const input = screen.getByRole("textbox", { name: "问题描述" }) as HTMLTextAreaElement;
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: "# 生产计划\n", selectionStart: 7 } });
  expect(screen.getByRole("heading", { name: "生产计划" })).toBeTruthy();
  expect(input.value).toBe("");

  fireEvent.change(input, { target: { value: "第二段内容", selectionStart: 5 } });
  expect(screen.getByRole("heading", { name: "生产计划" })).toBeTruthy();
  expect(input.value).toBe("第二段内容");

  // Backspace at the start of the second block merges back with the heading seamlessly, and Ctrl+Z / Ctrl+Shift+Z undo/redo it.
  input.setSelectionRange(0, 0);
  fireEvent.keyDown(input, { key: "Backspace" });
  expect(input.value).toBe("# 生产计划第二段内容");

  fireEvent.keyDown(input, { key: "z", ctrlKey: true });
  expect(screen.getByRole("heading", { name: "生产计划" })).toBeTruthy();
  expect(input.value).toBe("第二段内容");

  fireEvent.keyDown(input, { key: "z", ctrlKey: true, shiftKey: true });
  expect(input.value).toBe("# 生产计划第二段内容");

  // Delete at the end of a block also records an undoable history step.
  fireEvent.keyDown(input, { key: "z", ctrlKey: true });
  fireEvent.mouseDown(screen.getByRole("heading", { name: "生产计划" }));
  input.setSelectionRange(input.value.length, input.value.length);
  fireEvent.keyDown(input, { key: "Delete" });
  expect(input.value).toBe("# 生产计划第二段内容");
  fireEvent.keyDown(input, { key: "z", ctrlKey: true });
  expect(input.value).toBe("# 生产计划");
});

test("arrow navigation and Ctrl+A work across blocks in the live editor", () => {
  render(<Editor initial={"# 标题\n\n正文内容"} />);
  fireEvent.mouseDown(screen.getByRole("heading", { name: "标题" }));
  const input = screen.getByRole("textbox", { name: "问题描述" }) as HTMLTextAreaElement;
  expect(input.value).toBe("# 标题");

  input.setSelectionRange(4, 4);
  fireEvent.keyDown(input, { key: "ArrowDown" });
  expect(screen.getByRole("heading", { name: "标题" })).toBeTruthy();
  expect(input.value).toBe("正文内容");

  fireEvent.keyDown(input, { key: "a", ctrlKey: true });
  expect(input.value).toBe("# 标题\n\n正文内容");
});

test("clearing rendered content returns to an empty editable problem", () => {
  render(<Editor />);
  expect(screen.getByRole("heading", { name: "营养计划" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "清空" }));
  expect(screen.queryByRole("heading", { name: "营养计划" })).toBeNull();
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

test("pressing Enter at the end of a non-final block opens a new line between blocks instead of concatenating", () => {
  const spy = vi.fn();
  render(<Editor initial={"# 标题\n\n正文内容"} onChangeSpy={spy} />);
  fireEvent.mouseDown(screen.getByRole("heading", { name: "标题" }));
  const input = screen.getByRole("textbox", { name: "问题描述" }) as HTMLTextAreaElement;
  expect(input.value).toBe("# 标题");
  fireEvent.change(input, { target: { value: "# 标题\n", selectionStart: 5 } });
  expect(input.value).toBe("");
  fireEvent.change(input, { target: { value: "新增段落", selectionStart: 4 } });
  expect(spy).toHaveBeenLastCalledWith("# 标题\n新增段落\n\n正文内容");
});

test("IME composition from an empty editor and clicking a link inside a rendered block behave cleanly", () => {
  const spy = vi.fn();
  render(<Editor initial="" onChangeSpy={spy} />);
  const input = screen.getByRole("textbox", { name: "问题描述" }) as HTMLTextAreaElement;
  fireEvent.focus(input);
  fireEvent.compositionStart(input);
  fireEvent.change(input, { target: { value: "sheng", selectionStart: 5 } });
  fireEvent.compositionEnd(input, { target: { value: "生产", selectionStart: 2 } });
  expect(spy).toHaveBeenLastCalledWith("生产");
  fireEvent.keyDown(input, { key: "z", ctrlKey: true });
  expect(spy).toHaveBeenLastCalledWith("");

  cleanup();
  render(<Editor initial={"# 标题\n\n查看 [说明](https://example.org)"} />);
  const link = screen.getByRole("link", { name: "说明" });
  const down = createEvent.mouseDown(link, { button: 0 });
  fireEvent(link, down);
  expect(down.defaultPrevented).toBe(false);
});
