import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { Timeline } from "./Timeline";
import type { Step } from "./types";

afterEach(cleanup);

test("streamed output follows the bottom until the reader scrolls up", () => {
  const steps = [{ id: "call", type: "llm", title: "model", running: true, content: "" }] as Step[];
  const props = { steps, active: true, onShow: vi.fn() };
  const { rerender } = render(<Timeline {...props} live={{ call: { text: "First lines", reasoning: "" } }} />);
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
