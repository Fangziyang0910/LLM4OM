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
    const active = diagram?.querySelector(".is-current");
    if (active) {
      const scroll = diagram.querySelector(".diagram-scroll"), box = active.getBoundingClientRect(), frame = scroll.getBoundingClientRect();
      scroll.scrollTo({ top: scroll.scrollTop + box.y - frame.y - (frame.height - box.height) / 2, left: scroll.scrollLeft + box.x - frame.x - (frame.width - box.width) / 2, behavior: "instant" });
    }
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
      chart.innerHTML = axis() + `<polygon class="chart-region" points="${vertices.map(point).join(" ")}"/><path d="M${point([0, cutting])}L${point([cutting / 2, 0])}" class="chart-line"/><path d="M${point([0, 4])}L${point([8, 0])}" class="chart-line secondary"/>` + (integer ? result.points.map(p => `<circle cx="${44 + p[0] * 56}" cy="${280 - p[1] * 40}" r="3" class="chart-point"/>`).join("") : "") + (result.best ? `<circle cx="${44 + result.best[0] * 56}" cy="${280 - result.best[1] * 40}" r="7" class="chart-best"/>` : "");
      const download = demo.querySelector('[data-action="download"]');
      download.disabled = !result.best;
      if (!result.best) {
        output.textContent = t("无可行方案", "No feasible plan");
        demo.querySelector(".demo-explanation").textContent = t("B ≥ 5 已经需要至少 10 小时装配，但只有 8 小时。增加切割工时不能消除这个冲突。", "B ≥ 5 requires at least 10 finishing hours, but only 8 are available. More cutting capacity cannot remove this conflict.");
      } else {
        const [a, b] = result.best;
        output.textContent = `A = ${number(a)}, B = ${number(b)} · ${t("收益", "Objective")} ${number(result.objective)}`;
        demo.querySelector(".demo-explanation").textContent = t(`切割用 ${number(2 * a + b)} / ${cutting} 小时；装配用 ${number(a + 2 * b)} / 8 小时。${integer ? "点表示可行的整数方案；填色表示连续可行域。" : "数量允许分割，最优点可能位于两个整数点之间。"}`, `Cutting: ${number(2 * a + b)} / ${cutting} hours. Finishing: ${number(a + 2 * b)} / 8 hours. ${integer ? "Dots are feasible integer plans; shading is the continuous feasible region." : "Divisible quantities can place the optimum between integer points."}`);
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
      current.textContent = `${label(minimum)} · ${number(plans.get(minimum).objective)}`;
      saved.textContent = t("已保存：", "Saved: ") + [...plans].map(([n, p]) => `${label(n)} (${number(p.objective)})`).join(" · ");
    };
    demo.addEventListener("click", event => {
      const action = event.target.closest("button")?.dataset.action;
      if (!action) return;
      let message;
      if (action === "reset") { minimum = 0; plans.clear(); plans.set(0, production()); log.replaceChildren(); message = t("已恢复原方案：A = 3，B = 2，收益 13。", "Original restored: A = 3, B = 2, objective 13."); }
      if (action === "explain") {
        const [a, b] = plans.get(minimum).best;
        message = t(`查询 ${label(minimum)}：切割用 ${2 * a + b}/8，装配用 ${a + 2 * b}/8。余量分别是 ${8 - 2 * a - b} 和 ${8 - a - 2 * b}。读取已保存结果，没有重算。`, `Query ${label(minimum)}: cutting ${2 * a + b}/8, finishing ${a + 2 * b}/8; slack ${8 - 2 * a - b} and ${8 - a - 2 * b}. Read saved values; no solve.`);
      }
      if (action === "revise") { minimum = 3; plans.set(3, production({ minimumB: 3 })); message = t("新增约束 B ≥ 3 并重算：A = 2，B = 3，收益 12。新方案成为当前基准，原方案仍保留。", "Add B ≥ 3 and solve: A = 2, B = 3, objective 12. The new plan is current; the original is kept."); }
      if (action === "scenarios") {
        for (const n of [3, 4]) plans.set(n, production({ minimumB: n }));
        message = t(`从 ${label(minimum)} 这个固定基准分别计算：B ≥ 3 → 12；B ≥ 4 → 8。两个场景互不叠加，当前基准仍是 ${label(minimum)}。`, `Solve separately from the fixed ${label(minimum)} baseline: B ≥ 3 → 12; B ≥ 4 → 8. Scenarios do not accumulate. Current baseline stays ${label(minimum)}.`);
      }
      if (action === "original") { minimum = 0; message = t("已选原方案作为当前基准：收益 13。只切换引用，没有重新建模或求解。", "Selected the original as current: objective 13. Changed the reference without modeling or solving again."); }
      if (message) { const entry = document.createElement("p"); entry.textContent = message; log.append(entry); while (log.children.length > 5) log.firstElementChild.remove(); update(); pulse(entry); }
    });
  } else if (kind === "data") {
    let saved = { cutting: 8, finishing: 8 };
    demo.addEventListener("click", event => {
      const action = event.target.closest("button")?.dataset.action;
      if (action === "cancel") for (const name of Object.keys(saved)) input(name).value = saved[name];
      if (action !== "save") return;
      for (const name of Object.keys(saved)) if (!input(name).reportValidity()) return;
      saved = { cutting: Number(input("cutting").value), finishing: Number(input("finishing").value) };
      const result = production(saved);
      output.textContent = t(`新方案：${saved.cutting} / ${saved.finishing} 小时 → A = ${result.best[0]}，B = ${result.best[1]}，收益 ${result.objective}。原方案未改变。`, `New plan: ${saved.cutting} / ${saved.finishing} hours → A = ${result.best[0]}, B = ${result.best[1]}, objective ${result.objective}. Original unchanged.`);
      pulse(output);
    });
  } else if (kind === "convex") {
    const redraw = () => {
      const limit = Number(input("limit").value), p = projection(limit);
      demo.querySelector('[data-value="limit"]').textContent = number(limit);
      const xy = (x, y) => `${44 + x * 84},${280 - y * 60}`;
      chart.innerHTML = `<path d="M44 16V280H420" class="chart-axis"/><text x="405" y="306">x</text><text x="15" y="24">y</text><polygon points="${xy(0, 0)} ${xy(limit, 0)} ${xy(0, limit)}" class="chart-region"/><ellipse cx="128" cy="160" rx="${Math.sqrt(p.objective) * 84}" ry="${Math.sqrt(p.objective) * 60}" class="chart-contour"/><path d="M128 160L${xy(p.x, p.y)}" class="chart-line secondary"/><circle cx="128" cy="160" r="5" class="chart-point"/><text x="140" y="149">(1, 2)</text><circle cx="${44 + p.x * 84}" cy="${280 - p.y * 60}" r="7" class="chart-best"/><text x="${Math.min(350, 54 + limit * 84)}" y="268">${number(limit)}</text>`;
      output.textContent = `x = ${number(p.x)}, y = ${number(p.y)} · ${t("目标值", "Objective")} ${number(p.objective)}`;
      demo.querySelector(".demo-explanation").textContent = limit >= 3 ? t("目标点 (1, 2) 已可行，增加资源不会继续降低目标值。", "The target (1, 2) is feasible. More resources cannot reduce the objective further.") : t("最优点是目标到可行域的投影。这里变量连续，0.5 是合法数量。", "The optimum is the projection of the target onto the feasible set. Variables are continuous, so 0.5 is valid.");
      chart.setAttribute("aria-label", output.textContent);
    };
    demo.addEventListener("input", redraw); redraw();
  } else if (kind === "local") {
    let path, iteration = 0, timer;
    const play = demo.querySelector('[data-action="play"]');
    const stop = () => { clearInterval(timer); timer = undefined; play.textContent = t("播放迭代", "Play iterations"); play.setAttribute("aria-pressed", "false"); };
    const xy = x => `${44 + (x + 2) * 90},${260 - nonconvex(x) * 35}`;
    const show = () => {
      const x = path[iteration];
      chart.innerHTML = `<path d="M44 15V280H420M44 260H420" class="chart-axis"/><text x="401" y="304">x</text><text x="12" y="25">f(x)</text><text x="33" y="302">−2</text><text x="218" y="302">0</text><text x="399" y="302">2</text><path d="${Array.from({ length: 161 }, (_, i) => `${i ? "L" : "M"}${xy(-2 + i / 40)}`).join("")}" class="chart-line"/><path d="M${path.slice(0, iteration + 1).map(xy).join("L")}" class="chart-trail"/><circle cx="${44 + (x + 2) * 90}" cy="${260 - nonconvex(x) * 35}" r="7" class="chart-best"/>`;
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
