import { expect, test } from "@playwright/test";

for (const width of [1440, 390, 320]) {
  test(`Managed app removal and VPN dependency (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    let removalRequested = false;
    let packageId = "org.mediahub.mediaseed";
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname.replace(/^\/api(?:\/v1)?/, "");
      let data: unknown = [];
      if (path === "/auth/status") data = { needsSetup: false };
      else if (path === "/setup/status") data = { setup_required: false };
      else if (path === "/auth/me") data = { id: "admin", username: "administrator", role: "administrator", csrf: "synthetic", language: "da" };
      else if (path === "/settings") data = { display_name: "MediaHub", visible_navigation: ["/", "/settings"], dashboard_sections: [], theme: "dark" };
      else if (path === "/updates/summary") data = { count: 0, items: [], notifications: [] };
      else if (path === "/fjordhub/deployment") data = null;
      else if (path === "/catalog") data = [{ id: "org.mediahub.seedbox", availability: "available" }];
      else if (path === "/mediaseed/status") data = { configured: !removalRequested, available: true, url: "https://seed.example" };
      else if (path === "/mediavpn/status") data = { configured: true, available: true, url: "https://vpn.example" };
      else if (path === "/apps") data = removalRequested ? [{ id: "managed-app", name: "MediaVPN", packageId: "org.mediahub.mediavpn", state: "running", isMock: false, removable: true, health: { status: "healthy", summary: "Synthetic", checks: [] } }] : [{ id: "managed-app", name: "MediaSeed", packageId: "org.mediahub.mediaseed", state: "running", isMock: false, removable: true, health: { status: "healthy", summary: "Synthetic", checks: [] } }];
      else if (path.startsWith("/app-settings/")) data = { name: packageId.endsWith("mediaseed") ? "MediaSeed" : "MediaVPN", externalUrl: "", localUrl: "http://127.0.0.1:18802", removableApp: { id: "managed-app", packageId, state: "running", isMock: false } };
      else if (path === "/apps/managed-app/uninstall") {
        if (packageId.endsWith("mediavpn")) {
          await route.fulfill({ status: 409, json: { data: null, error: { code: "app_dependency", message: "Frakobl MediaVPN under VPN i MediaSeed først. Derefter kan MediaVPN afinstalleres uden at fjerne MediaSeed." } } });
          return;
        }
        if (route.request().method() === "POST") {
          expect(route.request().postDataJSON()).toEqual({ confirmedInstallationId: "synthetic-identity" });
          removalRequested = true;
          data = { state: "accepted", installationId: "synthetic-identity" };
        } else data = { state: removalRequested ? "succeeded" : "ready", installationId: "synthetic-identity", dataPreserved: removalRequested, message: "Downloads, appdata, credentials og VPN-profiler bevares." };
      }
      await route.fulfill({ json: { data, error: null, metadata: {} } });
    });
    await page.goto("/");
    await page.getByRole("button", { name: /^Afinstaller:/ }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(removalRequested).toBe(false);
    await page.getByRole("button", { name: "Bekræft fjernelse", exact: true }).click();
    await expect.poll(() => removalRequested).toBe(true);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    packageId = "org.mediahub.mediavpn";
    await page.goto("/");
    await page.getByRole("button", { name: /^Afinstaller:/ }).click();
    await expect(page.getByText("Frakobl MediaVPN under VPN i MediaSeed først. Derefter kan MediaVPN afinstalleres uden at fjerne MediaSeed.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Bekræft fjernelse", exact: true })).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}
