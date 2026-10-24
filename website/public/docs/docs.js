const locale = document.body.dataset.locale;
const english = locale === "en";
const say = (zh, en) => english ? en : zh;
const searchDialog = document.querySelector("#docs-search");
const searchInput = document.querySelector("#search-input");
const results = document.querySelector("#search-results");
const status = document.querySelector("#search-status");
const normalize = value => value.normalize("NFKC").toLowerCase();
let indexPromise;
let timer;
let searchVersion = 0;

try { localStorage.setItem("llm4om-site-language", locale); } catch {}
const languageLink = document.querySelector("#docs-language");
const syncLanguageAnchor = () => { const target = new URL(languageLink.href); target.hash = location.hash; languageLink.href = target; };
syncLanguageAnchor();
addEventListener("hashchange", syncLanguageAnchor);

function openSearch() {
  if (!searchDialog.open) searchDialog.showModal();
  searchInput.focus();
  searchInput.select();
}
document.querySelector("#search-open").addEventListener("click", openSearch);
document.querySelector("#search-open kbd").textContent = navigator.platform.includes("Mac") ? "⌘ K" : "Ctrl K";
document.querySelector("#mobile-menu").addEventListener("click", () => document.querySelector("#mobile-nav").showModal());
for (const button of document.querySelectorAll("[data-close]")) button.addEventListener("click", () => document.getElementById(button.dataset.close).close());
for (const dialog of document.querySelectorAll("dialog")) dialog.addEventListener("click", event => {
  const box = dialog.getBoundingClientRect();
  if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) dialog.close();
});
addEventListener("keydown", event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); openSearch(); }
});

function highlight(node, text, terms) {
  const first = terms.map(term => ({ start: normalize(text).indexOf(term), term })).filter(hit => hit.start >= 0).sort((a, b) => a.start - b.start)[0];
  if (!first) { node.textContent = text; return; }
  node.append(text.slice(0, first.start));
  const mark = document.createElement("mark");
  mark.textContent = text.slice(first.start, first.start + first.term.length);
  node.append(mark, text.slice(first.start + first.term.length));
}

async function search() {
  const version = ++searchVersion;
  const query = searchInput.value.trim();
  const terms = normalize(query).split(/\s+/).filter(Boolean);
  results.replaceChildren();
  if (!terms.length) { status.textContent = say("输入关键词查找文档", "Type to find a page"); return; }
  status.textContent = say("正在查找…", "Searching…");
  try {
    indexPromise ??= fetch(new URL(`../../search-${locale}.json`, location.href)).then(response => {
      if (!response.ok) throw new Error("Search index unavailable");
      return response.json();
    }).catch(error => { indexPromise = undefined; throw error; });
    const entries = await indexPromise;
    if (version !== searchVersion) return;
    const matches = entries.map(entry => {
      const title = normalize(entry.title);
      const description = normalize(entry.description);
      const body = normalize(entry.text);
      const score = terms.every(term => `${title} ${description} ${body}`.includes(term)) ? terms.reduce((total, term) => total + (title.includes(term) ? 30 : 0) + (description.includes(term) ? 8 : 0) + (body.includes(term) ? 1 : 0), 0) : 0;
      return { entry, score };
    }).filter(hit => hit.score > 0).sort((a, b) => b.score - a.score);
    status.textContent = matches.length ? say(`找到 ${matches.length} 篇文档`, `${matches.length} pages found`) : say("没有匹配的文档，试试更短的关键词", "No pages found. Try a shorter search.");
    for (const { entry } of matches.slice(0, 12)) {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = `../${entry.id}/`;
      const group = document.createElement("span"); group.className = "result-group"; group.textContent = entry.group;
      const title = document.createElement("strong"); highlight(title, entry.title, terms);
      const description = document.createElement("p");
      const match = Math.max(0, normalize(entry.text).indexOf(terms[0]) - 32);
      const showSummary = terms.some(term => normalize(`${entry.title} ${entry.description}`).includes(term));
      const excerpt = showSummary ? entry.description : `${match ? "…" : ""}${entry.text.slice(match, match + 130)}${entry.text.length > match + 130 ? "…" : ""}`;
      highlight(description, excerpt, terms);
      link.append(group, title, description); item.append(link); results.append(item);
    }
  } catch {
    if (version === searchVersion) status.textContent = say("搜索暂时无法加载。可通过目录阅读，或重新输入关键词重试。", "Search could not load. Browse the menu or type again to retry.");
  }
}
searchInput.addEventListener("input", () => { clearTimeout(timer); searchVersion++; timer = setTimeout(search, 100); });
searchInput.addEventListener("keydown", event => {
  if (event.key === "ArrowDown") { event.preventDefault(); results.querySelector("a")?.focus(); }
  if (event.key === "Enter") { event.preventDefault(); results.querySelector("a")?.click(); }
});
results.addEventListener("keydown", event => {
  if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
  event.preventDefault();
  const links = [...results.querySelectorAll("a")];
  const next = links.indexOf(document.activeElement) + (event.key === "ArrowDown" ? 1 : -1);
  if (next < 0) searchInput.focus(); else links[Math.min(next, links.length - 1)]?.focus();
});

for (const pre of document.querySelectorAll(".doc-prose pre")) {
  const code = pre.querySelector("code");
  if (!code) continue;
  const button = document.createElement("button");
  button.type = "button"; button.className = "copy-code"; button.textContent = say("复制", "Copy");
  button.setAttribute("aria-label", say("复制代码", "Copy code"));
  button.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(code.textContent); button.textContent = say("已复制", "Copied"); }
    catch { button.textContent = say("请选中文本复制", "Select text to copy"); }
    setTimeout(() => { button.textContent = say("复制", "Copy"); }, 1800);
  });
  pre.append(button);
}

const active = document.querySelector(".docs-sidebar [aria-current='page']");
if (active) {
  const nav = document.querySelector(".docs-sidebar > nav");
  nav.scrollTop = Math.max(0, active.offsetTop - nav.clientHeight * .35);
}
const toc = [...document.querySelectorAll(".docs-toc nav a")];
const headings = [...document.querySelectorAll(".doc-prose h2,.doc-prose h3")];
const observer = new IntersectionObserver(entries => {
  for (const entry of entries) if (entry.isIntersecting) {
    for (const link of toc) {
      if (link.hash === `#${entry.target.id}`) link.setAttribute("aria-current", "location"); else link.removeAttribute("aria-current");
    }
  }
}, { rootMargin: "-15% 0px -65% 0px" });
for (const heading of headings) observer.observe(heading);
