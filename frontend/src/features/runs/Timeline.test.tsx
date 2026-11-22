import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { Timeline } from "./Timeline";
import type { Step } from "./types";

afterEach(cleanup);

test("streamed output follows the bottom until the reader scrolls up", () => {
  const steps = [{ id: "call", type: "llm", title: "model", running: true, content: "" }] as Step[];
  const props = { steps, active: true, onShow: vi.fn() };
  const { rerender } = render(<Timeline {...props} live={{ call: { text: "First lines", reasoning: "" } }} />);
  fireEvent.click(screen.getByRole("button", { name: "查看模型原始输出" }));
  const output = screen.getByLabelText("当前生成内容");
  Object.defineProperties(output, { clientHeight: { value: 200 }, scrollHeight: { value: 1000 } });
  rerender(<Timeline {...props} live={{ call: { text: "More generated lines", reasoning: "" } }} />);
  expect(output.scrollTop).toBe(1000);
  output.scrollTop = 100;
  fireEvent.scroll(output);
  rerender(<Timeline {...props} live={{ call: { text: "New lines while reading the beginning", reasoning: "" } }} />);
  expect(output.scrollTop).toBe(100);
  output.scrollTop = 800;
  fireEvent.scroll(output);
  rerender(<Timeline {...props} live={{ call: { text: "Follow the latest lines again", reasoning: "" } }} />);
  expect(output.scrollTop).toBe(1000);
});

test("live steps show the localized role and keep provider reasoning in an optional raw view", () => {
  const steps = [{ id: "call", type: "llm", title: "trival.decision_variable_expert", running: true, content: "" }] as Step[];
  const original = "Analyze the binary variables in the tour.";
  const { rerender } = render(<Timeline steps={steps} active live={{ call: { text: "var_type: bool", reasoning: original } }} onShow={vi.fn()} />);
  expect(screen.getByText("定义决策变量")).toBeTruthy();
  expect(screen.queryByText(original, { exact: false })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "查看模型原始输出" }));
  expect(screen.getByLabelText("当前生成内容").textContent).toContain(original);
  expect(screen.getByLabelText("当前生成内容").textContent).toContain("var_type: bool");
  rerender(<Timeline steps={steps} active live={{ call: { text: "var_type: bool; domain: {0,1}", reasoning: original } }} onShow={vi.fn()} />);
  expect(screen.getByLabelText("当前生成内容").textContent).toContain("domain: {0,1}");
});
