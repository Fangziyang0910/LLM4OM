import { t } from "@/i18n";

// The platform's own routes. All requests are JSON; the server rejects other POST bodies.
export async function api<T>(path: string, body?: unknown, method = body === undefined ? "GET" : "POST"): Promise<T> {
  const response = await fetch(path, body === undefined ? { method } : {
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const value = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = value.detail;
    throw new Error(typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : t("请求失败（{status}）", { status: response.status }));
  }
  return value as T;
}
