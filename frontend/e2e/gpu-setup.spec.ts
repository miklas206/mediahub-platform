import { expect, test } from "@playwright/test";

test.use({ channel: "chromium" });

for (const width of [1440, 390]) {
  test(`GPU guide resumes, tests and selects Jellyfin GPU (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    let ready = false;
    let tested = false;
    const gpu = { id: "GPU-abcd1234-1234", name: "RTX 3070 Ti", vendor: "nvidia", method: "NVIDIA NVENC", available: true };
    await page.route("**/api/**", async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace(/^\/api(?:\/v1)?/, "");
      let data: unknown = [];
      if (path === "/auth/status") data = { needsSetup: false };
      else if (path === "/auth/me") data = { id: "test", username: "tester", role: "administrator", csrf: "test", language: "en" };
      else if (path === "/setup/status") data = { setup_required: false };
      else if (path === "/settings") data = { display_name: "MediaHub", theme: "dark", advanced_mode: false, visible_navigation: ["/", "/overview", "/settings"], dashboard_sections: [] };
      else if (path === "/updates/summary") data = { count: 0, items: [], notifications: [] };
      else if (path === "/hosts") data = [{ id: "local", name: "Local host" }];
      else if (path === "/fjordhub/deployment") data = null;
      else if (path === "/gpu-setup") data = { gpus: ready ? [gpu] : [], preparationRequired: !ready, test: tested ? { state: "succeeded", verified: true, gpuId: gpu.id, progress: 100, details: ["Hardware encoder passed"], testedAt: new Date().toISOString() } : { state: "idle", verified: false, details: [] } };
      else if (path === "/gpu-setup/test") {
        expect(request.postDataJSON()).toEqual({ hostId: "local", gpuId: gpu.id });
        tested = true;
        data = { state: "running" };
      }
      else if (path === "/container-apps/jellyfin/install-options") data = { hostId: "local", port: 8096, slots: [{ id: "appdata", required: true, readOnly: false }], storage: [{ id: "config", label: "App disk", kind: "appdata" }], gpus: [gpu] };
      else if (path === "/container-apps/jellyfin/status") data = { state: "not_installed" };
      else if (path === "/events/stream") {
        await route.fulfill({ contentType: "text/event-stream", body: "retry: 60000\n\n" });
        return;
      }
      await route.fulfill({ json: { data, error: null } });
    });
    await page.goto("/settings?section=General&gpuSetup=1");
    await expect(page.getByRole("heading", { name: "GPU setup", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await page.getByLabel("MediaHub LXC ID").fill("107");
    await expect(page.getByLabel("Proxmox GPU preparation command")).toContainText("--ctid 107");
    await expect(page.getByLabel("Proxmox GPU preparation command")).toContainText("v0.5.35");
    await page.getByRole("checkbox", { name: "Repair GPU access after an earlier setup" }).check();
    await expect(page.getByLabel("Proxmox GPU preparation command")).toContainText("--repair-video-access");
    await page.getByRole("checkbox", { name: "Repair GPU access after an earlier setup" }).uncheck();
    await page.getByLabel("MediaHub LXC ID").fill("107; reboot");
    await expect(page.getByLabel("Proxmox GPU preparation command")).toHaveCount(0);
    await page.getByLabel("MediaHub LXC ID").fill("107");
    await page.reload();
    await expect(page.getByLabel("MediaHub LXC ID")).toHaveValue("107");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`gpu-preparation-${width}.png`), fullPage: true });
    ready = true;
    await page.getByRole("button", { name: "Refresh GPU detection" }).click();
    await page.getByRole("radio", { name: /RTX 3070 Ti/ }).check();
    await page.getByRole("button", { name: "Continue to GPU test" }).click();
    await expect(page.getByRole("button", { name: "Continue to Jellyfin" })).toBeDisabled();
    await page.getByRole("button", { name: "Run GPU test", exact: true }).click();
    await expect(page.getByRole("button", { name: "Continue to Jellyfin" })).toBeEnabled();
    await page.getByRole("button", { name: "Continue to Jellyfin" }).click();
    await expect(page.getByRole("heading", { name: "GPU verified and ready for Jellyfin" })).toBeVisible();
    await page.getByRole("link", { name: "Open Jellyfin setup" }).click();
    await expect(page.getByLabel("GPU transcoding", { exact: false })).toHaveValue(gpu.id);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    expect(errors).toEqual([]);
  });
}
