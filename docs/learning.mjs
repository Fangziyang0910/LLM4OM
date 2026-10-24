import { production, projection, nonconvex, descent } from "./learning-models.mjs";

const english = document.body.dataset.locale === "en";
const t = (zh, en) => english ? en : zh;
const number = value => Number(value.toFixed(3)).toLocaleString(english ? "en-US" : "zh-CN");
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
const pauses = [];
const axis = (x = "A", y = "B") => `<path d="M44 16V280H424" class="chart-axis"/><text x="421" y="306">${x}</text><text x="14" y="24">${y}</text>${[0, 1, 2, 3, 4, 5, 6].map(i => `<text x="${44 + i * 56}" y="300">${i}</text><text x="24" y="${284 - i * 40}">${i}</text>`).join("")}`;
const point = ([a, b]) => `${44 + a * 56},${280 - b * 40}`;
const pulse = element => { if (!reduceMotion.matches) element.animate([{ opacity: .5 }, { opacity: 1 }], { duration: 240 }); };

for (const walkthrough of document.querySelectorAll("[data-walkthrough]")) {
  const panels = [...walkthrough.querySelectorAll(".step-panel")];
  const tabs = [...walkthrough.querySelectorAll("[data-step]")];
  let previous = walkthrough.parentElement.previousElementSibling;
  while (previous && !previous.matches(".doc-diagram")) previous = previous.previousElementSibling;
  const diagram = previous;
  let current = 0, timer;
  const play = walkthrough.querySelector('[data-action="play"]');
  const stop = () => { clearInterval(timer); timer = undefined; play.textContent = t("播放", "Play"); play.setAttribute("aria-pressed", "false"); };
  const show = index => {
    current = index;
    panels.forEach((panel, i) => { panel.hidden = i !== index; });
    tabs.forEach((tab, i) => tab.setAttribute("aria-pressed", String(i === index)));
    walkthrough.querySelector(".step-count").textContent = `${index + 1} / ${panels.length}`;
    walkthrough.querySelector('[data-action="previous"]').disabled = index === 0;
    walkthrough.querySelector('[data-action="next"]').disabled = index === panels.length - 1;
    diagram?.querySelectorAll(".node").forEach(node => node.classList.remove("is-current"));
    for (const id of panels[index].dataset.nodes.split(" ")) diagram?.querySelectorAll(`[id*="-flowchart-${CSS.escape(id)}-"]`).forEach(node => node.classList.add("is-current"));
    pulse(panels[index]);
  };
  walkthrough.dataset.ready = "true";
  walkthrough.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.action === "play" && !timer) {
      if (current === panels.length - 1) show(0);
      play.textContent = t("暂停", "Pause"); play.setAttribute("aria-pressed", "true");
      timer = setInterval(() => { show(current + 1); if (current === panels.length - 1) stop(); }, 4200);
      return;
    }
    stop();
    if (button.dataset.step !== undefined) show(Number(button.dataset.step));
    else if (button.dataset.action === "next") show(Math.min(current + 1, panels.length - 1));
    else if (button.dataset.action === "previous") show(Math.max(0, current - 1));
  });
  pauses.push(stop);
  show(0);
}

