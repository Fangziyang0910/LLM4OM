/** One recorded step of a run; the server sends it again, by id, when it finishes. */
export type Step = {
  id: string; time: number; type: "llm" | "artifact" | "solve" | "error"; title: string; content: string;
  running?: boolean; failed?: boolean; seconds?: number; node?: string;
  input_tokens?: number | null; output_tokens?: number | null;
  status?: string; objective?: number | null; code?: string; formulation?: string;
};
/** The constraints of an infeasible model that cannot hold together, found by `tool`. */
export type Diagnosis = { tool: string; items: string[]; total: number; error: string | null };
export type Solve = {
  status: string; objective: number | null; variables: Record<string, number>; output: string; error: string | null;
  diagnosis?: Diagnosis | null;
  solver?: string | null;
};
export type Usage = { llm_calls: number; solves: number; input_tokens: number; output_tokens: number };
export type Timing = { started_at: number; elapsed: number; finished_at?: number };
export type SourceRun = { thread_id: string; checkpoint_id: string };
export type Explanation = {
  summary: string; objective_label: string; objective_unit: string;
  decisions: { variable: string; label: string; unit: string }[]; notes: string[]; total_variables: number;
};
export type Infeasibility = {
  summary: string; conflicts: { explanation: string; constraints: string[] }[];
  adjustments: { title: string; instruction: string }[];
};
export type RunSpec = {
  version: string; method: string; source: string | null; parameters: Record<string, unknown>; limits: Record<string, number>;
  language: string; solver: string; preset: string | null; preset_name?: string;
  llm: { provider: string; model: string; base_url: string; temperature: number | null; max_tokens: number | null;
    timeout: number; max_retries: number; extra_body: Record<string, unknown> };
  sandbox: string; worker_image: string | null;
  explain?: boolean;
  locale?: "zh" | "en";
};
export type RunValues = {
  description?: string; data?: Record<string, string>; formulation?: string | null; code?: string | null;
  solve?: Solve | null; failure?: string | null; steps?: Step[]; usage?: Usage; spec?: RunSpec | null; timing?: Timing;
  revision?: { description: string; instruction: string } | null;
  explanation?: Explanation | null; explanation_error?: string | null;
  infeasibility?: Infeasibility | null;
};
/** What the run is and with what it ran, kept as thread metadata; `group` joins the runs of one comparison. */
export type RunMeta = {
  kind?: "run";
  title: string; method: string; language: string; preset?: string | null; provider: string | null; model: string | null;
  solver?: string;
  group?: string | null; note?: string; tags?: string[];
  origin?: string;
  parent?: SourceRun;
  scenario?: { name: string; instruction: string };
  conversation?: string;
  thinking?: boolean | null;
};
export type RequirementsMeta = Pick<RunMeta, "title" | "preset" | "provider" | "model" | "note" | "tags" | "origin" | "thinking"> & { kind: "requirements"; search?: boolean };
export type SolutionChatMeta = Pick<RunMeta, "title" | "preset" | "provider" | "model" | "note" | "tags" | "thinking"> & { kind: "solution_chat"; parent: SourceRun };
export type OptimizationMeta = Pick<RunMeta, "title" | "preset" | "provider" | "model" | "note" | "tags" | "thinking"> & {
  kind: "optimization"; method?: string | null; language?: string | null; search?: boolean;
};
/** A run in the history list. */
export type Entry<Meta = RunMeta | RequirementsMeta | SolutionChatMeta | OptimizationMeta> = {
  id: string; created: string; updated: string; meta: Meta; state: string; objective: number | null;
  failure: string | null; usage: Usage | null; elapsed: number | null;
};

export function isRunEntry(entry: Entry): entry is Entry<RunMeta> {
  return entry.meta.kind == null || entry.meta.kind === "run";
}
