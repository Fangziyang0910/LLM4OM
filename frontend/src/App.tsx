// workbench 应用主组件:配置表单、任务提交与轮询、运行视图、人工编辑与批量实验。
// DOM 契约(ids/classes)与轮询节奏沿用原实现,行为等价迁移自 app.js。
import { useEffect, useMemo, useRef, useState } from "react";
import { api, setApiToken } from "./api";
import type {
  ExperimentRecord,
  JobRecord,
  PluginManifest,
  RunConfig,
  Snapshot,
  UploadItem,
} from "./types";
import { artifactKey, artifactLabel, activeStep, format, pretty, shortMethod, status } from "./ui";
import { Candidates } from "./components/Candidates";
import { Connectivity } from "./components/Connectivity";
import { Clarification } from "./components/Clarification";
import { Decision } from "./components/Decision";
import { Records } from "./components/Records";
import { RuntimeDetails } from "./components/RuntimeDetails";
import { RevisionFields, buildDoc, validateRevision } from "./components/Revision";
import { StoryFlow } from "./components/StoryFlow";

const problemExamples: Record<string, string> = {
  production:
    "一家工厂生产产品 A 和 B。每件 A 的利润为 3，每件 B 的利润为 2。每件 A 消耗 2 单位原料和 1 单位工时；每件 B 消耗 1 单位原料和 2 单位工时。原料和工时的可用容量均为 8。决定两种产品的生产数量，数量必须是非负整数，使总利润最大。",
  projects:
    "有甲、乙、丙三个项目，费用分别为 4、3、5 万元，收益分别为 7、5、9 万元。总预算为 8 万元。每个项目只能选择或不选择，最多执行一次。决定选择哪些项目，使总收益最大，并且不超过预算。",
  diet: "两种食物 A、B 每份价格分别为 2、3 元，每份蛋白质分别为 3、4 克，每份膳食纤维分别为 2、1 克。每日至少需要 12 克蛋白质和 8 克膳食纤维。份数可以是非负小数。决定两种食物的份数，使总费用最小。",
};

const methodRequirements: Record<string, string> = {
  "llm4om.methods.optimus":
    "需要上传 params 与 labels 两个数据文件(或自定义数据 ID);求解走 Gurobi。",
  "llm4om.methods.coe": "多轮专家讨论,求解走 Gurobi。",
};

