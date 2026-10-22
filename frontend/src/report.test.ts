import { describe, expect, it } from "vitest";
import { report } from "./report";
import type { Options } from "./types";

const options = { methods: [{ id: "direct", name: "Direct", description: "", source: null, languages: null }],
  languages: [{ id: "pyomo", name: "Pyomo", solver: "HiGHS" }], providers: [], datasets: [] } as Options;

describe("run report", () => {
  it("holds the settings, problem, formulation, code and nonzero variables of a run", () => {
    const text = report({ title: "生产计划", method: "direct", language: "pyomo", provider: null, model: "m1", note: "核对过", tags: ["整数"] },
      { description: "最大化利润", data: { "a.csv": "x,1\n" }, formulation: "$$\\max 3x$$", code: "print('```')\n",
        solve: { status: "optimal", objective: 13, variables: { "x[A]": 3, "x[B]": 0 }, output: "", error: null },
        usage: { llm_calls: 1, solves: 1, input_tokens: 10, output_tokens: 5 } }, options);
    expect(text).toContain("- 建模方法：Direct\n- 代码写法：Pyomo (HiGHS)\n- 预设模型：m1");
    expect(text).toContain("## 备注\n\n核对过");
    expect(text).toContain("````python\nprint('```')\n````");  // a longer fence keeps code with ``` intact
    expect(text).toContain("| `x[A]` | 3 |");
    expect(text).not.toContain("x[B]");
  });
});
