import { render } from "@testing-library/react";
import { expect, test } from "vitest";
import { Markdown } from "./Content";

test("Markdown renders LaTeX in both delimiter styles", () => {
  const { container } = render(<Markdown text={"$x_i + \\frac{1}{2}$ and \\(y \\le 3\\)"} />);
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(2);
  expect(container.querySelector(".katex-error")).toBeNull();
});
