import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The build goes into the Python package; the LangGraph server serves it beside its API.
const server = "http://127.0.0.1:8767";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: { outDir: "../src/llm4om/server/web_assets", emptyOutDir: true, target: "es2022", chunkSizeWarningLimit: 1500 },
  server: { proxy: { "/api": server, "/threads": server, "/assistants": server } },
  test: { environment: "jsdom" },
});