for (const demo of document.querySelectorAll("[data-demo]")) {
  const kind = demo.dataset.demo;
  const output = demo.querySelector(".demo-result");
  const chart = demo.querySelector("svg");
  const input = name => demo.querySelector(`[name="${name}"]`);
  demo.dataset.ready = "true";
  if (kind === "production") {
    let result;
    const redraw = () => {
      const cutting = Number(input("cutting").value), minimumB = Number(input("minimumB").value), integer = input("domain").value === "integer";
      result = production({ cutting, minimumB, integer });
      const vertices = production({ cutting, minimumB, integer: false }).points;
      const center = vertices.length ? vertices.reduce((a, p) => [a[0] + p[0] / vertices.length, a[1] + p[1] / vertices.length], [0, 0]) : [0, 0];
      vertices.sort((a, b) => Math.atan2(a[1] - center[1], a[0] - center[0]) - Math.atan2(b[1] - center[1], b[0] - center[0]));
      demo.querySelector('[data-value="cutting"]').textContent = cutting;
      demo.querySelector('[data-model-cutting]').textContent = cutting;
      demo.querySelector('[data-model-minimum]').textContent = minimumB;
      demo.querySelector('[data-model-domain]').textContent = integer ? t("A、B 为非负整数", "A and B are nonnegative integers") : t("A、B 为非负连续量", "A and B are nonnegative continuous quantities");
      chart.innerHTML = axis() + `<polygon class="chart-region" points="${vertices.map(point).join(" ")}"/><path d="M${point([0, cutting])}L${point([cutting / 2, 0])}" class="chart-line"/><path d="M${point([0, 4])}L${point([8, 0])}" class="chart-line secondary"/>` + (integer ? result.points.map(p => `<circle cx="${44 + p[0] * 56}" cy="${280 - p[1] * 40}" r="3" class="chart-point"/>`).join("") : "") + (result.best ? `<circle cx="${44 + result.best[0] * 56}" cy="${280 - result.best[1] * 40}" r="7" class="chart-best"/>` : "");
      const download = demo.querySelector('[data-action="download"]');
      download.disabled = !result.best;
      if (!result.best) {
        output.textContent = t("无可行方案", "No feasible plan");
        demo.querySelector(".demo-explanation").textContent = t("B 至少 5 件需要装配 10 小时，超过可用的 8 小时。", "At least 5 units of B require 10 finishing hours; 8 hours are available.");
      } else {
        const [a, b] = result.best;
        output.textContent = `A = ${number(a)}, B = ${number(b)} · ${t(`利润 ${number(result.objective)} 元`, `Profit CNY ${number(result.objective)}`)}`;
        demo.querySelector(".demo-explanation").textContent = t(`切割使用 ${number(2 * a + b)} / ${cutting} 小时；装配使用 ${number(a + 2 * b)} / 8 小时。${integer ? "小圆点表示可行的整数产量组合。" : "当前按连续产量计算。"}`, `Cutting: ${number(2 * a + b)} / ${cutting} hours. Finishing: ${number(a + 2 * b)} / 8 hours. ${integer ? "Small dots show feasible whole-unit combinations." : "Quantities are currently continuous."}`);
      }
      chart.setAttribute("aria-label", output.textContent);
      pulse(output);
    };
    demo.addEventListener("input", redraw);
    demo.addEventListener("click", event => {
      const action = event.target.closest("button")?.dataset.action;
      if (action === "reset") { input("cutting").value = "8"; input("minimumB").value = "0"; input("domain").value = "integer"; redraw(); }
      if (action === "download" && result.best) {
        const csv = `variable,value\r\nA,${result.best[0]}\r\nB,${result.best[1]}\r\nobjective,${result.objective}\r\n`;
        const url = URL.createObjectURL(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }));
        const link = document.createElement("a"); link.href = url; link.download = "llm4om-teaching-plan.csv"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    });
    redraw();
  } else if (kind === "plans") {
    const log = demo.querySelector(".demo-messages"), current = demo.querySelector("[data-current]"), saved = demo.querySelector("[data-saved-plans]");
    let minimum = 0;
    const plans = new Map([[0, production()]]);
    const label = n => n === 0 ? t("原方案", "Original") : `B ≥ ${n}`;
    const update = () => {
      const result = plans.get(minimum);
      current.textContent = `${label(minimum)} · A = ${result.best[0]}, B = ${result.best[1]} · ${t(`利润 ${result.objective} 元`, `Profit CNY ${result.objective}`)}`;
      for (const [n, p] of plans) {
        let button = saved.querySelector(`[data-plan="${n}"]`);
        if (!button) { button = document.createElement("button"); button.type = "button"; button.dataset.plan = n; saved.append(button); }
        button.textContent = `${label(n)} · ${t(`${p.objective} 元`, `CNY ${p.objective}`)}`;
        button.setAttribute("aria-pressed", String(n === minimum));
      }
    };
    demo.addEventListener("click", event => {
      const button = event.target.closest("button");
      const action = button?.dataset.action;
      let message;
      if (button?.dataset.plan !== undefined) {
        minimum = Number(button.dataset.plan);
        message = t(`已选择 ${label(minimum)}，后续查询和调整以此为基准。`, `Selected ${label(minimum)} for subsequent questions and revisions.`);
      }
      if (action === "reset") { minimum = 0; plans.clear(); plans.set(0, production()); saved.replaceChildren(); log.replaceChildren(); message = t("已恢复原方案：A = 3，B = 2，利润 13 元。", "Original restored: A = 3, B = 2, profit CNY 13."); }
      if (action === "explain") {
        const [a, b] = plans.get(minimum).best;
        message = t(`${label(minimum)}：A = ${a}，B = ${b}。切割使用 ${2 * a + b}/8 小时，装配使用 ${a + 2 * b}/8 小时。`, `${label(minimum)}: A = ${a}, B = ${b}. Cutting: ${2 * a + b}/8 hours. Finishing: ${a + 2 * b}/8 hours.`);
      }
      if (action === "revise") { minimum = 3; plans.set(3, production({ minimumB: 3 })); message = t("将最低产量设为 B ≥ 3 并重算：A = 2，B = 3，利润 12 元。已选为当前讨论方案。", "Set minimum demand to B ≥ 3 and solve: A = 2, B = 3, profit CNY 12. This is now the discussion plan."); }
      if (action === "scenarios") {
        for (const n of [3, 4]) plans.set(n, production({ minimumB: n }));
        message = t(`以 ${label(minimum)} 为基准，分别设置 B 的最低产量：B ≥ 3 → 利润 12 元；B ≥ 4 → 利润 8 元。点击下方方案可继续讨论。`, `From ${label(minimum)}, compare two minimum orders: B ≥ 3 → profit CNY 12; B ≥ 4 → profit CNY 8. Select a saved plan below to discuss it.`);
      }
      if (action === "original") { minimum = 0; message = t("已选择原方案：A = 3，B = 2，利润 13 元。后续查询和调整以此为基准。", "Selected the original: A = 3, B = 2, profit CNY 13. Subsequent questions and revisions use this plan."); }
      if (message) { const entry = document.createElement("p"); entry.textContent = message; log.append(entry); while (log.children.length > 5) log.firstElementChild.remove(); update(); pulse(entry); }
    });
    update();
  } else if (kind === "data") {
    let saved = { cutting: 8, finishing: 8 };
    const run = demo.querySelector('[data-action="run"]'), save = demo.querySelector('[data-action="save"]'), cancel = demo.querySelector('[data-action="cancel"]');
    const update = () => {
      const dirty = Object.keys(saved).some(name => input(name).value !== String(saved[name]));
      run.disabled = dirty; save.disabled = !dirty; cancel.disabled = !dirty;
      demo.querySelector('[data-data-status]').textContent = dirty ? t("有未保存修改。保存数据后可开始建模；取消编辑可恢复已保存数值。", "You have unsaved edits. Save data to start modeling, or cancel to restore saved values.") : t(`已保存附件：切割 ${saved.cutting} 小时，装配 ${saved.finishing} 小时。点击“开始建模”使用这份数据。`, `Saved data: ${saved.cutting} cutting hours and ${saved.finishing} finishing hours. Start modeling to use these values.`);
    };
    demo.addEventListener("input", update);
    demo.addEventListener("click", event => {
      const action = event.target.closest("button")?.dataset.action;
      if (action === "cancel") { for (const name of Object.keys(saved)) input(name).value = saved[name]; update(); }
      if (action === "save") {
        for (const name of Object.keys(saved)) if (!input(name).reportValidity()) return;
        saved = { cutting: Number(input("cutting").value), finishing: Number(input("finishing").value) };
        for (const name of Object.keys(saved)) input(name).value = saved[name];
        update();
      }
      if (action === "run" && !run.disabled) {
        const result = production(saved);
        output.textContent = t(`运行结果（${saved.cutting} / ${saved.finishing} 小时）：A = ${result.best[0]}，B = ${result.best[1]}，利润 ${result.objective} 元。`, `Run result (${saved.cutting} / ${saved.finishing} hours): A = ${result.best[0]}, B = ${result.best[1]}, profit CNY ${result.objective}.`);
        pulse(output);
      }
    });
    update();
  } else if (kind === "convex") {
    const redraw = () => {
      const limit = Number(input("limit").value), p = projection(limit);
      demo.querySelector('[data-value="limit"]').textContent = number(limit);
      demo.querySelector('[data-model-limit]').textContent = number(limit);
      const xy = (x, y) => `${44 + x * 84},${280 - y * 60}`;
      chart.innerHTML = `<path d="M44 16V280H420" class="chart-axis"/>${[0, 1, 2, 3, 4].map(i => `<text x="${40 + i * 84}" y="300">${i}</text><text x="24" y="${284 - i * 60}">${i}</text>`).join("")}<text x="420" y="306">x</text><text x="15" y="24">y</text><polygon points="${xy(0, 0)} ${xy(limit, 0)} ${xy(0, limit)}" class="chart-region"/><ellipse cx="128" cy="160" rx="${Math.sqrt(p.objective) * 84}" ry="${Math.sqrt(p.objective) * 60}" class="chart-contour"/><path d="M128 160L${xy(p.x, p.y)}" class="chart-line secondary"/><circle cx="128" cy="160" r="5" class="chart-point"/><text x="140" y="149">(1, 2)</text><circle cx="${44 + p.x * 84}" cy="${280 - p.y * 60}" r="7" class="chart-best"/>`;
      output.textContent = `x = ${number(p.x)}, y = ${number(p.y)} · ${t("目标值", "Objective")} ${number(p.objective)}`;
      demo.querySelector(".demo-explanation").textContent = t(`资源使用 ${number(p.x + p.y)} / ${number(limit)}。最优点到目标 (1, 2) 的距离平方为 ${number(p.objective)}。`, `Resource use: ${number(p.x + p.y)} / ${number(limit)}. The squared distance from the optimum to target (1, 2) is ${number(p.objective)}.`);
      chart.setAttribute("aria-label", output.textContent);
    };
    demo.addEventListener("input", redraw); redraw();
  } else if (kind === "local") {
    let path, iteration = 0, timer;
    const play = demo.querySelector('[data-action="play"]');
    const stop = () => { clearInterval(timer); timer = undefined; play.textContent = t("播放迭代", "Play iterations"); play.setAttribute("aria-pressed", "false"); };
    const y = value => 270 - (value + .5) * 25;
    const xy = x => `${44 + (x + 2) * 90},${y(nonconvex(x))}`;
    const show = () => {
      const x = path[iteration];
      chart.innerHTML = `<path d="M44 15V280H420M44 ${y(0)}H420" class="chart-axis"/><text x="420" y="304">x</text><text x="12" y="25">f(x)</text><text x="33" y="302">−2</text><text x="218" y="302">0</text><text x="399" y="302">2</text>${[0, 4, 8].map(i => `<text x="24" y="${y(i) + 4}">${i}</text>`).join("")}<path d="${Array.from({ length: 161 }, (_, i) => `${i ? "L" : "M"}${xy(-2 + i / 40)}`).join("")}" class="chart-line"/><path d="M${path.slice(0, iteration + 1).map(xy).join("L")}" class="chart-trail"/><circle cx="${44 + (x + 2) * 90}" cy="${y(nonconvex(x))}" r="7" class="chart-best"/>`;
      output.textContent = `${t("迭代", "Iteration")} ${iteration} · x = ${number(x)} · f(x) = ${number(nonconvex(x))}`;
      chart.setAttribute("aria-label", output.textContent);
    };
    const reset = () => { stop(); path = descent(Number(input("start").value)); iteration = 0; show(); };
    input("start").addEventListener("change", reset);
    demo.addEventListener("click", event => {
      const action = event.target.closest("button")?.dataset.action;
      if (action === "reset") reset();
      if (action !== "play") return;
      if (timer) { stop(); return; }
      if (iteration === path.length - 1) iteration = 0;
      if (reduceMotion.matches) { iteration = path.length - 1; show(); return; }
      play.textContent = t("暂停", "Pause"); play.setAttribute("aria-pressed", "true");
      timer = setInterval(() => { iteration++; show(); if (iteration === path.length - 1) stop(); }, 110);
    });
    pauses.push(stop); reset();
  }
}
document.addEventListener("visibilitychange", () => { if (document.hidden) pauses.forEach(pause => pause()); });

