import { expect, test } from "vitest";
import { STATUS, duration, formatTokens, shortTitle, tone } from "./format";

test("rounded seconds carry over into minutes", () => {
  expect(duration(0.15)).toBe("0.1 秒");
  expect(duration(59.9)).toBe("1 分 0 秒");
  expect(duration(119.9)).toBe("2 分 0 秒");
});

test("local NLP statuses are distinct from global solver conclusions", () => {
  expect(STATUS.locally_optimal).toBe("局部最优");
  expect(STATUS.locally_infeasible).toBe("局部不可行");
  expect(tone("locally_infeasible")).toBe("warn");
  expect(tone("iteration_limit")).toBe("warn");
});

test("token counts use k, M and B", () => {
  expect([999, 1000, 1234, 12_345, 1_234_567, 1_000_000_000].map(formatTokens)).toEqual(["999", "1k", "1.2k", "12k", "1.2M", "1B"]);
});

test("long titles keep their first clause without bracketed details, and a scenario suffix stays", () => {
  expect(shortTitle("工厂生产 A、B 两种产品，数量必须是非负整数。每件 A 利润为 3")).toBe("工厂生产 A、B 两种产品");
  expect(shortTitle("请帮我把 12 个 AI 计算任务（算力需求 [18, 25, 14]）分配到 4 个 GPU 集群（上限 [80, 90]，系数 [1.0]）。")).toBe("请帮我把 12 个 AI 计算任务分配到 4 个 GPU 集群");
  expect(shortTitle("An office supply company makes two types of printers: color printers and black and white printers.")).toBe("An office supply company makes two types of printers");
  expect(shortTitle("生产计划 · B 至少 3 件")).toBe("生产计划 · B 至少 3 件");
  expect(shortTitle("单价 3.5 元的产品")).toBe("单价 3.5 元的产品");
  expect(shortTitle("x".repeat(80))).toBe("x".repeat(72) + "…");
  expect(shortTitle("长".repeat(40))).toBe("长".repeat(36) + "…");
});
