const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium, expect } = require("../frontend/node_modules/@playwright/test");

const base = (process.argv[2] || "http://127.0.0.1:8831/").replace(/\/?$/, "/");
const output = path.resolve(__dirname, "../artifacts/website/docs");

(async () => {
  const { production, projection, descent, nonconvex } = await import("./public/docs/learning-models.mjs");
  for (const [options, expected] of [[{}, 13], [{ cutting: 10 }, 16], [{ minimumB: 3 }, 12], [{ minimumB: 4 }, 8], [{ minimumB: 5 }, null], [{ integer: false }, 40 / 3]]) {
    const result = production(options);
    assert.equal(result.objective === null, expected === null);
    if (expected !== null) assert.ok(Math.abs(result.objective - expected) < 1e-9);
  }
  for (const cutting of [6, 8, 10, 12]) for (const minimumB of [0, 3, 4, 5]) {
    const integer = production({ cutting, minimumB }), continuous = production({ cutting, minimumB, integer: false });
    if (integer.best) {
      assert.ok(continuous.objective >= integer.objective - 1e-9);
      assert.ok(integer.best.every(Number.isInteger));
      assert.ok(2 * integer.best[0] + integer.best[1] <= cutting);
      assert.ok(integer.best[0] + 2 * integer.best[1] <= 8);
    }
  }
  assert.deepEqual(projection(0), { x: 0, y: 0, objective: 5 });
  assert.deepEqual(projection(1), { x: 0, y: 1, objective: 2 });
  assert.deepEqual(projection(2), { x: .5, y: 1.5, objective: .5 });
  assert.deepEqual(projection(4), { x: 1, y: 2, objective: 0 });
  for (const start of [-1.8, .3, 1.8]) {
    const values = descent(start).map(nonconvex);
    assert.ok(values.every((value, i) => !i || value <= values[i - 1] + 1e-10));
  }
  assert.ok(nonconvex(descent(-1.8).at(-1)) < nonconvex(descent(1.8).at(-1)));

  const { articles } = JSON.parse(await fs.readFile(path.join(__dirname, "docs-manifest.json"), "utf8"));
  const errors = [];
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
    const page = await context.newPage();
    page.on("pageerror", error => errors.push(error.message));
    page.on("response", response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
    for (const locale of ["zh", "en"]) {
      for (const article of articles.filter(a => a.method)) {
        await page.goto(`${base}docs/${locale}/${article.id}/`);
        await expect(page.locator(".doc-diagram svg")).toHaveCount(1);
        await expect(page.locator('[data-walkthrough][data-ready="true"]')).toHaveCount(1);
        const panels = page.locator(".step-panel");
        await expect(panels.first()).toBeVisible();
        for (const button of await page.locator("[data-step]").all()) {
          await button.click();
          const panel = page.locator('.step-panel:visible');
          await expect(panel).toHaveCount(1);
          for (const id of (await panel.getAttribute("data-nodes")).split(" ")) assert.ok(await page.locator(`.doc-diagram [id*="-flowchart-${id}-"].is-current`).count(), `Stage node ${id}: ${locale}/${article.id}`);
        }
        const frame = await page.locator(".diagram-scroll").evaluate(node => ({ height: node.clientHeight, content: node.scrollHeight }));
        assert.ok(frame.content <= frame.height + 1, `Vertically cropped overview: ${locale}/${article.id}`);
        const labels = await page.locator(".doc-diagram .nodeLabel").evaluateAll(nodes => nodes.map(node => ({ size: parseFloat(getComputedStyle(node).fontSize), scale: node.getScreenCTM().a })));
        assert.ok(labels.every(label => label.size * label.scale >= 13), `Unreadable graph ${locale}/${article.id}`);
      }
      await page.goto(`${base}docs/${locale}/quickstart/`);
      const demo = page.locator('[data-demo="production"]');
      await expect(demo.locator(".demo-result")).toContainText("13");
      await expect(demo.locator(".demo-model")).toContainText("3A + 2B");
      await expect(demo.locator(".chart-legend span")).toHaveCount(4);
      await demo.locator('[name="domain"]').selectOption("continuous");
      await expect(demo.locator(".demo-result")).toContainText("13.333");
      await demo.locator('[name="domain"]').selectOption("integer");
      await demo.locator('[name="cutting"]').fill("10");
      await expect(demo.locator(".demo-result")).toContainText("16");
      const downloadPromise = page.waitForEvent("download");
      await demo.locator('[data-action="download"]').click();
      const download = await downloadPromise;
      const stream = await download.createReadStream();
      const chunks = []; for await (const chunk of stream) chunks.push(chunk);
      assert.match(Buffer.concat(chunks).toString(), /A,4\r\nB,2\r\nobjective,16/);
      await demo.locator('[name="minimumB"]').selectOption("5");
      await expect(demo.locator('[data-action="download"]')).toBeDisabled();
      assert.equal(await demo.locator(".chart-best").count(), 0);
      await demo.locator('[data-action="reset"]').click();
      await expect(demo.locator(".demo-result")).toContainText("13");

      const video = page.locator("video");
      await expect(video).toHaveAttribute("preload", "none");
      assert.equal(await video.evaluate(node => node.autoplay), false);
      await expect(video.locator("source")).toHaveAttribute("src", new RegExp(`workbench-${locale}\\.mp4$`));
      await expect(video.locator("track")).toHaveAttribute("srclang", locale);
      const dataChapter = page.locator('[data-seek]').last();
      const seek = Number(await dataChapter.getAttribute("data-seek"));
      await dataChapter.click();
      await expect.poll(() => video.evaluate(node => Number.isFinite(node.duration) && node.duration > 10)).toBe(true);
      assert.equal(await video.evaluate(node => node.videoWidth), 1360);
      await expect.poll(() => video.evaluate((node, position) => node.currentTime >= position && node.currentTime < position + 3, seek)).toBe(true);
      await video.evaluate(node => node.pause());
      await page.locator(".recording-transcript summary").click();
      await expect(page.locator(".recording-transcript li")).toHaveCount(6);
      await expect(page.locator(".recording-transcript li").first()).toBeVisible();

      await page.goto(`${base}docs/${locale}/chat-agent/`);
      const plans = page.locator('[data-demo="plans"]');
      await plans.locator('[data-action="scenarios"]').click();
      await expect(plans.locator("[data-current]")).toContainText("13");
      await expect(plans.locator("[data-saved-plans]")).toContainText("12");
      await expect(plans.locator("[data-saved-plans]")).toContainText("8");
      await plans.locator('[data-plan="4"]').click();
      await expect(plans.locator("[data-current]")).toContainText("A = 0, B = 4");
      await expect(plans.locator('[data-plan="4"]')).toHaveAttribute("aria-pressed", "true");
      await plans.locator('[data-action="explain"]').click();
      await expect(plans.locator(".demo-messages p").last()).toContainText("4/8");
      await plans.locator('[data-action="revise"]').click();
      await expect(plans.locator("[data-current]")).toContainText("12");
      await plans.locator('[data-action="explain"]').click();
      await expect(plans.locator(".demo-messages p").last()).toContainText("7/8");
      await plans.locator('[data-action="original"]').click();
      await expect(plans.locator("[data-current]")).toContainText("13");
      await plans.locator('[data-action="reset"]').click();
      await expect(plans.locator('[data-plan]')).toHaveCount(1);

      await page.goto(`${base}docs/${locale}/attachments/`);
      const data = page.locator('[data-demo="data"]');
      await data.locator('[name="cutting"]').fill("10.0");
      await expect(data.locator(".demo-result")).toContainText("13");
      await expect(data.locator('[data-action="run"]')).toBeDisabled();
      await data.locator('[data-action="save"]').click();
      await expect(data.locator(".demo-result")).toContainText("13");
      await expect(data.locator('[name="cutting"]')).toHaveValue("10");
      await expect(data.locator('[data-action="run"]')).toBeEnabled();
      await data.locator('[data-action="run"]').click();
      await expect(data.locator(".demo-result")).toContainText("16");
      await expect(data.locator("[data-snapshot]")).toContainText("13");
      await data.locator('[name="cutting"]').fill("12");
      await data.locator('[data-action="cancel"]').click();
      await expect(data.locator('[name="cutting"]')).toHaveValue("10");
      await data.locator('[name="cutting"]').fill("-1");
      await data.locator('[data-action="save"]').click();
      await expect(data.locator(".demo-result")).toContainText("16");
      await expect(data.locator('[data-action="run"]')).toBeDisabled();
      await data.locator('[data-action="cancel"]').click();
      await expect(data.locator('[name="cutting"]')).toHaveValue("10");
      await expect(data.locator('[data-action="run"]')).toBeEnabled();

      await page.goto(`${base}docs/${locale}/cvxpy/`);
      await page.locator('[name="limit"]').fill("3");
      await expect(page.locator(".demo-result")).toContainText("x = 1, y = 2");
      await page.goto(`${base}docs/${locale}/casadi/`);
      await page.locator('[name="start"]').selectOption("1.8");
      await page.locator('[data-demo="local"] [data-action="play"]').click();
      await expect(page.locator(".demo-result")).toContainText("60");
      await expect(page.locator(".demo-model")).toContainText("(x² − 1)² + 0.2x");
      assert.equal(await page.locator('.chart-line').evaluate(node => { const box = node.getBBox(); return box.y >= 16 && box.y + box.height <= 280; }), true, 'Clipped objective curve');
    }
    for (const width of [1440, 768, 390, 320]) for (const locale of ["zh", "en"]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const id of ["direct", "trival", "autoformulation", "attachments", "cvxpy", "casadi", "quickstart"]) {
        await page.goto(`${base}docs/${locale}/${id}/`);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Overflow ${width}/${locale}/${id}`);
      }
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    for (const [locale, id, selector] of [["zh", "trival", "[data-walkthrough]"], ["en", "cvxpy", "[data-demo]"], ["en", "attachments", "[data-demo]"], ["zh", "chat-agent", "[data-demo]"]]) {
      await page.goto(`${base}docs/${locale}/${id}/`);
      await page.locator(selector).scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(output, `learning-${locale}-${id}.png`) });
    }
    await page.goto(`${base}docs/en/trival/`);
    await page.locator(".diagram-actions button").click();
    await expect(page.locator("#diagram-dialog")).toHaveJSProperty("open", true);
    await expect.poll(() => page.locator("#diagram-dialog img").evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
    await page.locator("[data-diagram-size]").click();
    await expect(page.locator("#diagram-dialog img")).toHaveClass("native-size");
    await page.locator("[data-diagram-size]").click();
    await expect(page.locator("#diagram-dialog img")).not.toHaveClass("native-size");
    await page.keyboard.press("Escape");
    await expect(page.locator("#diagram-dialog")).toHaveJSProperty("open", false);
    await context.close();

    const animated = await browser.newContext({ reducedMotion: "no-preference" });
    const motion = await animated.newPage();
    await motion.goto(`${base}docs/en/trival/`);
    const walk = motion.locator("[data-walkthrough]");
    await walk.locator('[data-action="play"]').click();
    await expect(walk.locator(".step-count")).toHaveText("2 / 4", { timeout: 6500 });
    await walk.locator('[data-action="play"]').click();
    await expect(walk.locator('[data-action="play"]')).toHaveAttribute("aria-pressed", "false");
    await motion.goto(`${base}docs/en/casadi/`);
    await motion.locator('[data-demo="local"] [data-action="play"]').click();
    await expect.poll(() => motion.locator(".demo-result").textContent()).not.toContain("Iteration 0");
    await motion.locator('[data-demo="local"] [data-action="play"]').click();
    const paused = await motion.locator(".demo-result").textContent();
    await motion.waitForTimeout(300);
    assert.equal(await motion.locator(".demo-result").textContent(), paused);
    await animated.close();

    const staticContext = await browser.newContext({ javaScriptEnabled: false });
    const staticPage = await staticContext.newPage();
    await staticPage.goto(`${base}docs/en/trival/`);
    assert.equal(await staticPage.locator(".step-panel:visible").count(), 4);
    await expect(staticPage.locator(".doc-diagram svg")).toBeVisible();
    await staticContext.close();
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
  console.log("PASS: complete method overviews and every stage highlight, exact numerical examples, saved-plan selection, separate data save/run and validation, CSV, localized video chapter seeks and transcripts, pause/replay, reduced motion, no-JS content and responsive layouts.");
})().catch(error => { console.error(error); process.exitCode = 1; });
