import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { toast } from "sonner";
import { Composer, initialDraft } from "./Composer";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

afterEach(() => { cleanup(); localStorage.removeItem("llm4om-draft"); vi.clearAllMocks(); });

function Form() {
  const [draft, setDraft] = useState(initialDraft);
  return <Composer options={{ methods: [{ id: "direct", name: "Direct", description: "", source: null, languages: null }],
    languages: [{ id: "pyomo", name: "Pyomo", solver: "highs" }], providers: [], datasets: [] }}
    presets={[]} draft={draft} setDraft={setDraft} onStart={vi.fn()} onCompare={vi.fn()}
    openPresets={vi.fn()} openExamples={vi.fn()} />;
}

test("finishing an attachment preserves text edited while the file was loading", async () => {
  const { container } = render(<Form />);
  let resolve!: (text: string) => void;
  const file = { name: "data.csv", size: 12, text: () => new Promise<string>(done => { resolve = done; }) };
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } });
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

test("an empty stored draft uses the defaults", () => {
  localStorage.setItem("llm4om-draft", "null");
  expect(initialDraft()).toMatchObject({ description: "", data: {}, method: "direct" });
});
