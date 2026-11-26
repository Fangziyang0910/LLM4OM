import { copy } from "./translations.js";
import { solveExample } from "./examples.mjs";

let language = document.documentElement.lang === "en" ? "en" : "zh";
let kind = "pareto";
let conditions = { cutting: 8, minimumB: 0, change: false, paretoIndex: 5 };
let view = "plan";
let result = null;
let progress = 1;
let playing = false;
let paused = false;
let elapsed = 0;
let previousFrame = 0;
let frame;
const duration = 3600;
const motionPreference = matchMedia("(prefers-reduced-motion: reduce)");
const studio = document.querySelector("#studio");
const $ = selector => document.querySelector(selector);
const t = (key, values = {}) => {
  const pair = copy[key];
  if (!pair) return key;
  return pair[language === "en" ? 1 : 0].replace(/\{(\w+)\}/g, (match, name) => values[name] ?? match);
};

function workbenchUrl() {
  const host = location.hostname;
  if (!host || host.endsWith("github.io")) return null;
  if (location.port === "8831" || host === "127.0.0.1" || host === "localhost" || /^\d+\.\d+\.\d+\.\d+$/.test(host)) {
    return `${location.protocol}//${host}:8767/`;
  }
  return null;
}

function syncWorkbenchLinks() {
  const live = workbenchUrl();
  for (const link of document.querySelectorAll(".workbench-link")) {
    const label = link.querySelector(".workbench-label");
    if (label) label.textContent = live ? t("openWorkbench") : t(label.dataset.i18n);
    if (live) {
      link.href = live;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    } else {
      const slug = link.dataset.docsFallback || "quickstart";
      link.href = `docs/${language}/${slug}/`;
      link.removeAttribute("target");
      link.removeAttribute("rel");
    }
  }
}

function question() {
  let text = t(`${kind}Question`);
  if (kind === "production" && conditions.cutting !== 8) text += `\n${t("productionAdjustment", { cutting: conditions.cutting })}`;
  if (kind === "production" && conditions.minimumB) text += `\n${t("productionMinimum", { minimum: conditions.minimumB })}`;
  if ((kind === "shifts" || kind === "delivery") && conditions.change) text += `\n${t(`${kind}Change`)}`;
  return text;
}

function updatePlayback() {
  const key = playing ? "pause" : paused ? "resume" : progress === 1 ? "replay" : "play";
  $("#play-text").textContent = t(key);
  $("#play-demo").setAttribute("aria-label", t(key));
  $("#play-icon path").setAttribute("d", playing ? "M5 4h4v12H5Zm7 0h4v12h-4Z" : "M7 4 16 10 7 16Z");
  $("#skip-demo").hidden = progress === 1;
}

function renderTimeline() {
  const phase = progress < 0.34 ? "input" : progress < 0.6 ? "model" : progress < 0.82 ? "solve" : "complete";
  studio.dataset.phase = phase;
  studio.setAttribute("aria-busy", String(progress < 1));
  const text = question();
  $("#demo-question").textContent = text.slice(0, Math.max(1, Math.ceil(text.length * Math.min(progress / 0.34, 1))));
  const step = phase === "input" ? 0 : phase === "model" ? 1 : phase === "solve" ? 2 : 3;
  for (const [index, node] of [...document.querySelectorAll("[data-stage]")].entries()) {
    node.classList.toggle("is-current", index === step);
    node.classList.toggle("is-done", index < step);
    node.querySelector("i").textContent = index < step ? "✓" : String(index + 1);
  }
  $("#playback-progress").style.width = `${progress * 100}%`;
}

function tick(now) {
  if (!playing) return;
  if (previousFrame) elapsed += now - previousFrame;
  previousFrame = now;
  progress = Math.min(1, elapsed / duration);
  renderTimeline();
  if (progress === 1) {
    playing = false;
    paused = false;
    updatePlayback();
  } else {
    frame = requestAnimationFrame(tick);
  }
}

