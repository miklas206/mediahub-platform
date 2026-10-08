import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`container apps require reviewed plans and show actual startup (${width}px)`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 950 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const mutations: { path: string; payload: Record<string, unknown> }[] = [];
    let accepted = false;
    let state = "installing";
    const installation = {
      app: "radarr",
      hostId: "local",
      storageIds: {
        appdata: "config",
        movies: "films",
        downloads: "downloads",
      },
      timezone: "Europe/Copenhagen",
    };
    const app = {
      id: "radarr",
      packageId: "org.mediahub.radarr",
      name: "Radarr",
      version: "0.1.0",
      state: "starting",
      isMock: false,
      detailPath: "/apps/install/radarr",
    };
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace(
        /^\/api(?:\/v1)?/,
        "",
      );
      let data: unknown = [];
      if (request.method() !== "GET")
        mutations.push({ path, payload: request.postDataJSON() });
      if (path === "/auth/status") data = { needsSetup: false };
      else if (path === "/setup/status") data = { setup_required: false };
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
          advanced_mode: false,
          visible_navigation: ["/", "/apps", "/store"],
          dashboard_sections: [],
          theme: "dark",
        };
      else if (path === "/updates/summary") data = { count: 0 };
      else if (path === "/fjordhub/deployment") data = null;
      else if (path === "/hosts") data = [{ id: "local", name: "Local host" }];
      else if (path === "/apps") data = accepted ? [app] : [];
      else if (path === "/catalog")
        data = ["jellyfin", "prowlarr", "radarr", "sonarr", "autobrr"].map(
          (id) => ({
            id: "org.mediahub." + id,
            name: id === "autobrr" ? id : id[0].toUpperCase() + id.slice(1),
            description: "Container app",
            category: "automation",
            version: "0.1.0",
            availability: "available",
            requiredRuntime: "docker",
            maintainer: { name: "MediaHub" },
            capabilities: [],
            storageRequirements: [],
          }),
        );
      else if (path === "/container-apps/radarr/install-options")
        data = {
          hostId: "local",
          port: 7878,
          slots: ["appdata", "movies", "downloads"].map((id) => ({
            id,
            required: true,
            readOnly: false,
          })),
          storage: [
            { id: "config", label: "App disk", kind: "appdata" },
            { id: "films", label: "Film disk", kind: "movies" },
            { id: "downloads", label: "Download disk", kind: "downloads" },
          ],
        };
      else if (path === "/container-apps/install-plan")
        data = {
          planDigest: "a".repeat(64),
          installation: request.postDataJSON(),
          url: "http://192.168.1.110:7878",
          mounts: ["/config", "/movies", "/downloads"].map((target) => ({
            target,
            readOnly: false,
          })),
        };
      else if (path === "/container-apps/install") {
        accepted = true;
        data = { state: "accepted" };
      } else if (path === "/container-apps/radarr/status")
        data = {
          state,
          health: "unknown",
          healthVerified: false,
          installation,
          url: "http://192.168.1.110:7878",
        };
      else if (path === "/events/stream") {
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
    await page.goto("/store");
    for (const id of ["jellyfin", "prowlarr", "radarr", "sonarr", "autobrr"]) {
      await expect(page.locator(`image[href="/assets/services/${id}.png"]`)).toBeVisible();
      expect(await page.evaluate(async (name) => {
        const image = new Image();
        image.src = `/assets/services/${name}.png`;
        await image.decode();
        return image.naturalWidth > 0 && image.naturalHeight > 0;
      }, id)).toBe(true);
    }
    await page.screenshot({ path: `../.qa/app-icons-${width}.png`, fullPage: true });
    for (const name of ["Jellyfin", "Prowlarr", "Radarr", "Sonarr", "autobrr"])
      await expect(
        page.getByRole("link", { name: `Install ${name} →`, exact: true }),
      ).toBeVisible();
    await page
      .getByRole("link", { name: "Install Radarr →", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Radarr", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Review installation", exact: true }),
    ).toBeDisabled();
    await page
      .getByLabel("App data storage", { exact: false })
      .selectOption("config");
    await page.getByLabel("Movies", { exact: false }).selectOption("films");
    await page
      .getByLabel("Downloads", { exact: false })
      .selectOption("downloads");
    await page
      .getByRole("button", { name: "Review installation", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Installation preview" }),
    ).toBeVisible();
    await page.getByLabel("Timezone", { exact: true }).fill("UTC");
    await expect(
      page.getByRole("heading", { name: "Installation preview" }),
    ).toHaveCount(0);
    await page
      .getByRole("button", { name: "Review installation", exact: true })
      .click();
    await page.screenshot({
      path: `../.qa/container-install-${width}.png`,
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Install Radarr", exact: true })
      .click();
    await expect(
      page.getByText("Installing container", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Open Radarr", exact: true }),
    ).toHaveCount(0);
    state = "running";
    await expect(
      page.getByRole("link", { name: "Open Radarr", exact: true }),
    ).toHaveAttribute("href", "http://192.168.1.110:7878");
    expect(mutations.map((entry) => entry.path)).toEqual([
      "/container-apps/install-plan",
      "/container-apps/install-plan",
      "/container-apps/install",
    ]);
    expect(mutations[2].payload.confirmedPlanDigest).toBe("a".repeat(64));
    expect(
      (mutations[2].payload.installation as typeof installation).timezone,
    ).toBe("UTC");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect(errors).toEqual([]);
  });
}
