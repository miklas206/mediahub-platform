import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`RSS date protection defaults and explicit per-feed opt-in (${width}px)`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    const submitted: Record<string, unknown>[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const feed = {
      id: "synthetic-feed",
      name: "Synthetic Freeleech TV",
      automatic: false,
      storageId: "downloads",
      downloadLocationId: "root",
      checkedAt: null,
      error: "",
      added: 0,
      pending: 0,
      baselineCount: 1,
      items: [],
    };
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
          id: "test",
          username: "synthetic-admin",
          role: "administrator",
          csrf: "test",
          language: "en",
          totpEnabled: false,
        };
      else if (path === "/settings")
        data = {
          display_name: "MediaHub",
          advanced_mode: false,
          visible_navigation: ["/", "/apps", "/store", "/settings"],
          dashboard_sections: [],
          theme: "dark",
        };
      else if (path === "/apps")
        data = [
          {
            id: "synthetic-seedbox",
            name: "Seedbox",
            packageId: "org.mediahub.seedbox",
            detailPath: "/apps/synthetic-seedbox?section=torrents",
            status: "installed",
            health: { status: "healthy", summary: "Synthetic fixture" },
            version: "test",
            capabilities: [],
          },
        ];
      else if (path === "/apps/synthetic-seedbox/runtime")
        data = {
          view: "seedbox",
          report: {
            health: "unknown",
            available: true,
            cached: false,
            agentOnline: true,
            checks: [],
          },
        };
      else if (path === "/seedbox/locations")
        data = {
          provider: "synthetic",
          available: false,
          countries: [],
          servers: [],
          current: null,
          operation: { state: "idle", step: null },
          automaticDescription: "",
        };
      else if (path === "/seedbox/torrents")
        data = {
          storageId: "downloads",
          downloadLocations: [
            { id: "root", label: "Top folder", storageLabel: "Downloads" },
          ],
          items: [],
          limit: 200,
          retentionSupported: false,
        };
      else if (path.startsWith("/seedbox/rss/feeds")) {
        if (
          route.request().method() === "PUT" ||
          route.request().method() === "POST"
        )
          submitted.push(route.request().postDataJSON());
        data = { feeds: [feed], intervalSeconds: 300 };
      } else if (path === "/events/stream") {
        await route.fulfill({
          contentType: "text/event-stream",
          body: "retry: 60000\n\n",
        });
        return;
      }
      await route.fulfill({
        json: { data, error: null, metadata: { version: "test" } },
      });
    });
    await page.goto("/apps");
    await page.getByRole("link", { name: /Open Seedbox/ }).click();
    const label =
      "Allow older or undated newly discovered entries (this feed only)";
    const add = page.locator(".panel").filter({
      has: page.getByRole("heading", { name: "Add feed", exact: true }),
    });
    await expect(add.getByLabel(label, { exact: true })).not.toBeChecked();
    await expect(add.getByText(/large amounts of old torrents/)).toBeVisible();
    const card = page.getByRole("region", { name: feed.name });
    await card.getByText("Feed settings", { exact: true }).click();
    await expect(card.getByLabel(label, { exact: true })).not.toBeChecked();
    await card.getByLabel(label, { exact: true }).check();
    await expect(
      card.getByLabel("Automatically download future entries", { exact: true }),
    ).not.toBeChecked();
    await card
      .getByRole("button", { name: "Save feed settings", exact: true })
      .click();
    await expect.poll(() => submitted.length).toBe(1);
    expect(submitted[0]).toMatchObject({
      automatic: false,
      allowOlderItems: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    expect(errors).toEqual([]);
  });
}
