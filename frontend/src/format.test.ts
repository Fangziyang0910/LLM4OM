import { expect, test } from "vitest";
import { STATUS, duration, tone } from "./format";

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
