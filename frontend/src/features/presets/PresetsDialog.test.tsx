import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "@/api";
import { PresetsDialog } from "./PresetsDialog";

vi.mock("@/api", () => ({ api: vi.fn() }));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

function openForm() {
  render(<PresetsDialog presets={[]} dailyTokens={0}
    providers={[{ id: "openai", label: "OpenAI", protocol: "openai", base_url: "https://example.com/v1" }]}
    onClose={vi.fn()} onChange={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("API 密钥"), { target: { value: "test-key" } });
  fireEvent.change(screen.getByLabelText("模型 ID"), { target: { value: "test-model" } });
  fireEvent.click(screen.getByRole("button", { name: "高级参数" }));
  return screen.getByLabelText("额外请求参数（JSON）");
}

test.each(["[]", "null", "true", "42", '"text"'])("preset parameters reject %s before a request and allow correction", value => {
  const input = openForm();
  fireEvent.change(input, { target: { value } });
  expect(input.getAttribute("aria-invalid")).toBe("true");
  expect(screen.getByText("请填写 JSON 对象，不能是数组、空值或单个值。")).toBeTruthy();
  expect((screen.getByRole("button", { name: "读取可用模型" }) as HTMLButtonElement).disabled).toBe(true);
  const form = input.closest("form")!;
  expect((document.querySelector('button[type="submit"]') as HTMLButtonElement).disabled).toBe(true);
  fireEvent.submit(form);
  expect(api).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: '{"thinking":{"type":"disabled"}}' } });
  expect(input.getAttribute("aria-invalid")).toBe("false");
  expect((document.querySelector('button[type="submit"]') as HTMLButtonElement).disabled).toBe(false);
  expect((screen.getByRole("button", { name: "读取可用模型" }) as HTMLButtonElement).disabled).toBe(false);
});

test("malformed preset JSON reports syntax errors and empty parameters use service defaults", () => {
  const input = openForm();
  fireEvent.change(input, { target: { value: "{" } });
  expect(screen.getByText("不是有效的 JSON。")).toBeTruthy();
  fireEvent.change(input, { target: { value: "   " } });
  expect(input.getAttribute("aria-invalid")).toBe("false");
  expect((document.querySelector('button[type="submit"]') as HTMLButtonElement).disabled).toBe(false);
});

test.each([
  ["接口地址", "http://127.0.0.1:8796/v1"],
  ["API 密钥", "updated-test-key"],
])("changing %s clears the previous model catalog and allows a fresh lookup", async (label, value) => {
  vi.mocked(api).mockResolvedValueOnce({ models: ["test-model-original"] });
  openForm();
  fireEvent.click(screen.getByRole("button", { name: "读取可用模型" }));
  expect(await screen.findByRole("button", { name: "test-model-original" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
  expect(screen.queryByRole("button", { name: "test-model-original" })).toBeNull();
  expect((screen.getByLabelText("模型 ID") as HTMLInputElement).value).toBe("test-model");
  vi.mocked(api).mockResolvedValueOnce({ models: ["test-model-updated"] });
  fireEvent.click(screen.getByRole("button", { name: "读取可用模型" }));
  expect(await screen.findByRole("button", { name: "test-model-updated" })).toBeTruthy();
  expect(vi.mocked(api).mock.lastCall?.[1]).toMatchObject(label === "接口地址" ? { base_url: value } : { api_key: value });
});
