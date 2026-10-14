import { expect, test } from "@playwright/test";

for (const width of [1440, 390, 320]) {
  test(`configure installed app domain at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 });
    const errors: string[] = [];
    const writes: unknown[] = [];
    page.on("pageerror", error => errors.push(error.message));
    const management = {configured: true, accountId: "a".repeat(32),
      apps: [{packageId: "org.mediahub.jellyfin", name: "Jellyfin"}],
      tunnels: [{id: "tunnel", name: "Home"}], routes: [], vpnRecords: [],
      connectors: {tunnel: {state: "stopped"}}, vpn: {profiles: [], message: null},
      discovery: {zones: [{id: "zone", name: "example.com"}], records: [], tunnels: [], issues: [], complete: true}};
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname.replace(/^\/api(?:\/v1)?/, "");
      let data: unknown = [];
      if (path === "/auth/status") data = {needsSetup: false};
      else if (path === "/auth/me") data = {id: "test", username: "tester", role: "administrator", csrf: "test", language: "en"};
      else if (path === "/settings") data = {display_name: "MediaHub", theme: "dark", visible_navigation: ["/", "/settings"], dashboard_sections: []};
      else if (path === "/setup/status") data = {setup_required: false};
      else if (path === "/updates/summary") data = {count: 0, items: [], notifications: []};
      else if (path === "/catalog") data = [{id: "org.mediahub.cloudflared", name: "Cloudflare Tunnel", availability: "available"}];
      else if (path.startsWith("/cloudflare/manage")) {
        if (route.request().method() === "POST") writes.push(route.request().postDataJSON());
        data = management;
      } else if (path === "/events/stream") {
        await route.fulfill({contentType: "text/event-stream", body: ": connected\n\n"}); return;
      }
      await route.fulfill({contentType: "application/json", body: JSON.stringify({data})});
    });
    await page.goto("/store/cloudflare");
    await expect(page.getByRole("heading", {name: "App domains", exact: true})).toBeVisible();
    await expect(page.getByLabel("Installed app")).toHaveText("Jellyfin");
    const form = page.locator("form").filter({has: page.getByLabel("Installed app")});
    await form.getByLabel("Record name", {exact: true}).fill("tv");
    await form.getByRole("button", {name: "Connect app domain"}).click();
    await expect.poll(() => writes.length).toBe(1);
    expect(writes[0]).toEqual({tunnelId: "tunnel", zoneId: "zone", hostname: "tv.example.com", packageId: "org.mediahub.jellyfin"});
    expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path: `test-results/cloudflare-domains-${width}.png`, fullPage: true});
  });
}
