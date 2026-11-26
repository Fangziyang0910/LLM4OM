import { act, cleanup, render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { api } from "@/api";
import { DisplayTranslationProvider, DisplayText } from "./DisplayTranslation";
import { Sidebar } from "./Sidebar";
import { Explanation } from "@/features/runs/Explanation";
import type { Entry } from "@/features/runs/types";

vi.mock("@/api", () => ({ api: vi.fn() }));
const observers = new Map<Element, (visible: boolean) => void>();
beforeEach(() => {
  vi.mocked(api).mockReset(); observers.clear();
  vi.stubGlobal("IntersectionObserver", class {
    constructor(private callback: IntersectionObserverCallback) {}
    observe(target: Element) { observers.set(target, visible => this.callback([{ target, isIntersecting: visible } as IntersectionObserverEntry], this as unknown as IntersectionObserver)); }
    disconnect() {}
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const client = () => new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
function view(texts: string[], locale: "zh" | "en" = "zh", cache = client(), hidden = "") {
  return <QueryClientProvider client={cache}><DisplayTranslationProvider locale={locale}>
    {texts.map((text, index) => <div key={index} hidden={text === hidden}><DisplayText text={text} /></div>)}
  </DisplayTranslationProvider></QueryClientProvider>;
}
async function reveal() {
  await act(async () => { for (const [node, callback] of observers) callback(!node.closest("[hidden]")); });
}
const answer = (_: string, body: unknown) => {
  const { texts, locale } = body as { texts: string[]; locale: string };
  return Promise.resolve({ locale, items: texts.map(original => ({ original, translation: locale === "zh" ? "中文 " + original : "English " + original, cached: false })) });
};

test("visible labels batch, deduplicate and reuse translations while hidden labels do not request", async () => {
  vi.mocked(api).mockImplementation(answer);
  const texts = ["Production plan", "Production plan", "Total profit", "Hidden plan"];
  const screen = render(view(texts, "zh", client(), "Hidden plan"));
  expect(api).not.toHaveBeenCalled();
  await reveal();
  await waitFor(() => expect(screen.container.textContent).toContain("中文 Total profit"));
  expect(api).toHaveBeenCalledTimes(1);
  expect(vi.mocked(api).mock.calls[0]).toEqual(["/api/display-translations", { texts: ["Production plan", "Total profit"], locale: "zh" }]);
  expect(screen.container.querySelector("span")?.title).toBe("Production plan");
  expect(screen.container.textContent).toContain("Hidden plan");
});

test("Chinese display translates English phrases even when Chinese characters are more numerous", async () => {
  vi.mocked(api).mockImplementation(answer);
  const source = "运输费用 Transport cost";
  const result = render(view([source]));
  await reveal();
  await waitFor(() => expect(result.container.textContent).toBe("中文 " + source));
  expect(vi.mocked(api).mock.calls[0]).toEqual(["/api/display-translations", { texts: [source], locale: "zh" }]);
});

test("requests never exceed 20 labels and the same language/text cache is shared after remount", async () => {
  vi.mocked(api).mockImplementation(answer);
  const texts = Array.from({ length: 41 }, (_, i) => "Visible label " + i);
  const cache = client(); const screen = render(view(texts, "zh", cache));
  await reveal();
  await waitFor(() => expect(screen.container.textContent).toContain("中文 Visible label 40"));
  expect(api).toHaveBeenCalledTimes(3);
  expect(vi.mocked(api).mock.calls.every(([, body]) => (body as { texts: string[] }).texts.length <= 20)).toBe(true);
  screen.unmount();
  const again = render(view([texts[0], texts[40]], "zh", cache)); await reveal();
  await waitFor(() => expect(again.container.textContent).toContain("中文 Visible label 40"));
  expect(api).toHaveBeenCalledTimes(3);
});

test("both language directions work and stale source responses cannot replace current labels", async () => {
  let finish: (value: unknown) => void = () => {};
  vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockImplementation(answer);
  const cache = client(); const screen = render(view(["Old plan"], "zh", cache)); await reveal();
  await waitFor(() => expect(api).toHaveBeenCalledTimes(1));
  screen.rerender(view(["运输方案"], "en", cache)); await reveal();
  await waitFor(() => expect(screen.container.textContent).toBe("English 运输方案"));
  await act(async () => { finish({ locale: "zh", items: [{ original: "Old plan", translation: "旧方案" }] }); });
  expect(screen.container.textContent).toBe("English 运输方案");
});

test.each(["error", "mismatch", "locale"])("%s keeps the original and never mutates the supplied text", async kind => {
  const source = "Original plan";
  if (kind === "error") vi.mocked(api).mockRejectedValueOnce(new Error("offline"));
  else vi.mocked(api).mockResolvedValueOnce({ locale: kind === "locale" ? "en" : "zh", items: [{ original: kind === "locale" ? source : "Other plan", translation: "错误" }] });
  const screen = render(view([source])); await reveal();
  await waitFor(() => expect(api).toHaveBeenCalledTimes(1));
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 50)); });
  expect(screen.container.textContent).toBe(source);
  expect(source).toBe("Original plan");
});

test("a display label without a provider stays original without requiring a QueryClient", () => {
  const screen = render(<DisplayText text="Original plan" />);
  expect(screen.container.textContent).toBe("Original plan");
  expect(api).not.toHaveBeenCalled();
});

test("sidebar search and accessible menus use visible cached translations but actions retain the original record", async () => {
  vi.mocked(api).mockImplementation(answer);
  const cache = client(); const onOpen = vi.fn();
  const entry: Entry = { id: "run-id", created: new Date().toISOString(), updated: new Date().toISOString(), state: "optimal",
    meta: { title: "Production plan", method: "direct", language: "pyomo", model: null, provider: null }, objective: 13,
    elapsed: 1, failure: null, usage: null };
  const sidebar = (query: string) => <QueryClientProvider client={cache}><DisplayTranslationProvider locale="zh">
    <Sidebar entries={[entry]} current={entry.id} options={null} presets={[]} query={query} hasMore={false} loading={false} error={null}
      onQuery={vi.fn()} onLoadMore={vi.fn()} onRetry={vi.fn()} onNew={vi.fn()} onAgent={vi.fn()} onOpen={onOpen}
      onCompare={vi.fn()} onDelete={vi.fn()} onExamples={vi.fn()} onPresets={vi.fn()} />
  </DisplayTranslationProvider></QueryClientProvider>;
  const result = render(sidebar("")); await reveal();
  await waitFor(() => expect(result.getByRole("button", { name: "更多操作：中文 Production plan" })).toBeTruthy());
  for (const query of ["中文", "Production plan"]) {
    result.rerender(sidebar(query));
    const button = result.getByRole("button", { name: /^中文 Production plan/ });
    button.click(); expect(onOpen).toHaveBeenLastCalledWith(entry);
  }
  expect(entry.meta.title).toBe("Production plan");
  expect(api).toHaveBeenCalledTimes(1);
});

test("business labels, units and short explanations translate while solver values and source data stay intact", async () => {
  vi.mocked(api).mockImplementation(answer);
  const explanation = { summary: "Produce only chairs.", objective_label: "Total profit", objective_unit: "dollars",
    decisions: [{ variable: "raw_x[0]", label: "Chairs produced", unit: "pieces" }], notes: ["Use integer quantities."], total_variables: 1 };
  const frozen = JSON.stringify(explanation);
  const result = render(<QueryClientProvider client={client()}><DisplayTranslationProvider locale="zh">
    <Explanation explanation={explanation} solve={{ status: "optimal", objective: 13, variables: { "raw_x[0]": 2 }, output: "", error: null }} />
  </DisplayTranslationProvider></QueryClientProvider>);
  await reveal(); await waitFor(() => expect(result.container.textContent).toContain("中文 Chairs produced"));
  expect(result.container.textContent).toContain("中文 Produce only chairs.");
  expect(result.container.textContent).toContain("中文 pieces");
  expect(result.container.textContent).toContain("中文 Use integer quantities.");
  expect(result.getByTitle("raw_x[0]").parentElement?.textContent).toContain("2");
  expect(JSON.stringify(explanation)).toBe(frozen);
  expect(vi.mocked(api).mock.calls.flatMap(([, body]) => (body as { texts: string[] }).texts)).not.toContain("raw_x[0]");
});

test("already localized text, numeric values and overlong labels remain original without requests", async () => {
  const long = "x".repeat(1001); const result = render(view(["中文方案", "12.5", long]));
  await reveal(); await act(async () => { await new Promise(resolve => setTimeout(resolve, 40)); });
  expect(api).not.toHaveBeenCalled();
  expect(result.container.textContent).toBe("中文方案12.5" + long);
});
