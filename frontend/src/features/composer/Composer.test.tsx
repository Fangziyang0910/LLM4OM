import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { toast } from "sonner";
import { Composer, initialDraft } from "./Composer";
import { useRunLauncher } from "./RunSettings";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/api", () => ({ api: vi.fn(async () => ({ libraries: {} })) }));
vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));

afterEach(() => { cleanup(); localStorage.removeItem("llm4om-draft"); vi.clearAllMocks(); });

function Form() {
  const [draft, setDraft] = useState(initialDraft);
  const [client] = useState(() => new QueryClient());
  return <QueryClientProvider client={client}><Composer options={{ methods: [{ id: "direct", name: "Direct", description: "", source: null, languages: null }],
    languages: [{ id: "pyomo", name: "Pyomo", solver: "highs" }], providers: [], datasets: [] }}
    presets={[]} draft={draft} setDraft={setDraft} onStart={vi.fn()} onCompare={vi.fn()}
    openPresets={vi.fn()} openExamples={vi.fn()} onDiscuss={vi.fn()} /></QueryClientProvider>;
}

test("finishing an attachment preserves text edited while the file was loading", async () => {
  const { container } = render(<Form />);
  let resolve!: (text: string) => void;
  const file = { name: "data.csv", size: 12, text: () => new Promise<string>(done => { resolve = done; }) };
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } });
  expect((screen.getByRole("button", { name: /正在读取数据/ }) as HTMLButtonElement).disabled).toBe(true);
  expect((container.querySelector('input[type="file"]') as HTMLInputElement).disabled).toBe(true);
  fireEvent.change(screen.getByRole("textbox", { name: "问题描述" }), { target: { value: "new problem" } });
  await act(async () => resolve("a,b\n1,2"));
  expect((screen.getByRole("textbox", { name: "问题描述" }) as HTMLTextAreaElement).value).toBe("new problem");
  expect(screen.getByText("data.csv")).toBeTruthy();
  expect(JSON.parse(localStorage.getItem("llm4om-draft")!)).toMatchObject({ description: "new problem", data: { "data.csv": "a,b\n1,2" } });
});

test("an unreadable text attachment reports the failure and keeps the draft", async () => {
  const { container } = render(<Form />);
  const file = { name: "data.csv", size: 12, text: () => Promise.reject(new Error("read failed")) };
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } });
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("无法读取 data.csv：read failed"));
  expect(JSON.parse(localStorage.getItem("llm4om-draft")!).data).toEqual({});
});

test("dropping unsupported files reports their format without discarding supported attachments", async () => {
  render(<Form />);
  const read = vi.fn(async () => "%PDF-1.7 binary contents");
  fireEvent.drop(screen.getByRole("textbox", { name: "问题描述" }), { dataTransfer: { files: [
    { name: "report.pdf", size: 20, text: read },
    { name: "data.CSV", size: 12, text: async () => "name,price\nA,003\n" },
  ] } });
  await screen.findByText("data.CSV");
  expect(screen.queryByText("report.pdf")).toBeNull();
  expect(read).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledWith("不支持 report.pdf，请添加 CSV、TSV、JSON、TXT 或 XLSX 文件。");
  expect(JSON.parse(localStorage.getItem("llm4om-draft")!).data).toEqual({ "data.CSV": "name,price\nA,003\n" });
});

test("an empty stored draft uses the defaults", () => {
  localStorage.setItem("llm4om-draft", "null");
  expect(initialDraft()).toMatchObject({ description: "", data: {}, method: "direct" });
});

test("saved backend pairs become one library while preserving the chosen backend", () => {
  localStorage.setItem("llm4om-draft", JSON.stringify({ language: "cvxpy_osqp" }));
  expect(initialDraft()).toMatchObject({ language: "cvxpy", solver: "OSQP" });
  localStorage.setItem("llm4om-draft", JSON.stringify({ language: "pywraplp" }));
  expect(initialDraft()).toMatchObject({ language: "ortools" });
});

