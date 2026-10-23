import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Infeasibility } from "@/features/runs/Infeasibility";

afterEach(cleanup);

it("shows the diagnostic evidence and sends a candidate to the revision form without running it", () => {
  const onAdjust = vi.fn();
  render(<Infeasibility onAdjust={onAdjust} explanation={{ summary: "产能不能满足最低交货量。",
    conflicts: [{ explanation: "最低交货量与切割能力冲突。", constraints: ["capacity: 2 x[A] + x[B] <= 8"] }],
    adjustments: [{ title: "增加切割能力", instruction: "将切割能力提高至 15，其他条件不变。" }] }} />);
  expect(screen.getByText("产能不能满足最低交货量。")).toBeTruthy();
  expect(screen.getByText("建议尚未验证。选择后可编辑调整要求，再重新建模验证。")).toBeTruthy();
  expect(onAdjust).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "尝试这个调整" }));
  expect(onAdjust).toHaveBeenCalledExactlyOnceWith("将切割能力提高至 15，其他条件不变。");
});