const methodExplainers: Record<string, string> = {
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

const tabPatterns: Record<string, RegExp> = {
  formulation: /formulation|model-ir|structured-ir|method\/state_/,
  code: /code|build|symbol-map|model\.py|factory\.py|native.*\.py/,
  candidates:
    /(?:^|\/)(?:candidate(?:-snapshot|-selection)?|assessment|formulation-changes|repair-state|evaluation)\.json$/,
  diagnostics: /diagnostic|execution|budget|report|trace/,
  data: /public-problem|data-views|dataset-manifest|data-bind/,
};

const tabHeadings: Record<string, string> = {
  formulation: "数学模型",
  code: "求解实现",
  candidates: "候选与修正",
  diagnostics: "实际运行记录",
  data: "问题与数据",
};

type View = "editor" | "run" | "experiment-editor" | "experiment-result";

export default function App() {
  const [config, setConfig] = useState<RunConfig>({});
  const [configJson, setConfigJson] = useState("");
  const [plugins, setPlugins] = useState<PluginManifest[]>([]);
  const [budgetText, setBudgetText] = useState({
    attempt: "",
    token: "",
    wall: "",
    solver: "",
  });
  const [modelText, setModelText] = useState("");
  const [baseUrlText, setBaseUrlText] = useState("");
  const [compatNote, setCompatNote] = useState("");
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [dataFilesReady, setDataFilesReady] = useState(false);
  const [description, setDescription] = useState("");
  const [problemJson, setProblemJson] = useState("");
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [currentJob, setCurrentJob] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [activeTab, setActiveTab] = useState("formulation");
  const [artifactChoice, setArtifactChoice] = useState("");
  const [artifactSelectedByUser, setArtifactSelectedByUser] = useState(false);
  const [view, setView] = useState<View>("editor");
  const [experiments, setExperiments] = useState<ExperimentRecord[]>([]);
  const [currentExperiment, setCurrentExperiment] = useState<string | null>(null);
  const [experimentSnapshot, setExperimentSnapshot] = useState<any>(null);
  const [experimentConfigurations, setExperimentConfigurations] = useState("");
  const [experimentBudget, setExperimentBudget] = useState("");
  const [taskOptions, setTaskOptions] = useState<any[]>([]);
  const [noticeState, setNoticeState] = useState<{ text: string; error: boolean }>({ text: "", error: false });
  const [doctorResult, setDoctorResult] = useState<any>(null);
  const [checkConnectivity, setCheckConnectivity] = useState(false);
  const [environmentText, setEnvironmentText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [doctorBusy, setDoctorBusy] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editOperation, setEditOperation] = useState("code");
  const [editTemplate, setEditTemplate] = useState<any>(null);
  const [editBase, setEditBase] = useState<any>(null);
  const [editOverrides, setEditOverrides] = useState<Record<string, string>>({});
  const [editDocumentText, setEditDocumentText] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  const editParent = useRef<{ job: string; run: string } | null>(null);
  const fingerprintRef = useRef("");
  const startedRef = useRef(false);

  const notice = (text: string, error = false) => setNoticeState({ text, error });

  useEffect(() => {
    (window as any).currentJob = currentJob;
  }, [currentJob]);
  useEffect(() => {
    (window as any).selectedRun = selectedRun;
  }, [selectedRun]);
  useEffect(() => {
    (window as any).snapshot = snapshot;
  }, [snapshot]);

  const refreshJobs = async () => {
    const result = await api<{ jobs: JobRecord[] }>("/api/jobs");
    setJobs(result.jobs);
  };
  const refreshExperiments = async () => {
    const result = await api<{ experiments: ExperimentRecord[] }>("/api/experiments");
    setExperiments(result.experiments);
  };

  const refreshRunFor = async (id: string, runId: string | null) => {
    const result = await api<Snapshot>(`/api/jobs/${id}${runId ? "?run_id=" + runId : ""}`);
    (window as any).snapshot = result;
    const fingerprint = JSON.stringify([
      result.job,
      result.artifacts,
      result.events,
      result.versions,
      result.latest_run_id,
    ]);
    if (fingerprint !== fingerprintRef.current) {
      fingerprintRef.current = fingerprint;
      setSnapshot(result);
    }
    const error = result.bundle?.error || result.job.error;
    if (error) notice(error.message || "运行未完成，请查看运行详情。", true);
    return result;
  };

  const refreshRun = async () => {
    if (!currentJob) return;
    const jobId = currentJob,
      runId = selectedRun;
    const result = await refreshRunFor(jobId, runId);
    if (currentJob !== jobId || selectedRun !== runId) return result;
    return result;
  };

  const refreshExperiment = async () => {
    if (!currentExperiment) return;
    const result = await api<any>(`/api/experiments/${currentExperiment}`);
    setExperimentSnapshot(result);
  };

  const refreshTasks = async () => {
    const { tasks } = await api<{ tasks: any[] }>("/api/tasks");
    setTaskOptions(tasks);
  };

  // 轮询:与原实现一致的两个节奏,通过 ref 读取最新状态。
  const stateRef = useRef<any>({});
  stateRef.current = {
    currentJob,
    currentExperiment,
    refreshJobs,
    refreshRun,
    refreshExperiments,
    refreshExperiment,
    notice,
  };
  useEffect(() => {
    const jobsTimer = setInterval(async () => {
      const { currentJob, refreshJobs, refreshRun, notice } = stateRef.current;
      try {
        await refreshJobs();
        if (currentJob) await refreshRun();
      } catch (error) {
        notice((error as Error).message, true);
      }
    }, 1500);
    const experimentTimer = setInterval(async () => {
      const { currentExperiment, refreshExperiments, refreshExperiment, notice } = stateRef.current;
      try {
        await refreshExperiments();
        if (currentExperiment) await refreshExperiment();
      } catch (error) {
        notice((error as Error).message, true);
      }
    }, 3000);
    return () => {
      clearInterval(jobsTimer);
      clearInterval(experimentTimer);
    };
  }, []);

  // ---- 配置表单 ----

  const methodManifest = plugins.find(
    (p) => p.manifest.plugin_id === config.method?.plugin_id,
  )?.manifest;
  const backendManifest = plugins.find(
    (p) => p.manifest.plugin_id === config.model_backend?.plugin_id,
  )?.manifest;
  const compatibleSolvers = methodManifest?.capabilities.solvers?.filter((id: string) => {
    const solver = plugins.find((p) => p.manifest.plugin_id === id)?.manifest;
    return (
      !backendManifest?.capabilities.handle_profile ||
      !solver?.capabilities.handle_profiles ||
      solver.capabilities.handle_profiles.includes(backendManifest.capabilities.handle_profile)
    );
  });

  const selectOptions = useMemo(() => {
    const build = (kind: string, selected: string | undefined, allowed?: string[]) => {
      const options: { value: string; label: string; disabled?: boolean }[] = plugins
        .filter(
          (p) =>
            p.manifest.kind === kind &&
            !p.manifest.capabilities.human_assisted &&
            (!allowed || allowed.includes(p.manifest.plugin_id)),
        )
        .map((p) => ({
          value: p.manifest.plugin_id,
          label:
            kind === "method"
              ? shortMethod(p.manifest.plugin_id)
              : kind === "solver_backend"
                ? p.manifest.plugin_id.split(".").at(-1)!.toUpperCase()
                : p.manifest.display_name,
        }));
      if (selected && !options.some((option) => option.value === selected))
        options.push({ value: selected, label: "当前配置不可用 · " + selected, disabled: true });
      return options;
    };
    return {
      method: build("method", config.method?.plugin_id),
      provider: build("llm_provider", config.llm?.provider_plugin_id),
      backend: build("model_backend", config.model_backend?.plugin_id),
      solver: build("solver_backend", config.solver?.plugin_id, compatibleSolvers),
    };
  }, [plugins, config.method?.plugin_id, config.llm?.provider_plugin_id, config.model_backend?.plugin_id, config.solver?.plugin_id, compatibleSolvers]);

  const solverSelectionDisabled = Boolean(
    selectOptions.solver.find((option) => option.value === config.solver?.plugin_id)?.disabled,
  );

  const showConfig = (next: RunConfig) => {
    setConfigJson(pretty(next));
    setModelText(next.llm?.model || "");
    setBaseUrlText(next.llm?.config?.base_url || "");
    setBudgetText({
      attempt: String(next.budget.max_llm_attempts ?? ""),
      token: String(next.budget.max_total_tokens ?? ""),
      wall: String(next.budget.wall_time_s ?? ""),
      solver: String(next.budget.max_solver_calls ?? ""),
    });
  };

  const readConfig = (): RunConfig => {
    const next = JSON.parse(configJson);
    next.llm.model = modelText;
    if (next.llm.provider_plugin_id !== "llm4om.providers.mock")
      next.llm.config.base_url = baseUrlText;
    next.budget.max_total_tokens = Number(budgetText.token);
    next.budget.wall_time_s = Number(budgetText.wall);
    next.budget.max_llm_attempts = Number(budgetText.attempt);
    next.budget.max_solver_calls = Number(budgetText.solver);
    setConfig(next);
    setConfigJson(pretty(next));
    return next;
  };

  const commitBudget = () => {
    try {
      readConfig();
    } catch (error) {
      notice((error as Error).message, true);
    }
  };

  const chooseMethod = (method: string) => {
    const next = { ...config, method: { ...(config.method || {}) } } as RunConfig;
    const switched: string[] = [];
    if (["llm4om.methods.optimus", "llm4om.methods.optimus_inline"].includes(method)) {
      next.method = {
        plugin_id: method,
        config:
          method === "llm4om.methods.optimus_inline"
            ? { rag_mode: null }
            : { rag_mode: null, params_data_id: "params", labels_data_id: "labels" },
      };
      next.model_backend = { ...next.model_backend, plugin_id: "llm4om.model_backends.gurobipy" };
      next.solver = { ...next.solver, plugin_id: "llm4om.solvers.gurobi" };
      delete next.compiler;
      switched.push("建模后端 gurobipy", "求解器 Gurobi");
    } else if (method === "llm4om.methods.coe") {
      next.method = {
        plugin_id: method,
        config: { max_collaborate_nums: 1, enable_reflection: true, max_trials: 2, seed: 0 },
      };
      next.model_backend = { ...next.model_backend, plugin_id: "llm4om.model_backends.gurobipy" };
      next.solver = { ...next.solver, plugin_id: "llm4om.solvers.gurobi" };
      delete next.compiler;
      switched.push("建模后端 gurobipy", "求解器 Gurobi");
    } else if (["llm4om.methods.direct", "llm4om.methods.feedback_repair"].includes(method)) {
      next.method = {
        plugin_id: method,
        config: { formulation_mode: "five_element", output_mode: "lp_ir" },
      };
      next.model_backend = { ...next.model_backend, plugin_id: "llm4om.model_backends.pyomo_factory" };
      next.solver = { ...next.solver, plugin_id: "llm4om.solvers.highs" };
      next.compiler = { plugin_id: "llm4om.compilers.lp_ir_to_pyomo" };
      switched.push("建模后端 pyomo_factory", "求解器 HiGHS", "编译器 lp_ir_to_pyomo");
    } else next.method = { plugin_id: method, config: {} };
    const classical = /optimus|coe/.test(method);
    next.budget = {
      ...next.budget,
      ...(classical
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
          }),
    };
    setConfig(next);
    showConfig(next);
    setCompatNote(
      switched.length
        ? "已按该方法声明的能力切换:" + switched.join(" · ") + "。可在下方手动调整。"
        : "",
    );
  };

  // ---- 任务提交与打开 ----

  const openJob = async (id: string, runId: string | null = null) => {
    setSelectedRun(runId);
    setArtifactSelectedByUser(false);
    setEditOpen(false);
    setSnapshot(null);
    fingerprintRef.current = "";
    setArtifactChoice("");
    setCurrentExperiment(null);
    setCurrentJob(id);
    setView("run");
    const result = await refreshRunFor(id, runId);
    if (result?.bundle?.stages?.formulation?.status === "not_available") setActiveTab("code");
    await refreshJobs();
  };

  const submitRun = async () => {
    try {
      setSubmitting(true);
      const next = readConfig();
      const payload: any = {
        description,
        config: next,
        data: uploads.map(({ data_id, format, base64, schema }) => ({
          data_id,
          format,
          base64,
          ...(schema ? { schema } : {}),
        })),
      };
      if (problemJson.trim()) {
        payload.problem = JSON.parse(problemJson);
        payload.problem.description = description;
      }
      const job = await api<JobRecord>("/api/jobs", payload);
      notice("运行已提交。");
      await openJob(job.job_id);
    } catch (error) {
      notice((error as Error).message, true);
    } finally {
      setSubmitting(false);
    }
  };

  const runDoctor = async () => {
    try {
      setDoctorBusy(true);
      setDoctorResult(null);
      notice("正在检查实际环境与兼容路径…");
      const result = await api<any>("/api/doctor", {
        config: readConfig(),
        check_connectivity: checkConnectivity,
      });
      setEnvironmentText(pretty(result));
      setDoctorResult(result);
      notice(
        result.connectivity_checks.status === "failed"
          ? "配置检查通过，模型接口检查未通过。"
          : "配置检查完成。",
        result.connectivity_checks.status === "failed",
      );
    } catch (error) {
      notice((error as Error).message, true);
    } finally {
      setDoctorBusy(false);
    }
  };

  // ---- 运行视图派生数据 ----

  const contents = snapshot?.contents || {};
  const publicValue = (ref: any) => artifactKey(snapshot, ref);
  const solve = contents[publicValue(snapshot?.bundle?.solve_result_ref) || ""];
  const solution = contents[publicValue(solve?.solution_ref) || ""];
  const model = contents[publicValue(snapshot?.bundle?.model_artifact_ref) || ""];
  const code = contents[publicValue(model?.code_ref) || ""];
  const solvedIR =
    code?.provenance?.origin === "deterministic_compilation"
      ? contents[publicValue(code.provenance.source_ir_ref) || ""]
      : null;

  const artifactEntries = useMemo(() => {
    if (!snapshot) return [] as [string, any][];
    const entries = Object.entries(snapshot.contents || {}).filter(([key]) =>
      tabPatterns[activeTab].test(key),
    );
    if (activeTab === "diagnostics") entries.unshift(["运行事件", snapshot.events || []]);
    const finalCandidate = snapshot.bundle?.final_candidate_id || "001";
    const score = ([name, value]: [string, any]) =>
      activeTab === "candidates"
        ? Number(name === "candidate-selection.json")
        : activeTab === "code"
          ? name === `candidates/${finalCandidate}/model.py`
            ? 2
            : Number(name.endsWith(".py"))
          : value?.representation
            ? 100 + Number(name.startsWith(`candidates/${finalCandidate}/`))
            : Number(name.match(/method\/state_(\d+)/)?.[1] || 0);
    entries.sort((a, b) => score(b) - score(a));
    return entries;
  }, [snapshot, activeTab]);

  useEffect(() => {
    if (!snapshot) return;
    const previous = artifactChoice;
    const values = artifactEntries.map(([name]) => name);
    if (artifactSelectedByUser && values.includes(previous)) setArtifactChoice(previous);
    else setArtifactChoice(values[0] || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifactEntries, artifactSelectedByUser]);

  const address = (runId: string | null | undefined) => {
    const url = new URL("/", location.origin);
    if (currentJob) {
      url.searchParams.set("job", currentJob);
      if (runId) url.searchParams.set("run", runId);
      if (activeTab !== "formulation") url.searchParams.set("tab", activeTab);
      if (artifactSelectedByUser && artifactChoice) url.searchParams.set("artifact", artifactChoice);
    }
    return url;
  };
  const runLinkAddress = address(snapshot?.job?.run_id);
  const runLink = {
    hidden: !currentJob || !snapshot?.job?.run_id,
    href: runLinkAddress.href,
  };
  useEffect(() => {
    const current = address(selectedRun);
    history.replaceState(null, "", current.pathname + current.search);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentJob, selectedRun, activeTab, artifactSelectedByUser, artifactChoice, snapshot?.job?.run_id]);

  const selectedArtifact = artifactEntries.find(([name]) => name === artifactChoice)?.[1];
  const selectedName = artifactChoice;
  const candidatePrefix = selectedName.startsWith("candidates/")
    ? selectedName.split("/")[1]
    : null;
  const isolatedContents = candidatePrefix
    ? Object.fromEntries(
        Object.entries(contents).filter(
          ([key]) => !key.startsWith("candidates/") || key.startsWith(`candidates/${candidatePrefix}/`),
        ),
      )
    : contents;
  const recordView =
    activeTab === "formulation" && selectedName.startsWith("method/state_")
      ? { representation: { state: selectedArtifact } }
      : selectedArtifact;

  const clarificationRequest = contents[publicValue(snapshot?.bundle?.clarification_request_ref) || ""];

  const openArtifact = (tab: string, key?: string) => {
    setActiveTab(tab);
    if (key) {
      setArtifactChoice(key);
      setArtifactSelectedByUser(true);
    }
  };

  // ---- 人工编辑 ----

  const loadEditTemplate = async (operation = editOperation) => {
    if (!currentJob) return;
    const parent = { job: currentJob, run: snapshot!.job.run_id! };
    setEditBusy(true);
    try {
      const document = await api<any>(
        `/api/jobs/${parent.job}/edit-template?operation=${operation}&run_id=${parent.run}`,
      );
      if (currentJob !== parent.job || snapshot?.job?.run_id !== parent.run)
        throw new Error("运行版本已改变，请重新载入编辑内容。");
      setEditDocumentText(pretty(document));
      editParent.current = parent;
      (window as any).editParent = parent;
      setEditTemplate(document);
      setEditBase(structuredClone(document));
      setEditOverrides({});
    } finally {
      setEditBusy(false);
    }
  };

  const submitEdit = async () => {
    try {
      setEditBusy(true);
      if (!editTemplate || currentJob !== editParent.current?.job)
        throw new Error("请先载入当前运行的编辑内容。");
      const edits = buildDoc(editBase, editOverrides, editTemplate);
      const problem = await validateEdit(edits);
      setEditDocumentText(pretty(edits));
      await api(`/api/jobs/${currentJob}/edit`, {
        edits: problem,
        parent_run_id: editParent.current!.run,
      });
      setSelectedRun(null);
      fingerprintRef.current = "";
      setEditOpen(false);
      notice("人工修订已提交。原运行保留，新结果会记录父运行和预算。");
      await refreshRun();
    } catch (error) {
      notice((error as Error).message, true);
    } finally {
      setEditBusy(false);
    }
  };

  const validateEdit = async (edits: any) => {
    const message = validateRevision(edits, editTemplate, contents["budget-ledger.json"]);
    if (message) throw new Error(message);
    const latest = await api<Snapshot>(`/api/jobs/${currentJob}?run_id=${editParent.current!.run}`);
    if (latest.job.run_id !== editParent.current!.run)
      throw new Error("运行版本已改变，请重新载入编辑内容。");
    return edits;
  };

  const editDoc = useMemo(
    () => (editBase ? buildDoc(editBase, editOverrides, editTemplate) : null),
    [editBase, editOverrides, editTemplate],
  );
  useEffect(() => {
    if (editDoc && editOpen) setEditDocumentText(pretty(editDoc));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editDoc]);

  const structuralMutation = (mutate: (doc: any) => void) => {
    const next = buildDoc(editBase, editOverrides, editTemplate);
    mutate(next);
    setEditBase(next);
    setEditOverrides({});
  };

  // ---- 启动 ----

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    (window as any).currentJob = null;
    (window as any).selectedRun = null;
    (window as any).snapshot = null;
    (window as any).editParent = null;
    (async () => {
      try {
        const params = new URLSearchParams(location.search);
        const result = await api<any>("/api/bootstrap");
        setApiToken(result.token);
        setDataFilesReady(true);
        setConfig(result.config);
        showConfig(result.config);
        setPlugins(result.plugins);
        setEnvironmentText(pretty(result.plugins));
        await refreshJobs();
        refreshExperiments().catch(() => {});
        const job = params.get("job"),
          run = params.get("run");
        if (job) {
          if (!/^[a-f0-9]{32}$/.test(job) || (run && !/^[a-f0-9]{32}$/.test(run)))
            throw new Error("运行链接中的标识无效。");
          await openJob(job, run);
          const tab = params.get("tab");
          if (tab && ["formulation", "code", "candidates", "diagnostics", "data"].includes(tab))
            setActiveTab(tab);
          const artifact = params.get("artifact");
          if (artifact) {
            setArtifactSelectedByUser(true);
            setArtifactChoice(artifact);
          }
        }
      } catch (error) {
        notice((error as Error).message, true);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- 渲染 ----

  const runBusy = ["running", "queued"].includes(snapshot?.job.status || "");

  return (
    <>
      <aside className="sidebar">
        <a className="brand" href="/">
          <span className="brand-symbol">∑</span> LLM<span>4</span>OM
        </a>
        <p className="subtitle">优化建模工作台</p>
        <button
          id="new-run"
          className={"nav" + (view === "editor" ? " active" : "")}
          onClick={() => {
            setCurrentExperiment(null);
            setCurrentJob(null);
            setSelectedRun(null);
            setSnapshot(null);
            setActiveTab("formulation");
            setView("editor");
            notice("");
          }}
        >
          ＋ 新建问题
        </button>
        <details className="developer-nav">
          <summary>开发者工具</summary>
          <button
            id="new-experiment"
            className="nav"
            onClick={async () => {
              setCurrentJob(null);
              setCurrentExperiment(null);
              setView("experiment-editor");
              setExperimentConfigurations(pretty([{ id: "configured-method", config: config }]));
              setExperimentBudget(
                pretty({
                  max_llm_attempts: 100,
                  max_total_tokens: 1000000,
                  max_solver_calls: 100,
                  wall_time_s: 3600,
                  max_concurrency: 2,
                }),
              );
              try {
                await refreshTasks();
              } catch (error) {
                notice((error as Error).message, true);
              }
            }}
          >
            实验管理
          </button>
          <div id="experiments">
            {experiments.map((experiment) => (
              <button
                key={experiment.experiment_id}
                className="job"
                onClick={() => {
                  setCurrentJob(null);
                  setCurrentExperiment(experiment.experiment_id);
                  setView("experiment-result");
                  refreshExperiment();
                }}
              >
                {`${experiment.status} · ${experiment.task_count}任务 × ${experiment.configuration_count}配置 × ${experiment.repeats}`}
              </button>
            ))}
          </div>
        </details>
        <h2 className="small-heading">运行记录</h2>
        <div id="jobs" aria-label="运行记录">
          {jobs.map((job) => (
            <button
              key={job.job_id}
              className={
                "job" +
                (job.job_id === currentJob ? " selected" : "") +
                (["failed", "cancelled"].includes(job.status) ? " failed" : "")
              }
              onClick={() => openJob(job.job_id)}
            >
              <strong>{job.description}</strong>
              <span>{`${status(job.status)} · ${shortMethod(job.method)}`}</span>
            </button>
          ))}
        </div>
        <p className="sidebar-footer">自然语言 → 优化模型 → 决策</p>
      </aside>
      <main>
        <header>
          <h1>
            {{ editor: "开始建模", run: "运行结果", "experiment-editor": "批量实验", "experiment-result": "实验结果" }[view] || "开始建模"}
          </h1>
        </header>
        <div id="notice" role="status" hidden={!noticeState.text}>
          {noticeState.text}
        </div>

        {view === "editor" ? (
          <section id="editor" className="editor-grid">
            <div className="panel problem-panel">
              <div className="panel-title">
                <h2>描述问题</h2>
                <label className="file-button">
                  导入问题
                  <input
                    id="problem-file"
                    type="file"
                    accept=".json"
                    onChange={async (event) => {
                      const file = event.target.files?.[0];
                      if (!file) return;
                      try {
                        const problem = JSON.parse(await file.text());
                        setProblemJson(pretty(problem));
                        setDescription(problem.description);
                        notice("问题规格已导入。请同时添加其中引用的公开数据。");
                      } catch (error) {
                        notice((error as Error).message, true);
                      }
                    }}
                  />
                </label>
              </div>
              <label htmlFor="description">用自然语言描述你的目标、决策和限制</label>
              <textarea
                id="description"
                rows={9}
                placeholder={
                  "例如：我想制定工厂的生产计划。在原料和工时有限的情况下，决定每种产品的生产数量，让总利润最大。"
                }
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
              <div className="example-chips">
                <span>从示例开始</span>
                {Object.entries(problemExamples).map(([key, text]) => (
                  <span key={key}>
                    <button
                      type="button"
                      className="example-chip"
                      data-example={key}
                      id={key === "production" ? "load-example" : undefined}
                      onClick={() => {
                        setDescription(text);
                        setProblemJson("");
                        setUploads([]);
                      }}
                    >
                      {{ production: "生产计划", projects: "项目选择", diet: "配餐优化" }[key]}
                    </button>
                  </span>
                ))}
              </div>
              <div className="upload-line">
                <label className="file-button">
                  ＋ 添加 CSV / JSON
                  <input
                    id="data-files"
                    type="file"
                    accept=".csv,.json"
                    disabled={!dataFilesReady}
                    multiple
                    onChange={async (event) => {
                      const files = Array.from(event.target.files || []);
                      for (const file of files) {
                        if (file.size > 8 * 1024 * 1024) {
                          notice("单个文件不能超过 8 MiB。", true);
                          continue;
                        }
                        const bytes = new Uint8Array(await file.arrayBuffer());
                        let binary = "";
                        for (let start = 0; start < bytes.length; start += 16384)
                          binary += String.fromCharCode(...bytes.subarray(start, start + 16384));
                        const upload: UploadItem = {
                          name: file.name,
                          size: file.size,
                          data_id: file.name.replace(/\.[^.]+$/, ""),
                          format: file.name.toLowerCase().endsWith(".csv") ? "csv" : "json",
                          base64: btoa(binary),
                        };
                        setUploads((prior) => [...prior, upload]);
                        try {
                          const preview = await api<any>("/api/data-preview", {
                            format: upload.format,
                            base64: upload.base64,
                          });
                          upload.preview = preview;
                        } catch (error) {
                          upload.previewError = "文件预览未完成：" + (error as Error).message;
                        }
                        setUploads((prior) => [...prior]);
                      }
                      event.target.value = "";
                    }}
                  />
                </label>
              </div>
              <div id="uploads">
                {uploads.map((upload, index) => (
                  <div className="upload-card" key={upload.name + index}>
                    <div className="upload-meta">
                      <input
                        aria-label="公开数据 ID"
                        value={upload.data_id}
                        onChange={(event) =>
                          setUploads((prior) =>
                            prior.map((item, i) =>
                              i === index ? { ...item, data_id: event.target.value } : item,
                            ),
                          )
                        }
                      />
                      <span>{`${upload.name} · ${upload.size} bytes`}</span>
                      <button
                        onClick={() => setUploads((prior) => prior.filter((_, i) => i !== index))}
                      >
                        移除
                      </button>
                    </div>
                    {upload.preview ? (
                      <>
                        <UploadPreview preview={upload.preview} />
                        <p className="hint">
                          {upload.preview.display_truncated
                            ? `显示 ${upload.preview.rows.length} / ${upload.preview.total_items} 行或字段，最多16列；长文本只显示前256字符。完整文件会用于提交。`
                            : `共 ${upload.preview.total_items} 行或字段。预览保留原始值，不改变提交的数据。`}
                        </p>
                      </>
                    ) : (
                      <p className="hint">{upload.previewError || "正在读取文件预览…"}</p>
                    )}
                    <details>
                      <summary>
                        {upload.format === "csv"
                          ? "高级：列类型与唯一键（CSV 默认保留原始字符串）"
                          : "高级：数据 schema"}
                      </summary>
                      <textarea
                        rows={6}
                        aria-label="公开数据 schema"
                        defaultValue={upload.schema ? pretty(upload.schema) : ""}
                        onChange={(event) => {
                          try {
                            const schema = event.target.value.trim()
                              ? JSON.parse(event.target.value)
                              : undefined;
                            setUploads((prior) =>
                              prior.map((item, i) => (i === index ? { ...item, schema } : item)),
                            );
                          } catch (error) {
                            notice((error as Error).message, true);
                          }
                        }}
                      />
                    </details>
                  </div>
                ))}
              </div>
              <details>
                <summary>高级：直接编辑问题 JSON</summary>
                <textarea
                  id="problem-json"
                  rows={12}
                  aria-label="完整公开问题规格"
                  placeholder="可导入或编辑 ProblemSpec；留空时根据上述描述创建。"
                  value={problemJson}
                  onChange={(event) => setProblemJson(event.target.value)}
                />
              </details>
            </div>
            <div className="panel settings-panel">
              <h2>建模方法</h2>
              <div className="field-grid">
                <label>
                  建模方法
                  <select
                    id="method"
                    value={config.method?.plugin_id || ""}
                    onChange={(event) => chooseMethod(event.target.value)}
                  >
                    {selectOptions.method.map((option) => (
                      <option key={option.value} value={option.value} disabled={option.disabled}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="advanced-field">
                  LLM 提供方
                  <select
                    id="provider"
                    value={config.llm?.provider_plugin_id || ""}
                    onChange={(event) => {
                      const next = {
                        ...config,
                        llm: { ...config.llm, provider_plugin_id: event.target.value },
                      };
                      setConfig(next);
                      setConfigJson(pretty(next));
                    }}
                  >
                    {selectOptions.provider.map((option) => (
                      <option key={option.value} value={option.value} disabled={option.disabled}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="wide">
                  模型
                  <input
                    id="model"
                    placeholder="模型 ID"
                    value={modelText}
                    onChange={(event) => setModelText(event.target.value)}
                  />
                </label>
                <label className="advanced-field">
                  建模后端
                  <select
                    id="backend"
                    value={config.model_backend?.plugin_id || ""}
                    onChange={(event) => {
                      const next = {
                        ...config,
                        model_backend: { ...config.model_backend, plugin_id: event.target.value },
                      };
                      setConfig(next);
                      showConfig(next);
                    }}
                  >
                    {selectOptions.backend.map((option) => (
                      <option key={option.value} value={option.value} disabled={option.disabled}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  求解器
                  <select
                    id="solver"
                    value={config.solver?.plugin_id || ""}
                    onChange={(event) => {
                      const next = { ...config, solver: { ...config.solver, plugin_id: event.target.value } };
                      setConfig(next);
                      showConfig(next);
                    }}
                  >
                    {selectOptions.solver.map((option) => (
                      <option key={option.value} value={option.value} disabled={option.disabled}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="wide advanced-field">
                  Provider URL
                  <input
                    id="base-url"
                    type="url"
                    value={baseUrlText}
                    onChange={(event) => setBaseUrlText(event.target.value)}
                  />
                </label>
              </div>
              <div id="method-explainer" className="method-explainer method-explainer-card">
                <p>{methodExplainers[config.method?.plugin_id] ||
                  "按所选方法的实际流程建模，保存公开步骤和输出。"}</p>
                {methodRequirements[config.method?.plugin_id] ? (
                  <p className="hint">{methodRequirements[config.method?.plugin_id]}</p>
                ) : null}
                {compatNote ? <p className="compat-note">{compatNote}</p> : null}
                {solverSelectionDisabled ? (
                  <p className="compat-note warning">
                    当前求解器与所选方法或建模后端不兼容;请选择可用求解器后再提交。
                  </p>
                ) : null}
              </div>
              <div id="budget-summary" className="budget-visual" aria-live="polite">
                <span className="pill">模型请求 ≤{config.budget?.max_llm_attempts ?? "—"}</span>
                <span className="pill">Token ≤{format(config.budget?.max_total_tokens)}</span>
                <span className="pill">时间 ≤{format(config.budget?.wall_time_s)} 秒</span>
                <span className="pill">求解 ≤{config.budget?.max_solver_calls ?? "—"}</span>
                {/optimus|coe/.test(config.method?.plugin_id || "") ? (
                  <p className="hint">此方法真实请求与费用显著更高。</p>
                ) : null}
              </div>
              <details className="advanced-controls">
                <summary>高级设置</summary>
                <div className="field-grid">
                  <label>
                    模型请求次数
                    <input
                      id="attempt-budget"
                      type="number"
                      min="1"
                      value={budgetText.attempt}
                      onChange={(event) => setBudgetText((prior) => ({ ...prior, attempt: event.target.value }))}
                      onBlur={commitBudget}
                    />
                  </label>
                  <label>
                    总 Token
                    <input
                      id="token-budget"
                      type="number"
                      min="1"
                      value={budgetText.token}
                      onChange={(event) => setBudgetText((prior) => ({ ...prior, token: event.target.value }))}
                      onBlur={commitBudget}
                    />
                  </label>
                  <label>
                    时间（秒）
                    <input
                      id="wall-budget"
                      type="number"
                      min="0.1"
                      step="any"
                      value={budgetText.wall}
                      onChange={(event) => setBudgetText((prior) => ({ ...prior, wall: event.target.value }))}
                      onBlur={commitBudget}
                    />
                  </label>
                  <label>
                    求解次数
                    <input
                      id="solver-budget"
                      type="number"
                      min="0"
                      value={budgetText.solver}
                      onChange={(event) => setBudgetText((prior) => ({ ...prior, solver: event.target.value }))}
                      onBlur={commitBudget}
                    />
                  </label>
                </div>
                <textarea
                  id="config-json"
                  rows={15}
                  aria-label="完整 RunConfig"
                  value={configJson}
                  onChange={(event) => setConfigJson(event.target.value)}
                />
                <button
                  id="apply-config"
                  className="secondary"
                  onClick={() => {
                    try {
                      const next = JSON.parse(configJson);
                      setConfig(next);
                      showConfig(next);
                      notice("完整配置已应用。");
                    } catch (error) {
                      notice((error as Error).message, true);
                    }
                  }}
                >
                  应用完整配置
                </button>
              </details>
              <label className="connectivity-option">
                <input
                  id="check-connectivity"
                  type="checkbox"
                  checked={checkConnectivity}
                  onChange={(event) => setCheckConnectivity(event.target.checked)}
                />
                检查配置时联网测试模型接口
              </label>
              <div className="actions">
                <button id="doctor" className="secondary" disabled={doctorBusy} onClick={runDoctor}>
                  检查配置
                </button>
                <button id="submit" className="primary" disabled={submitting || solverSelectionDisabled} onClick={submitRun}>
                  开始建模 →
                </button>
              </div>
              <div id="doctor-result" className="doctor-result" hidden={!doctorResult}>
                {doctorResult ? <Connectivity report={doctorResult} /> : null}
              </div>
            </div>
          </section>
        ) : null}

        {view === "experiment-editor" ? (
          <section id="experiment-editor" className="panel">
            <h2>批量 benchmark 实验</h2>
            <p className="hint">
              先使用 CLI 将任务冻结导入项目 runs/ 或工作区 tasks/。每个配置明确选择方法、模型、后端与预算。
            </p>
            <label htmlFor="task-choice">冻结任务</label>
            <select id="task-choice" multiple size={5}>
              {taskOptions.map((task) => (
                <option key={task.task_id} value={task.task_id}>
                  {`${task.source.dataset_id} · ${task.source.source_version} · ${task.N_selected}样本 · ${task.protocol_id}`}
                </option>
              ))}
            </select>
            <button id="refresh-tasks" className="secondary" onClick={() => refreshTasks().catch((error) => notice(error.message, true))}>
              刷新任务
            </button>
            <label htmlFor="experiment-configurations">配置变体 JSON（id 与完整 config）</label>
            <textarea
              id="experiment-configurations"
              rows={16}
              value={experimentConfigurations}
              onChange={(event) => setExperimentConfigurations(event.target.value)}
            />
            <label htmlFor="experiment-repeats">重复次数</label>
            <input id="experiment-repeats" type="number" min="1" max="1000" defaultValue="1" />
            <label htmlFor="experiment-budget">实验总预算 JSON</label>
            <textarea
              id="experiment-budget"
              rows={7}
              value={experimentBudget}
              onChange={(event) => setExperimentBudget(event.target.value)}
            />
            <label htmlFor="experiment-exclusions">显式排除 JSON（task_id、configuration_id、reason）</label>
            <textarea id="experiment-exclusions" rows={3} defaultValue="[]" />
            <button
              id="submit-experiment"
              className="primary"
              onClick={async () => {
                try {
                  const result = await api<{ experiment_id: string }>("/api/experiments", {
                    task_ids: Array.from(
                      document.querySelectorAll<HTMLOptionElement>("#task-choice option"),
                    )
                      .filter((option) => option.selected)
                      .map((option) => option.value),
                    configurations: JSON.parse(experimentConfigurations),
                    repeats: Number((document.getElementById("experiment-repeats") as HTMLInputElement).value),
                    budget: JSON.parse(experimentBudget),
                    exclusions: JSON.parse(
                      (document.getElementById("experiment-exclusions") as HTMLTextAreaElement).value,
                    ),
                  });
                  setCurrentExperiment(result.experiment_id);
                  setView("experiment-result");
                  await refreshExperiments();
                  notice("实验已提交。");
                } catch (error) {
                  notice((error as Error).message, true);
                }
              }}
            >
              运行批量实验
            </button>
          </section>
        ) : null}

        {view === "experiment-result" && experimentSnapshot ? (
          <ExperimentResult
            snapshot={experimentSnapshot}
            onCancelResume={async (action) => {
              try {
                await api(`/api/experiments/${currentExperiment}/${action}`, {});
                notice("实验操作已提交。");
                await refreshExperiment();
              } catch (error) {
                notice((error as Error).message, true);
              }
            }}
          />
        ) : null}

        {view === "run" && snapshot ? (
          <section id="result">
            <div className="run-heading">
              <div>
                <p className="eyebrow">建模与求解</p>
                <h2 id="run-title">{snapshot.job.description}</h2>
                <p id="run-meta">
                  {`${status(snapshot.job.status)} · ${
                    snapshot.bundle?.assisted &&
                    (contents["public-config.json"]?.method?.plugin_id || snapshot.job.method) !==
                      "llm4om.methods.assisted"
                      ? "人工辅助 · "
                      : ""
                  }${shortMethod(contents["public-config.json"]?.method?.plugin_id || snapshot.job.method)} · ${
                    snapshot.job.run_id || "正在准备"
                  }`}
                </p>
                <label className="version-selector" hidden={(snapshot.versions || []).length < 2}>
                  运行版本
                  <select
                    id="run-version"
                    aria-label="选择运行版本"
                    value={selectedRun || ""}
                    onChange={async (event) => {
                      setSelectedRun(event.target.value || null);
                      fingerprintRef.current = "";
                      setSnapshot(null);
                      setEditOpen(false);
                      setArtifactChoice("");
                      setArtifactSelectedByUser(false);
                      try {
                        await refreshRun();
                      } catch (error) {
                        notice((error as Error).message, true);
                      }
                    }}
                  >
                    <option value="">最新版本 / 正在执行</option>
                    {(snapshot.versions || []).map((version) => (
                      <option key={version.run_id} value={version.run_id}>
                        {(version.assisted ? "人工修订" : "运行") +
                          " · " +
                          status(version.status) +
                          " · " +
                          version.run_id.slice(0, 8) +
                          (version.parent_run_id
                            ? " ← " + version.parent_run_id.slice(0, 8)
                            : " · 原始版本")}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="actions">
                <button
                  id="cancel"
                  className="secondary"
                  hidden={snapshot.historical || !runBusy}
                  onClick={async () => {
                    try {
                      await api(`/api/jobs/${currentJob}/cancel`, {});
                      notice("操作已提交。");
                      await refreshRun();
                    } catch (error) {
                      notice((error as Error).message, true);
                    }
                  }}
                >
                  取消
                </button>
                <button
                  id="resume"
                  className="secondary"
                  hidden={snapshot.historical || !["failed", "cancelled"].includes(snapshot.job.status)}
                  onClick={async () => {
                    try {
                      await api(`/api/jobs/${currentJob}/resume`, {});
                      notice("操作已提交。");
                      await refreshRun();
                    } catch (error) {
                      notice((error as Error).message, true);
                    }
                  }}
                >
                  继续恢复
                </button>
                <button
                  id="rerun"
                  className="secondary"
                  hidden={Boolean(snapshot.historical)}
                  onClick={async () => {
                    try {
                      if (
                        !confirm("创建派生运行并继承预算记录。真实 LLM 可能产生新的请求费用，是否继续？")
                      )
                        return;
                      await api(`/api/jobs/${currentJob}/resume`, { strategy: "rerun" });
                      notice("操作已提交。");
                      await refreshRun();
                    } catch (error) {
                      notice((error as Error).message, true);
                    }
                  }}
                >
                  派生重跑
                </button>
                <button
                  id="edit-run"
                  className="secondary"
                  disabled={runBusy}
                  onClick={async () => {
                    try {
                      setEditOpen(true);
                      await loadEditTemplate();
                      document.getElementById("assisted-editor")?.scrollIntoView({ behavior: "smooth", block: "start" });
                    } catch (error) {
                      notice((error as Error).message, true);
                    }
                  }}
                >
                  编辑新版本
                </button>
                <a id="run-link" className="secondary" href={runLink.href} hidden={runLink.hidden}>
                  此版本链接
                </a>
                <a
                  id="export"
                  className="secondary"
                  href={`/api/jobs/${currentJob}/export${selectedRun ? "?run_id=" + selectedRun : ""}`}
                  hidden={!snapshot.bundle}
                >
                  下载结果
                </a>
              </div>
            </div>

            {editOpen ? (
              <section id="assisted-editor" className="panel">
                <h3>编辑并创建新版本</h3>
                <label htmlFor="edit-operation">编辑范围</label>
                <select
                  id="edit-operation"
                  value={editOperation}
                  disabled={editBusy}
                  onChange={(event) => {
                    setEditOperation(event.target.value);
                    loadEditTemplate(event.target.value).catch((error) => notice(error.message, true));
                  }}
                >
                  <option value="code">修改求解代码</option>
                  <option value="problem">修改问题描述与规则</option>
                  <option value="formulation">修改数学模型</option>
                </select>
                <button
                  id="load-edit-template"
                  className="secondary"
                  disabled={editBusy}
                  onClick={() => loadEditTemplate().catch((error) => notice(error.message, true))}
                >
                  重新载入原内容
                </button>
                <p className="hint">
                  原版本会保留。代码修订复用原数学表述；问题修订会重新建模。新结果标记为人工辅助。
                </p>
                {editBase ? (
                  <RevisionFields
                    base={editBase}
                    overrides={editOverrides}
                    onInput={(key, value) => setEditOverrides((prior) => ({ ...prior, [key]: value }))}
                    onRemoveConstraint={(index) =>
                      structuralMutation((doc) => doc.structured_ir.constraints.splice(index, 1))
                    }
                    onAddConstraint={() =>
                      structuralMutation((doc) => {
                        let counter = 1;
                        while (doc.structured_ir.constraints.some((item: any) => item.id === "C_USER_" + counter))
                          counter++;
                        doc.structured_ir.constraints.push({
                          id: "C_USER_" + counter,
                          expression: {
                            constant: 0,
                            terms: doc.structured_ir.variables.map((item: any) => ({
                              variable_id: item.id,
                              coefficient: 0,
                            })),
                          },
                          sense: "le",
                          rhs: 0,
                          requirement_ids: [],
                        });
                      })
                    }
                    ledger={contents["budget-ledger.json"]}
                  />
                ) : (
                  <div id="revision-fields" />
                )}
                <details
                  id="revision-advanced"
                  className="raw-record"
                  ref={(el) => {
                    if (el && editTemplate)
                      el.open = editTemplate.operation === "formulation" && !editTemplate.structured_ir;
                  }}
                >
                  <summary>高级：完整编辑文档</summary>
                  <textarea
                    id="assisted-document"
                    rows={16}
                    aria-label="完整编辑文档 JSON"
                    value={editDocumentText}
                    onChange={(event) => setEditDocumentText(event.target.value)}
                  />
                  <button
                    id="apply-edit-document"
                    className="secondary"
                    onClick={() => {
                      try {
                        const document = JSON.parse(editDocumentText);
                        if (document.operation !== editOperation)
                          throw new Error("完整文档的编辑范围应与当前选择一致。");
                        setEditBase(document);
                        setEditOverrides({});
                        notice("完整编辑文档已应用到表单。");
                      } catch (error) {
                        notice((error as Error).message, true);
                      }
                    }}
                  >
                    应用完整编辑文档
                  </button>
                </details>
                <div className="actions">
                  <button id="submit-edit" className="primary" disabled={editBusy} onClick={submitEdit}>
                    确认修订并运行
                  </button>
                  <button id="close-edit" className="secondary" onClick={() => setEditOpen(false)}>
                    取消编辑
                  </button>
                </div>
              </section>
            ) : null}

            <div id="stages" className="stage-grid">
              {(() => {
                const runningStep =
                  snapshot.job.status === "running" ? activeStep(snapshot) : null;
                return (["formulation", "code", "solve"] as const).map((stage) => {
                  const state =
                    runningStep?.phase === stage
                      ? "running"
                      : ["running", "queued"].includes(snapshot.job.status) &&
                          (!snapshot.bundle?.stages?.[stage]?.status ||
                            snapshot.bundle.stages[stage].status === "not_available")
                        ? "pending"
                        : snapshot.bundle?.stages?.[stage]?.status || "pending";
                  return (
                    <div className={"stage " + state} key={stage}>
                      <strong>
                        {{ formulation: "01 数学表述", code: "02 求解实现", solve: "03 求解结果" }[stage]}
                      </strong>
                      <span>{status(state)}</span>
                    </div>
                  );
                });
              })()}
            </div>
            <div className="experience-grid">
              <aside id="process-panel" className="panel process-panel">
                <StoryFlow
                  snapshot={snapshot}
                  finalObjective={
                    solve
                      ? { value: solve.objective_value ?? null, termination: solve.termination }
                      : null
                  }
                  onOpenArtifact={openArtifact}
                />
              </aside>
              <div className="output-column">
                {snapshot.job.status === "needs_input" && clarificationRequest ? (
                  <Clarification
                    key={clarificationRequest.request_id}
                    request={clarificationRequest}
                    problem={contents["public-problem.json"]}
                    rawRequest={pretty(clarificationRequest)}
                    onSubmit={async (payload) => {
                      await api(`/api/jobs/${currentJob}/resume`, payload as any);
                      notice("回答已提交，正在恢复。");
                      await refreshRun();
                    }}
                    onError={(message) => notice(message, true)}
                  />
                ) : (
                  <div id="clarification" className="panel" hidden />
                )}
                <div id="decision" className="panel">
                  <Decision
                    solve={solve}
                    solution={solution}
                    ledger={contents["budget-ledger.json"]}
                    snapshot={snapshot}
                    solvedIR={solvedIR}
                    onOpenDiagnostics={() => setActiveTab("diagnostics")}
                  />
                </div>
                <div className="tabs" role="tablist">
                  {(
                    [
                      ["formulation", "数学模型"],
                      ["code", "求解代码"],
                      ["candidates", "候选方案"],
                      ["diagnostics", "运行详情"],
                      ["data", "输入数据"],
                    ] as [string, string][]
                  ).map(([tab, label]) => (
                    <button
                      key={tab}
                      className={"tab" + (activeTab === tab ? " active" : "")}
                      data-tab={tab}
                      onClick={() => {
                        setActiveTab(tab);
                        setArtifactSelectedByUser(false);
                      }}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <div className="panel">
                  <div id="output-heading" className="output-heading">
                    {tabHeadings[activeTab]}
                  </div>
                  <select
                    id="artifact-choice"
                    aria-label={activeTab === "candidates" ? "选择原始候选记录" : "选择阶段记录"}
                    hidden={artifactEntries.length < 2}
                    value={artifactChoice}
                    onChange={(event) => {
                      setArtifactChoice(event.target.value);
                      setArtifactSelectedByUser(true);
                    }}
                  >
                    {artifactEntries.map(([name]) => (
                      <option key={name} value={name}>
                        {(name.startsWith("candidates/") ? "候选 " + name.split("/")[1] + " · " : "") +
                          (name === "运行事件" ? "运行事件" : artifactLabel(name))}
                      </option>
                    ))}
                  </select>
                  <div id="model-view" className="model-grid">
                    {activeTab === "candidates" ? (
                      <Candidates snapshot={snapshot} onOpenArtifact={openArtifact} />
                    ) : activeTab === "diagnostics" ? (
                      <RuntimeDetails snapshot={snapshot} />
                    ) : selectedArtifact === undefined &&
                      ["running", "queued", "needs_input"].includes(snapshot.job.status) ? (
                      <div className="empty-view">
                        <div className="empty-icon">◇</div>
                        <h3>
                          {snapshot.job.status === "needs_input"
                            ? "补充信息后继续建模"
                            : activeTab === "code"
                              ? "求解实现正在形成"
                              : "建模输出正在形成"}
                        </h3>
                        <p className="hint">完成的公开产物会自动出现在这里。可以在左侧查看当前的实际步骤。</p>
                      </div>
                    ) : (
                      <Records
                        value={recordView}
                        tab={activeTab}
                        contents={isolatedContents}
                        dataPreviews={snapshot.data_previews}
                      />
                    )}
                  </div>
                  <details className="raw-record">
                    <summary>查看原始记录</summary>
                    <pre id="artifact-content">
                      {pretty(selectedArtifact) || "此阶段尚无可用记录。"}
                    </pre>
                  </details>
                </div>
              </div>
            </div>
          </section>
        ) : null}

        <details id="environment" className="panel">
          <summary>高级：环境与接口信息</summary>
          <pre id="environment-content">{environmentText}</pre>
        </details>
      </main>
    </>
  );
}

function UploadPreview({ preview }: { preview: NonNullable<UploadItem["preview"]> }) {
  return (
    <div className="table-scroll upload-preview">
      <table className="visual-table">
        <thead>
          <tr>
            {preview.columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {preview.rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, cIndex) => (
                <td key={cIndex}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExperimentResult({
  snapshot,
  onCancelResume,
}: {
  snapshot: any;
  onCancelResume: (action: "cancel" | "resume") => Promise<void>;
}) {
  const progress = snapshot.progress || {};
  const match = (name: string) => (row: any) =>
    row[name + "_denominator"]
      ? `${row[name + "_numerator"]}/${row[name + "_denominator"]}`
      : "not_available";
  const renderTable = (columns: [string, any][], rows: any[]) => (
    <table className="visual-table">
      <thead>
        <tr>
          {columns.map(([label]) => (
            <th key={label}>{label}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index}>
            {columns.map(([, key], cIndex) => {
              const value = typeof key === "function" ? key(row) : row[key];
              return (
                <td key={cIndex}>
                  {value === null || value === undefined
                    ? "unknown"
                    : typeof value === "object"
                      ? pretty(value)
                      : String(value)}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
  return (
    <section id="experiment-result">
      <div className="run-heading">
        <div>
          <h2>实验结果与证据</h2>
          <p id="experiment-meta">{`${snapshot.job.status} · ${snapshot.job.experiment_id}`}</p>
        </div>
        <div className="actions">
          <button id="cancel-experiment" className="secondary" onClick={() => onCancelResume("cancel")}>
            取消实验
          </button>
          <button id="resume-experiment" className="secondary" onClick={() => onCancelResume("resume")}>
            继续实验
          </button>
          <a id="export-experiment" className="secondary" href={`/api/experiments/${snapshot.job.experiment_id}/export`}>
            下载公共报告
          </a>
        </div>
      </div>
      <div id="experiment-progress" className="decision-metrics">
        <div className="metric">
          <span>已保存 / 计划运行</span>
          <strong>{`${progress.N_saved || 0} / ${progress.N_selected_runs || "—"}`}</strong>
        </div>
        <div className="metric">
          <span>状态</span>
          <strong>{pretty(progress.statuses || {})}</strong>
        </div>
      </div>
      <div className="panel">
        <h3>分组比较</h3>
        <p className="hint">
          各来源、配置和 repeat 分开统计。候选求解成功不等于原问题正确；未知费用保留 unknown。
        </p>
        <div id="experiment-groups" className="table-scroll">
          {renderTable(
            [
              ["任务", "task_id"],
              ["配置", "configuration_id"],
              ["重复", "repeat"],
              ["完成/选中", (row: any) => `${row.N_completed}/${row.N_selected}`],
              ["独立可行", match("independent_feasibility")],
              ["目标匹配", match("objective_match")],
              ["已验证解", match("verified_solution")],
              ["Token 用量", "total_tokens"],
              ["费用", "cost"],
            ],
            snapshot.summary?.groups || [],
          )}
        </div>
      </div>
      <div className="panel">
        <h3>逐样本记录</h3>
        <p className="hint">
          页面展示前200条已保存记录。下载包含全部样本；JSONL保存完整公共评估与诊断。
        </p>
        <div id="experiment-rows" className="table-scroll">
          {renderTable(
            [
              ["样本", "case_id"],
              ["配置", "configuration_id"],
              ["重复", "repeat"],
              ["状态", "status"],
              ["Run", "run_id"],
              ["来源", "evidence_origin"],
              ["独立可行", match("independent_feasibility")],
              ["目标匹配", match("objective_match")],
              ["已验证解", match("verified_solution")],
            ],
            snapshot.rows || [],
          )}
        </div>
      </div>
      <details className="panel">
        <summary>完整分组协议、资源与排除记录</summary>
        <pre id="experiment-summary">{pretty(snapshot.summary || snapshot.job.error || "等待保存报告。")}</pre>
      </details>
    </section>
  );
}
