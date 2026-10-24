import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, expect, test, vi } from "vitest";
import { ChatMessages, type ChatProgress } from "./Messages";

afterEach(cleanup);
const question: Message = { type: "human", id: "question", content: "帮我看一下方案" };

test.each([
  ["calculation", { calculation: { expression: "2 - 2", result: 0, matched_variables: 0 } }, "计算核对"],
  ["selected_plan", { selected_plan: { name: "原方案", source: { thread_id: "original" } } }, "已选择：原方案"],
  ["plans", { plans: [{ name: "已求解方案", source: { thread_id: "saved" }, instruction: "原问题", status: "optimal", objective: 0 }] }, "已求解方案"],
  ["search", { query: "公开资料", results: [{ title: "实际来源", url: "https://example.org/reference" }] }, "实际来源"],
  ["draft", {}, "需求稿已整理"],
])("a typed %s artifact renders independently of the tool's name", (type, artifact, text) => {
  render(<ChatMessages messages={[question, { type: "tool", name: "another_capability", tool_call_id: "result", content: "",
    artifact: { ...artifact, type } }]} loading={false} label="优化助手" onRetry={vi.fn()} />);
  expect(screen.getByText(text)).toBeTruthy();
});

test("an unknown artifact type does not fall back to an unrelated legacy renderer", () => {
  render(<ChatMessages messages={[question, { type: "tool", name: "calculate", tool_call_id: "result", content: "",
    artifact: { type: "unknown", calculation: { expression: "1 + 1", result: 2, matched_variables: 0 } } }]}
    loading={false} label="优化助手" onRetry={vi.fn()} />);
  expect(screen.queryByLabelText("计算核对")).toBeNull();
});

test("chat formulas render as math while user-entered prices remain literal", () => {
  const { container } = render(<ChatMessages messages={[{...question, content: "单价 $4，另一项 $8。数量为 $x_A$。"},
    { type: "ai", content: String.raw`令 $x_A$ 为产量，约束为 \(2x_A + x_B \le 8\)。` }]}
    loading={false} label="优化助手" onRetry={vi.fn()} />);
  expect(container.querySelectorAll(".katex-mathml")).toHaveLength(3);
  expect(screen.getByRole("article", { name: "你" }).textContent).toContain("单价 $4，另一项 $8。");
});

test("reasoning-only streaming is visible, stays separate from the answer, and can be expanded", () => {
  const thought: Message = { type: "ai", id: "reply", content: "", additional_kwargs: { reasoning_content: "先核对资源容量。" } };
  const { container, rerender } = render(<ChatMessages messages={[question, thought]} loading label="优化助手" onRetry={vi.fn()} />);
  expect(screen.getByText("正在思考……")).toBeTruthy();
  expect(screen.queryByText("正在准备回复……")).toBeNull();
  const details = container.querySelector("details")!;
  expect(details.open).toBe(false);
  expect(screen.queryByText("先核对资源容量。")).toBeNull();
  details.open = true;
  fireEvent(details, new Event("toggle"));
  expect(screen.getByText("先核对资源容量。")).toBeTruthy();
  rerender(<ChatMessages messages={[question, { ...thought, content: "最终目标值是 13。" }]} loading={false} label="优化助手" onRetry={vi.fn()} />);
  expect(screen.getByText("思考过程")).toBeTruthy();
  expect(details.open).toBe(true);
  expect(screen.getByText("最终目标值是 13。")).toBeTruthy();
});

test("a first calculation's result card uses the stored objective and opens its independent run", () => {
  const open = vi.fn();
  render(<ChatMessages messages={[question, { type: "tool", name: "model_and_solve", tool_call_id: "calculate", content: "",
    artifact: { plans: [{ name: "生产计划", source: { thread_id: "calculated", checkpoint_id: "saved" },
      instruction: "实际问题", status: "optimal", objective: 0 }] } }]} loading={false} label="优化助手" onRetry={vi.fn()} onOpenPlan={open} />);
  const result = screen.getByRole("complementary", { name: "本轮计算结果" });
  expect(result.textContent).toContain("目标值 0");
  fireEvent.click(within(result).getByRole("button", { name: "查看计算方案" }));
  expect(open).toHaveBeenCalledWith("calculated");
});

test("arithmetic shows actual tool output with its expression available on demand", () => {
  render(<ChatMessages messages={[question, { type: "tool", name: "calculate", tool_call_id: "math", content: "",
    artifact: { calculation: { expression: "sum(values)", result: 0, matched_variables: 250 } } }]}
    loading={false} label="优化助手" onRetry={vi.fn()} />);
  const calculation = screen.getByLabelText("计算核对");
  expect(calculation.textContent).toContain("250 个实际决策值");
  expect(calculation.querySelector("strong")!.textContent).toBe("0");
  expect(calculation.querySelector("code")!.textContent).toBe("sum(values)");
  expect((calculation as HTMLDetailsElement).open).toBe(false);
});

test("choosing a saved plan has a compact receipt that opens that plan", () => {
  const open = vi.fn();
  render(<ChatMessages messages={[question, { type: "tool", name: "select_plan", tool_call_id: "choose", content: "",
    artifact: { selected_plan: { name: "第二个方案", source: { thread_id: "second" } } } }]}
    loading={false} label="优化助手" onRetry={vi.fn()} onOpenPlan={open} />);
  fireEvent.click(screen.getByRole("button", { name: "已选择：第二个方案" }));
  expect(open).toHaveBeenCalledWith("second");
});

