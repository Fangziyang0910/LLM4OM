const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium, expect } = require("../frontend/node_modules/@playwright/test");

const base = process.argv[2] || "http://127.0.0.1:8831/";
const output = path.join(__dirname, "../artifacts/website/v2");

(async () => {
  const { solveExample: solve } = await import("./public/examples.mjs");
  assert.deepEqual([8, 9, 10, 11, 12].map(cutting => solve("production", { cutting }).total), [13, 14, 16, 17, 18]);
  assert.deepEqual(solve("production"), { total: 13, quantities: [3, 2] });
  assert.equal(solve("production", { minimumB: 3 }).total, 12);
  assert.equal(solve("production", { minimumB: 5 }), null);
  assert.equal(solve("shifts").total, 6);
  assert.deepEqual(solve("shifts", { change: true }), { total: 18, days: [1, 0, 1, 0] });
  assert.deepEqual(solve("delivery"), { total: 9, destinations: [0, 1, 2] });
  assert.deepEqual(solve("delivery", { change: true }), { total: 17, destinations: [1, 0, 2] });
  assert.throws(() => solve("production", { cutting: 13 }), RangeError);
  assert.throws(() => solve("unknown"), RangeError);

  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", colorScheme: "dark" });
    const page = await context.newPage();
    page.on("pageerror", error => errors.push(error.message));
    page.on("response", response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
    assert.equal((await page.goto(`${base}?lang=zh`)).status(), 200);
    await expect(page.locator("#demo-objective")).toHaveText("13");
    await page.locator("#demo-data").click();
    await expect(page.locator("#model-content")).toBeVisible();
    await expect(page.locator("#model-data")).toContainText("装配 1 小时");
    await page.locator("#view-plan").click();
    await page.locator("#change-condition").click();
    await expect(page.locator("#demo-objective")).toHaveText("16");
    await expect(page.locator("#quantity-a")).toHaveText("4 件");
    await page.locator("#cutting-capacity").press("End");
    await expect(page.locator("#demo-objective")).toHaveText("18");
    await page.locator("#infeasible-condition").click();
    assert.equal(await page.locator("#conflict-message").isVisible(), true);
    assert.equal(await page.locator("#download-plan").isDisabled(), true);
    await expect(page.locator("#demo-objective")).toHaveText("—");
    await page.locator("#view-model").click();
    await expect(page.locator("#example-model")).toContainText("B ≥ 5");
    await page.locator("#view-model").press("ArrowLeft");
    await page.locator("#resolve-conflict").click();
    await expect(page.locator("#demo-objective")).toHaveText("13");

    for (const [kind, before, after] of [["shifts", "6", "18"], ["delivery", "9", "17"]]) {
      await page.locator(`[data-case="${kind}"]`).click();
      await expect(page.locator("#demo-objective")).toHaveText(before);
      await page.locator("#change-condition").click();
      await expect(page.locator("#demo-objective")).toHaveText(after);
      if (kind === "shifts") assert.equal(await page.locator('[data-person="0"]').evaluate(node => node.style.gridColumn), "2");
      if (kind === "delivery") {
        assert.equal(await page.locator("#route-active path").count(), 3);
        await expect(page.locator("#route-summary")).toContainText("仓库 B → 门店 1");
      }
    }
    const downloading = page.waitForEvent("download");
    await page.locator("#download-plan").click();
    const download = await downloading;
    const csv = await fs.readFile(await download.path(), "utf8");
    assert.match(csv, /"最低总运费 \(CNY\)","17"/);
    assert.match(csv, /"仓库 B","门店 1"/);

    await page.locator("#language-toggle").click();
    assert.equal(await page.locator("html").getAttribute("lang"), "en");
    await expect(page.locator("#demo-objective")).toHaveText("17");
    assert.doesNotMatch(await page.locator("main").innerText(), /[\u3400-\u9fff]/);
    await page.goto(base);
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    const missing = await page.evaluate(async () => {
      const { copy } = await import("./translations.js");
      return [...document.querySelectorAll("[data-i18n],[data-i18n-label]")].flatMap(node => [node.dataset.i18n, node.dataset.i18nLabel]).filter(key => key && (!copy[key]?.[0] || !copy[key]?.[1]));
    });
    assert.deepEqual(missing, []);
    await page.locator("#feature-image").scrollIntoViewIfNeeded();
    for (const locale of ["en", "zh"]) {
      if ((await page.locator("html").getAttribute("lang")) !== (locale === "en" ? "en" : "zh-CN")) await page.locator("#language-toggle").click();
      for (const item of ["plan", "scenarios", "data"]) {
        await page.locator(`[data-feature="${item}"]`).click();
        await expect(page.locator(".photo-stage")).toHaveAttribute("data-loading", "false");
        assert.equal(await page.locator("#feature-image").getAttribute("src"), `assets/screens/${locale}/${item}.png`);
        const brightness = await page.locator("#feature-image").evaluate(image => {
          const canvas = document.createElement("canvas"); canvas.width = canvas.height = 1;
          const ctx = canvas.getContext("2d"); ctx.drawImage(image, 0, 0, 1, 1);
          return [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3).reduce((a, b) => a + b) / 3;
        });
        assert.ok(brightness < 100, `Expected a dark ${locale} screenshot: ${item}`);
      }
      if (locale === "en") assert.doesNotMatch(await page.locator("main").innerText(), /[\u3400-\u9fff]/);
    }
    await page.locator('[data-feature="data"]').press("Home");
    await expect(page.locator('[data-feature="plan"]')).toHaveAttribute("aria-selected", "true");
    await page.locator("#enlarge-photo").click();
    assert.equal(await page.locator("dialog").evaluate(dialog => dialog.open), true);
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("dialog").evaluate(dialog => dialog.open), false);
    await page.locator(".faq-list summary").first().click();
    assert.equal(await page.locator(".faq-list details").first().getAttribute("open"), "");

    for (const viewport of [{ width: 1440, height: 1000 }, { width: 1280, height: 800 }, { width: 768, height: 1024 }, { width: 390, height: 844 }, { width: 360, height: 780 }, { width: 320, height: 740 }]) {
      await page.setViewportSize(viewport);
      for (const locale of ["en", "zh"]) {
        await page.goto(`${base}?lang=${locale}`);
        await page.evaluate(() => document.fonts.ready);
        for (const kind of ["production", "shifts", "delivery"]) {
          await page.locator(`[data-case="${kind}"]`).click();
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Overflow: ${viewport.width} ${locale} ${kind}`);
          assert.doesNotMatch(await page.locator("main").innerText(), /undefined|NaN/);
        }
        await page.locator('[data-case="production"]').click();
        await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
        if (viewport.width === 1440 || viewport.width === 390) await page.screenshot({ path: path.join(output, `${viewport.width === 1440 ? "desktop" : "mobile"}-${locale}.png`) });
      }
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`${base}?lang=zh`);
    await page.locator("#feature-image").scrollIntoViewIfNeeded();
    await expect(page.locator(".photo-stage")).toHaveAttribute("data-loading", "false");
    const style = ".site-header,.skip-link{visibility:hidden!important}";
    await page.locator("#studio").screenshot({ path: path.join(output, "interactive-zh.png"), style });
    await page.locator("#features").screenshot({ path: path.join(output, "features-zh.png"), style });
    await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
    await page.screenshot({ path: path.join(output, "full-page-zh.png"), fullPage: true });
    await context.close();

    const moving = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "no-preference", colorScheme: "dark" });
    const motion = await moving.newPage();
    motion.on("pageerror", error => errors.push(error.message));
    await motion.goto(`${base}?lang=en`);
    await expect(motion.locator("#studio")).not.toHaveAttribute("data-phase", "complete");
    await motion.locator("#play-demo").click();
    const stopped = await motion.locator("#playback-progress").getAttribute("style");
    await motion.waitForTimeout(300);
    assert.equal(await motion.locator("#playback-progress").getAttribute("style"), stopped, "Paused playback must not advance");
    await motion.locator("#play-demo").click();
    await expect(motion.locator("#play-text")).toHaveText("Replay", { timeout: 8000 });
    await expect(motion.locator("#demo-objective")).toHaveText("13");
    await motion.locator("#play-demo").click();
    await motion.locator("#language-toggle").click();
    await expect(motion.locator("#studio")).toHaveAttribute("data-phase", "complete");
    assert.doesNotMatch(await motion.locator("#demo-question").innerText(), /We make/);
    await motion.locator('[data-case="shifts"]').click();
    await motion.locator("#change-condition").click();
    assert.ok(await motion.locator('[data-person="0"]').evaluate(node => node.getAnimations().length > 0), "Staff changes should animate between days");
    await moving.close();
    assert.deepEqual(errors, []);
    console.log("PASS: three computed cases; sliders, conflicting requirements, CSV export; full bilingual copy and matching dark media; keyboard tabs/dialog; six viewport sizes; playback, pause/resume, language changes during playback, and animated staff reassignment.");
    console.log(`Screenshots: ${output}`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
