import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { RunView } from "./RunView";

vi.mock("@/lib/useDesktop", () => ({ useDesktop: () => false }));
vi.mock("./useRun", () => ({ useRun: () => ({
  meta: { title: "打印机", method: "direct" }, values: { code: "pass", solve: {
    variables: {}, objective: 0, status: "optimal", output: "", error: null,
  } }, steps: [], live: {}, run: { status: "success" }, streaming: false, error: null,
}) }));
vi.stubGlobal("ResizeObserver", class { observe = vi.fn(); disconnect = vi.fn(); });
afterEach(() => { cleanup(); window.history.replaceState(null, "", "/"); });

function show(embedded = false, checkpoint = "v1") {
  const noop = vi.fn();
  return render(<TooltipProvider><RunView threadId="printer" source={{ thread_id: "printer", checkpoint_id: checkpoint }}
    embedded={embedded} options={{ methods: [], languages: [], datasets: [], providers: [] }} onFinished={noop} onDiscuss={noop}
    onCompare={noop} onMetaChange={noop} onRevise={noop} onEdit={noop} onRerun={noop} onDelete={noop} onScenarios={noop}
    onConversation={noop} /></TooltipProvider>);
}

test("restores the artifact tab on reload without losing the pinned checkpoint", () => {
  window.history.replaceState(null, "", "/run/printer?checkpoint=v1&tab=invalid");
  const first = show();
  expect(screen.getByRole("tab", { selected: true, name: "求解结果" })).toBeTruthy();
  fireEvent.mouseDown(screen.getByRole("tab", { name: "求解代码" }), { button: 0 });
  expect(location.search).toBe("?checkpoint=v1&tab=code");
  first.unmount();
  show();
  expect(screen.getByRole("tab", { selected: true, name: "求解代码" })).toBeTruthy();
});

test("a conversation's saved tab applies only to the displayed run and checkpoint", () => {
  window.history.replaceState(null, "", "/agent/chat");
  const first = show(true);
  fireEvent.mouseDown(screen.getByRole("tab", { name: "求解代码" }), { button: 0 });
  first.unmount();
  const other = show(true, "v2");
  expect(screen.getByRole("tab", { selected: true, name: "求解结果" })).toBeTruthy();
  other.unmount();
  show(true);
  expect(screen.getByRole("tab", { selected: true, name: "求解代码" })).toBeTruthy();
});
