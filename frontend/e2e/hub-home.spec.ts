import { expect, test } from "@playwright/test";

for (const width of [1440, 390, 320]) {
  test(`MediaHub is the primary app hub (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const mutations: string[] = [];
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace(
        /^\/api(?:\/v1)?/,
        "",
      );
      if (request.method() !== "GET") mutations.push(path);
      let data: unknown = [];
      if (path === "/auth/status") data = { needsSetup: false };
      else if (path === "/users") data = [{ id: "test", username: "tester", role: "administrator", createdAt: "2026-10-09T12:00:00Z" }];
      else if (path === "/auth/me")
        data = {
          id: "test",
          username: "tester",
          role: "administrator",
          csrf: "test",
          language: "da",
        };
      else if (path === "/setup/status") data = { setup_required: false };
      else if (path === "/settings")
        data = {
          display_name: "MediaHub",
          advanced_mode: false,
          visible_navigation: ["/", "/maintenance", "/storage", "/activity", "/logs", "/updates", "/backups", "/integrations", "/settings"],
          dashboard_sections: [],
          theme: "dark",
        };
      else if (path === "/updates/summary") data = { count: 2 };
      else if (path === "/health")
        data = { status: "healthy", version: "beta" };
      else if (path === "/maintenance")
        data = { state: "idle", message: "Ready" };
      else if (path === "/runtime")
        data = {
          connected: false,
          version: null,
          docker: { available: false },
        };
      else if (path === "/fjordhub/deployment") data = null;
      else if (path === "/apps")
        data = [
          {
            id: "seedbox-real",
            name: "Seedbox",
            packageId: "org.mediahub.seedbox",
            detailPath: "/apps/seedbox-real",
            version: "1",
            state: "running",
            isMock: false,
            health: { status: "healthy", summary: "VPN connected", checks: [] },
          },
        ];
      else if (path === "/catalog")
        data = [
          "seedbox",
          "plex",
          "jellyfin",
          "cloudflared",
          "fjordhub",
          "windows-share",
        ].map((id) => ({
          id: `org.mediahub.${id}`,
          name: id,
          availability: "available",
        }));
      else if (path === "/integrations")
        data = [
          {
            id: "fjordhub-one",
            name: "FjordHub",
            enabled: true,
            baseUrl: "http://fjordhub.example",
            allowHttp: true,
            tokenConfigured: true,
            snapshot: {
              status: "online",
              apps: [{ id: "fjordflix", name: "FjordFlix", running_count: 1 }],
            },
          },
        ];
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
    await page.goto("/store");
    await expect(page).toHaveURL(/\/$/);
    await expect(
      page.getByRole("heading", { name: "MediaHub beta" }),
    ).toBeVisible();
    const cards = page.locator(".hub-app-card");
    await expect(cards).toHaveCount(6);
    await expect(page.locator(".app-store-page, .store-hero")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Tilf\u00f8j app", exact: true }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "Kan s\u00e6ttes op", exact: true }).click();
    await expect(cards).toHaveCount(3);
    await expect(page).toHaveURL(/\/$/);
    await page.getByRole("button", { name: "Alle apps", exact: true }).click();
    await expect(
      page.locator(
        ".sidebar nav a[href='/apps'], .sidebar nav a[href='/store'], .mobile-dock a[href='/apps'], .mobile-dock a[href='/store']",
      ),
    ).toHaveCount(0);
    await expect(
      page.locator("#hub-group-true + .hub-app-grid .hub-app-card"),
    ).toHaveCount(3);
    await expect(
      page.locator("#hub-group-false + .hub-app-grid .hub-app-card"),
    ).toHaveCount(3);
    await expect(
      page.getByRole("region", { name: "Administrer MediaHub" }),
    ).toHaveCount(0);
    await expect(
      page.locator('[data-app-id="org.mediahub.seedbox"] a'),
    ).toHaveAttribute("href", "/apps/seedbox-real");
    await expect(
      page.locator('[data-app-id="org.mediahub.jellyfin"] a'),
    ).toHaveAttribute("href", "/apps/install/jellyfin");
    await expect(
      page.locator('[data-app-id="org.mediahub.fjordhub"] a'),
    ).toHaveAttribute("href", "/integrations/fjordhub-one");
    await expect(page.locator('[data-app-id="healthcheck"] a')).toHaveAttribute(
      "href",
      "/maintenance",
    );
    await expect(page.getByText("FjordFlix", { exact: true })).toHaveCount(0);
    await expect(
      page.locator('[data-app-id="org.mediahub.plex"]'),
    ).toContainText("Ikke opsat");
    await page
      .getByRole("searchbox", { name: "Find en app" })
      .fill("cloudflare");
    await expect(cards).toHaveCount(1);
    await expect(cards.first()).toContainText("Cloudflare");
    await page
      .getByRole("searchbox", { name: "Find en app" })
      .fill("matches nothing");
    await expect(
      page.getByRole("heading", { name: "Ingen apps matcher" }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Vis alle apps", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Kan sættes op", exact: true })
      .click();
    await expect(cards).toHaveCount(3);
    await page
      .getByRole("button", { name: "Klar til at åbne", exact: true })
      .click();
    await expect(cards).toHaveCount(3);
    await page.getByRole("button", { name: "Alle apps", exact: true }).click();
    await expect(cards).toHaveCount(6);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `test-results/hub-home-${width}.png`,
      fullPage: true,
    });
    await page.locator('[data-app-id="healthcheck"] a').click();
    await expect(
      page.getByRole("heading", { name: "Healthcheck", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Opdater sundhedstjek" }).click();
    await expect(
      page.getByRole("button", { name: "Kontrollér og ryd op" }),
    ).toBeVisible();
    expect(mutations).toEqual([]);
    await expect(page.locator(".sidebar nav a")).toHaveCount(2);
    await page.getByRole("tab", { name: "Brugere", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Brugere", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Tilf\u00f8j bruger", exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "tester (dig)", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Slet tester", exact: true })).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/settings-users-${width}.png`, fullPage: true });
    expect(errors).toEqual([]);
  });
}
