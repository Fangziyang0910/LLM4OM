"use strict";
const $ = (id) => document.getElementById(id);
let token = "",
  config = {},
  plugins = [],
  uploads = [],
  currentJob = null,
  selectedRun = null,
  currentExperiment = null,
  snapshot = null,
  activeTab = "formulation",
  artifactSelectedByUser = false,
  clarificationSubmission = null,
  editSubmission = null,
  editParent = null,
  renderFingerprint = "";
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
function fillSelect(id, kind, selected, allowed) {
  $(id).replaceChildren();
  for (const item of plugins.filter(
    (p) =>
      p.manifest.kind === kind &&
      !p.manifest.capabilities.human_assisted &&
      (!allowed || allowed.includes(p.manifest.plugin_id)),
  )) {
    const option = document.createElement("option");
    option.value = item.manifest.plugin_id;
    option.textContent =
      kind === "method"
        ? UI.shortMethod(item.manifest.plugin_id)
        : kind === "solver_backend"
          ? item.manifest.plugin_id.split(".").at(-1).toUpperCase()
          : item.manifest.display_name;
    $(id).append(option);
  }
  if (!Array.from($(id).options).some((option) => option.value === selected)) {
    const unavailable = UI.node("option", "", "当前配置不可用 · " + selected);
    unavailable.value = selected;
    unavailable.disabled = true;
    $(id).append(unavailable);
  }
  $(id).value = selected;
}
function showConfig() {
  fillSelect("method", "method", config.method.plugin_id);
  fillSelect("provider", "llm_provider", config.llm.provider_plugin_id);
  fillSelect("backend", "model_backend", config.model_backend.plugin_id);
  const method = plugins.find(
    (p) => p.manifest.plugin_id === config.method.plugin_id,
  )?.manifest;
  const backend = plugins.find(
    (p) => p.manifest.plugin_id === config.model_backend.plugin_id,
  )?.manifest;
  const solverIds = method?.capabilities.solvers;
  const compatible = solverIds?.filter((id) => {
    const solver = plugins.find((p) => p.manifest.plugin_id === id)?.manifest;
    return (
      !backend?.capabilities.handle_profile ||
      !solver?.capabilities.handle_profiles ||
      solver.capabilities.handle_profiles.includes(
        backend.capabilities.handle_profile,
      )
    );
  });
  fillSelect("solver", "solver_backend", config.solver.plugin_id, compatible);
  $("submit").disabled = Boolean($("solver").selectedOptions[0]?.disabled);
  $("model").value = config.llm.model;
  $("base-url").value = config.llm.config.base_url || "";
  $("token-budget").value = config.budget.max_total_tokens;
  $("wall-budget").value = config.budget.wall_time_s;
  $("attempt-budget").value = config.budget.max_llm_attempts;
  $("solver-budget").value = config.budget.max_solver_calls;
  $("config-json").value = pretty(config);
  const explanations = {
    "llm4om.methods.direct":
      "一次模型调用联合生成数学表述与求解实现，再构建并求解候选模型。",
    "llm4om.methods.optimus_inline":
      "依次理解目标与约束、形成数学表述、编写代码，并根据执行反馈调试。适合直接输入问题。",
    "llm4om.methods.optimus":
      "使用公开参数和标签文件，分步形成数学表述与求解代码。需要 params 与 labels 数据。",
    "llm4om.methods.coe":
      "由协调者选择专家，进行建模讨论、代码生成与审查。页面展示实际参与的角色。",
    "llm4om.methods.feedback_repair":
      "遇到缺失或含糊的规则时可以先向你提问。生成候选模型后，依据公开执行反馈修正，并保存候选与选择关系。",
  };
  $("method-explainer").textContent =
    explanations[config.method.plugin_id] ||
    "按所选方法的实际流程建模，保存公开步骤和输出。";
  showBudgetSummary();
}
function showBudgetSummary() {
  $("budget-summary").textContent =
    `本次上限：${config.budget.max_llm_attempts} 次模型请求 · ${UI.format(config.budget.max_total_tokens)} Token · ${UI.format(config.budget.wall_time_s)} 秒`;
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
  config.budget.max_llm_attempts = Number($("attempt-budget").value);
  config.budget.max_solver_calls = Number($("solver-budget").value);
  $("config-json").value = pretty(config);
  showBudgetSummary();
  return config;
}
for (const id of [
  "attempt-budget",
  "token-budget",
  "wall-budget",
  "solver-budget",
])
  $(id).onchange = () => {
    try {
      readConfig();
    } catch (error) {
      notice(error.message, true);
    }
  };
