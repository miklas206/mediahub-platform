import { expect, test } from "@playwright/test";

for (const width of [390, 1440])
  for (const previousInstallation of [false, true]) {
    test(`opens local apps without domains at ${width}px (${previousInstallation ? "existing" : "fresh"} registration)`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(() => {
        window.EventSource = class extends EventTarget {
          close() {}
        } as unknown as typeof EventSource;
      });
      await page.context().route(
        (url) => url.hostname === "192.168.1.20",
        (route) =>
          route.fulfill({ contentType: "text/html", body: "Synthetic app" }),
      );
      const apps = ["plex", "jellyfin", "mediaseed", "mediavpn"].map(
        (id, index) => ({
          id: `installed-${id}`,
          packageId: `org.mediahub.${id}`,
          name: id,
          version: "1",
          state: "running",
          isMock: false,
          detailPath: `/apps/installed-${id}`,
          localUrl: `http://192.168.1.20:${8090 + index}/`,
          ...(previousInstallation ? { externalUrl: "" } : {}),
          health: {
            status: "healthy",
            summary: "Running",
            checks: [],
            lastChecked: "",
          },
        }),
      );
      await page.route("**/api/**", async (route) => {
        const path = new URL(route.request().url()).pathname.replace(
          /^\/api(?:\/v1)?/,
          "",
        );
        let data: unknown = [];
        if (path === "/auth/status") data = { needsSetup: false };
        else if (path === "/auth/me")
          data = {
            id: "admin",
            username: "admin",
            role: "administrator",
            csrf: "test",
            language: "da",
          };
        else if (path === "/settings")
          data = {
            display_name: "MediaHub",
            theme: "dark",
            visible_navigation: ["/", "/settings"],
            dashboard_sections: [],
          };
        else if (path === "/setup/status") data = { setup_required: false };
        else if (path === "/updates/summary")
          data = { count: 0, items: [], notifications: [] };
        else if (path === "/apps") data = apps;
        else if (path === "/catalog")
          data = ["seedbox", "plex", "jellyfin"].map((id) => ({
            id: `org.mediahub.${id}`,
            name: id,
            availability: "available",
          }));
        else if (path === "/fjordhub/deployment") data = null;
        else if (["/mediaseed/status", "/mediavpn/status"].includes(path))
          data = { configured: false, available: false, url: null };
        else if (path === "/events/stream") {
          await route.fulfill({
            contentType: "text/event-stream",
            body: ": connected\n\n",
          });
          return;
        }
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ data }),
        });
      });
      await page.goto("/");
      for (const app of apps) {
        const id = app.packageId.replace("mediaseed", "seedbox");
        const link = page.locator(`[data-app-id="${id}"] .hub-card-action`);
        await expect(link).toHaveAttribute("target", "_blank");
        const url = new URL((await link.getAttribute("href"))!);
        expect(url.origin).toBe(new URL(app.localUrl).origin);
        expect(url.pathname).toBe(
          id.endsWith("plex") ? "/web/index.html" : "/",
        );
        await expect(link).toContainText("Åbn app");
        const popupPromise = page.waitForEvent("popup");
        await link.click();
        const popup = await popupPromise;
        await expect(popup).toHaveURL(url.href);
        await popup.close();
      }
    });
  }
