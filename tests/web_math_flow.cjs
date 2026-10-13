"use strict";
// 数学排版验收:方法保存的 expression_text(无结构化 IR 项)经
// window.UI 门面渲染为 KaTeX 排版;结构化 IR 路径的交互表达式不受影响。
const assert = require("node:assert/strict");
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
    await page.goto(url);
    await page.waitForSelector(".job");
    await page.locator(".job").first().click();
    await page.waitForSelector(".objective-result strong");
    const rendered = await page.evaluate(() => {
      const contents = { ...window.snapshot.contents };
      const formulation = contents["candidates/001/formulation.json"];
      if (!formulation?.representation?.objective?.expression_text) return null;
      for (const name of Object.keys(contents))
        if (/structured-ir|model-ir|supplied-ir/.test(name)) delete contents[name];
      const host = document.createElement("div");
      document.querySelector("main").appendChild(host);
      UI.records(host, formulation, "formulation", contents);
      return {
        katex: host.querySelectorAll(".katex").length,
        fallback: host.querySelectorAll(".math-fallback").length,
        text: [...host.querySelectorAll(".math-tex")].map((el) => el.textContent).join(" "),
      };
    });
    assert.ok(rendered, "fixture 应包含 expression_text 表述");
    assert.ok(rendered.katex >= 2, "目标与约束应渲染 KaTeX");
    assert.equal(rendered.fallback, 0);
    assert.match(rendered.text, /∑/);
    assert.match(rendered.text, /≤/);
    await page.click('[data-tab="formulation"]');
    assert.ok(
      (await page.locator(".math-variable").count()) > 0,
      "结构化 IR 路径的交互式变量表达式应保持",
    );
    assert.deepEqual(errors, []);
    console.log(
      "Math rendering: expression_text → KaTeX (∑/≤/下标), structured-IR interactive path preserved.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
