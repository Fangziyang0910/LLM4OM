import { copy } from "./translations.js";
import { solveExample } from "./examples.mjs";

let language = document.documentElement.lang === "en" ? "en" : "zh";
let kind = "production";
let conditions = { cutting: 8, minimumB: 0, change: false };
let feature = "plan";
let view = "plan";
let result;
let progress = 1;
let playing = false;
let paused = false;
let elapsed = 0;
let previousFrame = 0;
let frame;
let autoplayStarted = false;
const duration = 4600;
const motionPreference = matchMedia("(prefers-reduced-motion: reduce)");
const studio = document.querySelector("#studio");
const $ = selector => document.querySelector(selector);
const t = (key, values = {}) => {
  if (!copy[key]) throw new Error(`Missing website text: ${key}`);
  return copy[key][language === "en" ? 1 : 0].replace(/\{(\w+)\}/g, (match, name) => values[name] ?? match);
};

function question() {
  let text = t(`${kind}Question`);
  if (kind === "production" && conditions.cutting !== 8) text += `\n${t("productionAdjustment", { cutting: conditions.cutting })}`;
  if (kind === "production" && conditions.minimumB) text += `\n${t("productionMinimum", { minimum: conditions.minimumB })}`;
  if (kind !== "production" && conditions.change) text += `\n${t(`${kind}Change`)}`;
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
  const phase = progress < .36 ? "input" : progress < .59 ? "model" : progress < .78 ? "solve" : "complete";
  const previousPhase = studio.dataset.phase;
  studio.dataset.phase = phase;
  studio.setAttribute("aria-busy", String(progress < 1));
  const text = question();
  $("#demo-question").textContent = text.slice(0, Math.max(1, Math.ceil(text.length * Math.min(progress / .36, 1))));
  $("#demo-question").setAttribute("aria-label", text);
  const step = phase === "input" ? 0 : phase === "model" ? 1 : phase === "solve" ? 2 : 3;
  for (const [index, node] of [...document.querySelectorAll("[data-stage]")].entries()) {
    node.classList.toggle("is-current", index === step);
    node.classList.toggle("is-done", index < step);
    node.querySelector("i").textContent = index < step ? "✓" : String(index + 1);
  }
  $("#playback-progress").style.width = `${progress * 100}%`;
  $("#demo-objective").textContent = phase === "complete" && result ? result.total : "—";
  if (kind === "production" && result) {
    $("#bar-a").style.width = `${phase === "complete" ? result.quantities[0] / 6 * 100 : 0}%`;
    $("#bar-b").style.width = `${phase === "complete" ? result.quantities[1] / 6 * 100 : 0}%`;
  }
  if (phase === "complete" && previousPhase !== "complete" && result && !motionPreference.matches) {
    $("#plan-content").animate([{ opacity: .3, transform: "translateY(18px) scale(.985)" }, { opacity: 1, transform: "translateY(0) scale(1)" }], { duration: 650, easing: "cubic-bezier(.16,1,.3,1)" });
  }
}

function announce() {
  $("#demo-announcement").textContent = result ? `${t(`${kind}Metric`)} ${result.total} ${t("currencyUnit")}. ${$("#result-description").textContent}` : t("conflictExplanation");
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
    announce();
  } else frame = requestAnimationFrame(tick);
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

function play(resume = false) {
  if (motionPreference.matches) { complete(); announce(); return; }
  cancelAnimationFrame(frame);
  if (!resume) { elapsed = 0; progress = 0; }
  previousFrame = 0;
  playing = true;
  paused = false;
  renderTimeline();
  updatePlayback();
  frame = requestAnimationFrame(tick);
}

function selectTabs(selector, selected) {
  for (const button of document.querySelectorAll(selector)) {
    const current = button === selected;
    button.setAttribute("aria-selected", String(current));
    button.tabIndex = current ? 0 : -1;
  }
}

