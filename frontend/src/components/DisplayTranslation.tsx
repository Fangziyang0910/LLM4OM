import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api";
import { locale as currentLocale } from "@/i18n";

type Locale = "zh" | "en";
type Reply = { locale: Locale; items: { original: string; translation: string; cached: boolean }[] };
const key = (language: Locale, text: string) => ["display-translation", language, text];
const Context = createContext<{
  language: Locale; request: (text: string, language: Locale) => Promise<string>;
  lookup: (text: string) => string; version: number;
} | null>(null);

function batchRequests() {
  type Pending = { text: string; language: Locale; resolve: (value: string) => void; reject: (error: unknown) => void };
  const pending: Pending[] = [];
  let timer: ReturnType<typeof setTimeout> | undefined;
  async function flush() {
    timer = undefined;
    const language = pending[0].language;
    const batch = pending.filter(item => item.language === language).slice(0, 20);
    for (const item of batch) pending.splice(pending.indexOf(item), 1);
    if (pending.length) timer = setTimeout(() => void flush(), 20);
    try {
      const response = await api<Reply>("/api/display-translations", { texts: batch.map(item => item.text), locale: language });
      for (const item of batch) {
        const matches = response?.locale === language && Array.isArray(response.items)
          ? response.items.filter(value => value.original === item.text) : [];
        const translated = matches.length === 1 ? matches[0].translation : undefined;
        if (typeof translated === "string" && translated.trim()) item.resolve(translated);
        else item.reject(new Error("Display translation did not match its source."));
      }
    } catch (error) { for (const item of batch) item.reject(error); }
  }
  return (text: string, language: Locale) => new Promise<string>((resolve, reject) => {
    pending.push({ text, language, resolve, reject });
    timer ??= setTimeout(() => void flush(), 20);
  });
}

/** Session cache and small visible-label batches; saved modeling data never passes through this view. */
export function DisplayTranslationProvider({ children, locale = currentLocale }: { children: ReactNode; locale?: Locale }) {
  const client = useQueryClient();
  const [request] = useState(batchRequests);
  const [version, setVersion] = useState(0);
  useEffect(() => client.getQueryCache().subscribe(event => {
    if (event.type === "updated" && event.query.queryKey[0] === "display-translation") setVersion(value => value + 1);
  }), [client]);
  const lookup = useCallback((text: string) => client.getQueryData<string>(key(locale, text)) ?? text, [client, locale]);
  const value = useMemo(() => ({ language: locale, request, lookup, version }), [locale, request, lookup, version]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

/** Read already translated visible titles for search; reading the cache never schedules a request. */
export function useDisplayLookup(): (text: string) => string {
  return useContext(Context)?.lookup ?? (text => text);
}

function needsTranslation(text: string, language: Locale) {
  if (!text.trim() || text.length > 1000) return false;
  const chinese = text.match(/[㐀-鿿]/g)?.length ?? 0;
  const words = text.match(/[A-Za-z]+/g)?.length ?? 0;
  return language === "zh" ? words > 0 : chinese > 0;
}

type LabelProps = { text: string; children: (text: string, ref: (node: HTMLElement | null) => void) => ReactNode };
export function DisplayLabel({ text, children }: LabelProps) {
  const context = useContext(Context);
  return context ? <VisibleLabel text={text} context={context}>{children}</VisibleLabel> : children(text, () => {});
}

function VisibleLabel({ text, children, context }: LabelProps & { context: NonNullable<React.ContextType<typeof Context>> }) {
  const [node, setNode] = useState<HTMLElement | null>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(entries => setVisible(entries.some(entry => entry.isIntersecting)));
    observer.observe(node);
    return () => observer.disconnect();
  }, [node]);
  const query = useQuery({
    queryKey: key(context.language, text), queryFn: () => context.request(text, context.language),
    enabled: visible && needsTranslation(text, context.language),
    staleTime: Infinity, gcTime: Infinity, retry: false, retryOnMount: false,
  });
  return children(query.data ?? text, setNode);
}

export function DisplayText({ text }: { text: string }) {
  return <DisplayLabel text={text}>{(translated, ref) => <span ref={ref} title={text}>{translated}</span>}</DisplayLabel>;
}
