import { expect, test } from "@playwright/test";

for (const width of [1440, 390, 320]) {
  test(`Separate MediaSeed opens from hub (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname.replace(/^\/api(?:\/v1)?/, "");
      let data: unknown = [];
      if (path === "/auth/status") data = { needsSetup: false };
      else if (path === "/auth/me") data = { id: "test", username: "tester", role: "administrator", csrf: "test", language: "da" };
      else if (path === "/settings") data = { display_name: "MediaHub", theme: "dark", advanced_mode: false, visible_navigation: ["/", "/overview", "/settings"], dashboard_sections: [] };
      else if (path === "/setup/status") data = { setup_required: false };
      else if (path === "/updates/summary") data = { count: 0, items: [], notifications: [] };
      else if (path === "/catalog") data = [{ id: "org.mediahub.seedbox", name: "Seedbox", availability: "available" }];
      else if (path === "/fjordhub/deployment") data = null;
      else if (path === "/mediaseed/status") data = { configured: true, available: true, url: "http://192.168.1.111:18800", preview: true };
      else if (path === "/mediavpn/status") data = { configured: true, available: true, url: "http://192.168.1.111:18802", preview: true };
      else if (path === "/events/stream") {
        await route.fulfill({ contentType: "text/event-stream", body: ": connected\n\n" });
        return;
      }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ data }) });
    });
    await page.goto("/");
    const card = page.locator('[data-app-id="org.mediahub.seedbox"]');
    await expect(card).toContainText("MediaSeed");
    await expect(card).toContainText("App tilgængelig");
    const link = card.getByRole("link", { name: "Åbn app · MediaSeed" });
    await expect(link).toHaveAttribute("href", "http://192.168.1.111:18800/");
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await expect(card.locator('image[href="/assets/services/mediaseed.svg"]')).toHaveCount(1);
    const settings = card.getByRole("link", { name: "Indstillinger: MediaSeed" });
    await expect(settings).toHaveAttribute("href", "/app-settings/org.mediahub.mediaseed");
    await expect(card.locator(".hub-card-top a")).toHaveCount(0);
    const settingsBounds = await settings.boundingBox();
    const iconBounds = await card.locator(".hub-app-icon").boundingBox();
    expect(settingsBounds!.y).toBeGreaterThan(iconBounds!.y + iconBounds!.height);
    expect(settingsBounds!.x).toBeGreaterThan(iconBounds!.x);
    const vpn = page.locator('[data-app-id="org.mediahub.mediavpn"]');
    await expect(vpn).toContainText("MediaVPN");
    await expect(vpn.getByRole("link", { name: "Åbn app · MediaVPN" })).toHaveAttribute("href", "http://192.168.1.111:18802/");
    await expect(vpn.locator('image[href="/assets/services/mediavpn.svg"]')).toHaveCount(1);
    expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/mediaseed-hub-${width}.png`, fullPage: true });
  });
}

