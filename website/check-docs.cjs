const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { JSDOM } = require("../frontend/node_modules/jsdom");
const { chromium, expect } = require("../frontend/node_modules/@playwright/test");

const root = path.join(__dirname, "public");
const base = (process.argv[2] || "http://127.0.0.1:8831/").replace(/\/?$/, "/");
const output = path.join(__dirname, "../artifacts/website/docs");

(async () => {
  const { articles } = JSON.parse(await fs.readFile(path.join(__dirname, "docs-manifest.json"), "utf8"));
  assert.equal(articles.filter(a => a.method).length, 13);
  assert.equal(articles.filter(a => a.library).length, 9);
  const headingCounts = new Map();
  for (const [languageIndex, locale] of ["zh", "en"].entries()) {
    const search = JSON.parse(await fs.readFile(path.join(root, `docs/search-${locale}.json`), "utf8"));
    assert.equal(search.length, articles.length);
    for (const entry of search) assert.doesNotMatch(entry.text, /stroke-dasharray|edge-animation|flowchart TB|&gt;|&amp;/, `Unreadable search text: ${locale}/${entry.id}`);
    for (const article of articles) {
      const relative = `docs/${locale}/${article.id}/`;
      const html = await fs.readFile(path.join(root, relative, "index.html"), "utf8");
      const document = new JSDOM(html).window.document;
      assert.equal(document.querySelector("h1").textContent, article.title[languageIndex]);
      const ids = [...document.querySelectorAll("[id]")].map(node => node.id);
      assert.equal(ids.length, new Set(ids).size, `Duplicate ID: ${relative}`);
      const headings = document.querySelectorAll(".doc-prose h2,.doc-prose h3").length;
      if (locale === "zh") headingCounts.set(article.id, headings);
      else assert.equal(headings, headingCounts.get(article.id), `Translation section mismatch: ${article.id}`);
      if (locale === "en") assert.doesNotMatch(document.querySelector("main").textContent, /[\u3400-\u9fff]/, `Chinese in English article: ${article.id}`);
      assert.ok(document.querySelector(".doc-prose").textContent.length > 400, `Thin content: ${relative}`);
      for (const node of document.querySelectorAll("a[href],link[href],script[src],img[src],source[src],track[src]")) {
        const url = new URL(node.getAttribute("href") || node.getAttribute("src"), `https://docs.test/LLM4OM/${relative}`);
        if (url.origin !== "https://docs.test") continue;
        assert.ok(url.pathname.startsWith("/LLM4OM/"), `Escapes GitHub project path: ${url}`);
        let target = path.join(root, decodeURIComponent(url.pathname.slice("/LLM4OM/".length)));
        if (url.pathname.endsWith("/")) target = path.join(target, "index.html");
        await fs.access(target).catch(() => { throw new Error(`Broken link in ${relative}: ${url}`); });
        if (url.hash && target.endsWith(".html")) {
          const destination = target === path.join(root, relative, "index.html") ? document : new JSDOM(await fs.readFile(target, "utf8")).window.document;
          assert.ok(destination.getElementById(decodeURIComponent(url.hash.slice(1))), `Broken anchor in ${relative}: ${url}`);
        }
      }
    }
  }

  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", colorScheme: "dark", permissions: ["clipboard-read", "clipboard-write"] });
    const page = await context.newPage();
    page.on("pageerror", error => errors.push(error.message));
    page.on("response", response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
    for (const locale of ["zh", "en"]) {
      for (const article of articles) {
        assert.equal((await page.goto(`${base}docs/${locale}/${article.id}/`)).status(), 200);
        await expect(page.locator("h1")).toHaveText(article.title[locale === "en" ? 1 : 0]);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Desktop overflow: ${locale}/${article.id}`);
      }
    }
    await page.goto(`${base}docs/en/trival/#section-2`);
    await expect(page.locator('.docs-sidebar [aria-current="page"]')).toHaveText("TriVAL");
    await page.locator("#docs-language").click();
    await expect(page).toHaveURL(/docs\/zh\/trival\/#section-2$/);
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
    await expect(page.locator(".doc-prose")).toContainText("max_validations");
    await expect(page.locator(".doc-prose")).toContainText("5");
    await page.goto(`${base}docs/?lang=en`);
    await expect(page).toHaveURL(/docs\/en\/introduction\/$/);
    await page.goto(`${base}docs/`);
    await expect(page).toHaveURL(/docs\/en\/introduction\/$/);

    for (const [locale, query, id] of [["en", "BIND", "bind"], ["zh", "无解", "conflicts"], ["en", "CP-SAT", "ortools"], ["en", "Bradley", "autoformulation"], ["zh", "单件利润", "attachments"]]) {
      await page.goto(`${base}docs/${locale}/introduction/`);
      await page.keyboard.press("Control+k");
      await expect(page.locator("#docs-search")).toHaveJSProperty("open", true);
      await page.locator("#search-input").fill(query);
      await expect(page.locator("#search-results a").first()).toBeVisible();
      assert.ok((await page.locator("#search-results a").evaluateAll(links => links.map(a => a.href))).some(href => href.endsWith(`/${id}/`)));
      assert.doesNotMatch(await page.locator("#search-results").innerText(), /stroke-dasharray|edge-animation|flowchart TB|&gt;/);
      await page.locator("#search-input").press("ArrowDown");
      assert.equal(await page.locator("#search-results a").first().evaluate(node => node === document.activeElement), true);
      await page.keyboard.press("Escape");
      await expect(page.locator("#docs-search")).toHaveJSProperty("open", false);
    }
    await page.goto(`${base}docs/en/introduction/`);
    await page.locator("#search-open").click();
    await page.locator("#search-input").fill("zz-no-such-page-123");
    await expect(page.locator("#search-status")).toContainText("No pages found");
    await page.locator("#search-input").fill('<img src=x onerror="alert(1)">');
    await expect(page.locator("#search-status")).toContainText("No pages found");
    assert.equal(await page.locator("#search-results img").count(), 0);
    await page.keyboard.press("Escape");
    await page.goto(`${base}docs/en/model-presets/`);
    const snippet = page.locator("pre").first();
    const expected = await snippet.locator("code").textContent();
    await snippet.locator("button").click();
    await expect(snippet.locator("button")).toHaveText("Copied");
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), expected);
    await page.goto(`${base}?lang=en`);
    await expect(page.locator('[data-docs="introduction"]')).toHaveAttribute("href", /docs\/en\/introduction\/$/);
    await page.locator('[data-docs="introduction"]').click();
    await expect(page.locator("h1")).toHaveText("LLM4OM documentation");

    for (const width of [1440, 1280, 768, 390, 360, 320]) {
      await page.setViewportSize({ width, height: width >= 768 ? 1000 : 844 });
      for (const locale of ["zh", "en"]) {
        for (const id of ["introduction", "chat-agent", "methods", "autoformulation", "solvers", "configuration"]) {
          await page.goto(`${base}docs/${locale}/${id}/`);
          await page.evaluate(() => document.fonts.ready);
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Overflow: ${width} ${locale}/${id}`);
        }
        if (width === 1440 || width === 390) {
          await page.goto(`${base}docs/${locale}/chat-agent/`);
          await page.screenshot({ path: path.join(output, `${width === 1440 ? "desktop" : "mobile"}-${locale}.png`) });
        }
      }
    }
    await page.goto(`${base}docs/en/chat-agent/`);
    await page.locator("#mobile-menu").click();
    await expect(page.locator("#mobile-nav")).toHaveJSProperty("open", true);
    await page.locator('#mobile-nav [data-article="backends"]').click();
    await expect(page.locator("h1")).toHaveText("Backends and licenses");
    await page.locator(".docs-inline-toc summary").click();
    await page.locator('.docs-inline-toc a[href="#section-3"]').click();
    await expect(page).toHaveURL(/#section-3$/);
    await page.locator("#search-open").click();
    await page.locator("#search-input").fill("license");
    await expect(page.locator("#search-results a").first()).toBeVisible();
    await page.screenshot({ path: path.join(output, "mobile-search-en.png") });
    await page.keyboard.press("Escape");

    await page.route("**/search-en.json", route => route.abort());
    await page.reload();
    await page.locator("#search-open").click();
    await page.locator("#search-input").fill("BIND");
    await expect(page.locator("#search-status")).toContainText("Search could not load");
    await page.unroute("**/search-en.json");
    await page.locator("#search-input").fill("Direct");
    await expect(page.locator("#search-results a").first()).toContainText("Direct");
    await context.close();

    const noScript = await browser.newPage({ javaScriptEnabled: false, viewport: { width: 390, height: 844 } });
    await noScript.goto(`${base}docs/en/quickstart/`);
    await expect(noScript.locator("h1")).toHaveText("Your first plan");
    await expect(noScript.locator("article")).toContainText("CNY 13");
    await noScript.locator("#docs-language").click();
    await expect(noScript.locator("h1")).toHaveText("完成第一个方案");
    assert.deepEqual(errors, []);
    console.log(`PASS: ${articles.length * 2} pages, internal links and anchors, translation parity, 13 method presets, 9 libraries; bilingual search, keyboard/dialogs, clipboard, index recovery, no-JS reading and six viewport sizes.`);
    console.log(`Screenshots: ${output}`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
