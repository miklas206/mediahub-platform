import { expect, test } from "@playwright/test";

const catalog = [
  {
    id: "org.mediahub.plex",
    name: "Plex",
    description: "Your media library",
    version: "1.0",
    category: "Media",
    availability: "available",
    requiredRuntime: "docker",
    maintainer: { name: "MediaHub" },
    capabilities: [],
    storageRequirements: [],
  },
  {
    id: "org.mediahub.seedbox",
    name: "Seedbox",
    description: "Downloads",
    version: "1.0",
    category: "Downloads",
    availability: "available",
    requiredRuntime: "docker",
    maintainer: { name: "MediaHub" },
    capabilities: [],
    storageRequirements: [],
  },
];
const installed = [
  {
    id: "plex",
    packageId: "org.mediahub.plex",
    name: "Plex",
    version: "1.0",
    state: "running",
    isMock: false,
    detailPath: "/apps/plex",
  },
];

for (const viewport of [
  { width: 1440, height: 1000 },
  { width: 390, height: 844 },
]) {
  test(`app order holds as metadata and health arrive (${viewport.width}px)`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const errors: string[] = [];
    const mutations: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let fullRequests = 0;
    let fullCompleted = false;
    let releaseHealth!: () => void;
    let releaseMetadata!: () => void;
    let releaseIntegrations!: () => void;
    const healthGate = new Promise<void>((resolve) => {
      releaseHealth = resolve;
    });
    let releaseCatalog!: () => void;
    const catalogGate = new Promise<void>((resolve) => {
      releaseCatalog = resolve;
    });
    const metadataGate = new Promise<void>((resolve) => {
      releaseMetadata = resolve;
    });
    const integrationsGate = new Promise<void>((resolve) => {
      releaseIntegrations = resolve;
    });
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname.replace(/^\/api(?:\/v1)?/, "");
      if (request.method() !== "GET") mutations.push(path);
      let data: unknown = [];
      if (path === "/apps") {
        if (url.searchParams.get("include_health") === "false") {
          await metadataGate;
          data = installed;
        } else {
          fullRequests++;
          await healthGate;
          fullCompleted = true;
          data = installed.map((app) => ({
            ...app,
            localUrl: "https://plex.example.test:32400",
            health: {
              status: "healthy",
              summary: "Ready",
              checks: [],
              lastChecked: "",
            },
          }));
        }
      } else if (path === "/integrations") {
        await integrationsGate;
      } else if (path === "/catalog") {
        await catalogGate;
        data = catalog;
      } else if (path === "/auth/status") data = { needsSetup: false };
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
          visible_navigation: ["/", "/apps", "/store", "/settings"],
          dashboard_sections: [],
          theme: "dark",
        };
      else if (path === "/updates/summary") data = { count: 0 };
      else if (path === "/fjordhub/deployment") data = null;
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
    try {
      await page.goto("/store");
      await expect(page.getByLabel("Loading apps…")).toBeVisible();
      await expect(page.locator("[data-app-id]")).toHaveCount(0);
      await expect.poll(() => fullRequests).toBeGreaterThan(0);
      releaseCatalog();
      await expect(page).toHaveURL(/\/$/);
      const plex = page.locator('[data-app-id="org.mediahub.plex"]');
      const seed = page.locator('[data-app-id="org.mediahub.seedbox"]');
      await expect(plex).toBeVisible();
      await expect(seed).toBeVisible();
      await expect(page.getByRole("link", { name: "App Store", exact: true })).toHaveCount(0);
      const order = () => page.locator("[data-app-id]").evaluateAll(cards => cards.map(card => card.getAttribute("data-app-id")));
      const initialOrder = await order();
      expect(initialOrder).toContain("org.mediahub.video-downloader");
      expect(initialOrder).toContain("org.mediahub.mediaupload");
      releaseMetadata();
      await expect(plex.getByRole("heading", { name: "Plex" })).toBeVisible();
      await expect(plex).toHaveClass(/configured/);
      await expect(
        plex.getByRole("link", { name: "Open app · Plex" }),
      ).toHaveAttribute("href", "/apps/plex");
      await expect(
        seed.getByRole("heading", { name: "MediaSeed" }),
      ).toBeVisible();
      await expect(
        seed.getByRole("link", { name: /Set up|View setup/ }),
      ).toBeVisible();
      releaseIntegrations();
      await expect(page.getByLabel("Loading apps…")).toHaveCount(0);
      expect(fullCompleted).toBe(false);
      expect(await order()).toEqual(initialOrder);
      releaseHealth();
      await expect.poll(() => fullCompleted).toBe(true);
      await expect(plex.getByRole("link", { name: "Open app · Plex" })).toHaveAttribute("href", "https://plex.example.test:32400/web/index.html");
      expect(await order()).toEqual(initialOrder);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      expect(mutations).toEqual([]);
      expect(errors).toEqual([]);
    } finally {
      releaseCatalog();
      releaseHealth();
      releaseMetadata();
      releaseIntegrations();
    }
  });
}
