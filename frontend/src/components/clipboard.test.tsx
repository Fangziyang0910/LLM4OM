import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { toast } from "sonner";
import { CopyButton, copyText } from "./Content";

vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const originalCommand = Object.getOwnPropertyDescriptor(document, "execCommand");

afterEach(() => {
  cleanup();
  document.querySelectorAll("textarea").forEach(area => area.remove());
  if (originalCommand) Object.defineProperty(document, "execCommand", originalCommand);
  else Reflect.deleteProperty(document, "execCommand");
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

test.each(["unavailable", "denied"])("copying works when the Clipboard API is %s and preserves the editing position", async state => {
  const writeText = vi.fn().mockRejectedValue(new Error("clipboard permission denied"));
  vi.stubGlobal("navigator", state === "denied" ? { clipboard: { writeText } } : {});
  const input = Object.assign(document.createElement("textarea"), { value: "keep this draft" });
  document.body.append(input);
  input.focus();
  input.setSelectionRange(2, 7);
  let copied = "";
  const fallback = vi.fn(() => {
    copied = document.querySelectorAll("textarea")[1].value;
    return true;
  });
  Object.defineProperty(document, "execCommand", { configurable: true, value: fallback });
  await copyText("生产数量 A=3，B=2");
  expect(copied).toBe("生产数量 A=3，B=2");
  expect(fallback).toHaveBeenCalledWith("copy");
  expect(document.querySelectorAll("textarea")).toHaveLength(1);
  expect(document.activeElement).toBe(input);
  expect([input.selectionStart, input.selectionEnd]).toEqual([2, 7]);
});

test("a successful Clipboard API copy does not use the fallback", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  const fallback = vi.fn();
  Object.defineProperty(document, "execCommand", { configurable: true, value: fallback });
  await copyText("source code");
  expect(writeText).toHaveBeenCalledWith("source code");
  expect(fallback).not.toHaveBeenCalled();
});

test("a failed fallback removes its temporary field and restores focus", async () => {
  vi.stubGlobal("navigator", {});
  const input = Object.assign(document.createElement("textarea"), { value: "keep this draft" });
  document.body.append(input);
  input.focus();
  Object.defineProperty(document, "execCommand", { configurable: true, value: () => { throw new Error("copy blocked"); } });
  await expect(copyText("source code")).rejects.toThrow("copy blocked");
  expect(document.querySelectorAll("textarea")).toHaveLength(1);
  expect(document.activeElement).toBe(input);
});

test("the copy button explains a blocked copy rather than failing silently", async () => {
  vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("copy blocked")) } });
  Object.defineProperty(document, "execCommand", { configurable: true, value: () => false });
  render(<CopyButton text="source code" />);
  fireEvent.click(screen.getByRole("button", { name: "复制" }));
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("复制失败，请选中文本后手动复制。"));
});
