import { createStore, get, set, update } from "idb-keyval";
import { t } from "@/i18n";
import { normalizeTarget } from "@/features/runs/target";
import type { Draft } from "@/types";

export const DRAFT_KEY = "llm4om-draft";

const DATABASE_PREFIX = "indexedDB:";
type DraftHeader = Omit<Draft, "data"> & { id: string; files: string[] };
type Snapshot = { id: string; draft: Draft };
const store = createStore("llm4om-drafts", "drafts");
let snapshot: Snapshot | undefined;
let latestSave = 0;
let restoreFailed = false;

export function initialDraft(): Draft {
  let saved: Partial<Draft> = {};
  try { saved = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "{}") ?? {}; } catch { /* storage may be unavailable */ }
  return normalizeDraft(saved);
}

function normalizeDraft(saved: Partial<Draft>): Draft {
  const target = normalizeTarget(saved.language, saved.solver);
  return { description: saved.description ?? "", data: saved.data ?? {}, method: saved.method ?? "direct",
    language: target.language, preset: saved.preset ?? null, solver: target.solver, time_limit: saved.time_limit,
    origin: saved.origin, comparing: saved.comparing ?? false, methods: saved.methods ?? [], presets: saved.presets ?? [] };
}

function readHeader(): DraftHeader | null {
  const stored = localStorage.getItem(DRAFT_KEY);
  return stored?.startsWith(DATABASE_PREFIX) ? JSON.parse(stored.slice(DATABASE_PREFIX.length)) : null;
}

/** The small header and the matching attachment snapshot restore as one draft. */
export async function restoreDraft(): Promise<Draft> {
  let header: DraftHeader | null;
  try { header = readHeader(); } catch { return initialDraft(); }
  if (!header) return initialDraft();
  try {
    snapshot = await get<Snapshot>(DRAFT_KEY, store);
    if (!snapshot) return normalizeDraft({});
    const { id, files, ...settings } = header;
    if (snapshot.id !== id) return normalizeDraft(snapshot.draft);
    const allFiles = snapshot.draft.data;
    return normalizeDraft({ ...settings, data: Object.fromEntries(files.map(name => [name, allFiles[name]])) });
  } catch {
    // Do not autosave an empty editor over an unreadable snapshot.
    restoreFailed = true;
    return normalizeDraft({});
  }
}

function saveHeader(id: string, { data, ...settings }: Draft) {
  localStorage.setItem(DRAFT_KEY, DATABASE_PREFIX + JSON.stringify({ id, files: Object.keys(data), ...settings }));
}

export async function saveDraft(draft: Draft): Promise<void> {
  if (restoreFailed) throw new Error(t("无法读取已保存的草稿，请重新加载页面。"));
  const version = ++latestSave;
  const stored = snapshot;
  if (stored && Object.keys(draft.data).length && readHeader()?.id === stored.id
      && Object.entries(draft.data).every(([name, content]) => stored.draft.data[name] === content)) {
    // Typing, changing settings or removing a file must survive an immediate reload.
    saveHeader(stored.id, draft);
    return;
  }
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  } catch (error) {
    if (!(error instanceof DOMException && error.name === "QuotaExceededError")) throw error;
    const id = Array.from(crypto.getRandomValues(new Uint32Array(4))).join("-");
    const next = { id, draft };
    await set(DRAFT_KEY, next, store);
    if (latestSave === version) {
      snapshot = next;
      saveHeader(id, draft);
    }
    return;
  }
  if (stored) {
    snapshot = undefined;
    await update<Snapshot | undefined>(DRAFT_KEY, current => current?.id === stored.id ? undefined : current, store);
  }
}
