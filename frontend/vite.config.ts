import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build goes into the Python package; the LangGraph server serves it beside its API.
const server = "http://127.0.0.1:8767";
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/llm4om/server/web_assets", emptyOutDir: true, target: "es2022", chunkSizeWarningLimit: 1500 },
  server: { proxy: { "/api": server, "/threads": server, "/assistants": server } },
});
