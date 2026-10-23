import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ProblemEditor } from "./ProblemEditor";

afterEach(cleanup);

const source = "# 营养计划\n\n- 鸡肉 $4\n- 大米 $8\n\n| 食物 | 蛋白质 |\n| --- | --- |\n| 鸡肉 | 18 |\n\n约束：\\(x \\le 8\\)。\n\n$$x \\ge 0$$";

function Editor() {
  const [value, setValue] = useState(source);
  return <ProblemEditor value={value} data={{}} onChange={setValue} onFiles={vi.fn()} onRemove={vi.fn()}
    onClear={() => setValue("")} onExamples={vi.fn()} />;
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
