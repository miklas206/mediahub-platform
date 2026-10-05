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
          dashboard_sections: [],
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
              apps: [],
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
          body: "retry: 60000\n\n",
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
    expect(requests.every((url) => !url.includes("192.168.50.20"))).toBe(true);
    expect(errors).toEqual([]);
  });
}
