"use strict";
const $ = (id) => document.getElementById(id);
let token = "",
  config = {},
  plugins = [],
  uploads = [],
  currentJob = null,
  snapshot = null,
  activeTab = "formulation";
const pretty = (value) =>
  typeof value === "string" ? value : JSON.stringify(value, null, 2);
function notice(text, error = false) {
  $("notice").hidden = !text;
  $("notice").textContent = text;
  $("notice").classList.toggle("error", error);
}
async function api(path, value) {
  const response = await fetch(
    path,
    value === undefined
      ? {}
      : {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-LLM4OM-Token": token,
          },
          body: JSON.stringify(value),
        },
  );
  const result = await response.json();
  if (!response.ok || result.error)
    throw new Error(result.error?.message || "请求失败");
  return result;
}
function fillSelect(id, kind, selected) {
  $(id).replaceChildren();
  for (const item of plugins.filter((p) => p.manifest.kind === kind)) {
    const option = document.createElement("option");
    option.value = item.manifest.plugin_id;
    option.textContent = item.manifest.display_name;
    $(id).append(option);
  }
  $(id).value = selected;
}
function showConfig() {
  fillSelect("method", "method", config.method.plugin_id);
  fillSelect("provider", "llm_provider", config.llm.provider_plugin_id);
  fillSelect("backend", "model_backend", config.model_backend.plugin_id);
  fillSelect("solver", "solver_backend", config.solver.plugin_id);
  $("model").value = config.llm.model;
  $("base-url").value = config.llm.config.base_url || "";
  $("token-budget").value = config.budget.max_total_tokens;
  $("wall-budget").value = config.budget.wall_time_s;
  $("config-json").value = pretty(config);
}
function readConfig() {
  config = JSON.parse($("config-json").value);
  config.method.plugin_id = $("method").value;
  config.llm.provider_plugin_id = $("provider").value;
  config.llm.model = $("model").value;
  config.model_backend.plugin_id = $("backend").value;
  config.solver.plugin_id = $("solver").value;
  if (config.llm.provider_plugin_id !== "llm4om.providers.mock")
    config.llm.config.base_url = $("base-url").value;
  config.budget.max_total_tokens = Number($("token-budget").value);
  config.budget.wall_time_s = Number($("wall-budget").value);
  $("config-json").value = pretty(config);
  return config;
}
function chooseMethod() {
  const method = $("method").value;
  if (method === "llm4om.methods.optimus") {
    config.method = {
      plugin_id: method,
      config: {
        rag_mode: null,
        params_data_id: "params",
        labels_data_id: "labels",
      },
    };
    config.model_backend.plugin_id = "llm4om.model_backends.gurobipy";
    config.solver.plugin_id = "llm4om.solvers.gurobi";
    delete config.compiler;
  } else if (method === "llm4om.methods.coe") {
    config.method = {
      plugin_id: method,
      config: {
        max_collaborate_nums: 1,
        enable_reflection: true,
        max_trials: 2,
        seed: 0,
      },
    };
    config.model_backend.plugin_id = "llm4om.model_backends.gurobipy";
    config.solver.plugin_id = "llm4om.solvers.gurobi";
    delete config.compiler;
  } else if (
    ["llm4om.methods.direct", "llm4om.methods.feedback_repair"].includes(method)
  ) {
    config.method = {
      plugin_id: method,
      config: { formulation_mode: "five_element", output_mode: "lp_ir" },
    };
    config.model_backend.plugin_id = "llm4om.model_backends.pyomo_factory";
    config.solver.plugin_id = "llm4om.solvers.highs";
    config.compiler = { plugin_id: "llm4om.compilers.lp_ir_to_pyomo" };
  }
  if (
    ![
      "llm4om.methods.direct",
      "llm4om.methods.feedback_repair",
      "llm4om.methods.optimus",
      "llm4om.methods.coe",
    ].includes(method)
  )
    config.method = { plugin_id: method, config: {} };
  showConfig();
}
function renderUploads() {
  $("uploads").replaceChildren();
  uploads.forEach((upload, index) => {
    const card = document.createElement("div");
    card.className = "upload-card";
    const meta = document.createElement("div");
    meta.className = "upload-meta";
    const name = document.createElement("input");
    name.value = upload.data_id;
    name.setAttribute("aria-label", "公开数据 ID");
    name.onchange = () => (upload.data_id = name.value);
    const remove = document.createElement("button");
    remove.textContent = "移除";
    remove.onclick = () => {
      uploads.splice(index, 1);
      renderUploads();
    };
    const label = document.createElement("span");
    label.textContent = `${upload.name} · ${upload.size} bytes`;
    meta.append(name, label, remove);
    const details = document.createElement("details"),
      summary = document.createElement("summary");
    summary.textContent =
      "数据 schema（CSV 默认为原始字符串，可明确声明数值／唯一键）";
    const schema = document.createElement("textarea");
    schema.rows = 6;
    schema.value = upload.schema ? pretty(upload.schema) : "";
    schema.setAttribute("aria-label", "公开数据 schema");
    schema.onchange = () => {
      try {
        upload.schema = schema.value.trim()
          ? JSON.parse(schema.value)
          : undefined;
      } catch (error) {
        notice(error.message, true);
      }
    };
    details.append(summary, schema);
    card.append(meta, details);
    $("uploads").append(card);
  });
}
async function refreshJobs() {
  const result = await api("/api/jobs");
  $("jobs").replaceChildren();
  for (const job of result.jobs) {
    const button = document.createElement("button");
    button.className = "job" + (job.job_id === currentJob ? " selected" : "");
    const title = document.createElement("strong");
    title.textContent = job.description;
    const meta = document.createElement("span");
    meta.textContent = `${job.status} · ${job.model}`;
    button.append(title, meta);
    button.onclick = () => openJob(job.job_id);
    $("jobs").append(button);
  }
}
async function openJob(id) {
  currentJob = id;
  $("editor").hidden = true;
  $("result").hidden = false;
  await refreshRun();
  await refreshJobs();
}
function artifactEntries() {
  const contents = snapshot?.contents || {};
  const patterns = {
    formulation: /formulation|model-ir/,
    code: /code|build|symbol-map|model\.py|factory\.py|native.*\.py/,
    candidates: /candidate|selection|feedback|repair|evaluation/,
    diagnostics: /diagnostic|execution|budget|report|trace/,
    data: /public-problem|data-views|dataset-manifest|data-bind/,
  };
  return Object.entries(contents).filter(([key]) =>
    patterns[activeTab].test(key),
  );
}
function showArtifact(value) {
  const text = pretty(value) || "此阶段尚无可用记录。";
  if ($("artifact-content").textContent !== text)
    $("artifact-content").textContent = text;
  $("model-view").replaceChildren();
  const representation = value?.representation;
  if (
    activeTab !== "formulation" ||
    !representation?.sets ||
    !representation?.variables
  )
    return;
  for (const [key, label] of [
    ["sets", "集合"],
    ["parameters", "参数"],
    ["variables", "变量与域"],
    ["objective", "目标"],
    ["constraints", "约束"],
  ]) {
    const card = document.createElement("section");
    card.className = "model-card";
    const title = document.createElement("h3");
    title.textContent = label;
    const content = document.createElement("pre");
    content.textContent = pretty(representation[key]);
    card.append(title, content);
    $("model-view").append(card);
  }
}
function renderArtifact() {
  const entries = artifactEntries();
  const previous = $("artifact-choice").value;
  $("artifact-choice").replaceChildren();
  if (activeTab === "diagnostics")
    entries.unshift(["运行事件", snapshot?.events || []]);
  for (const [name] of entries) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    $("artifact-choice").append(option);
  }
  if (entries.some(([name]) => name === previous))
    $("artifact-choice").value = previous;
  const selected = () =>
    entries.find(([name]) => name === $("artifact-choice").value)?.[1];
  showArtifact(selected());
  $("artifact-choice").onchange = () => showArtifact(selected());
}
function metric(label, value) {
  const box = document.createElement("div");
  box.className = "metric";
  const name = document.createElement("span");
  name.textContent = label;
  const number = document.createElement("strong");
  number.textContent = value ?? "—";
  box.append(name, number);
  return box;
}
async function refreshRun() {
  if (!currentJob) return;
  snapshot = await api(`/api/jobs/${currentJob}`);
  const { job, bundle, contents = {} } = snapshot;
  $("run-title").textContent = job.description;
  $("run-meta").textContent =
    `${job.status} · ${job.run_id || "等待应用分配 run_id"}`;
  $("stages").replaceChildren();
  for (const stage of ["formulation", "code", "solve"]) {
    const box = document.createElement("div");
    box.className = "stage";
    const title = document.createElement("strong");
    title.textContent = stage;
    const status = document.createElement("span");
    status.textContent = bundle?.stages?.[stage]?.status || "等待";
    box.append(title, status);
    $("stages").append(box);
  }
  const solve = Object.entries(contents).find(([name]) =>
    name.endsWith("solve-result.json"),
  )?.[1];
  const solution = Object.entries(contents).find(([name]) =>
    name.endsWith("solution.json"),
  )?.[1];
  $("decision").replaceChildren();
  const metrics = document.createElement("div");
  metrics.className = "metrics";
  metrics.append(
    metric("终止状态", solve?.termination),
    metric("目标值", solve?.objective_value),
    metric("求解器", solve?.solver_id),
    metric("实际 Token", contents["budget-ledger.json"]?.total_tokens),
    metric("费用", contents["budget-ledger.json"]?.cost ?? "未知"),
  );
  $("decision").append(metrics);
  if (solution?.variables) {
    const table = document.createElement("table");
    for (const [name, value] of Object.entries(solution.variables)) {
      const row = document.createElement("tr");
      for (const text of [name, value]) {
        const cell = document.createElement("td");
        cell.textContent = text;
        row.append(cell);
      }
      table.append(row);
    }
    $("decision").append(table);
  }
  const note = document.createElement("p");
  note.className = "hint";
  note.textContent =
    "求解结果针对候选模型。独立业务检查与表述正确性按各自证据显示。";
  $("decision").append(note);
  if (bundle?.error || job.error)
    notice(pretty(bundle?.error || job.error), true);
  $("export").href = `/api/jobs/${currentJob}/export`;
  $("export").hidden = !bundle;
  const request = Object.entries(contents).find(
    ([name]) =>
      name.startsWith("clarifications/") && name.endsWith("request.json"),
  )?.[1];
  $("clarification").hidden = job.status !== "needs_input";
  if (request) $("clarification-request").textContent = pretty(request);
  renderArtifact();
}
$("new-run").onclick = () => {
  currentJob = null;
  $("editor").hidden = false;
  $("result").hidden = true;
  notice("");
};
$("method").onchange = chooseMethod;
$("provider").onchange = () => {
  config.llm.provider_plugin_id = $("provider").value;
  $("config-json").value = pretty(config);
};
$("apply-config").onclick = () => {
  try {
    config = JSON.parse($("config-json").value);
    showConfig();
    notice("完整配置已应用。");
  } catch (error) {
    notice(error.message, true);
  }
};
$("data-files").onchange = async (event) => {
  for (const file of event.target.files) {
    if (file.size > 8 * 1024 * 1024) {
      notice("单个文件不能超过 8 MiB。", true);
      continue;
    }
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (let start = 0; start < bytes.length; start += 16384)
      binary += String.fromCharCode(...bytes.subarray(start, start + 16384));
    uploads.push({
      name: file.name,
      size: file.size,
      data_id: file.name.replace(/\.[^.]+$/, ""),
      format: file.name.toLowerCase().endsWith(".csv") ? "csv" : "json",
      base64: btoa(binary),
    });
  }
  renderUploads();
};
$("problem-file").onchange = async (event) => {
  try {
    const problem = JSON.parse(await event.target.files[0].text());
    $("problem-json").value = pretty(problem);
    $("description").value = problem.description;
    notice("问题规格已导入。请同时添加其中引用的公开数据。");
  } catch (error) {
    notice(error.message, true);
  }
};
$("doctor").onclick = async () => {
  try {
    notice("正在检查实际环境与兼容路径…");
    const result = await api("/api/doctor", { config: readConfig() });
    $("environment-content").textContent = pretty(result);
    $("environment").open = true;
    notice("环境与兼容检查通过。");
  } catch (error) {
    notice(error.message, true);
  }
};
$("submit").onclick = async () => {
  try {
    $("submit").disabled = true;
    const payload = {
      description: $("description").value,
      config: readConfig(),
      data: uploads.map(({ data_id, format, base64, schema }) => ({
        data_id,
        format,
        base64,
        ...(schema ? { schema } : {}),
      })),
    };
    if ($("problem-json").value.trim()) {
      payload.problem = JSON.parse($("problem-json").value);
      payload.problem.description = payload.description;
    }
    const job = await api("/api/jobs", payload);
    notice("运行已提交。");
    await openJob(job.job_id);
  } catch (error) {
    notice(error.message, true);
  } finally {
    $("submit").disabled = false;
  }
};
for (const [id, action] of [
  ["cancel", "cancel"],
  ["resume", "resume"],
  ["rerun", "resume"],
])
  $(id).onclick = async () => {
    try {
      if (
        id === "rerun" &&
        !confirm(
          "创建派生运行并继承预算记录。真实 LLM 可能产生新的请求费用，是否继续？",
        )
      )
        return;
      await api(
        `/api/jobs/${currentJob}/${action}`,
        id === "rerun" ? { strategy: "rerun" } : {},
      );
      notice("操作已提交。");
      await refreshRun();
    } catch (error) {
      notice(error.message, true);
    }
  };
$("answer-submit").onclick = async () => {
  try {
    await api(`/api/jobs/${currentJob}/resume`, {
      answers: JSON.parse($("answers").value),
    });
    notice("回答已提交，正在恢复。");
  } catch (error) {
    notice(error.message, true);
  }
};
document.querySelectorAll(".tab").forEach(
  (button) =>
    (button.onclick = () => {
      activeTab = button.dataset.tab;
      document
        .querySelectorAll(".tab")
        .forEach((item) => item.classList.toggle("active", item === button));
      renderArtifact();
    }),
);
async function start() {
  try {
    const result = await api("/api/bootstrap");
    token = result.token;
    config = result.config;
    plugins = result.plugins;
    showConfig();
    $("environment-content").textContent = pretty(result.plugins);
    await refreshJobs();
  } catch (error) {
    notice(error.message, true);
  }
}
start();
setInterval(async () => {
  try {
    await refreshJobs();
    if (currentJob) await refreshRun();
  } catch (error) {
    notice(error.message, true);
  }
}, 1500);
