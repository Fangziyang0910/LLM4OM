import { cleanup, fireEvent, render, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { Diff, Markdown } from "./Content";

const language = vi.hoisted(() => ({ value: "zh" }));
vi.mock("@/i18n", async () => {
  const { en } = await import("@/locales/en");
  return {
    get locale() { return language.value; },
    t: (text: string) => language.value === "zh" ? text : en[text] ?? text,
  };
});
afterEach(cleanup);

const model = "## Sets:\n$P=\\{A,B\\}$\n\n## Parameters:\n$p=3$\n\n## Variables:\n$x\\in\\mathbb{Z}_{\\ge0}$\n\n"
  + "## Objective:\n$$\\max 3x$$\n\n## Constraints:\n$x\\le8$\n\n## Custom heading\nKeep this prose.\n\n"
  + "```text\n## Sets:\n```";

test.each([
  ["zh", ["集合", "参数", "变量", "目标函数", "约束", "Custom heading"]],
  ["en", ["Sets", "Parameters", "Variables", "Objective", "Constraints", "Custom heading"]],
] as const)("model headings follow %s while formulas, code and prose retain their content", (locale, headings) => {
  language.value = locale;
  const { container } = render(<Markdown text={model} modelSections />);

  expect([...container.querySelectorAll("h2")].map(node => node.textContent)).toEqual(headings);
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(5);
  expect(container.querySelector("code, pre")?.textContent).toBe("## Sets:");
  expect(container.textContent).toContain("Keep this prose.");
  expect(container.querySelector(".katex-error")).toBeNull();
});

test("ordinary Markdown headings are unchanged without the model option", () => {
  language.value = "zh";
  const { container } = render(<Markdown text={"## Sets:\n\nA source heading."} />);
  expect(container.querySelector("h2")?.textContent).toBe("Sets:");
});

test("unknown artifact labels cannot resolve inherited dictionary properties", () => {
  language.value = "zh";
  const { container } = render(<Markdown text={"## constructor\n\n**toString**\n\nconstructor"} modelSections />);
  expect(container.querySelector("h2")?.textContent).toBe("constructor");
  expect(container.querySelector("strong")?.textContent).toBe("toString");
  expect(container.querySelectorAll("p")[1]?.textContent).toBe("constructor");
});

test("component headings accept the methods' lowercase and underscore protocol names", () => {
  language.value = "zh";
  const { container } = render(<Markdown text={"### parameters\n\n### decision_variables\n\n### equality_constraints\n\n### inequality_constraints"} modelSections />);
  expect([...container.querySelectorAll("h3")].map(node => node.textContent)).toEqual(["参数", "决策变量", "等式约束", "不等式约束"]);
});

test("model comparison localizes reading headings and retains literal source changes", () => {
  language.value = "zh";
  const { container } = render(<Diff before={model} after={model.replace("x\\le8", "x\\le10")}
    format="markdown" modelSections />);
  expect(within(container).getAllByRole("heading", { name: "集合" })).toHaveLength(2);
  fireEvent.click(within(container).getByRole("button", { name: "文本差异" }));
  expect(container.querySelector("pre")?.textContent).toContain("## Sets:");
  expect(container.querySelector("pre")?.textContent).toContain("x\\le8");
  expect(container.querySelector("pre")?.textContent).toContain("x\\le10");
});

test.each([
  ["zh", ["数学模型", "参数", "数据结构", "专家", "Unknown field"], "代码检查通过", "建模专家"],
  ["en", ["Formulation", "Parameters", "Data schema", "Expert", "Unknown field"], "Code validation passed", "Modeling Expert"],
] as const)("generated artifact labels follow %s without rewriting payloads", (locale, headings, flag, expert) => {
  language.value = locale;
  const source = '#### Formulation\n\n## Parameters:\n\n$p=3$\n\n✅ **Code validation passed**\n\n'
    + '#### Data schema\n\n```json\n{"parameters": [3, 2]}\n```\n\n#### Expert\n\nModeling Expert\n\n'
    + '## Unknown field\n\nKeep this prose.';
  const { container } = render(<Markdown text={source} modelSections />);

  expect([...container.querySelectorAll("h2,h4")].map(node => node.textContent)).toEqual(headings);
  expect(container.querySelector("strong")?.textContent).toBe(flag);
  expect(within(container).getByText(expert)).toBeTruthy();
  expect(container.querySelector("code,pre")?.textContent).toBe('{"parameters": [3, 2]}');
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(1);
});

test.each(["zh", "en"])("TriVAL inline model fields follow %s while math and code stay intact", locale => {
  language.value = locale;
  const source = "## variables\n- $y_{ij}$：是否选择路段；var_type：bool；domain：$\\{0,1\\}$；shape：[i,j]；unit：无。\n\n"
    + "- $z$; var_type: int; domain: $z \\ge 0$; shape: scalar.\n\n"
    + "## constraints\n- 条件：expr：$x+y=2$。\n\n## objectives\n- 旅行成本：type：min；expr：$x+y$。\n\n"
    + "- var_type: real; type: max.\n\n- type: satisfy.\n\n- parameter $p$; type: int; value: 3.\n\n"
    + "`var_type: bool`\n\n```json\n{\"var_type\": \"bool\", \"type\": \"min\"}\n```\n\n"
    + "- custom_type: bool; my_domain: 3; unknown identifier domain_x.\n\n$\\text{domain: bool}$";
  const { container } = render(<Markdown text={source} modelSections />);
  const prose = [...container.querySelectorAll("li")].map(node => node.textContent).join("\n");
  if (locale === "zh") {
    for (const label of ["变量类型：二元", "取值域：", "形状：", "单位：", "表达式：", "类型：最小化", "变量类型: 整数", "形状: 标量", "变量类型: 实数", "类型: 最大化", "类型: 满足约束", "类型: 整数"])
      expect(prose).toContain(label);
    expect(prose).not.toMatch(/\b(var_type|domain|shape|unit|expr|type)[：:]/);
  } else {
    expect(prose).toContain("var_type：bool");
    expect(prose).toContain("type：min");
    expect(prose).toContain("shape: scalar");
  }
  expect(prose).toContain("custom_type: bool; my_domain: 3; unknown identifier domain_x.");
  expect([...container.querySelectorAll("code")].map(node => node.textContent)).toContain("var_type: bool");
  expect(container.querySelector(".hljs")?.textContent).toBe('{"var_type": "bool", "type": "min"}');
  expect([...container.querySelectorAll("annotation")].map(node => node.textContent)).toContain("\\text{domain: bool}");
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(8);
});

test("ordinary Markdown prose keeps protocol-looking fields unchanged", () => {
  language.value = "zh";
  const { container } = render(<Markdown text="var_type: bool; domain: all; type: min" />);
  expect(container.textContent).toBe("var_type: bool; domain: all; type: min");
});
