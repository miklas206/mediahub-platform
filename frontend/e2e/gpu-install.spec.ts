import { expect, test } from "@playwright/test";

// Use an isolated Playwright browser, never the operator's installed Chrome.
test.use({channel: "chromium"});

for (const width of [1440, 390]) {
  test(`Jellyfin GPU choice is reviewed and survives installation (${width}px)`, async ({page}) => {
    await page.setViewportSize({width, height: 1000});
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    let installation: Record<string, unknown> = {};
    let accepted = false;
    await page.route("**/api/**", async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace(/^\/api(?:\/v1)?/, "");
      let data: unknown = [];
      if (path === "/auth/status") data = {needsSetup: false};
      else if (path === "/auth/me") data = {id: "test", username: "tester", role: "administrator", csrf: "test", language: "en"};
      else if (path === "/setup/status") data = {setup_required: false};
      else if (path === "/settings") data = {display_name: "MediaHub", theme: "dark", advanced_mode: false, visible_navigation: ["/", "/overview", "/settings"], dashboard_sections: []};
      else if (path === "/updates/summary") data = {count: 0, items: [], notifications: []};
      else if (path === "/hosts") data = [{id: "local", name: "Local host"}];
      else if (path === "/apps") data = accepted ? [{id: "jellyfin", packageId: "org.mediahub.jellyfin", name: "Jellyfin", state: "running", isMock: false}] : [];
      else if (path === "/fjordhub/deployment") data = null;
      else if (path === "/container-apps/jellyfin/install-options") data = {
        hostId: "local", port: 8096,
        slots: [{id: "appdata", required: true, readOnly: false}],
        storage: [{id: "config", label: "App disk", kind: "appdata"}],
        gpus: [
          {id: "GPU-abcd1234-1234", name: "RTX 3070 Ti", vendor: "nvidia", method: "NVIDIA NVENC", available: true},
          {id: "intel-offline", name: "Offline GPU", vendor: "intel", method: "Intel QSV", available: false},
        ],
      };
      else if (path === "/container-apps/install-plan") {
        installation = request.postDataJSON();
        data = {planDigest: "a".repeat(64), installation, url: "http://192.168.1.110:8096", mounts: [{target: "/config", readOnly: false}]};
      }
      else if (path === "/container-apps/install") {
        expect(request.postDataJSON().installation).toEqual(installation);
        accepted = true;
        data = {state: "accepted"};
      }
      else if (path === "/container-apps/jellyfin/status") data = {state: "running", installation};
      else if (path === "/events/stream") {
        await route.fulfill({contentType: "text/event-stream", body: "retry: 60000\n\n"});
        return;
      }
      await route.fulfill({json: {data, error: null}});
    });
    await page.goto("/apps/install/jellyfin");
    const gpu = page.getByLabel("GPU transcoding", {exact: false});
    await expect(gpu).toHaveValue("");
    await expect(gpu.locator('option[value="intel-offline"]')).toHaveJSProperty("disabled", true);
    await page.getByLabel("App data storage", {exact: false}).selectOption("config");
    await page.getByRole("button", {name: "Review installation", exact: true}).click();
    await expect(page.getByRole("heading", {name: "Installation preview"})).toBeVisible();
    expect(installation).not.toHaveProperty("gpuId");
    await gpu.selectOption("GPU-abcd1234-1234");
    await expect(page.getByRole("heading", {name: "Installation preview"})).toHaveCount(0);
    await page.getByRole("button", {name: "Review installation", exact: true}).click();
    await expect(page.locator("dd").filter({hasText: "RTX 3070 Ti"})).toBeVisible();
    expect(installation.gpuId).toBe("GPU-abcd1234-1234");
    await page.screenshot({path: test.info().outputPath(`gpu-preview-${width}.png`), fullPage: true});
    await page.getByRole("button", {name: "Install Jellyfin", exact: true}).click();
    await expect(page.getByText(/GPU access is configured/)).toBeVisible();
    await page.reload();
    await expect(page.getByText(/GPU access is configured/)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    expect(errors).toEqual([]);
  });
}
