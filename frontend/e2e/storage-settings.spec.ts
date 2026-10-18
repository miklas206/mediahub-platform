import { expect, test } from "@playwright/test";

for (const width of [1440, 390, 320]) {
  test(`Storage NAS and Windows guide at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    const writes: { path: string; body: Record<string, unknown> }[] = [];
    const inventory = {
      available: true,
      server: "192.168.1.15",
      passwordConfigured: false,
      smbRunning: false,
      locations: [
        {
          id: "media-root-test",
          label: "Main folder (all subfolders)",
          source: "/mnt/media",
          kind: "local",
          ready: true,
          totalBytes: 1e12,
          freeBytes: 5e11,
        },
        {
          id: "movies",
          label: "Movies",
          source: "/mnt/media/movies",
          kind: "local",
          ready: true,
          totalBytes: 1e12,
          freeBytes: 5e11,
        },
      ],
      nas: [] as object[],
      shares: [] as object[],
    };
    page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() => {
      window.EventSource = class extends EventTarget {
        close() {}
      } as unknown as typeof EventSource;
    });
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
          language: "en",
        };
      else if (path === "/setup/status") data = { setup_required: false };
      else if (path === "/settings")
        data = {
          display_name: "MediaHub",
          theme: "dark",
          advanced_mode: false,
          visible_navigation: ["/", "/settings"],
          dashboard_sections: [],
        };
      else if (path === "/updates/summary")
        data = { count: 0, items: [], notifications: [] };
      else if (path === "/fjordhub/deployment") data = null;
      else if (path === "/storage-control") data = inventory;
      else if (path === "/storage-control/nas") {
        const body = route.request().postDataJSON();
        writes.push({ path, body });
        inventory.nas.push({
          id: "a".repeat(24),
          ...body,
          password: undefined,
          ready: true,
          enabled: true,
        });
        data = { saved: true };
      } else if (path === "/storage-control/shares") {
        const body = route.request().postDataJSON();
        writes.push({ path, body });
        inventory.shares.push({
          name: body.name,
          storageId: body.storageId,
          readOnly: body.readOnly,
          unc: "\\\\192.168.1.15\\" + body.name,
          username: "mediahub",
        });
        inventory.passwordConfigured = true;
        inventory.smbRunning = true;
        data = { saved: true };
      }
      await route.fulfill({ json: { data } });
    });
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/settings?section=Storage");
    await expect(
      page.getByRole("tab", { name: "Storage", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    const nas = page.locator("section").filter({
      has: page.getByRole("heading", { name: "Connect a NAS", exact: true }),
    });
    await nas.getByLabel("Name", { exact: true }).fill("My NAS");
    await nas.getByLabel("NAS LAN address").fill("192.168.1.60");
    await nas.getByLabel("Share name", { exact: true }).fill("Media");
    await nas.getByLabel("NAS username").fill("nas-user");
    await nas.getByLabel("NAS password").fill("synthetic-nas-password");
    await nas.getByRole("button", { name: "Connect NAS", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Saved NAS connections" }),
    ).toBeVisible();
    await expect(nas.getByLabel("NAS password")).toHaveValue("");
    const windows = page.locator("section").filter({
      has: page.getByRole("heading", {
        name: "Share with Windows",
        exact: true,
      }),
    });
    await windows.getByLabel("Storage folder").selectOption("media-root-test");
    await windows
      .getByLabel("Windows sharing password", { exact: true })
      .fill("synthetic-smb-password");
    await windows.getByRole("button", { name: "Create Windows share" }).click();
    await expect(
      page.getByRole("heading", { name: "Windows network drives" }),
    ).toBeVisible();
    await page
      .getByText("Connect this folder in Windows", { exact: true })
      .click();
    await expect(page.locator(".storage-unc")).toContainText(
      "\\\\192.168.1.15\\MediaHub",
    );
    await expect(page.locator(".storage-guide")).toContainText(
      "Map network drive",
    );
    expect(writes).toHaveLength(2);
    expect(writes[0].body.readOnly).toBe(true);
    expect(writes[1].body.readOnly).toBe(true);
    expect(writes[1].body.storageId).toBe("media-root-test");
    for (const panel of await page.locator(".storage-settings .panel").all()) {
      expect(
        await panel.evaluate((element) =>
          parseFloat(getComputedStyle(element).paddingLeft),
        ),
      ).toBeGreaterThanOrEqual(16);
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `test-results/storage-${width}.png`,
      fullPage: true,
    });
    expect(errors).toEqual([]);
  });
}
