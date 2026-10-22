import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { en, patterns } from "./locales/en";

const files = (directory: string): string[] => readdirSync(directory).flatMap(name => {
  const path = join(directory, name);
  return statSync(path).isDirectory() ? files(path) : /\.tsx?$/.test(name) && !name.includes(".test.") ? [path] : [];
});

describe("English text", () => {
  it("covers every Chinese text the page passes to t()", () => {
    const keys = files("src").flatMap(path => [...readFileSync(path, "utf8").matchAll(/\bt\("((?:[^"\\]|\\.)*)"/g)].map(match => match[1]))
      .filter(key => /[㐀-鿿]/.test(key));
    expect(keys.length).toBeGreaterThan(200);
    expect(keys.filter(key => !(key in en))).toEqual([]);
  });

  it("keeps every placeholder of the Chinese text", () => {
    const names = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map(match => match[1]).sort();
    expect(Object.entries(en).filter(([zh, english]) => names(zh).join() !== names(english).join())).toEqual([]);
  });

  it("translates numbered step titles", () => {
    const [match, replacement] = patterns[0];
    expect("执行代码（第 2 次）".replace(match, replacement)).toBe("Run code (attempt 2)");
  });
});
