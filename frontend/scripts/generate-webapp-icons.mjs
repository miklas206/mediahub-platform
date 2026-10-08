import { chromium } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const publicDir = new URL("../public/", import.meta.url);
const logo = await readFile(new URL("favicon.svg", publicDir), "utf8");
const browser = await chromium.launch({ channel: "chrome" });
try {
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  for (const [name, size] of [
    ["apple-touch-icon.png", 180],
    ["icon-192.png", 192],
    ["icon-512.png", 512],
  ]) {
    await page.setViewportSize({ width: size, height: size });
    // Keep the full mark inside the circular safe zone of maskable icons.
    await page.setContent(`<style>
      body { margin: 0; width: 100vw; height: 100vh; background: #101719;
        display: flex; align-items: center; justify-content: center; }
      svg { width: 64%; height: 64%; }
    </style>${logo}`);
    await page.screenshot({ path: fileURLToPath(new URL(name, publicDir)) });
  }
} finally {
  await browser.close();
}
