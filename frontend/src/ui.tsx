// 与原 visuals.js 对齐的展示词汇与纯函数;结构化渲染组件在各组件文件中。
import type { ArtifactRef, Snapshot } from "./types";
import { splitVarName } from "./math";

export const statusNames: Record<string, string> = {
  running: "进行中",
  queued: "排队中",
  completed: "已完成",
  failed: "未完成",
  cancelled: "已取消",
  artifact_ready: "模型已生成",
  needs_input: "需要补充信息",
  unresolved: "等待确认",
  available: "已生成",
  pending: "等待中",
  not_available: "未提供",
  optimal: "模型最优",
  infeasible: "模型不可行",
  unbounded: "模型无界",
  proposed: "已生成",
  executed: "已执行",
  invalid: "未通过检查",
  selected: "最终选择",
};

export const methodNames: Record<string, string> = {
  "llm4om.methods.direct": "项目基线 · 单次生成",
  "llm4om.methods.optimus_inline": "OptiMUS",
  "llm4om.methods.optimus": "OptiMUS",
  "llm4om.methods.or_llm_agent": "OR-LLM-Agent",
  "llm4om.methods.optitree": "OptiTree",
  "llm4om.methods.autoformulation": "AutoFormulation · MCTS",
  "llm4om.methods.coe": "CoE · 专家协作",
  "llm4om.methods.feedback_repair": "项目基线 · 反馈修正",
  "llm4om.methods.assisted": "人工辅助修订",
};

const roles: Record<string, string> = {
  conductor: "选择参与专家",
  reducer: "汇总专家方案",
  public_evaluator: "生成公开检查输入",
  "Terminology Interpreter": "解释问题术语",
  "Parameter Extractor": "提取参数与决策",
  "Modeling Expert": "数学建模讨论",
  "Programming Example Provider": "构建代码示例",
  "Programming Expert": "生成求解代码",
  "Modeling Knowledge Supplement Expert": "补充建模方案",
  "Code Reviewer": "审查与修正代码",
};

export const format = (value: unknown): string =>
  typeof value === "number"
    ? value.toLocaleString("zh-CN", { maximumFractionDigits: 6 })
    : String(value ?? "—");

export const status = (value: string | undefined | null): string =>
  statusNames[value || ""] || value || "等待中";

export const shortMethod = (value: string | undefined): string =>
  methodNames[value || ""] || value?.split(".").at(-1) || "建模方法";

const parameterValue = (value: unknown): string =>
  Array.isArray(value)
    ? value.map(parameterValue).join(" · ")
    : value && typeof value === "object"
      ? Object.entries(value as Record<string, unknown>)
          .map(([key, item]) => key + " = " + parameterValue(item))
          .join("; ")
      : format(value);
export { parameterValue };

export const artifactLabel = (name: string): string =>
  (
    {
      "formulation.json": "数学表述",
      "structured-ir.json": "实例化模型",
      "formulation-snapshot.json": "表述来源",
      "model.py": "求解源码",
      "code-artifact.json": "代码来源",
      "record.json": "检查记录",
      "record-snapshot.json": "检查提案",
      "check.json": "公开检查",
      "selection.json": "最终选择",
      "formulation-changes.json": "表述变化",
      "repair-state.json": "修正过程",
      "evaluation.json": "独立评估",
      "solve-result.json": "求解结果",
      "public-problem.json": "原始问题与规则",
      "data-views.json": "模型数据视图",
      "dataset-manifest.json": "原始数据来源",
      "state_1_params.json": "问题与参数",
      "state_2_objective.json": "优化目标初稿",
      "state_3_constraints.json": "约束识别",
      "state_4_constraints_modeled.json": "约束数学表述",
      "state_5_objective_modeled.json": "完整数学表述",
      "state_6_code.json": "数学表述与代码",
    } as Record<string, string>
  )[name.split("/").at(-1) || ""] || name;

export function artifactKey(
  snapshot: Pick<Snapshot, "bundle" | "artifacts" | "contents"> | null | undefined,
  reference: ArtifactRef | null | undefined,
): string | undefined {
  if (reference?.namespace !== "run_public") return;
  const current = (
    snapshot?.bundle
      ? Object.values(snapshot.bundle.public_projections || {})
      : snapshot?.artifacts || []
  ).find((item) => item.relative_path === reference.relative_path);
  if (
    current?.namespace !== reference.namespace ||
    current?.sha256 !== reference.sha256 ||
    current?.size_bytes !== reference.size_bytes
  )
    return;
  return Object.keys(snapshot?.contents || {})
    .sort((a, b) => b.length - a.length)
    .find(
      (name) =>
        reference.relative_path === name ||
        reference.relative_path.endsWith("/" + name),
    );
}