for (const recording of document.querySelectorAll(".doc-recording")) {
  const video = recording.querySelector("video"), status = recording.querySelector(".recording-status");
  let requestedTime;
  recording.dataset.ready = "true";
  video.addEventListener("loadedmetadata", () => { if (requestedTime !== undefined) video.currentTime = requestedTime; });
  recording.addEventListener("click", async event => {
    const button = event.target.closest("[data-seek]");
    if (!button) return;
    requestedTime = Number(button.dataset.seek);
    if (video.readyState >= 1) video.currentTime = requestedTime;
    status.hidden = true;
    try { await video.play(); }
    catch { status.hidden = false; status.textContent = t("片段暂时无法播放，请使用播放器控件重试。", "The chapter could not play. Use the video controls to retry."); }
  });
  pauses.push(() => video.pause());
}

for (const figure of document.querySelectorAll(".doc-diagram")) {
  const button = document.createElement("button");
  button.type = "button"; button.textContent = t("放大查看", "Expand diagram"); button.setAttribute("aria-haspopup", "dialog");
  const dialog = document.querySelector("#diagram-dialog");
  button.addEventListener("click", () => {
    const image = dialog.querySelector("img");
    image.src = figure.dataset.src; image.alt = figure.querySelector("figcaption").textContent;
    image.classList.remove("native-size");
    dialog.querySelector("[data-diagram-size]").textContent = t("原始尺寸", "Actual size");
    dialog.showModal();
  });
  figure.querySelector(".diagram-actions").prepend(button);
}
document.querySelector("[data-diagram-size]").addEventListener("click", event => {
  const native = document.querySelector("#diagram-dialog img").classList.toggle("native-size");
  event.currentTarget.textContent = native ? t("适应窗口", "Fit to window") : t("原始尺寸", "Actual size");
});