test("changing run settings outside Composer persists to localStorage without overwriting the saved quick-solve text", () => {
  localStorage.setItem("llm4om-draft", JSON.stringify({ description: "quick-solve text", method: "direct", language: "pyomo" }));
  function StandaloneLauncher() {
    const [draft, setDraft] = useState(initialDraft);
    const { settingsTrigger, settingsDialog } = useRunLauncher({
      options: {
        methods: [
          { id: "direct", name: "Direct", description: "", source: null, languages: null },
          { id: "optimind", name: "OptiMind", description: "", source: null, languages: null },
        ],
        languages: [{ id: "pyomo", name: "Pyomo", solver: "highs" }],
        providers: [],
        datasets: [],
      },
      presets: [],
      draft,
      setDraft,
      onStart: vi.fn(),
      onCompare: vi.fn(),
      openPresets: vi.fn(),
      problem: { description: "requirements thread draft", data: {} },
    });
    return <>{settingsTrigger}{settingsDialog}</>;
  }
  render(<QueryClientProvider client={new QueryClient()}><StandaloneLauncher /></QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: "查看运行设置" }));
  fireEvent.click(screen.getByRole("radio", { name: "OptiMind" }));
  expect(JSON.parse(localStorage.getItem("llm4om-draft")!)).toMatchObject({
    description: "quick-solve text",
    method: "optimind",
  });
});

test("Ctrl+Enter does nothing while the launcher is disabled (such as on a failed thread screen)", () => {
  const onStart = vi.fn();
  function DisabledLauncher() {
    const [draft, setDraft] = useState(() => ({ ...initialDraft(), description: "saved quick-solve" }));
    const { settingsTrigger } = useRunLauncher({
      options: {
        methods: [{ id: "direct", name: "Direct", description: "", source: null, languages: null }],
        languages: [{ id: "pyomo", name: "Pyomo", solver: "highs" }],
        providers: [],
        datasets: [],
      },
      presets: [{ id: "p1", source: "saved", provider: "deepseek", model: "m1", base_url: "", temperature: null, max_tokens: null, extra_body: {}, tokens_today: 0 }],
      draft,
      setDraft,
      onStart,
      onCompare: vi.fn(),
      openPresets: vi.fn(),
      problem: { description: "saved quick-solve", data: {}, origin: "failed-thread" },
      disabled: true,
    });
    return settingsTrigger;
  }
  render(<QueryClientProvider client={new QueryClient()}><DisabledLauncher /></QueryClientProvider>);
  fireEvent.keyDown(window, { key: "Enter", ctrlKey: true });
  expect(onStart).not.toHaveBeenCalled();
});

test("selecting a self-contained method like AutoCO displays its built-in solver pool and launches with its own id", async () => {
  const onStart = vi.fn(async () => {});
  function AutoCOLauncher() {
    const [draft, setDraft] = useState(initialDraft);
    const { settingsTrigger, startButton, settingsDialog } = useRunLauncher({
      options: {
        methods: [
          { id: "direct", name: "Direct", description: "", source: null, languages: null },
          { id: "autoco", name: "AutoCO", description: "metaheuristic pool", source: null, languages: [], builtin_solver: true },
        ],
        languages: [{ id: "pyomo", name: "Pyomo", solver: "highs" }],
        providers: [],
        datasets: [],
      },
      presets: [{ id: "p1", source: "saved", provider: "deepseek", model: "m1", base_url: "", temperature: null, max_tokens: null, extra_body: {}, tokens_today: 0 }],
      draft,
      setDraft,
      onStart,
      onCompare: vi.fn(),
      openPresets: vi.fn(),
      problem: { description: "Solve a vehicle routing problem.", data: {} },
    });
    return <>{settingsTrigger}{startButton}{settingsDialog}</>;
  }
  render(<QueryClientProvider client={new QueryClient()}><AutoCOLauncher /></QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: "查看运行设置" }));
  fireEvent.click(screen.getByRole("radio", { name: /AutoCO/ }));
  expect(screen.getByText("AutoCO 内置智能优化算法池")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "完成" }));
  expect(screen.getByRole("button", { name: "查看运行设置" }).textContent).toBe("AutoCO");
  fireEvent.click(screen.getByRole("button", { name: "立即求解" }));
  await waitFor(() => expect(onStart).toHaveBeenCalledWith(expect.objectContaining({
    method: "autoco",
    language: "autoco",
    solver: "AUTO",
  })));
});
