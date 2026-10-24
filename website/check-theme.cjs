const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium, expect } = require("../frontend/node_modules/@playwright/test");

const base = (process.argv[2] || "http://127.0.0.1:8831/").replace(/\/?$/, "/");
const output = path.resolve(__dirname, "../artifacts/website/themes");
const choose = async (page, value) => {
  await page.locator(".theme-switcher > summary").click();
  await page.locator(`[data-theme-choice="${value}"]`).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme-preference", value);
};
const fits = async page => assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Overflow: ${page.url()}`);

(async () => {
  await fs.mkdir(output, { recursive: true });
  const { articles } = JSON.parse(await fs.readFile(path.join(__dirname, "docs-manifest.json"), "utf8"));
  const browser = await chromium.launch();
  const errors = [], assets = new Set();
  try {
    const context = await browser.newContext({ colorScheme: "light", reducedMotion: "reduce", viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    page.on("pageerror", error => errors.push(error.message));
    page.on("response", response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
    await page.goto(`${base}?lang=en`);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect(page.locator("html")).toHaveAttribute("data-theme-preference", "system");
    await page.emulateMedia({ colorScheme: "dark" });
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await choose(page, "light");
    await page.emulateMedia({ colorScheme: "light" });
    await page.emulateMedia({ colorScheme: "dark" });
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.locator("#change-condition").click();
    await page.locator("#view-model").click();
    await choose(page, "dark");
    await expect(page.locator("#demo-objective")).toHaveText("16");
    await expect(page.locator("#view-model")).toHaveAttribute("aria-selected", "true");
    await page.locator("#language-toggle").click();
    await page.locator(".theme-switcher > summary").click();
    await expect(page.locator('[data-theme-choice="system"]')).toHaveText("跟随系统");
    await page.keyboard.press("Escape");
    await expect(page.locator(".theme-switcher")).not.toHaveAttribute("open");
    await page.locator(".theme-switcher > summary").press("Enter");
    await page.locator('[data-theme-choice="light"]').focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect(page.locator(".theme-switcher > summary")).toBeFocused();
    for (const locale of ["zh", "en"]) {
      await page.goto(`${base}?lang=${locale}`);
      for (const theme of ["light", "dark"]) {
        await choose(page, theme);
        for (const feature of ["plan", "scenarios", "data"]) {
          await page.locator(`[data-feature="${feature}"]`).click();
          await expect(page.locator(".photo-stage")).toHaveAttribute("data-loading", "false");
          await expect(page.locator("#feature-image")).toHaveAttribute("src", `assets/screens/${locale}/${feature}${theme === "light" ? "-light" : ""}.png`);
          const brightness = await page.locator("#feature-image").evaluate(img => {
            const canvas = document.createElement("canvas"); canvas.width = canvas.height = 1;
            const ctx = canvas.getContext("2d"); ctx.drawImage(img, 0, 0, 1, 1);
            return [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3).reduce((a, b) => a + b) / 3;
          });
          assert.ok(theme === "light" ? brightness > 180 : brightness < 100, `Wrong screenshot appearance: ${theme}/${locale}/${feature}`);
        }
        await page.locator("#enlarge-photo").click();
        await expect(page.locator("#photo-dialog img")).toHaveAttribute("src", new RegExp(`/data${theme === "light" ? "-light" : ""}\\.png$`));
        await page.keyboard.press("Escape");
      }
    }
    await page.goto(`${base}docs/en/trival/`);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.locator('[data-step="2"]').click();
    const stage = await page.locator(".step-panel:visible").textContent();
    await choose(page, "light");
    await expect(page.locator(".step-panel:visible")).toHaveText(stage);
    await expect(page.locator('.doc-diagram svg:visible')).toHaveAttribute("data-diagram-theme", "light");
    await expect(page.locator(".diagram-actions a")).toHaveAttribute("href", /-light\.svg$/);
    await page.locator(".diagram-actions button").click();
    await expect(page.locator("#diagram-dialog img")).toHaveAttribute("src", /-light\.svg$/);
    await page.keyboard.press("Escape");
    await page.locator("#docs-language").click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect(page.locator(".theme-switcher > summary")).toHaveAttribute("aria-label", "外观");
    for (const theme of ["light", "dark"]) {
      await choose(page, theme);
      for (const locale of ["zh", "en"]) for (const article of articles) {
        await page.goto(`${base}docs/${locale}/${article.id}/`);
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        await fits(page);
        const paths = await page.locator("[data-light-src],[data-light-href]").evaluateAll(nodes => nodes.flatMap(node => [node.dataset.lightSrc, node.dataset.lightHref]).filter(Boolean).map(value => new URL(value, location.href).href));
        paths.forEach(value => assets.add(value));
        for (const svg of await page.locator(".doc-diagram svg:visible").all()) await expect(svg).toHaveAttribute("data-diagram-theme", theme);
        if (article.method) {
          const sizes = await page.locator(".doc-diagram .node text:visible").evaluateAll(nodes => nodes.map(node => parseFloat(getComputedStyle(node).fontSize) * node.getScreenCTM().a));
          assert.ok(sizes.length && sizes.every(size => size >= 13), `Unreadable ${theme} diagram: ${locale}/${article.id}`);
        }
      }
    }
    for (const url of assets) assert.equal((await context.request.get(url)).status(), 200, `Missing light asset: ${url}`);
    await page.goto(`${base}docs/en/attachments/`);
    await page.locator('[name="cutting"]').fill("10");
    await page.locator('[data-action="save"]').click();
    await choose(page, "light");
    await expect(page.locator('[name="cutting"]')).toHaveValue("10");
    await expect(page.locator('[data-action="run"]')).toBeEnabled();
    await page.locator('[data-action="run"]').click();
    await expect(page.locator(".demo-result")).toContainText("16");
    for (const locale of ["zh", "en"]) {
      await page.goto(`${base}docs/${locale}/quickstart/`);
      const video = page.locator("video");
      await expect(video).toHaveAttribute("preload", "none");
      assert.equal(await video.evaluate(node => node.paused && !node.autoplay), true);
      await expect(video.locator("source")).toHaveAttribute("src", new RegExp(`workbench-${locale}-light\\.mp4$`));
      await expect(video.locator("track")).toHaveAttribute("src", new RegExp(`workbench-${locale}-light\\.vtt$`));
      await expect(video).toHaveAttribute("poster", new RegExp(`${locale}/plan-light\\.png$`));
      const chapter = page.locator("[data-seek]").last(), position = Number(await chapter.getAttribute("data-light-seek"));
      await chapter.click();
      await expect.poll(() => video.evaluate((node, position) => node.currentTime >= position && node.currentTime < position + 3 && !node.paused, position)).toBe(true);
      await video.evaluate(node => node.pause());
      const time = await video.evaluate(node => node.currentTime);
      await choose(page, "dark");
      await expect.poll(() => video.evaluate((node, time) => node.readyState >= 1 && node.paused && Math.abs(node.currentTime - time) < .25, time)).toBe(true);
      await chapter.click();
      await expect.poll(() => video.evaluate(node => !node.paused)).toBe(true);
      await choose(page, "light");
      await expect.poll(() => video.evaluate((node, time) => node.readyState >= 1 && !node.paused && node.currentTime >= time - .25, time)).toBe(true);
      await expect(page.locator(".recording-status")).toBeHidden();
      await video.evaluate(node => node.pause());
    }
    await choose(page, "system");
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto(`${base}docs/en/trival/`);
    await page.locator(".diagram-actions button").click();
    await page.emulateMedia({ colorScheme: "dark" });
    await expect(page.locator("#diagram-dialog img")).toHaveAttribute("src", /en-trival-1\.svg$/);
    await page.keyboard.press("Escape");
    const other = await context.newPage();
    await other.goto(base);
    await choose(page, "light");
    await expect(other.locator("html")).toHaveAttribute("data-theme", "light");
    await other.close();
    for (const theme of ["light", "dark"]) {
      await choose(page, theme);
      for (const width of [1440, 1280, 768, 390, 360, 320]) for (const locale of ["zh", "en"]) {
        await page.setViewportSize({ width, height: 1000 });
        for (const route of [`?lang=${locale}`, `docs/${locale}/trival/`]) {
          await page.goto(base + route);
          await fits(page);
          await page.locator(".theme-switcher > summary").click();
          const menu = await page.locator(".theme-menu").boundingBox();
          assert.ok(menu.x >= 0 && menu.x + menu.width <= width, `Clipped theme menu: ${width}/${locale}`);
          await page.keyboard.press("Escape");
          if (theme === "light" && [1440, 390].includes(width)) {
            await page.evaluate(() => { document.activeElement?.blur(); scrollTo(0, 0); });
            await page.screenshot({ path: path.join(output, `${width}-${locale}-${route.includes("docs") ? "docs" : "home"}.png`) });
          }
        }
      }
    }
    await context.close();
    const blocked = await browser.newContext({ colorScheme: "dark" });
    await blocked.addInitScript(() => Object.defineProperty(window, "localStorage", { get() { throw new Error("Storage unavailable"); } }));
    const privatePage = await blocked.newPage();
    await privatePage.goto(base);
    await choose(privatePage, "light");
    await expect(privatePage.locator("html")).toHaveAttribute("data-theme", "light");
    await blocked.close();
    assert.deepEqual(errors, []);
    console.log("PASS: light/dark/system, persistence, OS changes, bilingual keyboard controls, tab sync, blocked storage, preserved demo/stage/video state, matching light media, all 92 Docs in both themes, light assets, diagram fonts and six responsive widths.");
    console.log(`Screenshots: ${output}`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
