import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { api } from "@/api";
import { Outputs, type Tab } from "./Outputs";
import { ReadingTranslation } from "@/components/ReadingTranslation";

const language = vi.hoisted(() => ({ value: "zh" }));
vi.mock("@/i18n", async () => {
  const { en } = await import("@/locales/en");
  return { get locale() { return language.value; }, t: (text: string, values?: Record<string, string | number>) => {
    const result = language.value === "zh" ? text : en[text] ?? text;
    return values ? result.replace(/\{(\w+)\}/g, (match, key: string) => key in values ? String(values[key]) : match) : result;
  } };
});
vi.mock("@/api", () => ({ api: vi.fn() }));
vi.stubGlobal("ResizeObserver", class { observe = vi.fn(); disconnect = vi.fn(); });
const original = "The daily profit is $p=50$.";
const translated = "每天的利润为 $p=50$。";

beforeEach(() => {
  language.value = "zh";
  vi.mocked(api).mockReset().mockResolvedValue({ original, translation: translated, locale: "zh", cached: false });
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: vi.fn(async () => {}) } });
});
afterEach(cleanup);

function show(tab: Tab, text = original, active = false) {
  const values = { description: text, formulation: text };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><Outputs values={values} steps={[]} active={active} tab={tab}
    setTab={vi.fn()} picked={{}} setPicked={vi.fn()} finished onAdjust={vi.fn()} /></QueryClientProvider>);
  return values;
}

test.each(["problem", "formulation"] as const)("%s displays reading prose in Chinese and preserves the original", async tab => {
  const values = show(tab);
  await screen.findByText(/每天的利润为/);
  expect(api).toHaveBeenCalledWith("/api/translations", { text: original, locale: "zh" });
  fireEvent.click(screen.getByRole("button", { name: "查看原文" }));
  expect(screen.getByText(/The daily profit is/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "查看译文" }));
  await screen.findByText(/每天的利润为/);
  fireEvent.click(screen.getByRole("button", { name: tab === "problem" ? "复制问题" : "复制数学模型" }));
  await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(original));
  expect(values).toEqual({ description: original, formulation: original });
  expect(api).toHaveBeenCalledTimes(1);
});

test("Chinese source prose is shown directly in Chinese", () => {
  show("problem", translated);
  expect(screen.getByText(/每天的利润为/)).toBeTruthy();
  expect(api).not.toHaveBeenCalled();
});

test("streaming models retain their original text without requesting translations", () => {
  show("formulation", original, true);
  expect(screen.getByText(/The daily profit is/)).toBeTruthy();
  expect(api).not.toHaveBeenCalled();
});

test("a failed reading translation retains the source and retries on request", async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error("unavailable"));
  show("formulation");
  await screen.findByText("阅读译文暂时无法生成，当前显示原文。");
  expect(screen.getByText(/The daily profit is/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  await screen.findByText(/每天的利润为/);
});

test("English display translates historical Chinese prose", async () => {
  language.value = "en";
  vi.mocked(api).mockResolvedValue({ original: translated, translation: original, locale: "en", cached: false });
  show("formulation", translated);
  await screen.findByText(/The daily profit is/);
  expect(api).toHaveBeenCalledWith("/api/translations", { text: translated, locale: "en" });
});

test("mixed prose can request a translation when the language heuristic skips it", async () => {
  const mixed = "这里已有较长的中文说明，需要保留全部条件。Minimize cost.";
  const result = "这里已有较长的中文说明，需要保留全部条件。最小化成本。";
  vi.mocked(api).mockResolvedValue({ original: mixed, translation: result });
  show("problem", mixed);
  expect(api).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "翻译为中文" }));
  await screen.findByText(result);
});

test("a late response for an earlier version never replaces the current version", async () => {
  const resolvers: ((value: unknown) => void)[] = [];
  vi.mocked(api).mockImplementation(() => new Promise(resolve => { resolvers.push(resolve); }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const view = (text: string) => <QueryClientProvider client={client}><ReadingTranslation text={text} render={value => <p>{value}</p>} /></QueryClientProvider>;
  const mounted = render(view(original));
  await waitFor(() => expect(resolvers).toHaveLength(1));
  const next = "The new daily profit is $p=80$.";
  mounted.rerender(view(next));
  await waitFor(() => expect(resolvers).toHaveLength(2));
  await act(async () => { resolvers[1]({ original: next, translation: "新利润为80。" }); });
  await screen.findByText("新利润为80。");
  await act(async () => { resolvers[0]({ original, translation: "旧利润为50。" }); });
  expect(screen.queryByText("旧利润为50。")).toBeNull();
  expect(screen.getByText("新利润为80。")).toBeTruthy();
});
