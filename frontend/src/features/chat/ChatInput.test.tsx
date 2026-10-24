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
