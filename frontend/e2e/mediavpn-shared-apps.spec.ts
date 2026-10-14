import { expect, test } from "@playwright/test";
for (const language of ["en", "da"])
  for (const width of [1440, 390, 320]) {
    test(`guided Proton domain ${width}px ${language}`, async ({ page }) => {
      test.skip(
        !process.env.MEDIAVPN_QA_URL,
        "Requires isolated static server",
      );
      const da = language === "da";
      await page.setViewportSize({ width, height: 950 });
      const errors: string[] = [];
      const writes: Array<{ path: string; body: unknown }> = [];
      page.on("pageerror", (e) => errors.push(e.message));
      const profile = {
        id: "a".repeat(24),
        name: "Ægir Øresund Åben",
        port_forwarding: true,
        state: "stopped",
        endpoint: "192.0.2.1",
        port: 51820,
      };
      const gateway = {
        configured: false,
        accountId: "",
        enabled: false,
        profileId: null as string | null,
        routes: [] as Array<Record<string, unknown>>,
        apps: [{ packageId: "org.mediahub.jellyfin", name: "Jellyfin" }],
        zones: [{ id: "b".repeat(32), name: "example.com" }],
        checks: [],
        issues: [],
        gateway: { providerReady: false, prerequisites: [] },
      };
      await page.route("**/api/**", async (route) => {
        const path = new URL(route.request().url()).pathname;
        let data: unknown = {};
        if (path === "/api/auth/status")
          data = { managed: true, needsSetup: false };
        else if (path === "/api/auth/me")
          data = {
            id: "admin",
            role: "administrator",
            language,
            csrf: "synthetic",
          };
        else if (path === "/api/runtime")
          data = { enabled: true, mediaSeedConnected: false };
        else if (path === "/api/profiles") data = [profile];
        else if (path === "/api/hub-apps")
          data = { gateway: { ready: false, profiles: [profile] }, apps: [] };
        else if (path.startsWith("/api/hub-web-gateway")) {
          if (route.request().method() !== "GET") {
            const body = route.request().postDataJSON();
            writes.push({ path, body });
            if (path.endsWith("/credentials")) {
              gateway.configured = true;
              gateway.accountId = body.accountId;
            }
            if (path.endsWith("/config")) {
              gateway.enabled = true;
              gateway.profileId = body.profileId;
              gateway.routes = body.routes.map((row: object) => ({
                ...row,
                id: "c".repeat(32),
                hostname: "tv.example.com",
                status: "pending-port",
                message: "Waiting for gateway verification",
              }));
            }
          }
          data = gateway;
        }
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(data),
        });
      });
      await page.goto(process.env.MEDIAVPN_QA_URL! + "/static/index.html");
      const panel = page.locator("#web-gateway");
      await expect(
        panel.getByRole("heading", {
          name: da ? "Fælles VPN-gateway" : "Shared VPN gateway",
        }),
      ).toBeVisible();
      await panel
        .getByRole("button", { name: da ? "Næste" : "Next", exact: true })
        .click();
      await expect(
        panel.getByLabel(da ? "VPN-profil" : "VPN profile"),
      ).toContainText("Ægir Øresund Åben");
      await panel
        .getByRole("button", { name: da ? "Næste" : "Next", exact: true })
        .click();
      await panel
        .getByLabel(da ? "Cloudflare-konto-ID" : "Cloudflare account ID")
        .fill("d".repeat(32));
      await panel
        .getByLabel(da ? "Cloudflare API-token" : "Cloudflare API token")
        .fill("synthetic-cloudflare-token");
      await panel
        .getByRole("button", {
          name: da ? "Tilslut Cloudflare" : "Connect Cloudflare",
          exact: true,
        })
        .click();
      await expect.poll(() => writes.length).toBe(1);
      await panel
        .getByRole("button", { name: da ? "Næste" : "Next", exact: true })
        .click();
      await panel
        .getByRole("button", {
          name: da ? "Tilføj app-domæne" : "Add app domain",
        })
        .click();
      await expect(
        panel.getByLabel(da ? "Installeret app" : "Installed app"),
      ).toContainText("Jellyfin");
      await panel.getByLabel(da ? "Subdomæne" : "Subdomain").fill("tv");
      await panel
        .getByRole("button", {
          name: da
            ? "Aktivér gateway og app-domæner"
            : "Activate gateway and app domains",
        })
        .click();
      await expect.poll(() => writes.length).toBe(2);
      expect(writes[1]).toEqual({
        path: "/api/hub-web-gateway/config",
        body: {
          enabled: true,
          profileId: profile.id,
          routes: [
            {
              packageId: "org.mediahub.jellyfin",
              zoneId: "b".repeat(32),
              label: "tv",
            },
          ],
        },
      });
      await expect(panel).not.toContainText("synthetic-cloudflare-token");
      expect(errors).toEqual([]);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: `test-results/gateway-guide-${language}-${width}.png`,
        fullPage: true,
      });
    });
  }
