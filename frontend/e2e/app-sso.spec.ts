import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`App roles can be assigned (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    let saved: unknown;
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname.replace(/^\/api(?:\/v1)?/, "");
      let data: unknown = [];
      if (path === "/auth/status") data = { needsSetup: false };
      else if (path === "/setup/status") data = { setup_required: false };
      else if (path === "/auth/me") data = { id: "admin", username: "administrator", role: "administrator", csrf: "synthetic", language: "da" };
      else if (path === "/settings") data = { display_name: "MediaHub", visible_navigation: ["/", "/settings"], dashboard_sections: [], theme: "dark" };
      else if (path === "/users") {
        if (route.request().method() === "POST") saved = route.request().postDataJSON();
        data = [{ id: "admin", username: "administrator", role: "administrator", appRoles: {}, createdAt: "2026-10-12T00:00:00Z" }];
      } else if (path === "/apps") data = [{ id: "seed", packageId: "org.mediahub.mediaseed", name: "MediaSeed", ssoSupported: true, isMock: false, state: "running", health: { status: "healthy", summary: "Synthetic", checks: [] } }];
      else if (path === "/system/status") data = { hostname: "synthetic", cpu: { percent: 0, cores: 1 }, ram: { totalBytes: 1, usedBytes: 0 }, disks: [], network: [], environment: "test", uptimeSeconds: 0 };
      else if (path === "/updates/summary") data = { count: 0, items: [], notifications: [] };
      else if (path === "/fjordhub/deployment") data = null;
      await route.fulfill({ json: { data, error: null, metadata: {} } });
    });
    await page.goto("/settings?section=Users");
    await page.getByRole("button", { name: "Tilf\u00f8j bruger" }).click();
    await page.getByLabel("Brugernavn", { exact: true }).fill("member");
    await page.getByLabel("Adgangskode", { exact: true }).fill("synthetic-password-only");
    await page.getByRole("combobox", { name: "Hub-rolle", exact: true }).selectOption("user");
    await page.getByLabel("Adgang til MediaSeed").selectOption("viewer");
    await page.getByRole("button", { name: "Gem bruger" }).click();
    await expect.poll(() => saved).toEqual({ username: "member", password: "synthetic-password-only", role: "user", appRoles: { "org.mediahub.mediaseed": "viewer" } });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/app-roles-${width}.png`, fullPage: true });
  });

  test(`Members only see their apps (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname.replace(/^\/api(?:\/v1)?/, "");
      const data = path === "/auth/status" ? { needsSetup: false } : path === "/setup/status" ? { setup_required: false } : path === "/auth/me" ? { id: "member", username: "member", role: "user", csrf: "synthetic" } : [{ id: "seed", name: "MediaSeed", openUrl: "https://seed.example/auth/hub/start" }];
      await route.fulfill({ json: { data, error: null, metadata: {} } });
    });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Mine apps" })).toBeVisible();
    await expect(page.getByRole("link", { name: "\u00c5bn app" })).toHaveAttribute("href", "https://seed.example/auth/hub/start");
    await expect(page.getByRole("button", { name: "Tilf\u00f8j bruger" })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/member-apps-${width}.png`, fullPage: true });
  });
}