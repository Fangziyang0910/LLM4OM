import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { Sidebar, resultText } from "./Sidebar";
import type { Entry } from "@/features/runs/types";

afterEach(cleanup);

const entry = (id: string, created: Date, state = "success"): Entry => ({
  id, created: created.toISOString(), updated: created.toISOString(), state,
  meta: { kind: "optimization", title: `对话 ${id}`, preset: null, provider: null, model: null },
  objective: null, elapsed: null, failure: null, usage: null,
});

test("every independent conversation remains visible within each date group", () => {
  const today = new Date(); today.setHours(12, 0, 0, 0);
  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1);
  const entries = [entry("newest", today), entry("second", today), entry("older", yesterday), entry("oldest", yesterday)];
  render(<Sidebar entries={entries} current="newest" options={null} presets={[]} query="" hasMore={false} loading={false} error={null}
    onQuery={vi.fn()} onLoadMore={vi.fn()} onRetry={vi.fn()} onNew={vi.fn()} onAgent={vi.fn()} onOpen={vi.fn()}
    onCompare={vi.fn()} onDelete={vi.fn()} onExamples={vi.fn()} onPresets={vi.fn()} />);
  const history = screen.getByRole("navigation", { name: "运行记录" });
  for (const item of entries) expect(within(history).getByRole("button", { name: new RegExp(`^${item.meta.title}`) })).toBeTruthy();
  expect(within(history).getByRole("button", { name: /^对话 newest/ }).getAttribute("aria-current")).toBe("page");
  expect(within(history).getAllByRole("heading").map(node => node.textContent)).toEqual(["今天", "昨天"]);
});

test.each(["optimization", "requirements", "solution_chat"] as const)("%s history reflects a stopped or failed turn", kind => {
  const conversation = entry("chat", new Date());
  conversation.meta = { ...conversation.meta, kind } as Entry["meta"];
  expect(resultText({ ...conversation, state: "interrupted" })).toBe("已停止");
  expect(resultText({ ...conversation, state: "error" })).toBe("运行出错");
  expect(resultText({ ...conversation, state: "timeout" })).toBe("超时");
  expect(resultText({ ...conversation, state: "pending" })).toBe("排队中");
});