function play(resume = false) {
  if (motionPreference.matches) { complete(); return; }
  cancelAnimationFrame(frame);
  if (!resume) { elapsed = 0; progress = 0; }
  previousFrame = 0;
  playing = true;
  paused = false;
  renderTimeline();
  updatePlayback();
  frame = requestAnimationFrame(tick);
}

function pause() {
  cancelAnimationFrame(frame);
  playing = false;
  paused = progress < 1;
  previousFrame = 0;
  updatePlayback();
}

function complete() {
  cancelAnimationFrame(frame);
  playing = false;
  paused = false;
  progress = 1;
  elapsed = duration;
  previousFrame = 0;
  renderTimeline();
  updatePlayback();
}

function selectTabs(selector, selected) {
  for (const button of document.querySelectorAll(selector)) {
    const current = button === selected;
    button.setAttribute("aria-selected", String(current));
    button.tabIndex = current ? 0 : -1;
  }
}

function renderPareto(solved) {
  const { front, index, point } = solved;
  const tagText = point.tag === "knee" ? t("paretoKneeTag")
    : point.tag === "cost" ? t("paretoCostTag")
      : point.tag === "risk" ? t("paretoRiskTag")
        : t("paretoCustomTag");

  $("#pareto-cost").textContent = point.cost.toFixed(1);
  $("#pareto-risk").textContent = point.risk.toFixed(2);
  $("#pareto-point-label").textContent = `#${point.id} · ${tagText}`;
  $("#pareto-slider").value = String(index);
  $("#demo-comparison").textContent = tagText;
  $("#demo-comparison").classList.toggle("is-changed", index !== 5);
  $("#result-description").textContent = t("paretoDesc", {
    id: point.id, tag: tagText, cost: point.cost.toFixed(1), risk: point.risk.toFixed(2),
  });

  // Render crisp interactive SVG scatter plot
  const svg = $("#pareto-svg");
  const W = 460, H = 156, padL = 44, padR = 16, padT = 16, padB = 28;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const minC = 270, maxC = 302, minR = 12, maxR = 19;
  const sx = c => padL + ((c - minC) / (maxC - minC)) * plotW;
  const sy = r => padT + plotH - ((r - minR) / (maxR - minR)) * plotH;

  const linePath = front.map((p, i) => `${i === 0 ? "M" : "L"}${sx(p.cost).toFixed(1)},${sy(p.risk).toFixed(1)}`).join(" ");
  const grid = [12, 15.5, 19].map(r => {
    const y = sy(r).toFixed(1);
    return `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="currentColor" stroke-opacity="0.1" stroke-dasharray="3 3"/>` +
      `<text x="${padL - 7}" y="${Number(y) + 3}" text-anchor="end" font-size="10" fill="var(--muted)" font-family="var(--mono)">${r}</text>`;
  }).join("");
  const xTicks = [272, 286, 300].map(c => {
    const x = sx(c).toFixed(1);
    return `<text x="${x}" y="${H - 8}" text-anchor="middle" font-size="10" fill="var(--muted)" font-family="var(--mono)">${c}</text>`;
  }).join("");
  const dots = front.map((p, i) => {
    const cx = sx(p.cost).toFixed(1), cy = sy(p.risk).toFixed(1);
    const active = i === index;
    const knee = p.tag === "knee";
    return `<g class="pareto-dot" data-pidx="${i}" style="cursor:pointer">` +
      `<circle cx="${cx}" cy="${cy}" r="11" fill="transparent"/>` +
      (active ? `<circle cx="${cx}" cy="${cy}" r="10" fill="var(--brand)" fill-opacity="0.18"/><circle cx="${cx}" cy="${cy}" r="6.5" fill="none" stroke="var(--brand)" stroke-width="2"/>` : "") +
      `<circle cx="${cx}" cy="${cy}" r="${active ? 4.4 : knee ? 4.2 : 3.5}" fill="${active || knee ? "var(--brand)" : "var(--text-secondary)"}" fill-opacity="${active ? 1 : knee ? 0.85 : 0.55}"/>` +
      `</g>`;
  }).join("");

  svg.innerHTML = `${grid}${xTicks}<path d="${linePath}" fill="none" stroke="var(--brand)" stroke-opacity="0.35" stroke-width="1.8"/>${dots}`;
  svg.querySelectorAll(".pareto-dot").forEach(el => {
    el.addEventListener("click", () => {
      conditions.paretoIndex = Number(el.dataset.pidx);
      renderCase();
    });
  });

  // Render 4 GPU cluster load bars
  $("#cluster-bars").innerHTML = point.loads.map((load, idx) => {
    const cap = point.caps[idx];
    const pct = Math.min(100, Math.round((load / cap) * 100));
    return `<div class="cluster-row">
      <div class="cluster-meta"><span>${t("paretoCluster", { n: idx })}</span><span>${load}/${cap} (${pct}%)</span></div>
      <div class="cluster-track"><div class="cluster-fill" style="width:${pct}%"></div></div>
    </div>`;
  }).join("");
}

