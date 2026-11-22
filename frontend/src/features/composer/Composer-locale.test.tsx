import { useState } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { Composer, initialDraft } from "./Composer";

const language = vi.hoisted(() => ({ value: "en" }));
vi.mock("@/i18n", async () => {
  const { en } = await import("@/locales/en");
  return {
    get locale() { return language.value; },
    t: (text: string) => language.value === "zh" ? text : en[text] ?? text,
  };
});
vi.mock("@/api", () => ({ api: vi.fn(async () => ({ libraries: {} })) }));
vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));

afterEach(() => { cleanup(); localStorage.removeItem("llm4om-draft"); });

function Form() {
  const [draft, setDraft] = useState(initialDraft);
  const [client] = useState(() => new QueryClient());
  return <QueryClientProvider client={client}><Composer
    options={{ methods: [{ id: "direct", name: "Direct", description: "", source: null, languages: null }],
      languages: [{ id: "pyomo", name: "Pyomo", solver: "highs" }], providers: [], datasets: [] }}
    presets={[]} draft={draft} setDraft={setDraft} onStart={vi.fn()} onCompare={vi.fn()}
    openPresets={vi.fn()} openExamples={vi.fn()} /></QueryClientProvider>;
}

test.each([
  ["en", "Production planning", "Increase profit", "A factory makes products A and B"],
  ["en", "Transportation", "With data", "Three warehouses ship one product to four customers"],
  ["en", "Assignment", "Reduce work time", "Assign 4 workers to 4 tasks"],
  ["zh", "生产计划", "提升利润", "工厂生产 A、B 两种产品"],
  ["zh", "运输问题", "附数据表", "三个仓库向四个客户运送同一种货物"],
  ["zh", "任务指派", "缩短工时", "把 4 名员工分配到 4 项任务"],
])("%s starter %s localizes its full card and draft while preserving data", (locale, title, tag, beginning) => {
  language.value = locale;
  render(<Form />);
  const card = screen.getByRole("button", { name: new RegExp(`^${title}`) });
  expect(within(card).getByText(tag)).toBeTruthy();
  expect(/[㐀-鿿]/.test(card.textContent ?? "")).toBe(locale === "zh");
  fireEvent.click(card);
  const draft = JSON.parse(localStorage.getItem("llm4om-draft")!);
  expect(draft.description.startsWith(beginning)).toBe(true);
  expect(/[㐀-鿿]/.test(draft.description)).toBe(locale === "zh");
  expect(draft.data).toEqual(title === "Transportation" || title === "运输问题" ? {
    "transport.csv": "from,C1,C2,C3,C4,supply\nW1,4,6,9,5,120\nW2,7,3,4,8,150\nW3,6,5,7,3,100\ndemand,80,90,110,70,\n",
  } : {});
});
