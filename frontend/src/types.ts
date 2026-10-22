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
