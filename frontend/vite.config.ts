import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The build goes into the Python package; the LangGraph server serves it beside its API.
const server = "http://127.0.0.1:8767";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    outDir: "../src/llm4om/server/web_assets", emptyOutDir: true, target: "es2022",
    // Libraries in chunks of their own stay cached across releases; the SDK chunk loads after the first paint.
    rolldownOptions: { output: { codeSplitting: { groups: [
      { name: "react", test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/ },
      { name: "markdown", test: /node_modules[\\/](katex|react-markdown|remark-|rehype-|micromark|mdast-|hast-|unified|highlight\.js|diff)/ },
      { name: "ui", test: /node_modules[\\/](@radix-ui|@floating-ui|radix-ui|sonner|tailwind-merge|@tanstack|lucide-react)/ },
    ] } } },
  },
  server: { proxy: { "/api": server, "/threads": server, "/assistants": server } },
  test: { environment: "jsdom", setupFiles: ["src/test-setup.ts"], include: ["src/**/*.test.{ts,tsx}"] },
});
