import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { RevisionDialog } from "./RevisionDialog";

afterEach(cleanup);

test("a pending revision stays visible until the accepted request finishes", async () => {
  let complete!: () => void;
  const request = new Promise<void>(resolve => { complete = resolve; });
  const close = vi.fn();
  const revise = vi.fn(() => request);
  render(<RevisionDialog onClose={close} onRevise={revise} />);
  fireEvent.change(screen.getByRole("textbox", { name: "要调整什么？" }), { target: { value: "B 至少生产 3 件" } });
  fireEvent.click(screen.getByRole("button", { name: "生成新方案" }));
  const cancel = screen.getByRole("button", { name: "取消" }) as HTMLButtonElement;
  expect(cancel.disabled).toBe(true);
  fireEvent.click(cancel);
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(close).not.toHaveBeenCalled();
  expect(revise).toHaveBeenCalledTimes(1);
  await act(async () => complete());
  expect(close).toHaveBeenCalledTimes(1);
});