test("recoverable tool errors keep details folded without hiding them", () => {
  render(<ChatMessages messages={[question, { type: "tool", name: "calculate", tool_call_id: "math", content: "division by zero", status: "error" }]}
    loading={false} label="优化助手" onRetry={vi.fn()} />);
  const details = screen.getByText("这一步未完成").closest("details")!;
  expect(details.open).toBe(false);
  expect(details.textContent).toContain("division by zero");
  expect(screen.queryByRole("button", { name: "重试这一轮" })).toBeNull();
});

test("only an unfinished turn offers retry, and error details stay available without filling the log", () => {
  const retry = vi.fn();
  const { rerender } = render(<ChatMessages messages={[question]} loading={false} label="方案助手" onRetry={retry} />);
  expect(screen.getByText("这轮回复已停止，可以重新回答。")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "重试这一轮" }));
  expect(retry).toHaveBeenCalledOnce();
  rerender(<ChatMessages messages={[question]} loading={false} label="方案助手" onRetry={retry} failure="HTTP 503: upstream unavailable" />);
  expect(screen.getByRole("alert")).toBeTruthy();
  const details = screen.getByText("查看错误详情").closest("details")!;
  expect(details.open).toBe(false);
  expect(details.textContent).toContain("HTTP 503");
  rerender(<ChatMessages messages={[question]} loading={false} label="方案助手" onRetry={retry} failure="CancelledError()" />);
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByText("这轮回复已停止，可以重新回答。")).toBeTruthy();
  rerender(<ChatMessages messages={[question, { type: "ai", content: "已回答" }]} loading={false} label="方案助手" onRetry={retry} />);
  expect(screen.queryByRole("button", { name: "重试这一轮" })).toBeNull();
  rerender(<ChatMessages messages={[]} loading={false} label="方案助手" onRetry={retry} failure="CancelledError()" />);
  expect(screen.queryByRole("button", { name: "重试这一轮" })).toBeNull();
  expect(screen.getByText("请从输入框重新发送，草稿会保留。")).toBeTruthy();
});

test("search sources are compact, use actual artifacts, and discard unsafe links", () => {
  render(<ChatMessages messages={[question, { type: "tool", name: "web_search", content: "", tool_call_id: "search",
    artifact: { query: "排班资料", results: [{ title: "排班参考", url: "https://example.org/guide", summary: "公开排班建议" },
      { title: "unsafe", url: "javascript:alert(1)" }] } }, { type: "ai", content: "这是[模型写的链接](https://other.example)" }]}
    loading={false} label="需求助手" onRetry={vi.fn()} />);
  const sources = screen.getByRole("complementary", { name: "搜索来源" });
  expect(sources.textContent).toContain("1 个来源");
  expect(sources.querySelector("details")!.open).toBe(false);
  expect(within(sources).queryByText("unsafe")).toBeNull();
  expect(within(sources).queryByText("模型写的链接")).toBeNull();
  expect(sources.textContent).toContain("公开排班建议");
});

test("a running calculation shows its actual stage once and removes it when the tool finishes", () => {
  const call: Message = { type: "ai", id: "assistant", content: "", tool_calls: [{ id: "calculate", name: "solve_scenarios", args: {} }] };
  const progress: ChatProgress = { type: "scenario_progress", tool_call_id: "calculate", name: "晚班增加一人", index: 2, total: 2, stage: "solve" };
  const { rerender } = render(<ChatMessages messages={[question, call]} loading label="方案助手" onRetry={vi.fn()} progress={progress} />);
  expect(screen.getAllByRole("status")).toHaveLength(1);
  expect(screen.getByRole("status").textContent).toContain("方案 2/2：晚班增加一人 · 正在求解");
  expect(screen.queryByText("正在准备回复……")).toBeNull();
  rerender(<ChatMessages messages={[question, call, { type: "tool", name: "solve_scenarios", content: "[]", tool_call_id: "calculate" }]}
    loading label="方案助手" onRetry={vi.fn()} progress={progress} />);
  expect(screen.queryByText(/方案 2\/2/)).toBeNull();
  expect(screen.getByText("正在准备回复……")).toBeTruthy();
});

test("computed plan cards show solver facts including zero values and open the saved plan", () => {
  const open = vi.fn(), compare = vi.fn();
  render(<ChatMessages messages={[question, { type: "tool", name: "solve_scenarios", content: "[]", tool_call_id: "calculate",
    artifact: { plans: [{ name: "零成本", instruction: "费用设为零", source: { thread_id: "zero", checkpoint_id: "saved" }, status: "optimal", objective: 0, group: "group" },
      { name: "条件冲突", instruction: "增加合同要求", source: { thread_id: "conflict", checkpoint_id: "saved2" }, status: "infeasible", objective: null, group: "group" }] } }]}
    loading={false} label="方案助手" onRetry={vi.fn()} onOpenPlan={open} onCompare={compare} />);
  const results = screen.getByRole("complementary", { name: "本轮计算结果" });
  expect(results.textContent).toContain("目标值 0");
  expect(results.textContent).toContain("不可行");
  fireEvent.click(within(results).getAllByRole("button", { name: "查看计算方案" })[0]);
  expect(open).toHaveBeenCalledWith("zero");
  fireEvent.click(within(results).getByRole("button", { name: "对比本轮方案" }));
  expect(compare).toHaveBeenCalledWith("group");
});
