// 公开运行数据的外形。字段按需声明,未知阶段如实缺失;不做任何补造。

export interface ArtifactRef {
  artifact_id?: string;
  media_type: string;
  sha256: string;
  size_bytes: number;
  namespace: string;
  relative_path: string;
  schema_version?: string;
}

export interface JobRecord {
  job_id: string;
  created_at: number;
  status: string;
  run_id: string | null;
  description: string;
  method: string;
  model: string;
  error?: { code: string; message: string } | null;
  assisted?: boolean;
  [key: string]: unknown;
}

export interface RunVersion {
  run_id: string;
  status: string;
  parent_run_id: string | null;
  operation: string | null;
  assisted: boolean;
  saved_at: number;
}

export interface RunEvent {
  sequence_no: number;
  kind: string;
  method_event?: MethodStep & { artifact_ref?: ArtifactRef; stage?: string };
  [key: string]: unknown;
}

export interface MethodStep {
  type?: string;
  step_id: string;
  label: string;
  actor: string;
  phase: "formulation" | "code" | "solve" | "coordination";
  status: "running" | "completed" | "failed";
  timestamp?: number;
  artifact_ref?: ArtifactRef;
}

export interface Snapshot {
  job: JobRecord;
  bundle: RunBundle | null;
  events: RunEvent[];
  artifacts: ArtifactRef[];
  contents: ArtifactContents;
  versions: RunVersion[];
  latest_run_id: string | null;
  historical: boolean;
  data_previews: Record<string, DataPreview>;
}

export interface RunBundle {
  status: string;
  assisted?: boolean;
  error?: { code: string; message: string } | null;
  final_candidate_id?: string;
  stages?: Record<string, { status: string; reason: string | null }>;
  model_artifact_ref?: ArtifactRef | null;
  solve_result_ref?: ArtifactRef | null;
  execution_result_ref?: ArtifactRef | null;
  clarification_request_ref?: ArtifactRef | null;
  public_projections?: Record<string, ArtifactRef>;
  artifacts?: ArtifactRef[];
}

export interface DataPreview {
  columns: string[];
  rows: string[][];
  total_items: number;
  display_truncated: boolean;
  metadata: { complete?: boolean; kind?: string; rows?: number; total_rows?: number | null; sha256?: string; size_bytes?: number };
}

export interface PluginManifest {
  manifest: {
    kind: string;
    plugin_id: string;
    display_name: string;
    capabilities: {
      solvers?: string[];
      handle_profile?: string;
      handle_profiles?: string[];
      human_assisted?: boolean;
      [key: string]: unknown;
    };
  };
}

export interface ExperimentRecord {
  experiment_id: string;
  created_at: number;
  status: string;
  task_count: number;
  configuration_count: number;
  repeats: number;
  error?: unknown;
}

export interface PluginSelection {
  plugin_id: string;
  config?: Record<string, unknown>;
}

export interface Budget {
  [key: string]: number | undefined;
  max_llm_attempts: number;
  max_total_tokens: number;
  max_candidates: number;
  max_repairs: number;
  max_solver_calls: number;
  wall_time_s: number;
  max_concurrency: number;
}

export interface RunConfig {
  schema_version: string;
  method: PluginSelection;
  llm: {
    provider_plugin_id: string;
    model: string;
    config: {
      base_url?: string;
      proxy_url?: string;
      credential_env?: string;
      response_artifact?: string;
      [key: string]: unknown;
    };
    role_models?: Record<string, unknown>;
  };
  compiler?: PluginSelection;
  model_backend: PluginSelection;
  solver: PluginSelection & { options?: Record<string, unknown> };
  executor: PluginSelection;
  store: PluginSelection;
  budget: Budget;
  reporters?: PluginSelection[];
  [key: string]: unknown;
}

export interface MethodPreset {
  config: Record<string, unknown>;
  model_backend: PluginSelection;
  solver: PluginSelection;
  compiler?: PluginSelection;
  budget: Partial<Budget>;
  explanation: string;
  requirements?: string;
}

export interface Bootstrap {
  token: string;
  config: RunConfig;
  plugins: PluginManifest[];
  method_presets: Record<string, MethodPreset>;
}

