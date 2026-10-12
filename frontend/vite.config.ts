import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 输出文件名固定为 workbench 服务路由表中的 /app.js 与 /style.css,
// 构建产物直接进入随 Python 包分发的 web_assets,服务端不需要任何改动。
export default defineConfig({
  base: "/",
  plugins: [react()],
  build: {
    outDir: "../src/llm4om/web_assets",
    emptyOutDir: true,
    target: "es2022",
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        chunkFileNames: "[name].js",
        assetFileNames: "style.css",
      },
    },
  },
});
