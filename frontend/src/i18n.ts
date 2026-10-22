import { en, patterns } from "./locales/en";

/**
 * The page's language. Text is written in Chinese and looked up in a dictionary for English; a missing entry shows
 * the Chinese. Changing the language reloads the page, so text is read once per load and needs no React state.
 */
export type Locale = "zh" | "en";
const KEY = "llm4om-locale";

function initial(): Locale {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "zh" || saved === "en") return saved;
  } catch { /* storage may be unavailable */ }
  return typeof navigator !== "undefined" && !navigator.language.toLowerCase().startsWith("zh") ? "en" : "zh";
}

export const locale: Locale = initial();
if (typeof document !== "undefined") document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";

export function setLocale(next: Locale): void {
  try { localStorage.setItem(KEY, next); } catch { /* storage may be unavailable */ }
  location.reload();
}

/** `text` in the page's language, with `{name}` replaced by `values.name`. */
export function t(text: string, values?: Record<string, string | number>): string {
  const translated = locale === "en" ? en[text] ?? pattern(text) : text;
  return values ? translated.replace(/\{(\w+)\}/g, (match, name: string) => name in values ? String(values[name]) : match) : translated;
}

/** Step titles with numbers in them, such as 执行代码（第 2 次）, by pattern; otherwise the text itself. */
function pattern(text: string): string {
  for (const [match, replacement] of patterns) if (match.test(text)) return text.replace(match, replacement);
  return text;
}

/** Dates and numbers follow the page's language. */
export const dateLocale = locale === "zh" ? "zh-CN" : "en-US";
