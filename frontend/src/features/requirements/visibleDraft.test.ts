import { expect, test } from "vitest";
import { visibleDraft } from "./visibleDraft";

test("settling the last open question hides its heading and empty optional sections", () => {
  const conditions = "## 已知条件\n每件 A 用 2 小时。预算无上限。";
  expect(visibleDraft(conditions + "\n\n## 待确认\n- 无（工时单位已确认）。\n\n## 备注\n\n附件：无。")).toBe(conditions);
  expect(visibleDraft("## Goal\nMinimize cost.\n\n## Open questions\nNone.\n\n**Notes:** N/A")).toBe("## Goal\nMinimize cost.");
});

test("real questions, business constraints and quoted examples survive cleanup", () => {
  const draft = "## 假设\n每周营业 5 天。\n\n## 约束\n- 无夜班。\n\n## 待确认事项\n- 无待确认项。\n- 周五需要几人？\n\n```text\n备注：无\n```";
  expect(visibleDraft(draft)).toBe(draft.replace("- 无待确认项。\n", ""));
  expect(visibleDraft("利润按元计。\n待确认：无。\n预算无上限。")).toBe("利润按元计。\n预算无上限。");
  const literal = "## 输入数据\n\n| 值 | 含义 |\n| --- | --- |\n| 无 | 无上限 |\n\n预算：无上限。\n";
  expect(visibleDraft(literal)).toBe(literal);
});