function chooseMethod() {
  const method = $("method").value;
  if (
    ["llm4om.methods.optimus", "llm4om.methods.optimus_inline"].includes(method)
  ) {
    config.method = {
      plugin_id: method,
      config:
        method === "llm4om.methods.optimus_inline"
          ? { rag_mode: null }
          : {
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
      "llm4om.methods.optimus_inline",
      "llm4om.methods.coe",
    ].includes(method)
  )
    config.method = { plugin_id: method, config: {} };
  const classical = /optimus|coe/.test(method);
  Object.assign(
    config.budget,
    classical
      ? {
          max_llm_attempts: 30,
          max_total_tokens: 300000,
          max_solver_calls: 12,
          max_repairs: 3,
          max_candidates: 4,
          wall_time_s: 1800,
        }
      : {
          max_llm_attempts: 4,
          max_total_tokens: 100000,
          max_solver_calls: 4,
          max_repairs: 2,
          max_candidates: 4,
          wall_time_s: 180,
        },
  );
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
    meta.textContent = `${UI.status(job.status)} · ${UI.shortMethod(job.method)}`;
    button.append(title, meta);
    button.onclick = () => openJob(job.job_id);
    $("jobs").append(button);
  }
}
async function openJob(id) {
  selectedRun = null;
  $("assisted-editor").hidden = true;
  $("step-output").hidden = true;
  snapshot = null;
  renderFingerprint = "";
  $("artifact-choice").replaceChildren();
  currentExperiment = null;
  $("experiment-editor").hidden = true;
  $("experiment-result").hidden = true;
  currentJob = id;
  $("editor").hidden = true;
  $("result").hidden = false;
  await refreshRun();
  if (snapshot?.bundle?.stages?.formulation?.status === "not_available")
    document.querySelector('[data-tab="code"]').click();
  await refreshJobs();
}
function artifactEntries() {
  const contents = snapshot?.contents || {};
  const patterns = {
    formulation: /formulation|model-ir|structured-ir|method\/state_/,
    code: /code|build|symbol-map|model\.py|factory\.py|native.*\.py/,
    candidates:
      /(?:^|\/)(?:candidate(?:-snapshot|-selection)?|assessment|formulation-changes|repair-state|evaluation)\.json$/,
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
  if (activeTab === "candidates") {
    UI.candidates($("model-view"), snapshot);
    return;
  }
  if (
    value === undefined &&
    ["running", "queued", "needs_input"].includes(snapshot?.job?.status)
  ) {
    UI.empty(
      $("model-view"),
      snapshot.job.status === "needs_input"
        ? "补充信息后继续建模"
        : activeTab === "code"
          ? "求解实现正在形成"
          : "建模输出正在形成",
      "完成的公开产物会自动出现在这里。可以在左侧查看当前的实际步骤。",
    );
    return;
  }
  const name = $("artifact-choice").value;
  const candidate = name.startsWith("candidates/") ? name.split("/")[1] : null;
  const contents = candidate
    ? Object.fromEntries(
        Object.entries(snapshot?.contents || {}).filter(
          ([key]) =>
            !key.startsWith("candidates/") ||
            key.startsWith(`candidates/${candidate}/`),
        ),
      )
    : snapshot?.contents || {};
  const view =
    activeTab === "formulation" && name.startsWith("method/state_")
      ? { representation: { state: value } }
      : value;
  UI.records(
    $("model-view"),
    view,
    activeTab,
    contents,
    snapshot?.data_previews,
  );
}
function renderArtifact() {
  const entries = artifactEntries();
  const score = ([name, value]) =>
    activeTab === "candidates"
      ? Number(name === "candidate-selection.json")
      : activeTab === "code"
        ? name ===
          `candidates/${snapshot?.bundle?.final_candidate_id || "001"}/model.py`
          ? 2
          : Number(name.endsWith(".py"))
        : value?.representation
          ? 100 +
            Number(
              name.startsWith(
                `candidates/${snapshot?.bundle?.final_candidate_id || "001"}/`,
              ),
            )
          : Number(name.match(/method\/state_(\d+)/)?.[1] || 0);
  entries.sort((a, b) => score(b) - score(a));
  $("output-heading").textContent = {
    formulation: "数学模型",
    code: "求解实现",
    candidates: "候选与修正",
    diagnostics: "实际运行记录",
    data: "问题与数据",
  }[activeTab];
  const previous = $("artifact-choice").value;
  $("artifact-choice").replaceChildren();
  if (activeTab === "diagnostics")
    entries.unshift(["运行事件", snapshot?.events || []]);
  for (const [name] of entries) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent =
      (name.startsWith("candidates/")
        ? "候选 " + name.split("/")[1] + " · "
        : "") + UI.artifactLabel(name);
    $("artifact-choice").append(option);
  }
  if (artifactSelectedByUser && entries.some(([name]) => name === previous))
    $("artifact-choice").value = previous;
  $("artifact-choice").hidden = entries.length < 2;
  $("artifact-choice").setAttribute(
    "aria-label",
    activeTab === "candidates" ? "选择原始候选记录" : "选择阶段记录",
  );
  const selected = () =>
    entries.find(([name]) => name === $("artifact-choice").value)?.[1];
  showArtifact(selected());
  $("artifact-choice").onchange = () => {
    artifactSelectedByUser = true;
    showArtifact(selected());
  };
}
function metric(label, value) {
  const box = UI.node("div", "metric");
  box.append(UI.node("span", "", label), UI.node("strong", "", value ?? "—"));
  return box;
}
async function refreshRun() {
  if (!currentJob) return;
  const jobId = currentJob,
    runId = selectedRun;
  const result = await api(
    `/api/jobs/${jobId}${runId ? "?run_id=" + runId : ""}`,
  );
  if (currentJob !== jobId || selectedRun !== runId) return;
  snapshot = result;
  const fingerprint = JSON.stringify([
    snapshot.job,
    snapshot.artifacts,
    snapshot.events,
    snapshot.versions,
    snapshot.latest_run_id,
  ]);
  if (fingerprint === renderFingerprint) return;
  renderFingerprint = fingerprint;
  const { job, bundle, contents = {} } = snapshot;
  const versions = snapshot.versions || [];
  $("run-version").replaceChildren();
  const latestOption = UI.node("option", "", "最新版本 / 正在执行");
  latestOption.value = "";
  $("run-version").append(latestOption);
  for (const version of versions) {
    const option = UI.node(
      "option",
      "",
      (version.assisted ? "人工修订" : "运行") +
        " · " +
        UI.status(version.status) +
        " · " +
        version.run_id.slice(0, 8) +
        (version.parent_run_id
          ? " ← " + version.parent_run_id.slice(0, 8)
          : " · 原始版本"),
    );
    option.value = version.run_id;
    $("run-version").append(option);
  }
  $("run-version").value = selectedRun || "";
  $("run-version").parentElement.hidden = versions.length < 2;
  const methodId =
    contents["public-config.json"]?.method?.plugin_id || job.method;
  $("run-title").textContent = job.description;
  $("run-meta").textContent =
    `${UI.status(job.status)} · ${bundle?.assisted && methodId !== "llm4om.methods.assisted" ? "人工辅助 · " : ""}${UI.shortMethod(methodId)} · ${job.run_id || "正在准备"}`;
  $("stages").replaceChildren();
  for (const stage of ["formulation", "code", "solve"]) {
    const box = document.createElement("div");
    box.className = "stage";
    const title = document.createElement("strong");
    title.textContent = {
      formulation: "01 数学表述",
      code: "02 求解实现",
      solve: "03 求解结果",
    }[stage];
    const status = document.createElement("span");
    const runningStep = snapshot.events?.findLast(
      (event) => event.method_event?.type === "modeling_step",
    )?.method_event;
    const state =
      bundle?.stages?.[stage]?.status ||
      (job.status === "running" &&
      (runningStep?.phase || "formulation") === stage
        ? "running"
        : "pending");
    status.textContent = UI.status(state);
    box.classList.add(state);
    box.append(title, status);
    $("stages").append(box);
  }
  const publicValue = (ref) => UI.artifactKey(snapshot, ref);
  const solve = contents[publicValue(bundle?.solve_result_ref)];
  const solution = contents[publicValue(solve?.solution_ref)];
  const model = contents[publicValue(bundle?.model_artifact_ref)];
  const code = contents[publicValue(model?.code_ref)];
  const solvedIR =
    code?.provenance?.origin === "deterministic_compilation"
      ? contents[publicValue(code.provenance.source_ir_ref)]
      : null;
  UI.decision(
    $("decision"),
    solve,
    solution,
    contents["budget-ledger.json"],
    snapshot,
    solvedIR,
  );
  UI.timeline(snapshot);
  if (bundle?.error || job.error)
    notice(
      (bundle?.error || job.error).message || "运行未完成，请查看运行详情。",
      true,
    );
  $("export").href =
    `/api/jobs/${currentJob}/export${selectedRun ? "?run_id=" + selectedRun : ""}`;
  $("export").hidden = !bundle;
  const request = contents[publicValue(bundle?.clarification_request_ref)];
  $("clarification").hidden = job.status !== "needs_input";
  if (
    request &&
    $("clarification-questions").dataset.requestId !== request.request_id
  ) {
    $("clarification-request").textContent = pretty(request);
    clarificationSubmission = UI.clarification(
      $("clarification-questions"),
      request,
      contents["public-problem.json"],
    );
  }
  renderArtifact();
  $("cancel").hidden =
    snapshot.historical || !["running", "queued"].includes(job.status);
  $("resume").hidden =
    snapshot.historical || !["failed", "cancelled"].includes(job.status);
  $("rerun").hidden = Boolean(snapshot.historical);
  $("edit-run").disabled = ["running", "queued"].includes(job.status);
}
$("run-version").onchange = async () => {
  selectedRun = $("run-version").value || null;
  renderFingerprint = "";
  snapshot = null;
  $("assisted-editor").hidden = true;
  $("step-output").hidden = true;
  $("artifact-choice").replaceChildren();
  artifactSelectedByUser = false;
  try {
    await refreshRun();
  } catch (error) {
    notice(error.message, true);
  }
};
$("new-run").onclick = () => {
  $("step-output").hidden = true;
  currentExperiment = null;
  $("experiment-editor").hidden = true;
  $("experiment-result").hidden = true;
  currentJob = null;
  selectedRun = null;
  snapshot = null;
  document.querySelector('[data-tab="formulation"]').click();
  $("editor").hidden = false;
  $("result").hidden = true;
  notice("");
};
$("method").onchange = chooseMethod;
$("solver").onchange = () => {
  config.solver.plugin_id = $("solver").value;
  showConfig();
};
$("backend").onchange = () => {
  config.model_backend.plugin_id = $("backend").value;
  showConfig();
};
const problemExamples = {
  production:
    "一家工厂生产产品 A 和 B。每件 A 的利润为 3，每件 B 的利润为 2。每件 A 消耗 2 单位原料和 1 单位工时；每件 B 消耗 1 单位原料和 2 单位工时。原料和工时的可用容量均为 8。决定两种产品的生产数量，数量必须是非负整数，使总利润最大。",
  projects:
    "有甲、乙、丙三个项目，费用分别为 4、3、5 万元，收益分别为 7、5、9 万元。总预算为 8 万元。每个项目只能选择或不选择，最多执行一次。决定选择哪些项目，使总收益最大，并且不超过预算。",
  diet: "两种食物 A、B 每份价格分别为 2、3 元，每份蛋白质分别为 3、4 克，每份膳食纤维分别为 2、1 克。每日至少需要 12 克蛋白质和 8 克膳食纤维。份数可以是非负小数。决定两种食物的份数，使总费用最小。",
};
for (const button of document.querySelectorAll("[data-example]"))
  button.onclick = () => {
    $("description").value = problemExamples[button.dataset.example];
    $("problem-json").value = "";
    uploads = [];
    renderUploads();
    $("description").focus();
  };
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
    if (!clarificationSubmission) throw new Error("澄清请求尚未加载。");
    const payload = clarificationSubmission();
    $("answer-submit").disabled = true;
    await api(`/api/jobs/${currentJob}/resume`, payload);
    notice("回答已提交，正在恢复。");
    await refreshRun();
  } catch (error) {
    notice(error.message, true);
  } finally {
    $("answer-submit").disabled = false;
  }
};
document.querySelectorAll(".tab").forEach(
  (button) =>
    (button.onclick = () => {
      activeTab = button.dataset.tab;
      artifactSelectedByUser = false;
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

function renderTable(container, columns, rows) {
  container.replaceChildren();
  const table = document.createElement("table"),
    head = document.createElement("thead"),
    body = document.createElement("tbody"),
    heading = document.createElement("tr");
  for (const [label] of columns) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = label;
    heading.append(th);
  }
  head.append(heading);
  for (const row of rows) {
    const line = document.createElement("tr");
    for (const [, key] of columns) {
      const td = document.createElement("td");
      const value = typeof key === "function" ? key(row) : row[key];
      td.textContent =
        value === null || value === undefined
          ? "unknown"
          : typeof value === "object"
            ? pretty(value)
            : String(value);
      line.append(td);
    }
    body.append(line);
  }
  table.append(head, body);
  container.append(table);
}
async function refreshExperiments() {
  const { experiments } = await api("/api/experiments");
  $("experiments").replaceChildren();
  for (const experiment of experiments) {
    const button = document.createElement("button");
    button.className = "job";
    button.textContent = `${experiment.status} · ${experiment.task_count}任务 × ${experiment.configuration_count}配置 × ${experiment.repeats}`;
    button.onclick = () => openExperiment(experiment.experiment_id);
    $("experiments").append(button);
  }
}
async function refreshTasks() {
  const { tasks } = await api("/api/tasks");
  $("task-choice").replaceChildren();
  for (const task of tasks) {
    const option = document.createElement("option");
    option.value = task.task_id;
    option.textContent = `${task.source.dataset_id} · ${task.source.source_version} · ${task.N_selected}样本 · ${task.protocol_id}`;
    $("task-choice").append(option);
  }
}
async function openExperiment(id) {
  currentJob = null;
  currentExperiment = id;
  $("editor").hidden = true;
  $("result").hidden = true;
  $("experiment-editor").hidden = true;
  $("experiment-result").hidden = false;
  await refreshExperiment();
}
async function refreshExperiment() {
  if (!currentExperiment) return;
  const result = await api(`/api/experiments/${currentExperiment}`);
  $("experiment-meta").textContent =
    `${result.job.status} · ${currentExperiment}`;
  const progress = result.progress || {};
  $("experiment-progress").replaceChildren(
    metric(
      "已保存 / 计划运行",
      `${progress.N_saved || 0} / ${progress.N_selected_runs || "—"}`,
    ),
    metric("状态", pretty(progress.statuses || {})),
  );
  const match = (name) => (row) =>
    row[name + "_denominator"]
      ? `${row[name + "_numerator"]}/${row[name + "_denominator"]}`
      : "not_available";
  renderTable(
    $("experiment-groups"),
    [
      ["任务", "task_id"],
      ["配置", "configuration_id"],
      ["Repeat", "repeat"],
      ["完成/选中", (row) => `${row.N_completed}/${row.N_selected}`],
      ["独立可行", match("independent_feasibility")],
      ["目标匹配", match("objective_match")],
      ["Verified solution", match("verified_solution")],
      ["Tokens", "total_tokens"],
      ["费用", "cost"],
    ],
    result.summary?.groups || [],
  );
  renderTable(
    $("experiment-rows"),
    [
      ["样本", "case_id"],
      ["配置", "configuration_id"],
      ["Repeat", "repeat"],
      ["状态", "status"],
      ["Run", "run_id"],
      ["来源", "evidence_origin"],
      ["独立可行", match("independent_feasibility")],
      ["目标匹配", match("objective_match")],
      ["Verified solution", match("verified_solution")],
    ],
    result.rows || [],
  );
  $("experiment-summary").textContent = pretty(
    result.summary || result.job.error || "等待保存报告。",
  );
  $("export-experiment").href = `/api/experiments/${currentExperiment}/export`;
}
$("new-experiment").onclick = async () => {
  currentJob = null;
  currentExperiment = null;
  $("editor").hidden = true;
  $("result").hidden = true;
  $("experiment-result").hidden = true;
  $("experiment-editor").hidden = false;
  $("experiment-configurations").value = pretty([
    { id: "configured-method", config: readConfig() },
  ]);
  $("experiment-budget").value = pretty({
    max_llm_attempts: 100,
    max_total_tokens: 1000000,
    max_solver_calls: 100,
    wall_time_s: 3600,
    max_concurrency: 2,
  });
  try {
    await refreshTasks();
  } catch (error) {
    notice(error.message, true);
  }
};
$("refresh-tasks").onclick = async () => {
  try {
    await refreshTasks();
  } catch (error) {
    notice(error.message, true);
  }
};
$("submit-experiment").onclick = async () => {
  try {
    $("submit-experiment").disabled = true;
    const result = await api("/api/experiments", {
      task_ids: Array.from(
        $("task-choice").selectedOptions,
        (option) => option.value,
      ),
      configurations: JSON.parse($("experiment-configurations").value),
      repeats: Number($("experiment-repeats").value),
      budget: JSON.parse($("experiment-budget").value),
      exclusions: JSON.parse($("experiment-exclusions").value),
    });
    await openExperiment(result.experiment_id);
    await refreshExperiments();
    notice("实验已提交。");
  } catch (error) {
    notice(error.message, true);
  } finally {
    $("submit-experiment").disabled = false;
  }
};
for (const action of ["cancel", "resume"])
  $(action + "-experiment").onclick = async () => {
    try {
      await api(`/api/experiments/${currentExperiment}/${action}`, {});
      notice("实验操作已提交。");
      await refreshExperiment();
    } catch (error) {
      notice(error.message, true);
    }
  };
setInterval(async () => {
  try {
    await refreshExperiments();
    if (currentExperiment) await refreshExperiment();
  } catch (error) {
    notice(error.message, true);
  }
}, 3000);
refreshExperiments().catch((error) => notice(error.message, true));

async function loadEditTemplate() {
  if (!currentJob) return;
  const parent = { job: currentJob, run: snapshot.job.run_id };
  const document = await api(
    `/api/jobs/${parent.job}/edit-template?operation=${$("edit-operation").value}&run_id=${parent.run}`,
  );
  if (currentJob !== parent.job || snapshot?.job?.run_id !== parent.run)
    throw new Error("运行版本已改变，请重新载入编辑内容。");
  $("assisted-document").value = pretty(document);
  editParent = parent;
  editSubmission = UI.revision(
    $("revision-fields"),
    document,
    snapshot.contents?.["budget-ledger.json"],
  );
  $("revision-advanced").open = document.operation === "formulation";
}
$("edit-run").onclick = async () => {
  try {
    $("assisted-editor").hidden = false;
    await loadEditTemplate();
    $("assisted-editor").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    notice(error.message, true);
  }
};
$("load-edit-template").onclick = async () => {
  try {
    await loadEditTemplate();
  } catch (error) {
    notice(error.message, true);
  }
};
$("edit-operation").onchange = () =>
  loadEditTemplate().catch((error) => notice(error.message, true));
$("close-edit").onclick = () => {
  $("assisted-editor").hidden = true;
};
$("apply-edit-document").onclick = () => {
  try {
    const document = JSON.parse($("assisted-document").value);
    if (document.operation !== $("edit-operation").value)
      throw new Error("完整文档的编辑范围应与当前选择一致。");
    editSubmission = UI.revision(
      $("revision-fields"),
      document,
      snapshot.contents?.["budget-ledger.json"],
    );
    notice("完整编辑文档已应用到表单。");
  } catch (error) {
    notice(error.message, true);
  }
};
$("submit-edit").onclick = async () => {
  try {
    $("submit-edit").disabled = true;
    if (!editSubmission || currentJob !== editParent?.job)
      throw new Error("请先载入当前运行的编辑内容。");
    const edits = editSubmission();
    const latest = await api(
      `/api/jobs/${currentJob}?run_id=${editParent.run}`,
    );
    if (latest.job.run_id !== editParent.run)
      throw new Error("运行版本已改变，请重新载入编辑内容。");
    $("assisted-document").value = pretty(edits);
    await api(`/api/jobs/${currentJob}/edit`, {
      edits,
      parent_run_id: editParent.run,
    });
    selectedRun = null;
    renderFingerprint = "";
    $("assisted-editor").hidden = true;
    notice("人工修订已提交。原运行保留，新结果会记录父运行和预算。");
    await refreshRun();
  } catch (error) {
    notice(error.message, true);
  } finally {
    $("submit-edit").disabled = false;
  }
};
