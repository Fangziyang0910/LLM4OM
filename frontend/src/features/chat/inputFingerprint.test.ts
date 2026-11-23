import { expect, test } from "vitest";
import { inputFingerprint } from "./inputFingerprint";

test("checkpoint inputs match UTF-8 SHA-256 in either attachment order", () => {
  const data = { "成本.csv": "容量\n10\n", "🧮.txt": "A😀" };
  const expected = "e5e615a058085ca721d574a574f1a16172dfe3915304a392ff938a541bfcbdbe";
  expect(inputFingerprint(data, "生产计划")).toBe(expected);
  expect(inputFingerprint(Object.fromEntries(Object.entries(data).reverse()), "生产计划")).toBe(expected);
});