for (const width of [1440, 390, 320]) {
  for (const installed of [true, false, "sso"]) {
    test(`Simple overview (${width}px, Seedbox ${installed})`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      const errors: string[] = [];
      const requests: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      const metrics = {
        hostname: "beta", version: "0.4.29", timestamp: "2026-10-11T12:00:00Z",
        coreUptimeSeconds: 3600, uptimeSeconds: 3600, environment: "beta",
        cpu: { percent: 12, cores: 6, scope: "core" },
        ram: { percent: 25, usedBytes: 1024 ** 3, totalBytes: 4 * 1024 ** 3, availableBytes: 3 * 1024 ** 3, cacheBytes: null, scope: "core" },
        disk: { percent: 25, usedBytes: 1024 ** 3, totalBytes: 4 * 1024 ** 3, freeBytes: 3 * 1024 ** 3, scope: "core" },
        network: { downloadBytesPerSecond: 2048, uploadBytesPerSecond: 1024 },
      };
      await page.route("**/api/**", async (route) => {
        const path = new URL(route.request().url()).pathname.replace(/^\/api(?:\/v1)?/, "");
        requests.push(path);
        let data: unknown = [];
        if (path === "/auth/status") data = { needsSetup: false };
        else if (path === "/auth/me") data = { id: "test", username: "tester", role: "administrator", csrf: "test", language: "da" };
        else if (path === "/settings") data = {
          display_name: "MediaHub", theme: "dark", advanced_mode: true,
          visible_navigation: ["/", "/settings"],
          dashboard_sections: ["apps", "system", "storage", "network", "activity", "core", "runtime", "integrations", "cloudflare", "torrents", "uploads"],
        };
        else if (path === "/setup/status") data = { setup_required: false };
        else if (path === "/apps") data = installed === "sso" ? [{ id: "org.mediahub.mediaseed", name: "MediaSeed", packageId: "org.mediahub.mediaseed", version: "connected", state: "registered", isMock: false, openUrl: "https://seed.example/auth/hub/start", health: { status: "healthy", checks: [] } }] : installed ? [{ id: "seedbox", name: "Seedbox", packageId: "org.mediahub.seedbox", state: "running", isMock: false, health: { status: "healthy", checks: [] } }] : [];
        else if (path === "/updates/summary") data = { count: 0, items: [], notifications: [] };
        else if (path === "/seedbox/torrents") data = { items: [] };
        else if (path === "/system/status") data = metrics;
        else if (path === "/events/stream") {
          await route.fulfill({ contentType: "text/event-stream", body: `event: system.status\ndata: ${JSON.stringify(metrics)}\n\n` });
          return;
        }
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ data }) });
      });
      await page.goto("/overview");
      if (width > 760) {
        await expect(page.locator('.sidebar nav a[href="/overview"]')).toBeVisible();
      } else {
        await page.locator('.mobile-menu').focus();
        await page.locator('.mobile-menu').press('Enter');
        await expect(page.locator('.sidebar nav a[href="/overview"]')).toBeVisible();
        await page.locator('.scrim').click();
      }
      const overview = page.locator(".overview-grid");
      await expect(overview.locator(".dashboard-card")).toHaveCount(installed === true ? 4 : 2);
      await expect(overview.locator('[data-section="apps"]')).toBeVisible();
      await expect(overview.locator('[data-section="system"]')).toBeVisible();
      await expect(page.locator(".control-summary, .dashboard-context")).toHaveCount(0);
      await expect(overview.locator('[data-section="storage"], [data-section="updates"], [data-section="activity"], [data-section="runtime"]')).toHaveCount(0);
      if (installed === "sso") {
        await expect(overview.getByRole("link", { name: "Åbn MediaSeed" })).toHaveAttribute("href", "https://seed.example/auth/hub/start");
        await expect(overview.getByRole("link", { name: "Åbn MediaSeed" })).toHaveAttribute("target", "_blank");
      }
      if (installed === true) {
        await expect(overview.locator('[data-section="torrents"]')).toBeVisible();
        await expect(overview.locator('[data-section="uploads"]')).toBeVisible();
        await expect(overview.locator(".overview-apps a")).toHaveAttribute("href", "/apps/seedbox");
        await expect(overview.locator('[data-section="torrents"] a')).toHaveAttribute("href", "/apps/seedbox?section=torrents");
        const bounds = await overview.locator(".dashboard-card").evaluateAll((elements) => elements.map((element) => ({ top: element.getBoundingClientRect().top, width: element.getBoundingClientRect().width })));
        expect(bounds[0].top).toBeLessThan(bounds[1].top);
        if (width > 760) {
          expect(bounds[2].top).toBeCloseTo(bounds[3].top, 0);
          expect(bounds[1].width).toBeGreaterThan(bounds[2].width);
        } else expect(bounds[2].top).toBeLessThan(bounds[3].top);
      }
      expect(requests.some((path) => path.startsWith("/events/history"))).toBe(false);
      expect(errors).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await page.screenshot({ path: `test-results/overview-${width}-${installed}.png`, fullPage: true });
    });
  }
}