function renderDelivery(destinations) {
  const costs = [[4, 8, 6], [7, 3, 9], [5, 6, 2]];
  const left = [[92, 42], [92, 110], [92, 178]];
  const right = [[508, 42], [508, 110], [508, 178]];
  const path = (a, b) => `M${a[0]} ${a[1]} C250 ${a[1]} 350 ${b[1]} ${b[0]} ${b[1]}`;
  $("#route-background").innerHTML = left.flatMap((a, i) => right.map((b, j) => {
    const blocked = conditions.change && i === 1 && j === 1;
    return `<path class="route-background" d="${path(a, b)}"${blocked ? ' stroke-dasharray="4 5" opacity="0.3"' : ""}/>`;
  })).join("");
  $("#route-active").innerHTML = destinations.map((dst, src) => `<path class="route-active" d="${path(left[src], right[dst])}"/>`).join("");
  $("#route-nodes").innerHTML =
    left.map(([x, y], i) => `<circle cx="${x}" cy="${y}" r="22"/><text x="${x}" y="${y}">W${i + 1}</text>`).join("") +
    right.map(([x, y], i) => `<circle class="destination" cx="${x}" cy="${y}" r="22"/><text x="${x}" y="${y}">S${i + 1}</text>`).join("");
  const routeList = destinations.map((dst, src) => `W${src + 1}→S${dst + 1} (¥${costs[src][dst]})`);
  $("#route-summary").innerHTML = routeList.map(item => `<span>${item}</span>`).join("");
  return routeList.join(" · ");
}

