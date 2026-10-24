import fs from "node:fs/promises";
import path from "node:path";
import http from "node:http";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("../frontend/node_modules/@playwright/test");
const directory = path.dirname(fileURLToPath(import.meta.url));
const output = path.join(directory, "public/docs/diagrams");
const config = {
  startOnLoad: false, securityLevel: "strict", theme: "base", look: "classic", htmlLabels: false,
  fontFamily: "Inter, Arial, sans-serif", deterministicIds: true,
  flowchart: { htmlLabels: false, curve: "basis", nodeSpacing: 25, rankSpacing: 38, padding: 16 },
  themeVariables: {
    darkMode: true, background: "#19161f", primaryColor: "#282137", primaryTextColor: "#eee5fc",
    primaryBorderColor: "#82709f", lineColor: "#ae99ce", secondaryColor: "#20352f", tertiaryColor: "#35283c",
    edgeLabelBackground: "#19161f", fontSize: "15px", clusterBkg: "#211c29", clusterBorder: "#635271"
  }
};
export const diagramHash = source => createHash("sha256").update(JSON.stringify(config) + "12.2.0" + source).digest("hex");
const server = http.createServer(async (request, response) => {
  const filename = path.resolve(directory, "." + new URL(request.url, "http://localhost").pathname);
  if (!filename.startsWith(directory + path.sep)) { response.writeHead(403).end(); return; }
  try {
    const data = await fs.readFile(filename);
    response.setHeader("Content-Type", filename.endsWith(".woff2") ? "font/woff2" : "text/javascript");
    response.end(data);
  } catch { response.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
let browser;
try {
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const origin = `http://127.0.0.1:${server.address().port}`;
  await page.goto(origin + "/package.json");
  await page.evaluate(async ({ origin, config }) => {
    const font = new FontFace("Inter", `url(${origin}/public/assets/inter-latin-wght-normal.woff2)`);
    document.fonts.add(await font.load());
    window.mermaid = (await import(`${origin}/node_modules/mermaid/dist/mermaid.esm.min.mjs`)).default;
    window.mermaid.initialize(config);
  }, { origin, config });
  await fs.mkdir(output, { recursive: true });
  let previous = {};
  try { previous = JSON.parse(await fs.readFile(path.join(output, "manifest.json"), "utf8")); } catch (error) { if (error.code !== "ENOENT") throw error; }
  const manifest = {};
  let rendered = 0;
  for (const locale of ["zh", "en"]) {
    for (const name of (await fs.readdir(path.join(directory, "content", locale))).filter(file => file.endsWith(".md")).sort()) {
      const markdown = await fs.readFile(path.join(directory, "content", locale, name), "utf8");
      let number = 0;
      for (const match of markdown.matchAll(/^```mermaid\n([\s\S]*?)^```/gm)) {
        const key = `${locale}-${name.slice(0, -3)}-${++number}`;
        const source = match[1];
        const hash = diagramHash(source);
        const filename = `${key}.svg`;
        manifest[key] = { hash, sourceHash: createHash("sha256").update(source).digest("hex"), file: filename };
        if (previous[key]?.hash === hash && await fs.access(path.join(output, filename)).then(() => true, () => false)) continue;
        const svg = await page.evaluate(async ({ key, source }) => (await window.mermaid.render(`diagram-${key}`, source)).svg, { key, source });
        if (/<script\b|<foreignObject\b|\son\w+=/i.test(svg)) throw new Error(`Unexpected active SVG content: ${key}`);
        await fs.writeFile(path.join(output, filename), svg + "\n");
        rendered++;
      }
    }
  }
  for (const key of Object.keys(previous)) if (!manifest[key]) await fs.rm(path.join(output, previous[key].file), { force: true });
  await fs.writeFile(path.join(output, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  console.log(`Prepared ${Object.keys(manifest).length} Mermaid diagrams (${rendered} rendered).`);
} finally {
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
}
