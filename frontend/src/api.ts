// 唯一的 HTTP 通道:沿用既有 workbench REST 形状,变更请求携带启动令牌。
export let apiToken = "";

export function setApiToken(token: string) {
  apiToken = token;
}

export async function api<T = unknown>(path: string, value?: unknown, apiKey?: string): Promise<T> {
  const response = await fetch(
    path,
    value === undefined
      ? {}
      : {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-LLM4OM-Token": apiToken,
            ...(apiKey ? { "X-LLM4OM-Provider-Key": apiKey } : {}),
          },
          body: JSON.stringify(value),
        },
  );
  const result = await response.json();
  if (!response.ok || result.error)
    throw new Error(result.error?.message || "请求失败");
  return result as T;
}
