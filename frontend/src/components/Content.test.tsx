import { render } from "@testing-library/react";
import { expect, test } from "vitest";
import { Markdown } from "./Content";

test("Markdown renders LaTeX in both delimiter styles", () => {
  const { container } = render(<Markdown text={"$x_i + \\frac{1}{2}$ and \\(y \\le 3\\)"} />);
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(2);
  expect(container.querySelector(".katex-error")).toBeNull();
});

test.each(["```python\n%s\n```", "~~~~\n%s\n~~~~~", "    %s", "``%s``"])(
  "math conversion preserves code in %s", fence => {
    const source = String.raw`pattern = r"\[x\] \(y\)"`;
    const { container } = render(<Markdown text={fence.replace("%s", source) + "\n\n\\(z\\)"} />);
    expect(container.querySelector("code, pre")?.textContent).toBe(source);
    expect(container.querySelectorAll(".katex-mathml")).toHaveLength(1);
  },
);
