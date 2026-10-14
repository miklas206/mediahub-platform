import { textOutsideCards } from "./text-containment";
import { expect, test } from "@playwright/test";
for (const width of [1440, 768, 390, 320])
  test(`Plex installation settings and managed domain ${width}`, async ({
    page,
  }) => {
    await page.addInitScript(() => {
      class Source extends EventTarget {
        onopen: (() => void) | null = null;
        close() {}
        constructor() {
          super();
          queueMicrotask(() => this.onopen?.());
        }
      }
      window.EventSource = Source as unknown as typeof EventSource;
    });
    await page.setViewportSize({ width, height: 1000 });
    const writes: unknown[] = [];
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    let label = "plex";
    let claimed = false;
    let linking = false;
    const claims: unknown[] = [];
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname.replace(
        /^\/api(?:\/v1)?/,
        "",
      );
      let data: unknown = [];
      if (path === "/plex/account") {
        if (route.request().method() === "POST") {
          claims.push(route.request().postDataJSON());
          linking = true;
          data = { state: "accepted" };
        } else
          data = {
            claimed,
            openUrl: "https://plex.example.com/web/index.html",
            operation: {
              state: linking ? "running" : "idle",
              message: linking
                ? "Linking Plex to your account"
                : "Plex account setup is required",
            },
          };
      } else if (path === "/auth/status") data = { needsSetup: false };
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
          operatorUrl: "https://plex.example.com/web/index.html",
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
    ).toHaveAttribute("href", "https://plex.example.com/web/index.html");
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
    await page
      .getByLabel("Plex claim token", { exact: true })
      .fill("claim-synthetic-browser-token");
    await page
      .getByRole("button", { name: "Link Plex account", exact: true })
      .click();
    await expect
      .poll(() => claims)
      .toEqual([{ claimToken: "claim-synthetic-browser-token" }]);
    await expect(
      page.getByLabel("Plex claim token", { exact: true }),
    ).toHaveValue("");
    await expect(
      page.getByRole("button", {
        name: "Linking Plex to your account",
        exact: true,
      }),
    ).toBeDisabled();
    claimed = true;
    linking = false;
    await expect(page.locator(".plex-account-setup")).toContainText(
      "Plex is linked to your account",
      { timeout: 10000 },
    );
    await expect(page.locator(".plex-account-setup a")).toHaveAttribute(
      "href",
      "https://plex.example.com/web/index.html",
    );
    const popup = page
      .locator(".notification-popup.success")
      .filter({ hasText: "Plex is linked to your account" });
    await expect(popup).toBeVisible();
    await expect(
      popup.getByRole("link", { name: "Open Plex for configuration" }),
    ).toHaveAttribute("href", "https://plex.example.com/web/index.html");
    await expect(popup).toContainText(
      "Open Plex to finish setup and add your media libraries.",
    );
    await popup.getByRole("button", { name: "Dismiss notification" }).click();
    await expect(popup).toHaveCount(0);
    await expect(page.locator(".plex-account-setup")).toContainText(
      "Open Plex to finish setup and add your media libraries.",
    );
    await page.reload();
    await page.bringToFront();
    await expect(page.locator(".plex-account-setup")).toContainText(
      "Plex is linked to your account",
      { timeout: 10000 },
    );
    await expect(popup).toHaveCount(0);
    for (const panel of [".plex-account-setup", ".app-vpn-domain"]) {
      expect(
        await page.locator(panel + " h2").evaluate((heading) => {
          const h = heading.getBoundingClientRect(),
            p = heading.closest(".panel")!.getBoundingClientRect();
          return h.left - p.left >= 12 && h.top - p.top >= 12;
        }),
      ).toBe(true);
    }
    await page.getByLabel("Subdomain", { exact: true }).fill("a".repeat(100));
    expect(await textOutsideCards(page)).toEqual([]);
    await page.screenshot({
      path: test.info().outputPath("plex-panels.png"),
      fullPage: true,
    });
    expect(claims).toHaveLength(1);
    expect(errors).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
