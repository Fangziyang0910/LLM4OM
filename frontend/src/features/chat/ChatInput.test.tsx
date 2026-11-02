import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ChatInput } from "./ChatInput";

afterEach(cleanup);

test.each(["", " \n "])("Enter never sends an empty or whitespace draft: %j", value => {
  const onSend = vi.fn();
  render(<ChatInput value={value} onChange={() => {}} disabled={false} loading={false} onSend={onSend}
    onStop={() => {}} presets={[]} onPreset={() => {}} openPresets={() => {}} label="消息" onThinking={() => {}} />);
  fireEvent.keyDown(screen.getByRole("textbox", { name: "消息" }), { key: "Enter" });
  expect(onSend).not.toHaveBeenCalled();
});

test("pending attachments block every send path while keeping message editing available", () => {
  const send = vi.fn(), change = vi.fn();
  const { container } = render(<ChatInput value="next message" onChange={change} disabled={false} loading={false} sendingDisabled onSend={send}
    onStop={() => {}} presets={[]} onPreset={() => {}} openPresets={() => {}} label="消息" onThinking={() => {}} />);
  const input = screen.getByRole("textbox", { name: "消息" }) as HTMLTextAreaElement;
  expect(input.disabled).toBe(false);
  expect((screen.getByRole("button", { name: "发送" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(input, { target: { value: "edited message" } });
  expect(change).toHaveBeenCalledWith("edited message");
  fireEvent.keyDown(input, { key: "Enter" });
  fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
  fireEvent.keyDown(input, { key: "Enter", metaKey: true });
  fireEvent.submit(container.querySelector("form")!);
  expect(send).not.toHaveBeenCalled();
});
