import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  use: {
    baseURL: process.env.MEDIAHUB_QA_URL || "http://127.0.0.1:18766",
    trace: "off",
    channel: "chrome",
  },
});