export function roleLabel(role: string | undefined): string {
  if (!role) return "";
  if (roles[role]) return roles[role];
  if (/debug/.test(role)) return "检查与调试代码";
  if (/code/.test(role)) return "生成求解实现";
  if (/objective.*formulation/.test(role)) return "形成目标函数";
  if (/constraint.*formulation/.test(role)) return "形成约束表述";
  if (/objective/.test(role)) return "解析优化目标";
  if (/constraint/.test(role)) return "识别业务约束";
  return role;
}

// 方法保存的 sense 可能是 le/ge,也可能是 \leq、geq、>= 这类写法;
// 统一归一为标准键再映射符号,未识别的写法不原样显示。
const senseKeys: Record<string, string> = {
  le: "le", leq: "le", "<=": "le", "<": "le", lt: "le",
  ge: "ge", geq: "ge", ">=": "ge", ">": "ge", gt: "ge",
  eq: "eq", "=": "eq", "==": "eq",
  neq: "ne", "!=": "ne", ne: "ne",
};

export function senseKey(sense: unknown): string {
  const key = String(sense ?? "")
    .trim()
    .replace(/^[\\$]+/, "")
    .toLowerCase();
  return senseKeys[key] || "other";
}

export function senseOperator(sense: unknown): string {
  return ({ le: "≤", ge: "≥", eq: "=", ne: "≠" } as Record<string, string>)[senseKey(sense)] || "";
}

// 变量名排版:xA / x_A / x1 显示为字母 + 下标;普通单词与中文名原样显示。
// 拆分规则与文本公式路径(math.splitVarName)一致。
export function VarSymbol({ name }: { name: unknown }) {
  const [head, sub] = splitVarName(String(name ?? ""));
  if (sub)
    return (
      <>
        <i>{head}</i>
        <sub>{sub}</sub>
      </>
    );
  return <>{head}</>;
}
export const assumptionStatusNames: Record<string, string> = {
  explicit: "原文声明",
  proposed: "待确认",
  confirmed: "已确认",
};

const failureAdvice: Record<string, [string, string]> = {
  provider_timeout: ["模型服务响应超时", "检查模型服务状态与请求时限，再决定是否创建新运行。"],
  provider_connection_error: ["暂时无法连接模型服务", "检查服务地址和连接。已保存的记录会保留。"],
  auth_error: ["模型服务认证失败", "检查服务端配置的凭据。"],
  llm_output_truncated: ["模型输出未生成完整", "调整输出上限或简化问题后重新建模。"],
  budget_exhausted: ["本次运行已达到预算上限", "查看实际消耗，调整预算后创建新的运行。"],
  checkpoint_incompatible: [
    "保存记录与当前版本不兼容",
    "历史结果仍可查看。新的执行需要使用当前版本的配置。",
  ],
};

const connectionDiagnosis: Record<string, [string, string]> = {
  tls_interrupted: [
    "模型服务的 TLS 连接被中断",
    "检查服务或显式代理的连接路线。请求用量可能未知，原记录已保留。",
  ],
  tls_certificate: ["模型服务证书校验失败", "检查服务证书与本机可信证书配置，再创建新运行。"],
  tls_error: ["模型服务的 TLS 连接失败", "检查服务和代理的 TLS 连接配置。"],
  dns_error: ["模型服务域名解析失败", "检查服务地址和使用路线的 DNS。"],
  connection_refused: ["模型服务连接被拒绝", "检查服务或代理是否正在监听配置的地址和端口。"],
  connection_reset: ["模型服务连接被重置", "检查服务或显式代理的连接路线。请求用量可能未知。"],
  timeout: failureAdvice.provider_timeout,
};

export function failureDiagnosis(
  code: string | undefined,
  connectionDiagnostic: string | undefined,
): [string, string] {
  return (
    (connectionDiagnostic && connectionDiagnosis[connectionDiagnostic]) ||
    (code && failureAdvice[code]) || [
      "这次建模未完成",
      "查看已保存的步骤和诊断，修改输入或配置后再执行。",
    ]
  );
}

export const pretty = (value: unknown): string =>
  typeof value === "string" ? value : JSON.stringify(value, null, 2);

export const phaseLabel = (phase: string | undefined): string =>
  (
    {
      formulation: "数学表述",
      code: "求解实现",
      solve: "数值求解",
      coordination: "方法协调",
    } as Record<string, string>
  )[phase || ""] || phase || "";

export function activeStep(snapshot: Snapshot | null | undefined) {
  const current = new Map<string, any>();
  let solver: any = null;
  for (const event of snapshot?.events || []) {
    const step = event.method_event;
    if (step?.type === "modeling_step")
      current.set(step.step_id, { ...step, sequence: event.sequence_no });
    if (event.kind === "solver_started")
      solver = {
        phase: "solve",
        label: "正在求解模型",
        actor: "求解器",
        sequence: event.sequence_no,
        status: "running",
      };
    if (event.kind === "solver_finished") solver = null;
  }
  return [...current.values(), ...(solver ? [solver] : [])]
    .filter((step) => step.status === "running")
    .sort((a, b) => b.sequence - a.sequence)[0];
}
