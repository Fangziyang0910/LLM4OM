/** A request to model one problem: the composer's draft. */
export type Draft = {
  description: string; data: Record<string, string>; method: string; language: string; preset: string | null;
  comparing?: boolean; methods?: string[]; presets?: string[];  // a comparison runs every method with every preset
};
