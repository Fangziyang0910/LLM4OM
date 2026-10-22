export type Method = { id: string; name: string; description: string; source: string | null; languages: string[] | null };
export type Language = { id: string; name: string; solver: string };
export type Provider = { id: string; label: string; protocol: string; base_url: string };
export type Dataset = { id: string; title: string; description: string; count: number; license: string; source_url: string };
export type Options = { methods: Method[]; languages: Language[]; providers: Provider[]; datasets: Dataset[] };

/** A fixed LLM configuration; the server never returns its key. `env` comes from the server's LLM4OM_LLM_* variables. */
export type Preset = {
  id: string; source: "env" | "saved"; provider: string; model: string; base_url: string;
  temperature: number | null; max_tokens: number | null; extra_body: Record<string, unknown>;
  tokens_today: number;
};
/** The presets and each one's daily token budget; 0 means no budget. */
export type Presets = { presets: Preset[]; daily_tokens: number };

/** One recorded step of a run; the server sends it again, by id, when it finishes. */
export type Step = {
  id: string; time: number; type: "llm" | "artifact" | "solve" | "error"; title: string; content: string;
  running?: boolean; failed?: boolean; seconds?: number; node?: string;
  input_tokens?: number | null; output_tokens?: number | null;
  status?: string; objective?: number | null; code?: string; formulation?: string;
};
/** The constraints of an infeasible model that cannot hold together, found by `tool`; for reading only. */
export type Diagnosis = { tool: string; items: string[]; total: number; error: string | null };
export type Solve = {
  status: string; objective: number | null; variables: Record<string, number>; output: string; error: string | null;
  diagnosis?: Diagnosis | null;
};
export type Usage = { llm_calls: number; solves: number; input_tokens: number; output_tokens: number };
export type RunValues = {
  description?: string; data?: Record<string, string>; formulation?: string | null; code?: string | null;
  solve?: Solve | null; failure?: string | null; steps?: Step[]; usage?: Usage;
};
/** What the run is and with what it ran, kept as thread metadata; `group` joins the runs of one comparison. */
export type RunMeta = {
  title: string; method: string; language: string; preset?: string | null; provider: string | null; model: string | null;
  group?: string | null; note?: string; tags?: string[];
};
/** A request to model one problem: the composer's draft. */
export type Draft = {
  description: string; data: Record<string, string>; method: string; language: string; preset: string | null;
  comparing?: boolean; methods?: string[]; presets?: string[];  // a comparison runs every method with every preset
};
/** A run in the history list. */
export type Entry = {
  id: string; created: string; updated: string; meta: RunMeta; state: string; objective: number | null;
  failure: string | null; usage: Usage | null;
};
