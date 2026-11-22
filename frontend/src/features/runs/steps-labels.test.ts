import { expect, test, vi } from "vitest";
import { preview, roleLabel, roleName } from "./steps";

const language = vi.hoisted(() => ({ value: "zh" }));
vi.mock("@/i18n", async () => {
  const { en } = await import("@/locales/en");
  return {
    get locale() { return language.value; },
    t: (text: string) => language.value === "zh" ? text : en[text] ?? text,
  };
});

test.each([
  ["zh", ["语义事实提取", "检查约束语义", "建模专家", "反向反思：编程专家", "生成参数", "排序不等式约束", "BIND 建模", "OptiMind 建模与反思"]],
  ["en", ["Extract semantic facts", "Check constraint semantics", "Modeling Expert", "Programming Expert (backward)", "Generate parameters", "Rank inequality constraints", "BIND modeling", "OptiMind modeling and reflection"]],
] as const)("known roles have %s display labels without changing their identifiers", (locale, expected) => {
  language.value = locale;
  const roles = ["trival.semantic_fact_extractor", "sac_compare", "Modeling Expert", "Programming Expert (backward)",
    "generate.parameters", "rank.inequality_constraints", "bind_generate", "optimind_generate"];

  expect(roles.map(roleLabel)).toEqual(expected);
  expect(roleName("trival.semantic_fact_extractor")).toBe("semantic fact extractor");
  expect(roleLabel("plugin.custom_validator")).toBe("custom validator");
  expect(roleLabel("plugin.constructor")).toBe("constructor");
  expect(roleLabel("plugin.toString")).toBe("toString");
});

test("generated artifact previews localize labels and ordinary source previews stay unchanged", () => {
  language.value = "zh";
  const source = "#### Formulation\n\n## Parameters\n\n✅ **Code validation passed**";
  expect(preview(source, 160, true)).toBe("数学模型 · 参数 · ✅ 代码检查通过");
  expect(preview(source)).toBe("Formulation · Parameters · ✅ Code validation passed");
  expect(preview("**Attempts**: 2\n\n## Objective and constraints", 160, true)).toBe("尝试次数: 2 · 目标函数与约束");
});

test.each([["zh", "解读求解结果"], ["en", "Explain the result"]])("result explanation role follows %s", (locale, expected) => {
  language.value = locale;
  expect(roleLabel("explain_result")).toBe(expected);
  expect(roleName("explain_result")).toBe("explain result");
});

test.each([
  ["zh", ["梳理问题语义", "建立数学模型", "检查数学模型", "生成问题代码", "选择优化算法"]],
  ["en", ["Ground problem semantics", "Formulate the model", "Review the formulation", "Generate problem code", "Select an optimization algorithm"]],
] as const)("AutoCO call roles follow %s without changing protocol names", (locale, expected) => {
  language.value = locale;
  const roles = ["semantic_grounding", "formulate", "review_formulation", "instantiate", "kg_agent"];
  expect(roles.map(roleLabel)).toEqual(expected);
  expect(roles.map(roleName)).toEqual(["semantic grounding", "formulate", "review formulation", "instantiate", "kg agent"]);
});
