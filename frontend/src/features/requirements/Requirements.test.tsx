import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { initialDraft } from "@/features/composer/Composer";
import { client } from "@/features/runs/sdk";
import { Requirements } from "./Requirements";

vi.mock("@/api", () => ({ api: vi.fn(async () => ({ libraries: {} })) }));
vi.mock("@/features/runs/sdk", () => ({
  client: { threads: { get: vi.fn(), search: vi.fn(), update: vi.fn(), create: vi.fn(), updateState: vi.fn() }, runs: { create: vi.fn(), cancel: vi.fn() } },
}));
vi.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: vi.fn(() => ({
    messages: [], values: {}, isLoading: false, isThreadLoading: false,
    error: undefined, submit: vi.fn(), stop: vi.fn(), joinStream: vi.fn(), switchThread: vi.fn(),
  })),
}));
vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });

afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks(); });

test("Ctrl+Enter on the Requirements thread-error screen never submits an unrelated quick-solve draft", async () => {
  vi.mocked(client.threads.search).mockRejectedValueOnce(new Error("thread load failed"));
  const onStart = vi.fn();
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Harness() {
    const [draft, setDraft] = useState(() => ({ ...initialDraft(), description: "unrelated quick-solve problem" }));
    return <Requirements
      threadId="broken-thread"
      searchConfigured={false}
      options={{ methods: [{ id: "direct", name: "Direct", description: "", source: null, languages: null }],
        languages: [{ id: "pyomo", name: "Pyomo", solver: "highs" }], providers: [], datasets: [] }}
      presets={[{ id: "p1", source: "saved", provider: "deepseek", model: "m1", base_url: "", temperature: null, max_tokens: null, extra_body: {}, tokens_today: 0 }]}
      draft={draft}
      setDraft={setDraft}
      onStart={onStart}
      onCompare={vi.fn()}
      openPresets={vi.fn()}
      onFinished={vi.fn()}
      onUse={vi.fn()}
    />;
  }
  render(<QueryClientProvider client={query}><Harness /></QueryClientProvider>);
  await screen.findByText("thread load failed");
  fireEvent.keyDown(window, { key: "Enter", ctrlKey: true });
  expect(onStart).not.toHaveBeenCalled();
});
