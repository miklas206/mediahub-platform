import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`FjordFlix ordered gallery, streams and independent stale states (${width}px)`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    const requests: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("request", (r) => requests.push(r.url()));
    let phase = "good";
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname.replace(
        /^\/api(?:\/v1)?/,
        "",
      );
      if (path.includes("/fjordflix/posters/")) {
        await route.fulfill({ status: 404, body: "Poster unavailable" });
        return;
      }
      let data: unknown = [];
      if (path === "/auth/status") data = { needsSetup: false };
      else if (path === "/setup/status") data = { setup_required: false };
      else if (path === "/auth/me")
        data = {
          id: "fixture",
          username: "fixture",
          role: "administrator",
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
      else if (path === "/integrations" && phase === "network") {
        await route.abort("failed");
        return;
      } else if (path === "/integrations")
        data = [
          {
            id: "hub",
            name: "Fixture FjordHub",
            baseUrl: "https://192.168.50.20:8443",
            enabled: true,
            tokenConfigured: true,
            allowHttp: false,
            lastSuccessfulSync: "2026-10-05T20:00:00Z",
            nextSync: 0,
            snapshot: {
              status: "online",
              stale: false,
              capabilities: ["docker.resources.read"],
              metrics: { cpuPercent: 25 },
              apps: [
                {
                  id: "fjordflix",
                  name: "FjordFlix",
                  container_count: 1,
                  running_count: 1,
                  url: "https://192.168.50.20:9234/",
                },
                {
                  id: "fjordcalendar",
                  name: "FjordCalendar",
                  container_count: 1,
                  running_count: 1,
                },
              ],
              fjordflix:
                phase === "legacy"
                  ? null
                  : {
                      ok: true,
                      stale: phase === "stale",
                      error:
                        phase === "stale"
                          ? "FjordFlix data is unavailable."
                          : undefined,
                      library_count: phase === "empty" ? 0 : 12,
                      items:
                        phase === "empty"
                          ? []
                          : Array.from({ length: 10 }, (_, i) => ({
                              id: String(i),
                              title: i === 0 ? "Æøå newest" : `Title ${i}`,
                              poster_id: String(i),
                              overview: "Description æøå",
                              genres: ["Drama"],
                            })),
                      streams:
                        phase === "empty"
                          ? []
                          : [
                              {
                                id: "s",
                                title: "Current movie",
                                user: "Anna",
                                client: "Browser",
                                state: "paused",
                                mode: "Direct Play",
                                position: 120,
                                duration: 7200,
                                height: 1080,
                                mbps: 8,
                                encoder: "Original",
                              },
                            ],
                    },
            },
          },
        ];
      else if (path === "/events/stream") {
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
    await page.goto("/integrations");
    await expect(
      page.getByRole("heading", { name: "Recently added · last 10" }),
    ).toBeVisible();
    await expect(page.locator(".fjordflix-title")).toHaveCount(10);
    await expect(page.locator(".fjordflix-title h4").first()).toHaveText(
      "Æøå newest",
    );
    await expect(
      page.getByText("paused · Direct Play", { exact: false }),
    ).toBeVisible();
    await expect(page.getByText("8 Mbit/s", { exact: false })).toBeVisible();
    for (const card of await page.locator(".fjordflix-title").all()) {
      await card.scrollIntoViewIfNeeded();
    }
    await expect(
      page.getByRole("img", { name: "Poster unavailable" }),
    ).toHaveCount(11);
    await expect(page.getByText("25.0%", { exact: true })).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    phase = "network";
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(
      page.getByText("Showing last good FjordFlix data · stale"),
    ).toBeVisible();
    await expect(
      page.getByText("MediaHub connection interrupted."),
    ).toBeVisible();
    await expect(page.locator(".fjordflix-title")).toHaveCount(10);
    await expect(page.getByText("25.0%", { exact: true })).toBeVisible();
    phase = "stale";
    await page.reload();
    await expect(
      page.getByText("Showing last good FjordFlix data · stale"),
    ).toBeVisible();
    await expect(page.locator(".fjordflix-title")).toHaveCount(10);
    await expect(page.getByText("25.0%", { exact: true })).toBeVisible();
    phase = "empty";
    await page.reload();
    await expect(page.getByText("No titles in the library.")).toBeVisible();
    await expect(page.getByText("No active streams.")).toBeVisible();
    await expect(page.locator(".fjordflix-title")).toHaveCount(0);
    phase = "legacy";
    await page.reload();
    await expect(page.getByText("25.0%", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "FjordFlix", exact: true }),
    ).toHaveCount(0);
    phase = "good";
    await page.goto("/");
    const card = page.locator(".fjordflix-service-tile");
    await expect(card).toHaveCount(1);
    await expect(card.getByText("12", { exact: true })).toBeVisible();
    await expect(card.getByText("1", { exact: true })).toBeVisible();
    await expect(card.locator(".plex-poster")).toHaveCount(10);
    await expect(card.locator(".plex-poster").first()).toHaveAttribute(
      "title",
      "Æøå newest",
    );
    await expect(
      card.getByRole("link", { name: "Open FjordFlix" }),
    ).toHaveAttribute("href", "https://192.168.50.20:9234/");
    await expect(
      card.getByRole("button", { name: "Show more covers" }),
    ).toBeVisible();
    await card.getByRole("button", { name: "Show more covers" }).click();
    await expect
      .poll(() => card.locator(".plex-posters").evaluate((el) => el.scrollLeft))
      .toBeGreaterThan(0);
    await expect(
      page.getByRole("link", {
        name: "FjordCalendar",
      }),
    ).toHaveAttribute("href", "https://192.168.50.20:8443/#card-fjordcalendar");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.getByRole("button", { name: "Customize layout" }).click();
    await page.getByText("Choose cards", { exact: true }).click();
    const choice = page.getByRole("checkbox", {
      name: "FjordFlix · Fixture FjordHub",
      exact: true,
    });
    await expect(choice).toBeChecked();
    await choice.uncheck();
    await expect(page.locator(".fjordflix-service-tile")).toHaveCount(0);
    await choice.check();
    await expect(page.locator(".fjordflix-service-tile")).toHaveCount(1);
    await page.getByRole("button", { name: "Done arranging" }).click();
    phase = "stale";
    await page.reload();
    await expect(
      page
        .locator(".fjordflix-service-tile")
        .getByText("Showing last good FjordFlix data · stale"),
    ).toBeVisible();
    await expect(
      page.locator(".fjordflix-service-tile .plex-poster"),
    ).toHaveCount(10);
    phase = "empty";
    await page.reload();
    await expect(
      page
        .locator(".fjordflix-service-tile")
        .getByText("No titles in the library."),
    ).toBeVisible();
    phase = "legacy";
    await page.reload();
    await expect(page.locator(".fjordflix-service-tile")).toHaveCount(0);
    expect(requests.every((url) => !url.includes("192.168.50.20"))).toBe(true);
    expect(errors).toEqual([]);
  });
}
