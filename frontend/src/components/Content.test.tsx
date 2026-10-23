import { render } from "@testing-library/react";
import katex from "katex";
import { expect, test, vi } from "vitest";
import { Markdown } from "./Content";

test("Markdown renders LaTeX in both delimiter styles", () => {
  const { container } = render(<Markdown text={"$x_i + \\frac{1}{2}$ and \\(y \\le 3\\)"} />);
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(2);
  expect(container.querySelector(".katex-error")).toBeNull();
});

test("multiline display math supports aligned equations and does not swallow surrounding text", () => {
  const { container } = render(<Markdown text={String.raw`目标函数：
\[
\begin{aligned}
\max\quad & 3x_A + 2x_B \\
\text{s.t.}\quad & 2x_A + x_B \le 8
\end{aligned}
\]
其中数量为非负整数。`} />);
  expect(container.querySelectorAll(".katex-display")).toHaveLength(1);
  expect(container.querySelector(".katex-error")).toBeNull();
  expect(container.textContent).toContain("其中数量为非负整数。");
});

test("prices, inline formulas, display formulas and reference links coexist", () => {
  const { container } = render(<Markdown text={String.raw`A costs $4 and B costs $8. Let $x_A$ be its quantity.

目标为 \[\max\ 3x_A + 2x_B\]。参见[说明][guide]。

[guide]: https://example.org/guide`} />);
  expect(container.textContent).toContain("A costs $4 and B costs $8.");
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(2);
  expect(container.querySelectorAll(".katex-display")).toHaveLength(1);
  expect(container.querySelector("a")?.getAttribute("href")).toBe("https://example.org/guide");
});

test("unfinished streamed math stays readable and becomes valid without an error flash", () => {
  const { container, rerender } = render(<Markdown text={"$$\n\\frac{1}{"} />);
  expect(container.textContent).toContain("\\frac{1}{");
  expect(container.querySelector(".katex-error")).toBeNull();
  rerender(<Markdown text={"$$\n\\frac{1}{2}\n$$"} />);
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(1);
  expect(container.querySelector(".katex-error")).toBeNull();
});

test("appending text does not retypeset an existing formula", () => {
  const typeset = vi.spyOn(katex, "renderToString");
  try {
    const { rerender } = render(<Markdown text={"$x_A$ 是生产数量。"} />);
    rerender(<Markdown text={"$x_A$ 是生产数量。请继续核对资源。"} />);
    expect(typeset).toHaveBeenCalledTimes(1);
  } finally { typeset.mockRestore(); }
});

test.each(["```python\n%s\n```", "~~~~\n%s\n~~~~~", "    %s", "``%s``"])(
  "math conversion preserves code in %s", fence => {
    const source = String.raw`pattern = r"\[x\] \(y\)"`;
    const { container } = render(<Markdown text={fence.replace("%s", source) + "\n\n\\(z\\)"} />);
    expect(container.querySelector("code, pre")?.textContent).toBe(source);
    expect(container.querySelectorAll(".katex-mathml")).toHaveLength(1);
  },
);
