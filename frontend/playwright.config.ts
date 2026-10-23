import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

// The browser tests run the built workbench (`npm run build` first) on a fresh workspace, with a scripted LLM
// and the local sandbox, so they need no key and no Docker. `uv sync --all-extras` provides the server.
const LLM_PORT = 8796, APP_PORT = 8797;
const workspace = process.env.LLM4OM_E2E_WORKSPACE ??= mkdtempSync(join(tmpdir(), "llm4om-e2e-"));

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://127.0.0.1:${APP_PORT}`, trace: "retain-on-failure", ...devices["Desktop Chrome"], locale: "zh-CN" },
  webServer: [
    { command: `uv run python e2e/mock_llm.py ${LLM_PORT}`, url: `http://127.0.0.1:${LLM_PORT}/v1/models`, reuseExistingServer: false },
    {
      command: `uv run llm4om serve --sandbox local --host 127.0.0.1 --port ${APP_PORT} --workspace ${workspace}`,
      url: `http://127.0.0.1:${APP_PORT}/api/options`, timeout: 120_000, reuseExistingServer: false,
      env: { LLM4OM_LLM_PROVIDER: "openai_compatible", LLM4OM_LLM_MODEL: "mock-model", LLM4OM_LLM_API_KEY: "e2e-not-a-key",
             LLM4OM_SEARCH_API_KEY: "e2e-search-key", LLM4OM_SEARCH_BASE_URL: `http://127.0.0.1:${LLM_PORT}/v1`,
             LLM4OM_LLM_NAME: "deepseek-v4.1 flash-1017",
             LLM4OM_LLM_EXTRA_BODY: "{}", LANGSMITH_TRACING: "false", LANGCHAIN_TRACING_V2: "false",
             LLM4OM_LLM_BASE_URL: `http://127.0.0.1:${LLM_PORT}/v1` },
    },
  ],
});