function renderCase() {
  result = solveExample(kind, conditions);
  const isPareto = kind === "pareto";
  const isProd = kind === "production";
  const isShifts = kind === "shifts";
  const isDelivery = kind === "delivery";

  $("#demo-engine").textContent = t(`${kind}Engine`);
  $("#demo-file").textContent = t(`${kind}File`);
  $("#plan-title").textContent = t(`${kind}Title`);
  $("#metric-label").textContent = t(`${kind}Metric`);
  $("#metric-currency").hidden = isPareto || !result;

  $("#pareto-plot").hidden = !isPareto;
  $("#production-plot").hidden = !isProd || !result;
  $("#shifts-plot").hidden = !isShifts;
  $("#delivery-plot").hidden = !isDelivery;
  $("#conflict-message").hidden = !!result;
  $("#download-plan").disabled = !result;

  // Follow-up buttons
  const condBtn = $("#change-condition");
  const secBtn = $("#secondary-condition");
  const resetBtn = $("#reset-condition");

  if (isPareto) {
    $("#condition-label").textContent = t("paretoBtnCost");
    secBtn.hidden = false;
    secBtn.textContent = t("paretoBtnRisk");
    resetBtn.hidden = conditions.paretoIndex === 5;
    $("#demo-objective").textContent = t("paretoCount");
    $("#demo-status").textContent = t("paretoStatus");
    $("#demo-status").className = "status-badge";
    renderPareto(result);
  } else if (isProd) {
    $("#condition-label").textContent = t("productionChange");
    secBtn.hidden = false;
    secBtn.textContent = t("productionConflict");
    resetBtn.hidden = conditions.cutting === 8 && conditions.minimumB === 0;
    $("#capacity-value").textContent = t("hours", { n: conditions.cutting });
    $("#cutting-capacity").value = String(conditions.cutting);
    if (!result) {
      $("#demo-objective").textContent = "—";
      $("#demo-status").textContent = t("infeasible");
      $("#demo-status").className = "status-badge is-infeasible";
      $("#demo-comparison").textContent = t("infeasible");
      $("#demo-comparison").className = "comparison";
      $("#result-description").textContent = t("conflictExplanation");
    } else {
      const [a, b] = result.quantities;
      $("#demo-objective").textContent = String(result.total);
      $("#demo-status").textContent = t("optimal");
      $("#demo-status").className = "status-badge";
      const diff = result.total - 13;
      $("#demo-comparison").textContent = diff === 0 ? (conditions.cutting === 8 && !conditions.minimumB ? t("baseline") : t("unchanged")) : t("changedDelta", { delta: `${diff > 0 ? "+" : ""}¥${diff}` });
      $("#demo-comparison").classList.toggle("is-changed", diff !== 0);
      $("#quantity-a").textContent = t("units", { n: a });
      $("#quantity-b").textContent = t("units", { n: b });
      $("#bar-a").style.width = `${(a / 6) * 100}%`;
      $("#bar-b").style.width = `${(b / 6) * 100}%`;
      $("#result-description").textContent = t("productionResult", { a, b, total: result.total });
    }
  } else if (isShifts) {
    $("#condition-label").textContent = t("shiftsChange");
    secBtn.hidden = true;
    resetBtn.hidden = !conditions.change;
    $("#demo-objective").textContent = String(result.total);
    $("#demo-status").textContent = t("optimal");
    $("#demo-status").className = "status-badge";
    const diff = result.total - 6;
    $("#demo-comparison").textContent = conditions.change ? t("changedDelta", { delta: `+¥${diff}` }) : t("baseline");
    $("#demo-comparison").classList.toggle("is-changed", conditions.change);
    const mon = [], tue = [];
    result.days.forEach((day, idx) => {
      const card = document.querySelector(`.person[data-person="${idx}"]`);
      const name = t(`person${idx}`);
      if (day === 0) { mon.push(name); card.style.gridColumn = "1"; card.style.gridRow = String(mon.length + 1); }
      else { tue.push(name); card.style.gridColumn = "2"; card.style.gridRow = String(tue.length + 1); }
    });
    $("#result-description").textContent = t("shiftsResult", { mon: mon.join("、"), tue: tue.join("、"), total: result.total });
  } else if (isDelivery) {
    $("#condition-label").textContent = t("deliveryChange");
    secBtn.hidden = true;
    resetBtn.hidden = !conditions.change;
    $("#demo-objective").textContent = String(result.total);
    $("#demo-status").textContent = t("optimal");
    $("#demo-status").className = "status-badge";
    const diff = result.total - 9;
    $("#demo-comparison").textContent = conditions.change ? t("changedDelta", { delta: `+¥${diff}` }) : t("baseline");
    $("#demo-comparison").classList.toggle("is-changed", conditions.change);
    const summary = renderDelivery(result.destinations);
    $("#result-description").textContent = t("deliveryResult", { routes: summary, total: result.total });
  }

  // Math Model tab
  $("#model-intro").textContent = t(`${kind}ModelIntro`);
  if (isProd) {
    const minLine = conditions.minimumB ? t("productionMinConstraint", { minimum: conditions.minimumB }) : "";
    $("#example-model").textContent = t("productionModelCode", { cutting: conditions.cutting, minLine });
  } else if (isShifts || isDelivery) {
    $("#example-model").textContent = t(`${kind}ModelCode`, { extra: conditions.change ? t(`${kind}Extra`) : "" });
  } else {
    $("#example-model").textContent = t("paretoModelCode");
  }
  $("#model-data").textContent = t(`${kind}ModelData`);
  renderTimeline();
}

