import { expect, test } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { textOutsideCards } from "./text-containment";
for (const app of ["mediaseed", "mediavpn"])
  for (const width of [1440, 768, 390, 320])
    for (const language of ["da", "en"])
      test(`app text audit ${app} ${width} ${language}`, async ({ page }) => {
        await page.emulateMedia({ reducedMotion: "reduce" });
        await page.setViewportSize({ width, height: 1000 });
        const workspace =
          process.env.MEDIAHUB_QA_APP_SOURCES ||
          resolve(import.meta.dirname, "../../../..");
        const projectName = app === "mediaseed" ? "MediaSeed" : "MediaVPN";
        const root = [projectName, app]
          .map((name) => resolve(workspace, name, app, "static"))
          .find((path) => existsSync(resolve(path, "index.html")));
        if (!root)
          throw new Error("Missing standalone app checkout for " + projectName);
        const errors: string[] = [];
        page.on("pageerror", (e) => errors.push(e.message));
        await page.route("https://audit.example/**", async (route) => {
          const path = new URL(route.request().url()).pathname;
          if (path === "/healthz") {
            return route.fulfill({
              json: { status: "healthy", version: "0.2.37" },
            });
          }
          if (path.startsWith("/api/")) {
            let data: unknown = [];
            if (path === "/api/auth/status")
              data = { needsSetup: false, managed: true };
            else if (path === "/api/auth/me")
              data = {
                id: "audit",
                role: "administrator",
                csrf: "test",
                language,
                username: "Tester",
                managed: true,
              };
            else if (path === "/api/runtime")
              data = { enabled: true, mediaSeedConnected: true };
            else if (path === "/api/dashboard")
              data = {
                runtime: { downloadsEnabled: false },
                torrents: [],
                queue: null,
              };
            else if (path === "/api/profiles")
              data = [
                {
                  id: "a".repeat(24),
                  name: "VPN-" + "LongProfileName".repeat(5),
                  state: "connected",
                  healthy: true,
                  country: "Sweden",
                  publicIp: "198.51.100.8",
                  endpoint: "192.0.2.1",
                  port: 51820,
                  forwardedPort: 45000,
                },
              ];
            else if (path === "/api/hub-apps")
              data = {
                apps: [{ id: "mediaseed", name: "MediaSeed", enabled: false }],
                gateway: { enabled: false, ready: false, profiles: [] },
              };
            else if (path === "/api/hub-web-gateway")
              data = {
                configured: false,
                enabled: false,
                apps: [],
                zones: [],
                routes: [],
                gateway: { ready: false },
                plexPort: { available: false },
              };
            else if (path === "/api/storage")
              data = {
                freeBytes: 1000000,
                totalBytes: 2000000,
                defaultLocation: "downloads",
                locations: [
                  {
                    id: "downloads",
                    label: "Downloads",
                    available: true,
                    writable: true,
                    freeBytes: 1000000,
                    totalBytes: 2000000,
                  },
                ],
              };
            else if (path === "/api/storage/folders")
              data = { writable: true, folders: [], truncated: false };
            else if (path === "/api/vpn")
              data = {
                enabled: false,
                profiles: [],
                providers: [],
                available: false,
              };
            return route.fulfill({ json: data });
          }
          const file =
            path === "/" ? "index.html" : path.replace(/^\/static\//, "");
          const mime: Record<string, string> = {
            js: "application/javascript",
            css: "text/css",
            svg: "image/svg+xml",
            html: "text/html",
            webp: "image/webp",
          };
          return route.fulfill({
            body: readFileSync(resolve(root, file)),
            contentType:
              mime[file.split(".").at(-1)!] || "application/octet-stream",
          });
        });
        await page.goto("https://audit.example/");
        await expect(page.locator("#workspace")).toBeVisible();
        const tabs =
          app === "mediaseed"
            ? [
                '[data-view="downloads"]',
                '[data-view="feeds"]',
                '[data-view="trackers"]',
                '[data-view="vpn"]',
              ]
            : ["#tab-connection", "#tab-cloudflare"];
        for (const tab of tabs) {
          await page.locator(tab).click();
          await page.waitForLoadState("networkidle");
          expect(await textOutsideCards(page), tab).toEqual([]);
          expect(
            await page.evaluate(
              () => document.documentElement.scrollWidth <= innerWidth + 1,
            ),
            tab,
          ).toBe(true);
        }
        await page.locator(".app-settings-button").click();
        await expect(page.locator("#app-settings")).toBeVisible();
        expect(await textOutsideCards(page)).toEqual([]);
        await page.screenshot({
          path: test.info().outputPath("settings.png"),
          fullPage: true,
        });
        await page.keyboard.press("Escape");
        if (app === "mediaseed") {
          await page.locator('[data-view="downloads"]').click();
          await page.locator("#new-torrent").click();
          await expect(page.locator("#add-torrent")).toBeVisible();
          expect(await textOutsideCards(page)).toEqual([]);
          expect(
            await page
              .locator("#add-torrent")
              .evaluate((e) => e.scrollWidth <= e.clientWidth + 1),
          ).toBe(true);
          await page.screenshot({
            path: test.info().outputPath("add-torrent-dialog.png"),
            fullPage: true,
          });
        }
        if (app === "mediavpn") {
          await page.locator("#tab-connection").click();
          await page.locator("#add").click();
          await expect(page.locator("#profile-dialog")).toBeVisible();
          expect(await textOutsideCards(page)).toEqual([]);
          await page.screenshot({
            path: test.info().outputPath("profile-dialog.png"),
            fullPage: true,
          });
          const form = page.locator("#profile-form");
          await form.locator('[name="name"]').fill("QA");
          await page.locator("#configuration").setInputFiles({
            name: "qa.conf",
            mimeType: "text/plain",
            buffer: Buffer.from("[Interface]"),
          });
          await form
            .getByRole("button", {
              name: language === "da" ? "Næste" : "Next",
              exact: true,
            })
            .click();
          await expect(
            form.getByRole("checkbox", { name: "MediaSeed" }),
          ).toBeVisible();
          expect(await textOutsideCards(page), "VPN app selection").toEqual([]);
          expect(
            await page.evaluate(
              () => document.documentElement.scrollWidth <= innerWidth + 1,
            ),
          ).toBe(true);
        }
        expect(errors).toEqual([]);
      });
