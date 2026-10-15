"use strict";
// 数学排版验收:方法保存的表达式(无结构化 IR 项)经 window.UI 门面渲染为
// KaTeX 排版,覆盖 ASCII 线性语法、$定界 LaTeX、混合记号与裸公式 description;
// 结构化 IR 路径的交互表达式不受影响。
const assert = require("node:assert/strict");
const { completedRun } = require("./helpers/browser_fixture.cjs");
const { chromium } = require(process.env.LLM4OM_BROWSER_MODULE || "playwright");
const url = process.env.LLM4OM_WEB_TEST_URL;
assert.ok(url && ["127.0.0.1", "localhost"].includes(new URL(url).hostname));
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.LLM4OM_BROWSER_EXECUTABLE,
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await completedRun(page);
    const rendered = await page.evaluate(() => {
      const contents = { ...window.snapshot.contents };
      const formulation = contents["checks/001/formulation.json"];
      if (!formulation?.representation?.objective?.expression_text) return null;
      for (const name of Object.keys(contents))
        if (/structured-ir|model-ir|supplied-ir/.test(name)) delete contents[name];
      // 真实运行里模型常保存 $…$ 定界的 LaTeX、混合记号,以及把 ASCII 公式写进 description。
      const state = formulation.representation.state || formulation.representation;
      state.objective.expression_text = "$\\min 2x_A + 3x_B$";
      state.objective.description = "The goal is to minimize the total cost";
      state.constraints = [
        { id: "C1", description: "2 * x_A + 1 * x_B >= 8", expression_text: "$2 xA + xB \\geq 8$" },
        { id: "C2", description: "resource limit", expression_text: "$2x_A + x_B <= 8$" },
        { id: "C3", description: "nonnegative", expression_text: "$x_A \\geq 0$" },
        // LLM 常按 JSON 习惯写双反斜杠,并把变量并写为 xA:
        // KaTeX 会把 \\ 当换行、geq 当变量渲染,必须先归一。
        { id: "C4", description: "escaped form", expression_text: "$2 x_A + x_B \\\\geq 8$" },
        { id: "C5", description: "juxtaposed", expression_text: "$xA \\\\geq 0$" },
        // 长公式必须在容器内换行,而不是横向滚动条裁切。
        {
          id: "C6",
          description: "long",
          expression_text:
            "$x_A + x_B + x_A + x_B + x_A + x_B + x_A + x_B + x_A + x_B \\\\geq 100$",
        },
      ];
      const host = document.createElement("div");
      host.id = "math-host-1";
      document.body.appendChild(host);
      UI.records(host, formulation, "formulation", contents);
      const textPath = {
        katex: host.querySelectorAll(".katex").length,
        fallback: host.querySelectorAll(".math-fallback").length,
        // 只取可见渲染文本;KaTeX 的 MathML 注记含原始源码,不能作为断言对象。
        text: [...host.querySelectorAll(".katex-html")].map((el) => el.textContent).join(" "),
        all: host.textContent,
      };
      // 结构化路径:方法也会把约束存为 terms+sense+rhs,sense 用 \geq 这类 LaTeX 写法,
      // 变量名是 xA/xB(无下划线)。
      state.constraints = [
        {
          id: "C1",
          description: "resource limit",
          expression: {
            terms: [
              { variable_id: "xA", coefficient: 2 },
              { variable_id: "xB", coefficient: 1 },
            ],
            constant: 0,
          },
          sense: "\\geq",
          rhs: 8,
        },
      ];
      const irHost = document.createElement("div");
      irHost.id = "math-host-2";
      document.body.appendChild(irHost);
      UI.records(irHost, formulation, "formulation", contents);
      return {
        ...textPath,
        subscripts: irHost.querySelectorAll(".math-variable sub").length,
        bound: [...irHost.querySelectorAll(".math-bound")].map((el) => el.textContent).join(" "),
        raw: irHost.textContent,
      };
    });
    assert.ok(rendered, "fixture 应包含 expression_text 表述");
    assert.ok(rendered.katex >= 5, "目标与约束应渲染 KaTeX");
    assert.equal(rendered.fallback, 0);
    assert.match(rendered.text, /min/);
    assert.match(rendered.text, /≥/);
    assert.match(rendered.text, /≤/);
    // 双反斜杠归一后不得再出现 geq/leq 字样
    assert.doesNotMatch(rendered.text, /geq|leq/, "LaTeX 命令不应作为变量渲染");
    // 裸公式 description 不再原样重复显示为文本
    assert.doesNotMatch(rendered.all, /2 \* x_A/);
    // 结构化路径:变量名 xA 排版为下标,LaTeX 写法的 sense(\geq)映射为 ≥,不再原样显示
    assert.ok(rendered.subscripts >= 2, "xA/xB 变量名应排版下标");
    assert.match(rendered.bound, /≥/);
    assert.doesNotMatch(rendered.raw, /geq/, "LaTeX sense 不应原样显示");
    // 窄屏下长公式应换行,不产生横向溢出(允许 2px:KaTeX 下标 vlist
    // 自带 -2px 负边距,scrollWidth 会报告该测量伪影,不可见)
    await page.setViewportSize({ width: 390, height: 844 });
    const overflowing = await page.evaluate(() =>
      [...document.querySelectorAll("#math-host-1 .math-expression")].filter(
        (el) => el.scrollWidth > el.clientWidth + 2,
      ).length,
    );
    assert.equal(overflowing, 0, "长公式应在容器内换行,不得横向裁切");
    await page.evaluate(() => document.querySelectorAll('[id^="math-host-"]').forEach(host => host.remove()));
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.click('[data-tab="formulation"]');
    assert.ok(
      (await page.locator(".math-variable").count()) > 0,
      "结构化 IR 路径的交互式变量表达式应保持",
    );
    assert.deepEqual(errors, []);
    console.log(
      "Math rendering: ASCII + $-delimited LaTeX + mixed notation → KaTeX (min/≥/≤), bare-formula description deduped, structured-IR interactive path preserved.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
