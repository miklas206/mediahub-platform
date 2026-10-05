import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`FjordHub scoped home and local launch settings (${width}px)`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    const writes: unknown[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let override: string | null = null;
    let viewer = false;
    let updateRunning = false;
    let updateFinished = false;
    let starts = 0;
    const info = {
      id: "fjordflix",
      name: "FjordFlix",
      port: 9234,
      installed: true,
      icon_path: null,
      permissions: { updates: true, app_data: false },
    };
    const updateView = () => ({
      app_info: {
        fjordflix: info,
        fjordhub: { ...info, id: "fjordhub", name: "FjordHub", port: 8443 },
      },
      app_info_stale: false,
      updates: {
        fjordflix: {
          app_id: "fjordflix",
          ok: true,
          running: updateRunning,
          update_available: !updateFinished,
          accepted: updateRunning,
          current_rev: updateFinished ? "new" : "old",
          remote_rev: "new",
        },
      },
    });
    const row = () => ({
      id: "hub",
      name: "Fixture FjordHub",
      baseUrl: "https://192.168.50.20:8443",
      allowHttp: false,
      enabled: true,
      tokenConfigured: true,
      lastSuccessfulSync: null,
      nextSync: 0,
      appLaunchOverrides: override ? { fjordflix: override } : {},
      snapshot: {
        status: "online",
        app_info: { fjordflix: info },
        app_info_stale: false,
        capabilities: ["docker.resources.read"],
        apps: [
          {
            id: "fjordflix",
            name: "FjordFlix",
            container_count: 1,
            running_count: 1,
            url: "https://192.168.50.20:9234/",
          },
          {
            id: "urban-explorer",
            name: "UrbanExplorer",
            container_count: 1,
            running_count: 1,
          },
        ],
        metrics: { cpuPercent: 25 },
        fjordflix: { ok: true, library_count: 0, items: [], streams: [] },
      },
    });
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname.replace(
        /^\/api(?:\/v1)?/,
        "",
      );
      let data: unknown = [];
      if (path === "/auth/status") data = { needsSetup: false };
      else if (path === "/setup/status") data = { setup_required: false };
      else if (path === "/auth/me")
        data = {
          id: "fixture",
          username: "fixture-admin",
          role: viewer ? "viewer" : "administrator",
          csrf: "fixture",
          language: "en",
        };
      else if (path === "/settings")
        data = {
          display_name: "MediaHub",
          advanced_mode: false,
          visible_navigation: ["/", "/apps", "/integrations"],
          dashboard_sections: ["apps", "integrations"],
          theme: "dark",
        };
      else if (path === "/updates/summary") data = { count: 0 };
      else if (path === "/fjordhub/deployment") data = null;
      else if (path === "/integrations/hub/updates/fjordflix/start") {
        expect(route.request().method()).toBe("POST");
        expect(route.request().headers()["x-mediahub-csrf"]).toBe("fixture");
        starts += 1;
        updateRunning = true;
        await route.fulfill({
          status: 202,
          json: { data: updateView(), error: null },
        });
        return;
      } else if (path.endsWith("/updates") && path.startsWith("/integrations/"))
        data = updateView();
      else if (path === "/integrations")
        data = [
          row(),
          {
            ...row(),
            id: "other",
            name: "Other FjordHub",
            appLaunchOverrides: {},
          },
        ];
      else if (path === "/integrations/hub/apps/fjordflix/launch-url") {
        expect(route.request().method()).toBe("PUT");
        expect(route.request().headers()["x-mediahub-csrf"]).toBe("fixture");
        const body = route.request().postDataJSON();
        writes.push(body);
        if (body.url?.includes("evil.example")) {
          await route.fulfill({
            status: 422,
            json: {
              data: null,
              error: {
                code: "invalid_launch_url",
                message: "Use a credential-free same-host HTTP(S) app URL",
              },
            },
          });
          return;
        }
        override = body.url;
        data = {
          id: "hub",
          appLaunchOverrides: override ? { fjordflix: override } : {},
        };
      } else if (path === "/events/stream") {
        await route.fulfill({
          contentType: "text/event-stream",
          body: `event: system.status\ndata: ${JSON.stringify({ hostname: "fixture", version: "fixture", timestamp: new Date().toISOString(), uptimeSeconds: 123, coreUptimeSeconds: 123, cpu: { percent: 25, cores: 4 }, ram: { percent: 20, totalBytes: 1024, usedBytes: 200 }, disk: { percent: 20, totalBytes: 1024, usedBytes: 200, freeBytes: 824 }, network: { downloadBytesPerSecond: 0, uploadBytesPerSecond: 0 } })}\n\nretry: 60000\n\n`,
        });
        return;
      }
      await route.fulfill({
        json: { data, error: null, metadata: { version: "fixture" } },
      });
    });
    await page.goto("/integrations/hub");
    await expect(
      page
        .getByRole("heading", { name: "Fixture FjordHub", exact: true })
        .first(),
    ).toBeVisible();
    await expect(
      page.locator(".workspace").getByText("Other FjordHub", { exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("link", { name: "Open FjordHub", exact: true }),
    ).toHaveAttribute("href", "https://192.168.50.20:8443");
    await expect(
      page.getByText("Signed in as", { exact: false }),
    ).toContainText("fixture-admin");
    const form = page.getByRole("form", { name: "FjordFlix · App launch URL" });
    const input = form.locator("input");
    await input.fill("https://192.168.50.20:9000/movies");
    await form.getByRole("button", { name: "Save", exact: true }).click();
    await expect(form.getByRole("status")).toHaveText("App launch URL saved");
    await expect(
      page
        .locator(".workspace")
        .getByRole("link", { name: "Open app", exact: true }),
    ).toHaveAttribute("href", "https://192.168.50.20:9000/movies");
    const nav = page.locator(".fjordhub-app-navigation").first();
    await expect(nav.locator(":scope > a")).toHaveAttribute(
      "href",
      "/integrations/hub",
    );
    await expect(nav.locator(":scope > a")).not.toHaveAttribute(
      "target",
      "_blank",
    );
    await expect(
      nav.getByRole("link", { name: "FjordFlix", exact: true }),
    ).toHaveAttribute("href", "https://192.168.50.20:9000/movies");
    await expect(
      nav.getByRole("link", { name: "UrbanExplorer", exact: true }),
    ).toHaveAttribute("title", "Manage in FjordHub (app address unavailable)");
    await input.fill("https://evil.example/?token=do-not-reflect");
    await form.getByRole("button", { name: "Save", exact: true }).click();
    await expect(form.getByRole("alert")).toContainText("same-host");
    await expect(input).toHaveValue("https://192.168.50.20:9000/movies");
    await page.reload();
    await expect(input).toHaveValue("https://192.168.50.20:9000/movies");
    await page.goto("/");
    await expect(
      page
        .locator(".fjordflix-service-tile")
        .first()
        .getByRole("link", { name: "Open FjordFlix" }),
    ).toHaveAttribute("href", "https://192.168.50.20:9000/movies");
    await page.goto("/apps");
    await expect(
      page.getByRole("link", { name: "FjordHub overview" }).first(),
    ).toHaveAttribute("href", "/integrations/hub");
    await page.goto("/integrations/hub");
    await form.getByRole("button", { name: "Use default link" }).click();
    await expect(input).toHaveValue("");
    await expect(
      page
        .locator(".workspace")
        .getByRole("link", { name: "Open app", exact: true }),
    ).toHaveAttribute("href", "https://192.168.50.20:9234/");
    const updates = page.getByRole("region", { name: "FjordHub-opdateringer" });
    const childUpdate = updates
      .locator("article")
      .filter({ has: page.getByText("FjordFlix", { exact: true }) });
    await expect(
      childUpdate.getByRole("button", { name: "Opdatér app" }),
    ).toBeEnabled();
    expect(starts).toBe(0);
    page.once("dialog", (dialog) => dialog.accept());
    await childUpdate.getByRole("button", { name: "Opdatér app" }).click();
    await expect(childUpdate.getByRole("status")).toContainText(
      "Start accepteret (202)",
    );
    await expect(
      childUpdate.getByRole("button", { name: "Opdatér app" }),
    ).toBeDisabled();
    updateRunning = false;
    updateFinished = true;
    await expect(
      childUpdate.getByText("Ingen opdatering tilgængelig", { exact: true }),
    ).toBeVisible({ timeout: 10000 });
    expect(starts).toBe(1);
    await page.screenshot({
      path: `test-results/fjordhub-home-${width}.png`,
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    viewer = true;
    await page.reload();
    await expect(
      page.getByText("Only administrators can change app launch URLs."),
    ).toBeVisible();
    await expect(input).toHaveCount(0);
    await expect(updates.getByRole("button")).toHaveCount(0);
    await page.goto("/integrations/missing");
    await expect(page.getByText("Integration not found")).toBeVisible();
    expect(writes).toHaveLength(3);
    expect(errors).toEqual([]);
  });
}