function setView(next) {
  view = next;
  selectTabs(".plan-tabs button", document.querySelector(`.plan-tabs button[data-view="${next}"]`));
  $("#plan-content").hidden = next !== "plan";
  $("#model-content").hidden = next !== "model";
}

/** Real workbench screenshots follow both the page language and the theme. */
function syncShots() {
  const dark = document.documentElement.dataset.theme === "dark";
  for (const img of document.querySelectorAll("img[data-shot]")) {
    img.dataset.lightSrc = `assets/screens/${language}/${img.dataset.shot}-light.webp`;
    img.dataset.darkSrc = `assets/screens/${language}/${img.dataset.shot}-dark.webp`;
    const next = dark ? img.dataset.darkSrc : img.dataset.lightSrc;
    if (img.getAttribute("src") !== next) img.src = next;
  }
}

function applyLanguage() {
  document.documentElement.lang = language === "en" ? "en" : "zh-CN";
  document.title = t("pageTitle");
  const desc = document.querySelector('meta[name="description"]');
  if (desc) desc.content = t("pageDescription");
  $("#language-name").textContent = language === "en" ? "中文" : "EN";
  $("#language-toggle").setAttribute("aria-label", language === "en" ? "切换到中文" : "Switch to English");
  for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  for (const el of document.querySelectorAll("[data-i18n-label]")) el.setAttribute("aria-label", t(el.dataset.i18nLabel));
  for (const el of document.querySelectorAll("[data-i18n-alt]")) el.alt = t(el.dataset.i18nAlt);
  for (const link of document.querySelectorAll("a[data-docs]")) link.href = `docs/${language}/${link.dataset.docs}/`;
  syncWorkbenchLinks();
  syncShots();
  updatePlayback();
  renderCase();
}