function renderRoutes(animate) {
  const svgNS = "http://www.w3.org/2000/svg";
  const make = (tag, attributes, text) => {
    const node = document.createElementNS(svgNS, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (text) node.textContent = text;
    return node;
  };
  const path = (source, target) => `M105 ${40 + source * 75} C240 ${40 + source * 75},360 ${40 + target * 75},495 ${40 + target * 75}`;
  const background = $("#route-background");
  const active = $("#route-active");
  const nodes = $("#route-nodes");
  background.replaceChildren(); active.replaceChildren(); nodes.replaceChildren();
  for (let source = 0; source < 3; source++) {
    for (let target = 0; target < 3; target++) background.append(make("path", { d: path(source, target), class: "route-background" }));
    const line = make("path", { d: path(source, result.destinations[source]), class: "route-active", pathLength: "1" });
    active.append(line);
    if (animate && !motionPreference.matches) {
      line.style.strokeDasharray = "1";
      line.animate([{ strokeDashoffset: "1" }, { strokeDashoffset: "0" }], { duration: 650, delay: source * 70, easing: "cubic-bezier(.16,1,.3,1)", fill: "both" });
    }
    for (const side of [0, 1]) {
      const x = side ? 515 : 85, y = 40 + source * 75;
      nodes.append(make("circle", { cx: x, cy: y, r: 22, class: side ? "destination" : "source" }));
      nodes.append(make("text", { x, y: y + 1 }, side ? String(source + 1) : "ABC"[source]));
    }
  }
  $("#route-summary").replaceChildren(...result.destinations.map((target, source) => {
    const item = document.createElement("span");
    item.textContent = `${t("warehouse")} ${"ABC"[source]} → ${t("store")} ${target + 1}`;
    return item;
  }));
}

function renderExample(animate = false) {
  const oldPositions = new Map([...document.querySelectorAll("[data-person]")].map(node => [node, node.getBoundingClientRect()]));
  result = solveExample(kind, conditions);
  const baseline = solveExample(kind);
  const changed = kind === "production" ? conditions.cutting !== 8 || conditions.minimumB !== 0 : conditions.change;
  selectTabs("[data-case]", $(`#case-${kind}`));
  $("#demo-body").setAttribute("aria-labelledby", `case-${kind}`);
  $("#plan-title").textContent = t(`${kind}Title`);
  $("#metric-label").textContent = t(`${kind}Metric`);
  $("#demo-file").textContent = t(`${kind}File`);
  $("#condition-label").textContent = t(`${kind}Change`);
  $("#change-condition").disabled = kind === "production" ? conditions.cutting === 10 && conditions.minimumB === 0 : conditions.change;
  $("#infeasible-condition").hidden = kind !== "production";
  $("#reset-condition").hidden = !changed;
  for (const name of ["production", "shifts", "delivery"]) $(`#${name}-plot`).hidden = name !== kind || !result;
  $("#conflict-message").hidden = Boolean(result);
  $("#demo-status").textContent = t(result ? "optimal" : "infeasible");
  $("#demo-status").classList.toggle("is-infeasible", !result);
  $(".currency").hidden = !result;
  $("#demo-comparison").textContent = !result ? "" : changed ? t("comparison", { difference: `${result.total > baseline.total ? "+" : result.total < baseline.total ? "−" : ""}${Math.abs(result.total - baseline.total)}` }) : t("baseline");
  $("#demo-comparison").classList.toggle("is-changed", Boolean(changed && result));
  $("#download-plan").disabled = !result;
  if (kind === "production") {
    $("#cutting-capacity").value = conditions.cutting;
    $("#capacity-value").textContent = `${conditions.cutting} ${t("resourceUnits")}`;
    if (result) {
      $("#quantity-a").textContent = `${result.quantities[0]} ${t("pieces")}`;
      $("#quantity-b").textContent = `${result.quantities[1]} ${t("pieces")}`;
    }
  }
  if (kind === "shifts") {
    const rows = [2, 2];
    for (const node of document.querySelectorAll("[data-person]")) {
      for (const animation of node.getAnimations()) animation.cancel();
      const day = result.days[Number(node.dataset.person)];
      node.style.gridColumn = String(day + 1);
      node.style.gridRow = String(rows[day]++);
      if (animate && !motionPreference.matches) {
        const before = oldPositions.get(node), after = node.getBoundingClientRect();
        if (before.width > 0) node.animate([{ transform: `translate(${before.x - after.x}px,${before.y - after.y}px)` }, { transform: "translate(0,0)" }], { duration: 600, easing: "cubic-bezier(.16,1,.3,1)" });
      }
    }
  }
  if (kind === "delivery") renderRoutes(animate);
  const quantities = result?.quantities ?? [0, 0];
  $("#result-description").textContent = result ? t(`${kind}Result`, { a: quantities[0], b: quantities[1], cutting: conditions.cutting, cuttingUsed: 2 * quantities[0] + quantities[1], finishingUsed: quantities[0] + 2 * quantities[1] }) : t("conflictExplanation");
  $("#model-intro").textContent = t(`${kind}ModelIntro`);
  $("#example-model").textContent = t(`${kind}Model`, {
    cutting: conditions.cutting,
    minimum: conditions.minimumB ? t("minimumB", { minimum: conditions.minimumB }) : "",
    extra: conditions.change ? t(`${kind}Extra`) : "",
  });
  $("#model-data").textContent = t(`${kind}ModelData`);
  renderTimeline();
  updatePlayback();
  if (animate && !motionPreference.matches && result) $("#demo-objective").animate([{ opacity: .3, transform: "translateY(8px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 500, easing: "cubic-bezier(.16,1,.3,1)" });
}

function renderFeature() {
  selectTabs("[data-feature]", $(`#feature-${feature}`));
  $("#feature-panel").setAttribute("aria-labelledby", `feature-${feature}`);
  $("#feature-description").dataset.i18n = `${feature}FeatureDescription`;
  $("#feature-description").textContent = t(`${feature}FeatureDescription`);
  const image = $("#feature-image");
  const source = `assets/screens/${language}/${feature}${document.documentElement.dataset.theme === "light" ? "-light" : ""}.png`;
  const stage = $(".photo-stage");
  image.alt = t(`${feature}Alt`);
  stage.dataset.loading = "true";
  const loaded = () => {
    if (image.getAttribute("src") === source) { stage.style.aspectRatio = `${image.naturalWidth} / ${image.naturalHeight}`; stage.dataset.loading = "false"; }
  };
  image.onload = loaded;
  image.src = source;
  if (image.complete && image.naturalWidth > 0) loaded();
  $("#dialog-image").src = source;
  $("#dialog-image").alt = image.alt;
}

function applyLanguage() {
  complete();
  document.documentElement.lang = language === "en" ? "en" : "zh-CN";
  for (const node of document.querySelectorAll("[data-i18n]")) node.textContent = t(node.dataset.i18n);
  for (const node of document.querySelectorAll("[data-i18n-label]")) node.setAttribute("aria-label", t(node.dataset.i18nLabel));
  for (const node of document.querySelectorAll("[data-docs]")) node.href = `docs/${language}/${node.dataset.docs}/`;
  document.title = t("pageTitle");
  $("meta[name='description']").content = t("pageDescription");
  $("meta[property='og:title']").content = t("pageTitle");
  $("meta[property='og:description']").content = t("pageDescription");
  $("#language-name").textContent = language === "zh" ? "EN" : "中文";
  $("#language-toggle").setAttribute("aria-label", language === "zh" ? "Switch to English" : "切换为中文");
  renderExample();
  renderFeature();
  announce();
}

function bindTabs(selector, select) {
  const buttons = [...document.querySelectorAll(selector)];
  for (const [index, button] of buttons.entries()) {
    button.addEventListener("click", () => select(button));
    button.addEventListener("keydown", event => {
      if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
      select(buttons[next]);
      buttons[next].focus();
    });
  }
}

bindTabs("[data-case]", button => {
  complete(); kind = button.dataset.case; conditions = { cutting: 8, minimumB: 0, change: false }; renderExample(true); autoplayStarted = true; announce();
});
bindTabs("[data-feature]", button => { feature = button.dataset.feature; renderFeature(); });
bindTabs("[data-view]", button => {
  view = button.dataset.view; selectTabs("[data-view]", button);
  $("#plan-content").hidden = view !== "plan"; $("#model-content").hidden = view !== "model";
});
$("#demo-data").addEventListener("click", () => { complete(); $("#view-model").click(); $("#view-model").focus(); });

$("#language-toggle").addEventListener("click", () => {
  language = language === "zh" ? "en" : "zh";
  try { localStorage.setItem("llm4om-site-language", language); } catch { /* The language switch also works without storage. */ }
  const url = new URL(location.href); url.searchParams.set("lang", language); history.replaceState(null, "", url);
  applyLanguage();
});
$("#play-demo").addEventListener("click", () => { autoplayStarted = true; if (playing) pause(); else play(paused); });
$("#skip-demo").addEventListener("click", () => { complete(); announce(); });
$("#change-condition").addEventListener("click", () => {
  complete(); conditions = kind === "production" ? { cutting: 10, minimumB: 0, change: false } : { ...conditions, change: true }; renderExample(true); announce();
});
$("#infeasible-condition").addEventListener("click", () => { complete(); conditions.minimumB = 5; renderExample(true); announce(); });
function reset() { complete(); conditions = { cutting: 8, minimumB: 0, change: false }; renderExample(true); announce(); }
$("#reset-condition").addEventListener("click", reset);
$("#resolve-conflict").addEventListener("click", reset);
$("#cutting-capacity").addEventListener("input", event => { complete(); conditions.cutting = Number(event.target.value); conditions.minimumB = 0; renderExample(); announce(); });

$("#download-plan").addEventListener("click", () => {
  if (!result) return;
  let rows = [[t(`${kind}Title`), ""], [t(`${kind}Metric`) + " (CNY)", result.total]];
  if (kind === "production") rows.push([t("productA"), result.quantities[0]], [t("productB"), result.quantities[1]], [t("cuttingCapacity"), conditions.cutting]);
  if (kind === "shifts") rows.push(...result.days.map((day, person) => [t(`person${person}`), t(day ? "tuesday" : "monday")]));
  if (kind === "delivery") rows.push(...result.destinations.map((store, warehouse) => [`${t("warehouse")} ${"ABC"[warehouse]}`, `${t("store")} ${store + 1}`]));
  const csv = "\uFEFF" + rows.map(row => row.map(cell => `"${String(cell).replaceAll('"', '""')}"`).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = `llm4om-${kind}-${language}.csv`; document.body.append(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

const dialog = $("#photo-dialog");
document.addEventListener("llm4om:themechange", renderFeature);
$("#enlarge-photo").addEventListener("click", () => dialog.showModal());
$("#close-photo").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });
document.addEventListener("visibilitychange", () => { if (document.hidden && playing) pause(); });
motionPreference.addEventListener("change", () => { if (motionPreference.matches) { complete(); document.body.classList.remove("motion-ready"); } });

applyLanguage();
if ("IntersectionObserver" in window) {
  if (!motionPreference.matches) {
    const reveals = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) { entry.target.classList.add("is-visible"); reveals.unobserve(entry.target); }
    }, { threshold: .06 });
    document.body.classList.add("motion-ready");
    for (const node of document.querySelectorAll(".reveal")) reveals.observe(node);
  }
  new IntersectionObserver(entries => {
    if (entries[0].isIntersecting && !autoplayStarted && !motionPreference.matches) { autoplayStarted = true; play(); }
    else if (!entries[0].isIntersecting && playing) pause();
  }, { threshold: .2 }).observe(studio);
}