for (const width of [1440, 390, 320]) {
  test(`Compact update cards preserve console (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname.replace(/^\/api(?:\/v1)?/, "");
      let data: unknown = {};
      if (path === "/auth/status") data = { needsSetup: false };
      else if (path === "/auth/me") data = { id: "test", username: "tester", role: "administrator", csrf: "test", language: "da" };
      else if (path === "/settings") data = { display_name: "MediaHub", advanced_mode: false, theme: "dark" };
      else if (path === "/setup/status") data = { setup_required: false };
      else if (path === "/apps") data = [{ id: "plex", name: "Plex", packageId: "org.mediahub.plex", isMock: false, state: "running", detailPath: "/apps/plex", health: { status: "healthy", checks: [] } }];
      else if (path === "/updates/summary" || path === "/updates/check") data = { count: 0, items: [], notifications: [], checkedAt: 1791580000 };
      else if (path === "/updates/platform") data = { configured: true, installedVersion: "0.4.29", installedCommit: "a".repeat(40), latestCommit: "a".repeat(40), repository: "test/hub", updateAvailable: false, installReady: false };
      else if (path === "/updates/platform/operation") data = { enabled: true, state: "failed", progress: 100, message: "Download interrupted", logs: ["Preserved console output"], steps: [] };
      else if (path === "/updates/queue") data = { state: "idle", items: [], logs: [] };
      else if (path === "/system/status") data = { version: "0.4.29" };
      else if (path.includes("versions")) data = { available: true, plex: { version: "1.42" } };
      else if (["/catalog", "/integrations", "/notifications"].includes(path)) data = [];
      else if (path === "/events/stream") {
        await route.fulfill({ contentType: "text/event-stream", body: ": connected\n\n" });
        return;
      }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ data }) });
    });
    await page.goto("/settings?section=Updates");
    const cards = page.locator(".updates-components > .update-component-card");
    await expect(cards).toHaveCount(2);
    await expect(cards.first()).toContainText("0.4.29");
    await expect(page.getByText("Cannot read properties of undefined", { exact: false })).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Opdater alle", exact: true })).toBeVisible();
    await expect(cards.first().getByText("Download interrupted", { exact: true })).toHaveCount(0);
    await page.locator(".updates-console > details > summary").click();
    await page.locator(".updates-console").getByText("Konsol", { exact: true }).last().click();
    await expect(page.locator(".updates-console").getByLabel("Opdateringskonsol")).toContainText("Preserved console output");
    const bounds = await cards.evaluateAll((elements) => elements.map((element) => ({ width: element.getBoundingClientRect().width, top: element.getBoundingClientRect().top })));
    if (width > 760) {
      expect(bounds[0].width).toBeLessThan(400);
      expect(bounds[0].top).toBeCloseTo(bounds[1].top, 0);
    } else expect(bounds[1].top).toBeGreaterThan(bounds[0].top);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/settings-updates-${width}.png`, fullPage: true });
  });
}

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
      else if (path === "/security") data = { totpEnabled: false, recoveryCodesRemaining: 0, requireTotp: false };
      else if (path === "/security/sessions") data = [{ id: "session-test", current: true, createdAt: "2026-10-09T12:00:00Z", expiresAt: 1791633600 }];
      else if (path === "/auth/preferences") data = request.postDataJSON();
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
      else if (path === "/updates/summary") data = { count: 2, items: [], notifications: [] };
      else if (path === "/health")
        data = { status: "healthy", version: "beta" };
      else if (path === "/maintenance")
        data = { state: "succeeded", message: "Maintenance completed. Removed 0 old update files and unused build cache. Media, app data and rollback backups were preserved." };
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
              storage: [],
              events: [],
              app_info: {},
              apps: [{ id: "fjordflix", name: "FjordFlix", running_count: 1 }],
            },
          },
        ];
      else if (path === "/integrations/fjordhub-one/updates") data = { app_info: {}, updates: {} };
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
      page.locator('[data-app-id="org.mediahub.seedbox"] .hub-card-action'),
    ).toHaveAttribute("href", "/apps/seedbox-real");
    await expect(
      page.locator('[data-app-id="org.mediahub.jellyfin"] .hub-card-action'),
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
      page.getByRole("tab", { name: "Healthcheck", exact: true, selected: true }),
    ).toBeVisible();
    const popup = page.locator(".notification-popups > .notification-popup.success");
    await expect(popup).toHaveCount(0);
    await page.getByRole("button", { name: "Opdater sundhedstjek" }).click();
    await expect(popup).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Kontrollér og ryd op" }),
    ).toBeVisible();
    expect(mutations).toEqual([]);
    await expect(page.locator(".sidebar nav a")).toHaveCount(3);
    await expect(page.getByRole("tab")).toHaveText([
      "Generelt", "Brugere", "Sikkerhed", "Integrationer",
      "Opdateringer", "Healthcheck", "Aktivitet", "Logfiler",
    ]);
    await page.getByRole("tab", { name: "Brugere", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Brugere", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Tilf\u00f8j bruger", exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "tester (dig)", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Slet tester", exact: true })).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/settings-users-${width}.png`, fullPage: true });
    await page.getByRole("tab", { name: "Generelt", exact: true }).click();
    await expect(page.getByRole("button", { name: "Tilpas layout", exact: true })).toHaveCount(0);
    await expect(page.getByRole("group", { name: "Farvepaletter" })).toBeVisible();
    await expect(page.locator('.appearance-controls input[type="color"]')).toHaveCount(3);
    await expect(page.locator(".appearance-depth, .appearance-preview")).toHaveCount(0);
    await expect(page.getByRole("combobox", { name: "Sprog", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Havblå", exact: true }).click();
    const colorInputs = page.locator('.appearance-controls input[type="text"]');
    await colorInputs.nth(0).fill("#123abc");
    await colorInputs.nth(1).fill("#abcdef");
    await colorInputs.nth(2).fill("#234567");
    const preferencesRequest = page.waitForRequest((request) => request.url().includes("/auth/preferences") && request.method() === "PUT");
    await page.getByRole("button", { name: "Gem farver", exact: true }).click();
    expect((await preferencesRequest).postDataJSON().appearance).toMatchObject({ accent: "#123abc", secondary: "#abcdef", background: "#234567" });
    await expect(page.getByRole("button", { name: "Gem farver", exact: true })).toBeDisabled();
    await expect(colorInputs.nth(0)).toHaveValue("#123abc");
    await expect(page.getByRole("button", { name: "Gemt", exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "Havblå", exact: true }).click();
    await page.getByRole("button", { name: "Gemt", exact: true }).click();
    await expect(colorInputs.nth(0)).toHaveValue("#123abc");
    await expect(page.getByRole("button", { name: "Gem farver", exact: true })).toBeDisabled();
    const tabs = await page.getByRole("tablist").boundingBox();
    const general = await page.locator(".settings-general-compact").boundingBox();
    expect(Math.abs(tabs!.x + tabs!.width / 2 - general!.x - general!.width / 2)).toBeLessThan(2);
    const container = await page.locator(".settings-general-compact").evaluate((element) => {
      const bounds = element.parentElement!.getBoundingClientRect();
      return { x: bounds.x, width: bounds.width };
    });
    expect(Math.abs(general!.x + general!.width / 2 - container.x - container.width / 2)).toBeLessThan(2);
    expect(mutations).toEqual(["/auth/preferences"]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/settings-general-${width}.png`, fullPage: true });
    await expect(page.locator('[data-layout-title="Workspace preferences"]')).toHaveCount(0);
    await expect(page.getByText("Vælg din menu", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Vælg dit dashboard", { exact: true })).toHaveCount(0);
    const settingsBounds = await page.locator(".settings-content").boundingBox();
    expect(settingsBounds!.width).toBeCloseTo(general!.width, 0);
    for (const tabName of ["Brugere", "Sikkerhed", "Integrationer", "Healthcheck", "Aktivitet", "Logfiler"]) {
      await page.getByRole("tab", { name: tabName, exact: true }).click();
      if (tabName === "Sikkerhed") {
        await expect(page.locator(".security-workspace > header")).toHaveCount(0);
        await expect(page.locator('.security-card form input[name="newPassword"]')).toBeVisible();
        await expect(page.locator(".session-row")).toHaveCount(1);
        if (width > 760) {
          const cardBounds = await page.locator(".security-grid .security-card").evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height));
          expect(Math.abs(cardBounds[0] - cardBounds[1])).toBeLessThan(1);
        }
        await page.screenshot({ path: `test-results/settings-security-${width}.png`, fullPage: true });
      }
      await expect.poll(() => page.locator(".settings-content").evaluate((element, expected) => {
        if (!element.isConnected || !element.parentElement) return null;
        const bounds = element.getBoundingClientRect();
        const parent = element.parentElement!.getBoundingClientRect();
        const parentStyle = getComputedStyle(element.parentElement!);
        const availableWidth = parent.width - parseFloat(parentStyle.paddingLeft) - parseFloat(parentStyle.paddingRight);
        return {
          widthMatches: bounds.width <= availableWidth + 1,
          centered: Math.abs(bounds.x + bounds.width / 2 - parent.x - parent.width / 2) < 1,
          noOverflow: document.documentElement.scrollWidth <= window.innerWidth,
        };
      }, { width: general!.width }), { message: tabName }).toEqual({ widthMatches: true, centered: true, noOverflow: true });
    }
    expect(errors).toEqual([]);
    const tabRows = await page.getByRole("tab").evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().top));
    if (width > 760) expect(Math.max(...tabRows) - Math.min(...tabRows)).toBeLessThan(1);
    const footerBefore = await page.locator(".footer").boundingBox();
    expect(await page.locator(".footer").evaluate((element) => getComputedStyle(element).position)).toBe("fixed");
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    const footerAfter = await page.locator(".footer").boundingBox();
    expect(footerAfter!.y).toBeCloseTo(footerBefore!.y, 0);
    expect(footerAfter!.y + footerAfter!.height).toBeLessThanOrEqual(1000);
    if (width <= 760) {
      const dock = await page.locator(".mobile-dock").boundingBox();
      expect(footerAfter!.y + footerAfter!.height).toBeLessThanOrEqual(dock!.y);
    }
  });
}
