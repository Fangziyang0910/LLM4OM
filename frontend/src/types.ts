export type Method = { id: string; name: string; description: string; source: string | null; languages: string[] | null };
export type Language = { id: string; name: string; solver: string };
export type Provider = { id: string; label: string; protocol: string; base_url: string };
export type Dataset = { id: string; title: string; description: string; count: number; license: string; source_url: string };
export type Options = { methods: Method[]; languages: Language[]; providers: Provider[]; datasets: Dataset[] };

/** A fixed LLM configuration; the server never returns its key. `env` comes from the server's LLM4OM_LLM_* variables. */
export type Preset = {
  id: string; source: "env" | "saved"; provider: string; model: string; base_url: string;
  temperature: number | null; max_tokens: number | null; extra_body: Record<string, unknown>;
};

/** One recorded step of a run; the server sends it again, by id, when it finishes. */
export type Step = {
  id: string; time: number; type: "llm" | "artifact" | "solve" | "error"; title: string; content: string;
  running?: boolean; failed?: boolean; seconds?: number; node?: string;
  input_tokens?: number | null; output_tokens?: number | null;
  status?: string; objective?: number | null; code?: string; formulation?: string;
};
export type Solve = { status: string; objective: number | null; variables: Record<string, number>; output: string; error: string | null };
export type Usage = { llm_calls: number; solves: number; input_tokens: number; output_tokens: number };
export type RunValues = {
  description?: string; data?: Record<string, string>; formulation?: string | null; code?: string | null;
  solve?: Solve | null; failure?: string | null; steps?: Step[]; usage?: Usage;
};
/** Who made the run and with what; kept as thread metadata. */
export type RunMeta = { title: string; method: string; language: string; preset?: string | null; provider: string | null; model: string | null };
/** A request to model one problem: the composer's draft. */
export type Draft = { description: string; data: Record<string, string>; method: string; language: string; preset: string | null };
/** A run in the history list. */
export type Entry = { id: string; created: string; meta: RunMeta; state: string; objective: number | null };
