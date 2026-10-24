(() => {
  const root = document.documentElement;
  const system = matchMedia("(prefers-color-scheme: dark)");
  const choices = ["light", "dark", "system"];
  let preference = "system", control;
  try { const saved = localStorage.getItem("llm4om-site-theme"); if (choices.includes(saved)) preference = saved; } catch {}

  function labels() {
    if (!control) return;
    const english = root.lang === "en";
    const title = english ? "Appearance" : "外观";
    control.querySelector("summary").setAttribute("aria-label", title);
    control.querySelector("summary").title = title;
    control.querySelector(".theme-menu").setAttribute("aria-label", title);
    control.querySelectorAll("[data-theme-choice]").forEach((button, i) => {
      button.textContent = (english ? ["Light", "Dark", "System"] : ["浅色", "深色", "跟随系统"])[i];
      button.setAttribute("aria-pressed", String(button.dataset.themeChoice === preference));
    });
  }

  function apply() {
    const theme = preference === "system" ? (system.matches ? "dark" : "light") : preference;
    const light = theme === "light";
    root.dataset.theme = theme;
    root.dataset.themePreference = preference;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = light ? "#faf9fc" : "#101014";
    labels();
    for (const image of document.querySelectorAll("img[data-light-src]")) image.src = light ? image.dataset.lightSrc : image.dataset.darkSrc;
    for (const figure of document.querySelectorAll(".doc-diagram[data-light-src]")) figure.dataset.src = light ? figure.dataset.lightSrc : figure.dataset.darkSrc;
    for (const link of document.querySelectorAll("a[data-light-href]")) link.href = light ? link.dataset.lightHref : link.dataset.darkHref;
    for (const recording of document.querySelectorAll(".doc-recording")) {
      const video = recording.querySelector("video"), source = video.querySelector("source"), track = video.querySelector("track");
      const target = light ? video.dataset.lightSrc : video.dataset.darkSrc;
      if (!target || source.getAttribute("src") === target) continue;
      const time = video.currentTime, resume = !video.paused, loaded = video.readyState >= 1, preload = video.preload;
      source.src = target;
      video.poster = light ? video.dataset.lightPoster : video.dataset.darkPoster;
      track.src = light ? track.dataset.lightSrc : track.dataset.darkSrc;
      recording.querySelectorAll("[data-seek]").forEach(button => { button.dataset.seek = light ? button.dataset.lightSeek : button.dataset.darkSeek; });
      recording.querySelector(".recording-status").hidden = true;
      if (loaded) {
        video.preload = "metadata";
        video.addEventListener("loadedmetadata", () => {
          video.currentTime = Math.min(time, video.duration);
          video.preload = preload;
          if (resume) video.play().catch(() => {});
        }, { once: true });
      }
      video.load();
    }
    document.dispatchEvent(new Event("llm4om:themechange"));
  }

  apply();
  system.addEventListener("change", () => { if (preference === "system") apply(); });
  addEventListener("storage", event => {
    if (event.key === "llm4om-site-theme") { preference = choices.includes(event.newValue) ? event.newValue : "system"; apply(); }
  });
  document.addEventListener("DOMContentLoaded", () => {
    control = document.createElement("details");
    control.className = "theme-switcher";
    control.innerHTML = `<summary><svg class="theme-sun" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/></svg><svg class="theme-moon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M20.6 14A9 9 0 0 1 10 3.4 9 9 0 1 0 20.6 14Z"/></svg></summary><div class="theme-menu" role="group">${choices.map(value => `<button type="button" data-theme-choice="${value}"></button>`).join("")}</div>`;
    document.querySelector(".header-actions,.docs-header-links")?.prepend(control);
    control.addEventListener("click", event => {
      const button = event.target.closest("[data-theme-choice]");
      if (!button) return;
      preference = button.dataset.themeChoice;
      try { localStorage.setItem("llm4om-site-theme", preference); } catch {}
      apply(); control.open = false; control.querySelector("summary").focus();
    });
    document.addEventListener("click", event => { if (!control.contains(event.target)) control.open = false; });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && control.open) { control.open = false; control.querySelector("summary").focus(); }
    });
    control.addEventListener("focusout", event => { if (event.relatedTarget && !control.contains(event.relatedTarget)) control.open = false; });
    new MutationObserver(labels).observe(root, { attributes: true, attributeFilter: ["lang"] });
    apply();
  });
})();
