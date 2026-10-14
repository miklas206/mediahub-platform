import { expect, test } from "@playwright/test";

for (const width of [1440, 390, 320]) {
  test(`select shared VPN app at ${width}px`, async ({ page }) => {
    test.skip(!process.env.MEDIAVPN_QA_URL, "Requires an isolated MediaVPN static server");
    await page.setViewportSize({width, height: 950});
    const errors: string[] = [];
    const writes: unknown[] = [];
    page.on("pageerror", error => errors.push(error.message));
    const shared = {gateway: {enabled: true, ready: true, profileId: "a".repeat(24), profiles: [{id: "a".repeat(24), name: "Synthetic Proton"}]},
      apps: [{id: "jellyfin", name: "Jellyfin", enabled: false, ready: false, phase: "idle"}]};
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      let data: unknown = {};
      if (path === "/api/auth/status") data = {managed: true, needsSetup: false};
      else if (path === "/api/auth/me") data = {id: "admin", role: "administrator", language: "en", csrf: "synthetic"};
      else if (path === "/api/runtime") data = {enabled: true, mediaSeedConnected: false};
      else if (path === "/api/profiles") data = [];
      else if (path === "/api/hub-apps/jellyfin") {
        writes.push(route.request().postDataJSON());
        shared.apps[0].enabled = true; data = shared;
      } else if (path === "/api/hub-apps") data = shared;
      await route.fulfill({contentType: "application/json", body: JSON.stringify(data)});
    });
    await page.goto(process.env.MEDIAVPN_QA_URL! + "/static/index.html");
    const panel = page.locator("#shared-apps");
    await expect(panel.getByRole("heading", {name: "Shared VPN gateway"})).toBeVisible();
    await expect(panel.getByRole("checkbox")).toHaveCount(1);
    await expect(page.locator(".app-connections:not(#shared-apps)")).toBeHidden();
    await panel.getByRole("checkbox").check();
    await expect.poll(() => writes.length).toBe(1);
    expect(writes[0]).toEqual({enabled: true});
    await expect(panel.getByRole("checkbox")).toBeChecked();
    expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path: `test-results/vpn-apps-${width}.png`, fullPage: true});
  });
}
