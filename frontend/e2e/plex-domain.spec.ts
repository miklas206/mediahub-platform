import { expect, test } from "@playwright/test";
for (const width of [1440, 390])
  test(`Plex installation settings and managed domain ${width}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    const writes: unknown[] = [];
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    let label = "plex";
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
      else if (path === "/settings")
        data = {
          display_name: "MediaHub",
          theme: "dark",
          advanced_mode: false,
          visible_navigation: ["/", "/overview", "/settings"],
          dashboard_sections: [],
        };
      else if (path === "/setup/status") data = { setup_required: false };
      else if (path === "/updates/summary")
        data = { count: 0, items: [], notifications: [] };
      else if (path === "/apps")
        data = [
          {
            id: "plex-unique",
            packageId: "org.mediahub.plex",
            name: "Plex",
            state: "running",
            isMock: false,
            version: "1",
            detailPath: "/apps/plex-unique",
            health: { status: "healthy", summary: "Ready", checks: [] },
          },
        ];
      else if (path === "/apps/plex-unique/runtime")
        data = {
          view: "plex",
          operatorUrl: "https://plex.example.com/web",
          report: {
            available: true,
            health: "healthy",
            cached: false,
            agentOnline: true,
            plex: {
              running: true,
              claimed: false,
              version: "1",
              libraries: [],
              activeStreams: 0,
              memoryBytes: null,
              cpuPercent: null,
            },
          },
        };
      else if (path === "/apps/plex-unique/plex/recent-media")
        data = { items: [], libraries: [], available: true };
      else if (path === "/vpn-gateway")
        data = {
          configured: true,
          enabled: true,
          zones: [{ id: "a".repeat(32), name: "example.com" }],
          routes: [
            {
              packageId: "org.mediahub.plex",
              zoneId: "a".repeat(32),
              label,
              hostname: label + ".example.com",
              httpsVerified: true,
            },
          ],
        };
      else if (path === "/vpn-gateway/apps/plex-unique/domain") {
        writes.push(route.request().postDataJSON());
        label = route.request().postDataJSON().label;
        data = {};
      } else if (path === "/events/stream") {
        await route.fulfill({
          contentType: "text/event-stream",
          body: ": connected\n\n",
        });
        return;
      }
      await route.fulfill({ json: { data } });
    });
    await page.goto("/apps/plex-unique");
    await expect(
      page.getByRole("link", { name: "Open Plex settings" }),
    ).toHaveAttribute("href", "https://plex.example.com/web");
    await expect(
      page.getByText("This Plex server is not linked to a Plex account yet.", {
        exact: false,
      }),
    ).toBeVisible();
    await page.getByLabel("Subdomain", { exact: true }).fill("movies");
    await page.getByRole("button", { name: "Save Plex domain" }).click();
    await expect
      .poll(() => writes)
      .toEqual([{ zoneId: "a".repeat(32), label: "movies" }]);
    await expect(
      page.getByText("Plex domain saved.", { exact: false }),
    ).toBeVisible();
    expect(errors).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
