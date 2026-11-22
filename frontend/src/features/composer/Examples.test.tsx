import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { api } from "@/api";
import { Examples } from "./Examples";

vi.mock("@/api", () => ({ api: vi.fn() }));
const language = vi.hoisted(() => ({ value: "zh" }));
vi.mock("@/i18n", async () => {
  const { en } = await import("@/locales/en");
  return { get locale() { return language.value; }, t: (text: string) => language.value === "zh" ? text : en[text] ?? text };
});
afterEach(cleanup);
beforeEach(() => {
  language.value = "zh";
  vi.mocked(api).mockReset();
  HTMLElement.prototype.scrollTo = vi.fn();
});

const original = "Ship 10 whole packages from A to B at $2 each.";
const translated = "从 A 向 B 运输10个整包，每包费用为2美元。";
const page = { total: 1, cases: [{ id: "sample-1", sample_id: "1", subset: "nl4opt", description: original }] };
const dataset = { id: "nl4opt", title: "NL4Opt", description: "自然语言线性优化问题。", count: 1, license: "MIT", source_url: "https://example.org" };

function openLibrary() {
  const onUse = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><Examples open onClose={vi.fn()} datasets={[dataset]} onUse={onUse} /></QueryClientProvider>);
  return onUse;
}

test("an example translates on request and can use either the translation or its original", async () => {
  vi.mocked(api).mockResolvedValueOnce(page).mockResolvedValueOnce({ original, translation: translated, cached: false, locale: "zh" });
  const onUse = openLibrary();
  await screen.findByText(original);
  expect(api).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByRole("button", { name: "翻译为中文" }));
  await screen.findByText(translated);
  expect(api).toHaveBeenLastCalledWith("/api/datasets/nl4opt/translation", { case_id: "sample-1", locale: "zh" });
  fireEvent.click(screen.getByRole("button", { name: "带入译文" }));
  expect(onUse).toHaveBeenLastCalledWith(translated);

  fireEvent.click(screen.getByRole("button", { name: "查看原文" }));
  expect(screen.getByText(original)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "带入原文" }));
  expect(onUse).toHaveBeenLastCalledWith(original);
  fireEvent.click(screen.getByRole("button", { name: "查看译文" }));
  expect(screen.getByText(translated)).toBeTruthy();
  expect(api).toHaveBeenCalledTimes(2);
});

test("a failed translation preserves the original and offers another attempt", async () => {
  vi.mocked(api).mockResolvedValueOnce(page).mockRejectedValueOnce(new Error("Translation unavailable"));
  const onUse = openLibrary();
  await screen.findByText(original);
  fireEvent.click(screen.getByRole("button", { name: "翻译为中文" }));
  await screen.findByText("Translation unavailable");
  fireEvent.click(screen.getByRole("button", { name: "带入此案例" }));
  expect(onUse).toHaveBeenLastCalledWith(original);

  vi.mocked(api).mockResolvedValueOnce({ original, translation: translated, cached: false, locale: "zh" });
  fireEvent.click(screen.getByRole("button", { name: "重新翻译" }));
  await waitFor(() => expect(screen.getByText(translated)).toBeTruthy());
});

test("the original example renders explicit LaTeX units and its data table while preserving the source", async () => {
  const source = String.raw`Output is $10 \ \mathrm{kg} / \ \mathrm{h}$; prices are $4 and $8.

| Week | 1 | 2 |
|---|---|---|
| I | 10000 | 12000 |`;
  vi.mocked(api).mockResolvedValueOnce({ total: 1, cases: [{ ...page.cases[0], description: source }] });
  const onUse = openLibrary();
  await screen.findByRole("table");
  expect(document.querySelectorAll(".katex-mathml")).toHaveLength(1);
  expect(screen.getByText(/prices are \$4 and \$8/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "带入此案例" }));
  expect(onUse).toHaveBeenLastCalledWith(source);
});

test.each([
  ["zh", "译文为空，请重试。", "翻译为中文"],
  ["en", "The translation was empty. Please retry.", "Translate to English"],
])("translation validation errors follow the %s interface language", async (locale, expected, button) => {
  language.value = locale;
  vi.mocked(api).mockResolvedValueOnce(page).mockRejectedValueOnce(new Error(
    'HTTP 502: {"detail":"The translation was empty. Please retry."}'));
  openLibrary();
  fireEvent.click(await screen.findByRole("button", { name: button }));
  await screen.findByText(expected);
});
