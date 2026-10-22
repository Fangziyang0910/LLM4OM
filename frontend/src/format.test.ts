import { expect, test } from "vitest";
import { duration } from "./format";

test("rounded seconds carry over into minutes", () => {
  expect(duration(0.15)).toBe("0.1 秒");
  expect(duration(59.9)).toBe("1 分 0 秒");
  expect(duration(119.9)).toBe("2 分 0 秒");
});