export interface PublicProblem {
  schema_version: string;
  problem_id: string;
  revision: string;
  description: string;
  requirements: { id: string; text: string; [key: string]: unknown }[];
  assumptions: { id: string; text: string; [key: string]: unknown }[];
  data_refs: { data_id: string; path: string; [key: string]: unknown }[];
  [key: string]: unknown;
}

export interface LinearExpression {
  constant: number;
  terms: { variable_id: string; coefficient: number }[];
}

export interface GroundedLPIR {
  problem_type: "lp" | "milp";
  variables: {
    id: string;
    name?: string;
    domain: "continuous" | "integer" | "binary";
    lower_bound: number | null;
    upper_bound: number | null;
    requirement_ids: string[];
  }[];
  objective: { sense: "min" | "max"; expression: LinearExpression; requirement_ids: string[] };
  constraints: {
    id: string;
    expression: LinearExpression;
    sense: "le" | "ge" | "eq";
    rhs: number;
    requirement_ids: string[];
  }[];
  [key: string]: unknown;
}

export interface FormulationArtifact {
  representation_kind: string;
  representation: Record<string, unknown>;
  [key: string]: unknown;
}

export interface EditDocument {
  schema_version: string;
  operation: "problem" | "formulation" | "code";
  reason: string;
  budget: Budget;
  problem: PublicProblem;
  formulation: FormulationArtifact | null;
  structured_ir: GroundedLPIR | null;
  code: { representation_kind: string; source: string; data_json: Record<string, unknown> | null } | null;
  model_metadata: Record<string, unknown>;
}

export interface BudgetLedger {
  llm_attempts?: number;
  external_llm_requests?: number;
  solver_calls?: number;
  candidates?: number;
  known_total_tokens?: number;
  total_tokens?: number | null;
  [key: string]: unknown;
}

export interface SolveResult {
  termination: string;
  objective_value: number | null;
  has_primal_solution: boolean;
  solution_ref: ArtifactRef | null;
  [key: string]: unknown;
}

export interface ModelArtifact {
  formulation_ref: ArtifactRef | null;
  code_ref: ArtifactRef | null;
  stage_status: Record<string, { status: string; reason?: string | null }>;
}

export interface CodeArtifact {
  representation_ref: ArtifactRef;
  provenance: { origin: string; source_ir_ref?: ArtifactRef };
}

export interface CandidateRecord {
  candidate_id: string;
  sequence_no: number;
  status: string;
  artifact_ref: ArtifactRef | null;
  parent_ids?: string[];
  change_reason?: string;
}

export interface CandidateAssessment {
  stages: Record<string, { status: string }>;
  solve_result_ref: ArtifactRef | null;
  formulation_changes_ref: ArtifactRef | null;
  diagnostics: { code: string; message?: string }[];
}

export interface FormulationChanges {
  changed_sections: string[];
  ir_changed_sections: string[];
  constraint_ids_added: string[];
  constraint_ids_removed: string[];
  requirements_lost: string[];
  source_formulation_available: boolean;
}

export interface LLMAttempt {
  attempt_id?: string;
  role?: string;
  diagnostic?: string;
  connection_diagnostic?: string;
  usage?: { total_tokens?: number | null };
  [key: string]: unknown;
}

export interface ExecutionResult {
  wall_time_s?: number;
  resources?: { cpu_time_s?: number | null; peak_memory_bytes?: number | null };
}

export interface ArtifactContents extends Record<string, unknown> {
  "public-config.json"?: RunConfig;
  "public-problem.json"?: PublicProblem;
  "budget-ledger.json"?: BudgetLedger;
  "llm-trace.json"?: { attempts: LLMAttempt[] };
  "candidate-selection.json"?: { candidate_id: string; reason: string; rule: string };
}

export type Notice = (text: string, error?: boolean) => void;

export interface DatasetSummary {
  task_id: string;
  dataset_id: string | null;
  source_version: string | null;
  adapter_id: string;
  N_cases: number;
  N_selected: number;
}

export interface UploadItem {
  name: string;
  size: number;
  data_id: string;
  format: "csv" | "json";
  base64: string;
  schema?: unknown;
  preview?: { columns: string[]; rows: string[][]; total_items: number; display_truncated: boolean };
  previewError?: string;
}
