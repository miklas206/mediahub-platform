import { build } from "vite";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";

await build({
  configFile: false,
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  plugins: [react()],
  build: {
    outDir: process.argv[2],
    lib: {
      entry: resolve("e2e/compatibility.tsx"),
      name: "QAComponents",
      formats: ["iife"],
      fileName: () => "components.js",
    },
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
});
