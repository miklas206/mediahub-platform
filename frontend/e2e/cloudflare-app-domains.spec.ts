import { expect, test } from "@playwright/test";
for (const language of ["en", "da"])
  for (const width of [1440, 390, 320]) {
    test(`retired Cloudflare link ${width}px ${language}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 950 });
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.route("**/api/**", async (route) => {
        const path = new URL(route.request().url()).pathname.replace(
          /^\/api(?:\/v1)?/,
          "",
        );
        let data: unknown = [];
        if (path === "/auth/status") data = { needsSetup: false };
        else if (path === "/auth/me")
          data = {
            id: "test",
            username: "tester",
            role: "administrator",
            csrf: "test",
            language,
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
        else if (path === "/managed-install/prerequisites")
          data = { state: "ready" };
        else if (path === "/managed-install/org.mediahub.mediavpn")
          data = {
            alreadyRunning: true,
            operation: { state: "idle" },
            planDigest: "a".repeat(64),
          };
        else if (path === "/mediavpn/status")
          data = {
            configured: true,
            available: true,
            url: "https://vpn.example",
            openUrl: "https://vpn.example/auth/hub/start",
          };
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
      await page.goto("/store/cloudflare");
      await expect(page).toHaveURL(/\/store\/mediavpn$/);
      await expect(
        page.getByRole("link", {
          name: language === "da" ? "Åbn gatewayguiden" : "Open gateway guide",
        }),
      ).toHaveAttribute("href", "https://vpn.example/auth/hub/start");
      await expect(
        page.getByRole("heading", { name: "Cloudflare Tunnel", exact: true }),
      ).toHaveCount(0);
      expect(errors).toEqual([]);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
    });
  }
