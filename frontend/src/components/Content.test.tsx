import { fireEvent, render, within } from "@testing-library/react";
import katex from "katex";
import { expect, test, vi } from "vitest";
import { t } from "@/i18n";
import { Diff, Markdown } from "./Content";

test("price protection also applies when a price sentence contains a LaTeX text command", () => {
  const source = String.raw`Cost is $4 per \text{item} and $8 per box.`;
  const { container } = render(<Markdown text={source} singleDollarMath={false} />);
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(0);
  expect(container.textContent).toBe(source);
});

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

test("prices adjacent to Chinese text and math, escaped dollars in math, and inline table math all render cleanly", () => {
  const { container } = render(<Markdown text={String.raw`单价$4，变量$x_A$，折扣为$\$10 + x$。

| 项 | 公式 |
| --- | --- |
| 目标 | $$3x_A + 2x_B$$ |`} />);
  expect(container.textContent).toContain("单价$4，变量");
  expect(container.querySelector("table")).toBeTruthy();
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(3);
  expect(container.querySelector(".katex-error")).toBeNull();
});

test("Markdown comparison renders complete multiline formulas and can reveal the source changes", () => {
  const before = String.raw`## Objective
\[
\begin{aligned}
\max\quad & 3x + 2y \\
\text{s.t.}\quad & 2x + y \le 8
\end{aligned}
\]
The quantities are integers.`;
  const after = before.replace("\\le 8", "\\le 10");
  const view = render(<Diff before={before} after={after} format="markdown" />);
  const content = within(view.container);

  expect(view.container.querySelectorAll(".katex-display")).toHaveLength(2);
  expect(view.container.querySelectorAll("h2")).toHaveLength(2);
  expect(content.getAllByText("The quantities are integers.")).toHaveLength(2);
  expect(view.container.querySelector(".katex-error")).toBeNull();

  fireEvent.click(content.getByRole("button", { name: t("文本差异") }));
  expect(view.container.querySelector(".katex")).toBeNull();
  expect(view.container.querySelector("pre")?.textContent).toContain("\\le 8");
  expect(view.container.querySelector("pre")?.textContent).toContain("\\le 10");

  fireEvent.click(content.getByRole("button", { name: t("阅读对照") }));
  expect(view.container.querySelectorAll(".katex-display")).toHaveLength(2);
});

test("problem comparison preserves prices and code while rendering explicit integer-domain math", () => {
  const source = String.raw`A costs $4 and B costs $8.

\[
x,y \in \mathbb{Z}_{\ge 0}
\]

` + "```python\n" + String.raw`pattern = r"\[x\]"` + "\n```";
  const { container } = render(<Diff before={source} after={source.replace("$4", "$5")}
    format="markdown" singleDollarMath={false} />);

  expect(container.textContent).toContain("A costs $4 and B costs $8.");
  expect(container.textContent).toContain("A costs $5 and B costs $8.");
  expect(container.querySelectorAll(".katex-display")).toHaveLength(2);
  expect(container.querySelector(".katex-error")).toBeNull();
  expect(within(container).getAllByText((_, element) => element?.tagName === "CODE" && element.textContent === String.raw`pattern = r"\[x\]"`)).toHaveLength(2);
});

test("code comparison defaults to literal line changes without mathematical rendering", () => {
  const before = String.raw`pattern = r"\[x\]"`;
  const after = String.raw`pattern = r"\[y\]"`;
  const view = render(<Diff before={before} after={after} />);

  expect(view.container.querySelector("pre")?.textContent).toContain(before);
  expect(view.container.querySelector("pre")?.textContent).toContain(after);
  expect(view.container.querySelector(".katex")).toBeNull();
  expect(within(view.container).queryByRole("button", { name: t("阅读对照") })).toBeNull();
});

test.each(["align", "align*", "equation", "equation*"])("LaTeX environment %s renders without outer math delimiters", environment => {
  const equation = environment.startsWith("align") ? String.raw`x &= 1 \\ y &= 2` : "x = 1";
  const text = `Before.\n\n\\begin{${environment}}\n${equation}\n\\end{${environment}}\n\nAfter.`;
  const { container } = render(<Markdown text={text} />);

  expect(container.querySelectorAll(".katex-display")).toHaveLength(1);
  expect(container.querySelector(".katex-error")).toBeNull();
  expect(container.textContent).toContain("Before.");
  expect(container.textContent).toContain("After.");
});

test("five-element LaTeX lists and standalone constraints remain readable together", () => {
  const { container } = render(<Markdown text={String.raw`## Sets:
\begin{itemize}
    \item $Cities=\{A,B\}$: cities.
\end{itemize}

## Parameters:
\begin{itemize}
    \item $c$: cost per package.
    \[
    c=1
    \]
\end{itemize}

## Constraints:
\begin{align}
x &\le 10 \\
x &\ge 0
\end{align}`} />);

  expect(container.querySelectorAll("li")).toHaveLength(2);
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(4);
  expect(container.querySelectorAll(".katex-display")).toHaveLength(2);
  expect(container.querySelector(".katex-error")).toBeNull();
  expect(container.textContent).not.toContain("\\begin{itemize}");
  expect(container.textContent).not.toContain("\\item");
});

test.each(["```text\n%s\n```", "~~~~\n%s\n~~~~~", "    %s", "``%s``"])(
  "LaTeX environment recognition preserves code in %s", fence => {
    const source = String.raw`pattern = r"\begin{align} \item x \end{align}"`;
    const { container } = render(<Markdown text={fence.replace("%s", source) + String.raw`

\begin{equation}
z=3
\end{equation}`} />);

    expect(container.querySelector("code, pre")?.textContent).toBe(source);
    expect(container.querySelectorAll(".katex-display")).toHaveLength(1);
  },
);