function downloadCsv() {
  if (!result) return;
  let csv = "";
  if (kind === "pareto") {
    csv = "solution,tag,total_electricity_cost,total_fault_risk,cluster_0,cluster_1,cluster_2,cluster_3\n" +
      result.front.map(p => `${p.id},${p.tag || ""},${p.cost},${p.risk},${p.loads.join(",")}`).join("\n");
  } else if (kind === "production") {
    csv = `product,quantity\nA,${result.quantities[0]}\nB,${result.quantities[1]}\ntotal_profit,${result.total}\n`;
  } else if (kind === "shifts") {
    csv = "employee,day\n" + result.days.map((d, i) => `${t(`person${i}`)},${d === 0 ? t("monday") : t("tuesday")}`).join("\n");
  } else {
    csv = "warehouse,store\n" + result.destinations.map((dst, src) => `W${src + 1},S${dst + 1}`).join("\n") + `\ntotal_cost_cny,${result.total}\n`;
  }
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `gios-${kind}-solution.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// Keep the roving tab stop reachable with the standard tab-list keys.
for (const list of document.querySelectorAll('[role="tablist"]')) {
  list.addEventListener("keydown", event => {
    const buttons = [...list.querySelectorAll('[role="tab"]')];
    const index = buttons.indexOf(event.target);
    if (index < 0) return;
    const next = { Home: 0, End: buttons.length - 1,
      ArrowLeft: (index + buttons.length - 1) % buttons.length, ArrowRight: (index + 1) % buttons.length }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    buttons[next].focus();
    buttons[next].click();
  });
}

// Event bindings
document.querySelectorAll(".case-tabs button").forEach(btn => {
  btn.addEventListener("click", () => {
    kind = btn.dataset.case;
    conditions = { cutting: 8, minimumB: 0, change: false, paretoIndex: 5 };
    selectTabs(".case-tabs button", btn);
    setView("plan");
    complete();
    renderCase();
  });
});

document.querySelectorAll(".plan-tabs button").forEach(btn => {
  btn.addEventListener("click", () => setView(btn.dataset.view));
});
$("#demo-data").addEventListener("click", () => setView("model"));

$("#pareto-slider").addEventListener("input", event => {
  conditions.paretoIndex = Number(event.target.value);
  renderCase();
});
$("#cutting-capacity").addEventListener("input", event => {
  conditions.cutting = Number(event.target.value);
  conditions.minimumB = 0;
  renderCase();
});

$("#change-condition").addEventListener("click", () => {
  if (kind === "pareto") conditions.paretoIndex = 0;
  else if (kind === "production") { conditions.cutting = 10; conditions.minimumB = 0; }
  else conditions.change = true;
  setView("plan");
  renderCase();
});
$("#secondary-condition").addEventListener("click", () => {
  if (kind === "pareto") conditions.paretoIndex = 8;
  else if (kind === "production") { conditions.cutting = 8; conditions.minimumB = 5; }
  setView("plan");
  renderCase();
});
$("#reset-condition").addEventListener("click", () => {
  conditions = { cutting: 8, minimumB: 0, change: false, paretoIndex: 5 };
  renderCase();
});
$("#resolve-conflict").addEventListener("click", () => {
  conditions = { cutting: 8, minimumB: 0, change: false, paretoIndex: 5 };
  renderCase();
});

$("#play-demo").addEventListener("click", () => {
  if (playing) pause();
  else play(paused);
});
$("#skip-demo").addEventListener("click", complete);
$("#download-plan").addEventListener("click", downloadCsv);

const dialog = $("#photo-dialog");
document.querySelectorAll("[data-zoom-shot]").forEach(btn => {
  btn.addEventListener("click", () => {
    const srcImg = btn.closest("figure")?.querySelector("img");
    if (!srcImg) return;
    $("#dialog-image").src = srcImg.src;
    $("#dialog-image").alt = srcImg.alt;
    dialog.showModal();
  });
});
$("#close-photo").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });

$("#language-toggle").addEventListener("click", () => {
  language = language === "en" ? "zh" : "en";
  try { localStorage.setItem("llm4om-site-language", language); } catch {}
  applyLanguage();
});

document.addEventListener("llm4om:themechange", syncShots);

// Installation snippets: tabs with arrow-key focus, and a copy button for the visible one.
const codeTabs = [...document.querySelectorAll(".code-tabs [role=tab]")];
function selectCode(tab) {
  for (const item of codeTabs) {
    const selected = item === tab;
    item.setAttribute("aria-selected", String(selected));
    item.tabIndex = selected ? 0 : -1;
    document.getElementById(item.getAttribute("aria-controls")).hidden = !selected;
  }
}
codeTabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectCode(tab));
  tab.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    const next = codeTabs[(index + (event.key === "ArrowRight" ? 1 : codeTabs.length - 1)) % codeTabs.length];
    selectCode(next);
    next.focus();
  });
});
$("#copy-code")?.addEventListener("click", async event => {
  const panel = document.querySelector(".code-window pre:not([hidden])");
  // Comments are instructions for the reader, not commands to paste.
  const text = panel.innerText.split("\n").filter(line => !line.trim().startsWith("#")).join("\n").trim();
  const button = event.currentTarget;
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = t("copied");
    setTimeout(() => { button.textContent = t("copy"); }, 1600);
  } catch {}
});

// Smooth scroll reveal (pre-reveals ahead of viewport + passive scroll fallback)
if (!motionPreference.matches && "IntersectionObserver" in window) {
  document.documentElement.classList.add("motion-ready");
  const reveals = [...document.querySelectorAll(".reveal")];
  const show = el => el.classList.add("is-visible");
  const revealInView = () => {
    const cutoff = window.innerHeight + 160;
    for (const el of reveals) {
      if (!el.classList.contains("is-visible") && el.getBoundingClientRect().top <= cutoff) {
        show(el);
      }
    }
  };
  const io = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        show(entry.target);
        io.unobserve(entry.target);
      }
    }
  }, { threshold: 0.01, rootMargin: "160px 0px" });
  reveals.forEach(el => io.observe(el));
  window.addEventListener("scroll", revealInView, { passive: true });
  window.addEventListener("resize", revealInView, { passive: true });
  window.addEventListener("hashchange", () => setTimeout(revealInView, 50));
  revealInView();
}

applyLanguage();
