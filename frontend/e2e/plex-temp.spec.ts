import { expect, test } from "@playwright/test";

for (const width of [1440, 390, 320]) {
  test(`Plex temporary storage selection ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
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
    const errors: string[] = [];
    const plans: Record<string, unknown>[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
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
      else if (path === "/plex/install-status")
        data = { operation: { state: "idle" } };
      else if (path === "/plex/install-options")
        data = {
          hostId: "local",
          storage: [
            { id: "movies", kind: "movies", label: "My movies" },
            { id: "tv", kind: "tv", label: "My shows" },
            { id: "appdata", kind: "appdata", label: "App storage" },
            { id: "temp", kind: "temp", label: "Media pool / Temp" },
          ],
        };
      else if (path === "/plex/install-plan") {
        plans.push(route.request().postDataJSON());
        data = { planDigest: "a".repeat(64) };
      }
      await route.fulfill({ json: { data } });
    });
    await page.goto("/apps/install/plex");
    await expect(page.getByRole("checkbox").first()).toBeVisible();
    await page.getByRole("checkbox", { name: /My movies/ }).check();
    await page.getByRole("checkbox", { name: /My shows/ }).check();
    await page
      .getByLabel("App data storage", { exact: true })
      .selectOption("appdata");
    await page.getByLabel("Temporary transcoding storage").selectOption("temp");
    await page
      .getByRole("button", { name: "Review installation", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Install Plex", exact: true }),
    ).toBeVisible();
    expect(plans).toEqual([
      expect.objectContaining({
        tempStorageId: "temp",
        moviesStorageIds: ["movies"],
        tvStorageIds: ["tv"],
        otherStorageIds: [],
      }),
    ]);
    await page.getByLabel("Temporary transcoding storage").selectOption("");
    await expect(
      page.getByRole("button", { name: "Review installation", exact: true }),
    ).toBeEnabled();
    expect(await page.getByRole("checkbox").count()).toBe(2);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect(errors).toEqual([]);
    await page.screenshot({
      path: test.info().outputPath("plex-temp.png"),
      fullPage: true,
    });
  });
}
