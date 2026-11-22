import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { Markdown } from "./Content";

const language = vi.hoisted(() => ({ value: "zh" }));
vi.mock("@/i18n", () => ({ get locale() { return language.value; }, t: (text: string) => text }));
afterEach(cleanup);

const types = ["binary", "integer", "continuous", "permutation", "assignment"];
const forms = ["linear", "quadratic", "nonlinear", "minmax"];
const categories = ["bound", "capacity", "precedence", "conflict", "equality", "nonlinear"];
const source = "## Parameters (scale: small)\n- `min` = 3: capacity\n\n## Variables\n"
  + types.map(type => `- \`min\` (${type}, domain \`{0,1}\`, shape \`[i,j]\`): decision $x_i$`).join("\n")
  + "\n\n## Objectives\n" + forms.map(form => `- **max** \`min\` (${form}): \`max(x)\` — profit`).join("\n")
  + "\n\n## Constraints\n" + categories.map(category => `- \`min\` (${category}): \`x <= 3\` — limit`).join("\n")
  + '\n\n```json\n{"var_type":"integer","sense":"max","form":"linear"}\n```';

test.each(["zh", "en"])("AutoCO fixed reading labels follow %s while source values, code and formulas stay intact", locale => {
  language.value = locale;
  const { container } = render(<Markdown text={source} modelSections />);
  const text = container.textContent ?? "";
  if (locale === "zh") {
    expect(container.querySelector("h2")?.textContent).toBe("参数（规模：小型）");
    for (const label of ["二元", "整数", "连续", "排列", "指派", "取值域", "形状", "最大化", "线性", "二次", "非线性", "极小极大", "边界", "容量", "先后关系", "互斥", "等式"])
      expect(text).toContain(label);
    expect(text).not.toMatch(/\((binary|integer|continuous|permutation|assignment), domain/);
  } else {
    expect(container.querySelector("h2")?.textContent).toBe("Parameters (scale: small)");
    expect(text).toContain("(integer, domain");
    expect(container.querySelector("strong")?.textContent).toBe("max");
  }
  const code = [...container.querySelectorAll("code")].map(node => node.textContent);
  for (const raw of ["min", "{0,1}", "[i,j]", "max(x)", "x <= 3", '{"var_type":"integer","sense":"max","form":"linear"}'])
    expect(code).toContain(raw);
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(5);
});

test("AutoCO mapping requires the fixed scale header and complete known field shapes", () => {
  language.value = "zh";
  const lookalike = "## Variables\n- `x` (integer, domain `{0,1}`, shape `[i]`): prose\n\n**max** `profit` (linear): `max(x)`";
  const { container } = render(<Markdown text={lookalike} modelSections />);
  expect(container.textContent).toContain("(integer, domain");
  expect(container.querySelector("strong")?.textContent).toBe("max");
  const other = render(<Markdown text={"## Parameters (scale: small)\n\n## Variables\n- `x` (plugin_type, domain `all`, shape `scalar`): unknown"} modelSections />);
  expect(other.container.textContent).toContain("(plugin_type, domain all, shape scalar): unknown");
});

test("ordinary source Markdown keeps the AutoCO protocol labels verbatim", () => {
  language.value = "zh";
  const { container } = render(<Markdown text={source} />);
  expect(container.querySelector("h2")?.textContent).toBe("Parameters (scale: small)");
  expect(container.textContent).toContain("(integer, domain");
  expect(container.querySelector("strong")?.textContent).toBe("max");
});
