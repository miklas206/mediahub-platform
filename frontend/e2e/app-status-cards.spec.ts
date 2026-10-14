import { expect, test } from "@playwright/test";
import { textOutsideCards } from "./text-containment";

for (const width of [1440, 390, 320])
  test(`app cards, addresses and live uptime ${width}`, async ({ page }) => {
    await page.clock.install();
    await page.setViewportSize({ width, height: 1000 });
    const origin = "http://192.168.1.111:18800",
      domain = "https://seed.example.com";
    let running = true,
      startedAt = new Date(Date.now() - 7200000).toISOString(),
      externalUrl = domain;
    let reads = 0;
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname.replace(
        /^\/api(?:\/v1)?/,
        "",
      );
      let data: unknown = [];
      const app = {
        id: "managed-seed",
        packageId: "org.mediahub.mediaseed",
        name: "MediaSeed",
        version: "1.0",
        isMock: false,
        state: "running",
        localUrl: origin,
        externalUrl,
        startedAt,
        running,
        observedAt: Date.now() / 1000,
        health: { status: "healthy", summary: "Running", checks: [] },
      };
      if (path === "/auth/status") data = { needsSetup: false };
      else if (path === "/setup/status") data = { setup_required: false };
      else if (path === "/auth/me")
        data = {
          id: "admin",
          username: "tester",
          role: "administrator",
          csrf: "test",
          language: "en",
        };
      else if (path === "/settings")
        data = {
          display_name: "MediaHub",
          theme: "dark",
          visible_navigation: ["/", "/settings"],
          dashboard_sections: [],
        };
      else if (path === "/updates/summary")
        data = { count: 0, items: [], notifications: [] };
      else if (path === "/catalog")
        data = [
          {
            id: "org.mediahub.seedbox",
            name: "MediaSeed",
            availability: "available",
          },
        ];
      else if (path === "/apps") data = [app];
      else if (path === "/fjordhub/deployment") data = null;
      else if (path === "/mediaseed/status")
        data = {
          configured: true,
          available: true,
          url: origin,
          openUrl: domain + "/auth/hub/start",
        };
      else if (path === "/mediavpn/status")
        data = { configured: false, available: false, url: null };
      else if (path === "/app-settings/org.mediahub.mediaseed") {
        if (route.request().method() === "PUT")
          externalUrl = route.request().postDataJSON().externalUrl;
        else reads++;
        data = {
          ...app,
          externalUrl,
          ssoManaged: true,
          configurationPath: null,
          containers: [
            { name: "mediaseed-app", state: running ? "running" : "stopped" },
          ],
        };
      } else if (path === "/events/stream")
        return route.fulfill({
          contentType: "text/event-stream",
          body: ": connected\n\n",
        });
      await route.fulfill({ json: { data } });
    });
    await page.goto("/");
    const card = page.locator('[data-app-id="org.mediahub.seedbox"]');
    await expect(
      card.getByRole("link", { name: origin + "/", exact: true }),
    ).toHaveAttribute("href", origin + "/");
    await expect(
      card.getByRole("link", { name: domain + "/", exact: true }),
    ).toHaveAttribute("href", domain + "/");
    await expect(card.locator(".app-uptime")).toContainText("02:00:");
    await expect(
      card.getByRole("link", { name: "Settings: MediaSeed", exact: true }),
    ).toHaveAttribute("href", "/app-settings/org.mediahub.mediaseed");
    expect(await textOutsideCards(page)).toEqual([]);
    await page.screenshot({
      path: test.info().outputPath("home-addresses.png"),
      fullPage: true,
    });
    await card
      .getByRole("link", { name: "Settings: MediaSeed", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "MediaSeed · App status" }),
    ).toBeVisible();
    const timer = page.locator(".app-status-page .app-uptime");
    const before = await timer.textContent(),
      previousReads = reads;
    await page.clock.runFor(1100);
    await expect(timer).not.toHaveText(before!);
    expect(reads).toBe(previousReads);
    const field = page.getByLabel("External app address");
    await field.fill("https://draft.example.com");
    running = false;
    await page.clock.runFor(10100);
    await expect(timer).toContainText("Stopped");
    await expect(field).toHaveValue("https://draft.example.com");
    running = true;
    startedAt = new Date(Date.now()).toISOString();
    await page.clock.runFor(10100);
    await expect(timer).toContainText("00:00:");
    expect(await textOutsideCards(page)).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: test.info().outputPath("app-status.png"),
      fullPage: true,
    });
    expect(errors).toEqual([]);
  });
