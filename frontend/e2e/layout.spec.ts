import { expect, test } from "@playwright/test";
import danish from "../src/locales/da.json" with { type: "json" };

test("VPN card keeps its content on hover and can move above the other VPN cards", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1400 });
  await page.goto("/apps/seedbox?section=vpn");
  await expect(
    page.getByRole("heading", { name: "VPN Location", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Customize layout" }).click();
  const group = page.locator(".vpn-location-content");
  const card = group.locator('.layout-item[data-layout-title="VPN Location"]');
  const surface = card.locator(":scope > .layout-drag-surface");
  await surface.hover();
  expect(
    await surface.evaluate((node) => getComputedStyle(node).backgroundColor),
  ).toBe("rgba(0, 0, 0, 0)");
  await expect(
    card.getByRole("heading", { name: "VPN Location", exact: true }),
  ).toBeVisible();
  await expect(card.getByText("Current", { exact: true })).toBeVisible();
  while (
    await card
      .getByRole("button", { name: "Move VPN Location earlier", exact: true })
      .isEnabled()
  ) {
    await card
      .getByRole("button", { name: "Move VPN Location earlier", exact: true })
      .click();
  }
  await expect(group.locator(":scope > .layout-item").first()).toHaveAttribute(
    "data-layout-title",
    "VPN Location",
  );
  const heading = (await page
    .getByRole("heading", { name: "Seedbox", exact: true })
    .boundingBox())!;
  expect((await card.boundingBox())!.y).toBeGreaterThan(heading.y);
  await page.reload();
  await expect(group.locator(":scope > .layout-item").first()).toHaveAttribute(
    "data-layout-title",
    "VPN Location",
  );
});

test("card edges resize width and height on the grid with persistent, readable content", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1600 });
  await page.goto("/apps/seedbox?section=vpn");
  await expect(
    page.getByRole("heading", { name: "VPN Location", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Customize layout" }).click();
  const group = page.locator(".vpn-location-content");
  const card = group.locator('.layout-item[data-layout-title="VPN Location"]');
  async function pull(edge: string, dx: number, dy: number) {
    const handle = card.locator(`:scope > .resize-${edge}`);
    await handle.scrollIntoViewIfNeeded();
    const box = (await handle.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(
      box.x + box.width / 2 + dx,
      box.y + box.height / 2 + dy,
      { steps: 8 },
    );
    await page.mouse.up();
  }
  await pull("right", -300, 0);
  const width = (await card.boundingBox())!.width;
  expect(width / (await group.boundingBox())!.width).toBeLessThan(0.8);
  expect(width / (await group.boundingBox())!.width).toBeGreaterThan(0.65);
  await pull("bottom", 0, 96);
  const height = (await card.boundingBox())!.height;
  expect(height % 24).toBe(0);
  await pull("top", 0, -48);
  expect((await card.boundingBox())!.height).toBe(height + 48);
  await pull("left", 100, 0);
  expect((await card.boundingBox())!.width).toBeLessThan(width);
  const savedWidth = (await card.boundingBox())!.width;
  const savedHeight = (await card.boundingBox())!.height;
  await page.getByRole("button", { name: "Done arranging" }).click();
  await page.reload();
  await expect(card).toHaveClass(/has-custom-height/);
  expect((await card.boundingBox())!.width).toBeCloseTo(savedWidth, 0);
  expect((await card.boundingBox())!.height).toBe(savedHeight);
  await expect(
    card.getByRole("combobox", { name: "Country", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Customize layout" }).click();
  await pull("bottom", 0, -1000);
  expect((await card.boundingBox())!.height).toBe(144);
  expect(
    await card
      .locator(":scope > .layout-item-content")
      .evaluate((node) =>
        [
          node,
          ...node.querySelectorAll<HTMLElement>(
            ".panel, .dashboard-card, .layout-card",
          ),
        ].some((content) => content.scrollHeight > content.clientHeight),
      ),
  ).toBe(true);
  await card
    .getByRole("button", {
      name: "Restore automatic height for VPN Location",
      exact: true,
    })
    .click();
  await expect(card).not.toHaveClass(/has-custom-height/);
  await page.screenshot({
    path: "../.qa/grid-resize-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(async () => {
      const box = (await page.locator(".sidebar").boundingBox())!;
      return box.x + box.width;
    })
    .toBeLessThanOrEqual(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../.qa/grid-resize-mobile.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test.beforeEach(async ({ page }) => {
  const metrics = {
    hostname: "QA",
    version: "QA",
    timestamp: new Date().toISOString(),
    uptimeSeconds: 3600,
    coreUptimeSeconds: 3600,
    cpu: { percent: 10, cores: 4 },
    ram: { totalBytes: 1e9, usedBytes: 1e8, availableBytes: 9e8, percent: 10 },
    disk: { totalBytes: 1e9, usedBytes: 1e8, freeBytes: 9e8, percent: 10 },
    network: { downloadBytesPerSecond: 1000, uploadBytesPerSecond: 2000 },
  };
  await page.addInitScript((metrics) => {
    class QuietEventSource {
      addEventListener(
        name: string,
        callback: (event: { data: string }) => void,
      ) {
        if (name === "system.status")
          queueMicrotask(() => callback({ data: JSON.stringify(metrics) }));
      }
      close() {}
    }
    Object.defineProperty(window, "EventSource", { value: QuietEventSource });
  }, metrics);
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    let data: unknown = [];
    const app = {
      id: "seedbox",
      name: "Seedbox",
      packageId: "org.mediahub.seedbox",
      version: "QA",
      state: "running",
      isMock: false,
      health: { status: "healthy", checks: [] },
    };
    if (path === "/auth/status") data = { needsSetup: false };
    if (path === "/setup/status") data = { setup_required: false };
    if (path === "/auth/me")
      data = {
        id: "layout-qa",
        username: "qa",
        role: "admin",
        csrf: "qa",
        language: "en",
      };
    if (path === "/settings")
      data = {
        display_name: "MediaHub",
        theme: "dark",
        advanced_mode: true,
        visible_navigation: [
          "/",
          "/apps",
          "/store",
          "/storage",
          "/hosts",
          "/activity",
          "/logs",
          "/updates",
          "/backups",
          "/integrations",
          "/settings",
        ],
        dashboard_sections: ["storage", "torrents", "apps", "system"],
      };
    if (path === "/system/status") data = metrics;
    if (path === "/apps") data = [app];
    if (path === "/updates/summary")
      data = {
        count: 0,
        checkedAt: 1,
        items: [],
        notifications: [],
        intervalHours: 24,
        lastError: null,
      };
    if (path === "/updates/platform")
      data = {
        configured: false,
        installedVersion: "QA",
        latestVersion: null,
        assets: {},
        updateAvailable: false,
        message: "QA",
      };
    if (path.endsWith("/operation") || path === "/updates/queue")
      data = { state: "idle", message: "", logs: [], items: [] };
    if (path === "/backups")
      data = { includes: ["Configuration"], excludes: ["Media"] };
    if (path === "/hosts")
      data = [
        {
          id: "qa",
          name: "Local host",
          address: "http://qa.local",
          local: true,
          status: "online",
          capabilities: [],
        },
      ];
    if (path === "/runtime")
      data = { connected: true, version: "QA", docker: { available: true } };
    if (path === "/catalog")
      data = [
        {
          id: "org.mediahub.seedbox",
          name: "Seedbox",
          version: "QA",
          description: "Torrent downloads",
          maintainer: { name: "QA" },
          capabilities: [],
          configFields: [],
          storageRequirements: [],
        },
      ];
    if (path === "/seedbox/rss/feeds/settings") data = { intervalSeconds: 300 };
    if (path === "/security")
      data = {
        totpEnabled: false,
        requireTotp: false,
        recoveryCodesRemaining: 0,
      };
    if (path === "/network")
      data = {
        pending: {
          listen_host: "127.0.0.1",
          port: 18766,
          base_url: "http://localhost",
          trusted_proxies: [],
          allowed_origins: [],
        },
      };
    if (path === "/apps/seedbox/runtime")
      data = {
        view: "seedbox",
        report: {
          health: "healthy",
          available: true,
          cached: false,
          agentOnline: true,
          qBittorrent: {
            healthy: true,
            running: true,
            apiAuthenticated: true,
            torrents: 2,
            downloading: 1,
            seeding: 1,
            downloadSpeed: 1000,
            uploadSpeed: 500,
          },
          vpn: { verified: true },
          storage: { mounted: true, appWritable: true },
        },
      };
    if (path === "/seedbox/torrents")
      data = {
        storageId: "qa",
        limit: 100,
        items: [
          {
            hash: "a",
            name: "Downloading a very long torrent name ".repeat(5),
            progress: 0.4,
            state: "downloading",
            dlspeed: 1000,
            upspeed: 50,
            eta: 60,
            size: 10000,
            ratio: 0.5,
            actionsAllowed: true,
          },
          {
            hash: "b",
            name: "Completed torrent",
            progress: 1,
            state: "uploading",
            dlspeed: 0,
            upspeed: 500,
            eta: 8640000,
            size: 10000,
            ratio: 0.5,
            actionsAllowed: true,
          },
          {
            hash: "c",
            name: "Paused torrent",
            progress: 0.1,
            state: "stoppedDL",
            dlspeed: 0,
            upspeed: 0,
            eta: 8640000,
            size: 10000,
            ratio: 0.5,
            actionsAllowed: true,
          },
        ],
      };
    if (path === "/seedbox/locations")
      data = {
        available: true,
        countries: ["Denmark"],
        servers: [],
        current: { country: "Denmark" },
        operation: { state: "idle" },
      };
    if (path === "/seedbox/rss/feeds")
      data = { feeds: [], intervalSeconds: 300 };
    await route.fulfill({ json: { data } });
  });
});

test("Danish covers every workspace page and switches back to English without reloading", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let language = "da";
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        data: {
          id: "layout-qa",
          username: "qa",
          role: "admin",
          csrf: "qa",
          language,
        },
      },
    }),
  );
  await page.route("**/api/v1/auth/preferences", async (route) => {
    language = route.request().postDataJSON().language;
    await route.fulfill({ json: { data: { language } } });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  for (const [path, expected] of [
    ["/", "Dine apps"],
    ["/apps", "Ét sted til dine apps, deres status og betjening."],
    ["/store", "Tilføj kun det, du har brug for."],
    ["/storage", "Mediefiler"],
    ["/hosts", "Værter og agenter"],
    ["/activity", "Hændelsestidslinje"],
    ["/logs", "Core-logbuffer"],
    ["/updates", "Opdateringsoversigt"],
    ["/backups", "Opret krypteret backup"],
    ["/integrations", "Forbind FjordHub"],
    ["/settings", "Sprog"],
    ["/apps/seedbox?section=torrents", "Dine feeds"],
    ["/apps/seedbox?section=vpn", "VPN-placering"],
    ["/apps/seedbox?section=settings", "Driftskontroller"],
  ]) {
    await page.goto(path);
    await expect(page.locator("html")).toHaveAttribute("lang", "da");
    await expect(
      page.getByText(expected, { exact: true }).first(),
      path,
    ).toBeVisible();
    // Check complete UI sentences, excluding command output and identity/product names.
    expect(errors, path).toEqual([]);
    const text = await page.locator("body").innerText();
    const leaks = Object.entries(danish).filter(
      ([source, translated]) =>
        source !== translated &&
        source.length > 30 &&
        !source.includes("{") &&
        !source.includes("?") &&
        text.includes(source),
    );
    expect(leaks, path).toEqual([]);
  }
  await page.goto("/settings");
  for (const name of [
    "Vedligeholdelse",
    "Lager",
    "Netværk",
    "Agent",
    "Sikkerhed",
    "Avanceret",
  ]) {
    await page.getByRole("tab", { name, exact: true }).click();
    await expect(page.getByRole("tab", { name, exact: true })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  }
  await page.getByRole("tab", { name: "Generelt", exact: true }).click();
  await page.getByLabel("Sprog", { exact: true }).selectOption("en");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(
    page.getByRole("heading", { name: "Language", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("tab", { name: "Network", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await page.getByLabel("Language", { exact: true }).selectOption("da");
  await expect(
    page.getByRole("heading", { name: "Sprog", exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/store");
  await expect(
    page.getByText("Tilføj kun det, du har brug for."),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../.qa/danish-store-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  expect(errors).toEqual([]);
});

test("Danish translates Cloudflare and VPN server messages and keeps country submission unchanged", async ({
  page,
}) => {
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        data: {
          id: "layout-qa",
          username: "qa",
          role: "admin",
          csrf: "qa",
          language: "da",
        },
      },
    }),
  );
  const country = "Denmark";
  await page.route("**/api/v1/seedbox/locations", (route) =>
    route.fulfill({
      json: {
        data: {
          available: true,
          countries: [country, "Sweden"],
          servers: [],
          current: {
            country,
            countryEvidence: "independent GeoIP and provider catalog",
          },
          automaticDescription:
            "Compares download and upload through up to 3 P2P servers. Keeps the current server unless the combined measured speed improves by 25%. Tests interrupt torrent connections and use up to 30 MiB. Measurements include current network load; torrent speeds may differ.",
          operation: {
            state: "failed",
            progress: 40,
            step: "Location change blocked; qBittorrent remains stopped",
          },
        },
      },
    }),
  );
  await page.route("**/api/v1/apps/seedbox/runtime", (route) =>
    route.fulfill({
      json: {
        data: {
          view: "seedbox",
          report: {
            health: "healthy",
            available: true,
            cached: false,
            agentOnline: true,
            qBittorrent: {
              healthy: true,
              running: true,
              downloadSpeed: 0,
              uploadSpeed: 0,
            },
            vpn: { verified: true, externalIp: "193.29.107.106" },
            storage: { mounted: true, appWritable: true },
            portForwarding: {
              status: "healthy",
              currentPort: 20000,
              qBittorrentVerified: true,
              expiresAt: Date.now() / 1000 + 300,
            },
          },
        },
      },
    }),
  );
  await page.route("**/api/v1/seedbox/port-reachability", (route) =>
    route.fulfill({
      json: {
        data: {
          status: "reachable",
          address: "193.29.107.106",
          port: 20000,
          checkedAt: Date.now() / 1000,
          message:
            "TCP connection to the VPN torrent port succeeded from MediaHub Core",
        },
      },
    }),
  );
  await page.goto("/apps/seedbox?section=vpn");
  await expect(page.getByText("Indgående TCP-forbindelse")).toBeVisible();
  await expect(
    page.getByText(
      "TCP-forbindelse til VPN-torrentport lykkedes fra MediaHub Core",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Land", exact: true }),
  ).toHaveValue(country);
  await expect(
    page
      .getByRole("combobox", { name: "Land", exact: true })
      .getByRole("option", { name: "Danmark" }),
  ).toHaveAttribute("value", country);
  await expect(
    page.getByText(
      "Skift af placering blokeret; qBittorrent forbliver stoppet",
    ),
  ).toBeVisible();
  await expect(
    page.getByText(/Sammenligner download og upload gennem op til 3/),
  ).toBeVisible();
  await page.screenshot({
    path: "../.qa/danish-vpn.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.route("**/api/v1/apps/cloudflare/runtime", (route) =>
    route.fulfill({
      json: {
        data: {
          view: "cloudflare",
          report: {
            health: "healthy",
            available: true,
            cached: false,
            agentOnline: true,
            cloudflare: {
              configured: true,
              status: "healthy",
              checkedAt: Date.now() / 1000,
              metricsReachable: true,
              connections: 4,
              routeCount: 1,
              message: "Tunnel and configured public routes are reachable",
              routes: [
                {
                  url: "https://mediahub.example.com",
                  hostname: "mediahub.example.com",
                  reachable: true,
                  statusCode: 200,
                  latencyMs: 30,
                  message: "Route reached Cloudflare/origin",
                },
              ],
            },
          },
        },
      },
    }),
  );
  await page.route(
    "**/api/v1/catalog/org.mediahub.cloudflared/configuration",
    (route) =>
      route.fulfill({
        json: {
          data: {
            values: {
              tunnel_name: "My tunnel",
              public_hostnames: "mediahub.example.com",
              origin_url: "https://192.168.1.50:18765",
            },
            secrets: {},
          },
        },
      }),
  );
  await page.goto("/apps/cloudflare");
  await expect(
    page.getByText("Ruten nåede Cloudflare/oprindelsesserveren"),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Gemt Cloudflare-konfiguration" }),
  ).toBeVisible();
  await expect(page.getByText("1 tunnelkonfiguration gemt")).toBeVisible();
  await page.screenshot({
    path: "../.qa/danish-cloudflare.png",
    fullPage: true,
    animations: "disabled",
  });
});

test("Danish covers installation guides and App Store descriptions", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        data: {
          id: "layout-qa",
          username: "qa",
          role: "admin",
          csrf: "qa",
          language: "da",
        },
      },
    }),
  );
  await page.route(
    "**/api/v1/catalog/org.mediahub.cloudflared/configuration",
    (route) => route.fulfill({ json: { data: { values: {}, secrets: {} } } }),
  );
  await page.route("**/api/v1/seedbox/wizard/targets", (route) =>
    route.fulfill({ json: { data: { bound: false, hosts: [] } } }),
  );
  await page.route("**/api/v1/seedbox/wizard", (route) =>
    route.fulfill({
      status: 409,
      json: {
        error: {
          code: "seedbox_missing",
          message: "Seedbox is not configured",
        },
      },
    }),
  );
  await page.route("**/api/v1/plex/install-options", (route) =>
    route.fulfill({ json: { data: { hostId: "qa", storage: [] } } }),
  );
  await page.route("**/api/v1/catalog", (route) =>
    route.fulfill({
      json: {
        data: [
          {
            id: "org.mediahub.plex",
            name: "Plex",
            version: "QA",
            availability: "available",
            description:
              "Organize and stream your own media, with persistent configuration and read-only media access.",
            maintainer: { name: "MediaHub contributors" },
            category: "media",
            configFields: [],
            storageRequirements: [],
            capabilities: [],
          },
          {
            id: "org.mediahub.seedbox",
            name: "Seedbox",
            version: "QA",
            availability: "available",
            description:
              "Protected downloads with Proton WireGuard, verified port forwarding and everyday torrent controls.",
            maintainer: { name: "MediaHub contributors" },
            category: "downloads",
            configFields: [],
            storageRequirements: [],
            capabilities: [],
          },
        ],
      },
    }),
  );
  await page.goto("/store");
  await expect(
    page.getByText(/Organiser og stream dine egne medier/),
  ).toBeVisible();
  await expect(
    page.getByText(/Beskyttede downloads med Proton WireGuard/),
  ).toBeVisible();
  for (const [path, expected] of [
    ["/store/cloudflare", "Hvad MediaHub kan klargøre"],
    ["/store/fjordhub", "Guidet FjordHub-installation"],
    [
      "/apps/install/plex",
      "Vælg dine eksisterende mediemapper. Plex læser originalerne — intet flyttes eller kopieres.",
    ],
    ["/apps/install/seedbox", "Vælg din dedikerede Seedbox-vært"],
  ]) {
    await page.goto(path);
    await expect(
      page.getByText(expected, { exact: true }).first(),
      path,
    ).toBeVisible();
    expect(errors, path).toEqual([]);
  }
});

test("RSS download history shows current performance and adapts to card width", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.clock.install();
  let uploaded = 3 * 1024 ** 3;
  let unavailable = false;
  const torrent = {
    hash: "a".repeat(40),
    name: "Renamed release",
    progress: 1,
    state: "uploading",
    size: 2 * 1024 ** 3,
    uploaded,
    downloaded: 2 * 1024 ** 3,
    dlspeed: 0,
    upspeed: 2048,
    ratio: 0,
    seeding_time: 25 * 3600,
    num_seeds: 2,
    num_leechs: 3,
    eta: 0,
    actionsAllowed: true,
  };
  await page.route("**/api/v1/seedbox/torrents", (route) =>
    route.fulfill(
      unavailable
        ? { status: 503, json: { error: { message: "Unavailable" } } }
        : {
            json: {
              data: {
                storageId: "downloads",
                downloadLocations: [{ id: "root", label: "Top folder" }],
                limit: 500,
                items: [
                  { ...torrent, uploaded },
                  {
                    ...torrent,
                    hash: "b".repeat(40),
                    name: "Legacy release",
                    progress: 0.25,
                    state: "downloading",
                    uploaded: 0,
                  },
                  {
                    ...torrent,
                    hash: "d".repeat(40),
                    name: "Duplicate release",
                  },
                  {
                    ...torrent,
                    hash: "e".repeat(40),
                    name: "Duplicate release",
                  },
                ],
              },
            },
          },
    ),
  );
  await page.route("**/api/v1/seedbox/rss/feeds", (route) =>
    route.fulfill({
      json: {
        data: {
          intervalSeconds: 300,
          feeds: [
            {
              id: "feed-qa",
              name: "Dansk TV",
              automatic: true,
              storageId: "downloads",
              downloadLocationId: "root",
              checkedAt: 1700000000,
              error: "",
              added: 4,
              pending: 0,
              baselineCount: 0,
              items: [],
              automaticHistory: [
                {
                  id: "new",
                  title:
                    "Original.release.with.a.long.name.1080p.WEB-DL.x264-SHOWTIME",
                  torrentHash: "a".repeat(40),
                  addedAt: 1700000000,
                  alreadyPresent: false,
                },
                {
                  id: "legacy",
                  title: "Legacy release",
                  addedAt: 1700000000,
                  alreadyPresent: false,
                },
                {
                  id: "missing",
                  title: "Renamed release",
                  torrentHash: "c".repeat(40),
                  addedAt: 1700000000,
                  alreadyPresent: false,
                },
                {
                  id: "ambiguous",
                  title: "Duplicate release",
                  addedAt: 1700000000,
                  alreadyPresent: false,
                },
              ],
            },
          ],
        },
      },
    }),
  );
  await page.goto("/apps/seedbox?section=torrents");
  const feed = page.getByRole("region", { name: "Dansk TV" });
  await feed
    .getByText("Automatic download history (4)", { exact: true })
    .click();
  const rows = feed.locator(".rss-download-history li");
  const first = rows.nth(0);
  await expect(first.locator(".rss-history-state")).toHaveText(
    "Seeding · 100%",
  );
  await expect(
    first
      .locator(".rss-history-stats > div")
      .filter({ has: page.locator("dt", { hasText: "Share ratio" }) })
      .locator("dd"),
  ).toHaveText("1.50");
  await expect(first).toContainText("3.0 GiB");
  await expect(first).toContainText("1d 1h");
  await expect(first).toContainText("2.0 KiB/s");
  await expect(first).toContainText("2 / 3");
  await expect(rows.nth(1).locator(".rss-history-state")).toHaveText(
    "Downloading · 25%",
  );
  await expect(rows.nth(2)).toContainText("Statistics unavailable");
  await expect(rows.nth(3)).toContainText("Statistics unavailable");
  uploaded = 4 * 1024 ** 3;
  await page.clock.runFor(5500);
  await expect(first).toContainText("4.0 GiB");
  await expect(
    first
      .locator(".rss-history-stats > div")
      .filter({ has: page.locator("dt", { hasText: "Share ratio" }) })
      .locator("dd"),
  ).toHaveText("2.00");

  await page.getByRole("button", { name: "Customize layout" }).click();
  await page
    .locator(
      '.layout-item[data-layout-title="Your feeds"] .layout-width select',
    )
    .selectOption("33");
  await page.getByRole("button", { name: "Done arranging" }).click();
  await expect(first.locator(".rss-history-stats")).toBeVisible();
  expect(
    await feed.evaluate((node) => node.scrollWidth <= node.clientWidth + 1),
  ).toBe(true);
  await feed.screenshot({
    path: "../.qa/rss-history-stats.png",
    animations: "disabled",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(first.locator(".rss-history-stats")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(
    await feed.evaluate((node) => node.scrollWidth <= node.clientWidth + 1),
  ).toBe(true);
  await feed.getByLabel("Search automatic download history").fill("Legacy");
  await expect(rows).toHaveCount(1);
  await expect(rows.first().locator(".rss-history-state")).toHaveText(
    "Downloading · 25%",
  );
  await feed.getByLabel("Search automatic download history").fill("");
  await feed.screenshot({
    path: "../.qa/rss-history-stats-mobile.png",
    animations: "disabled",
  });
  unavailable = true;
  await page.clock.runFor(5500);
  await expect(feed.locator(".rss-history-stats")).toHaveCount(0);
  await expect(rows.nth(0)).toContainText("Statistics unavailable");
  unavailable = false;
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        data: {
          id: "layout-qa",
          username: "qa",
          role: "admin",
          csrf: "qa",
          language: "da",
        },
      },
    }),
  );
  await page.reload();
  await feed.locator("details").first().locator("summary").click();
  await expect(first).toContainText("Uploadet");
  await expect(first).toContainText("Delingsratio");
  await expect(first).toContainText("2,00");
  await expect(feed).toContainText("én hel kopi uploadet");
  await expect(rows.nth(2)).toContainText("Statistik utilgængelig");
  expect(errors).toEqual([]);
});

test("all layout cards resize without a column prerequisite and keep their content contained", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  for (const path of [
    "/",
    "/apps/seedbox?section=vpn",
    "/apps/seedbox?section=torrents",
    "/apps/seedbox?section=settings",
    "/apps",
    "/store",
    "/storage",
    "/hosts",
    "/integrations",
    "/activity",
    "/logs",
    "/updates",
    "/backups",
    "/settings",
    "/settings#Maintenance",
    "/settings#Storage",
    "/settings#Network",
    "/settings#Agent",
    "/settings#Security",
    "/settings#Advanced",
  ]) {
    await page.goto(path);
    if (path.includes("#"))
      await page
        .getByRole("tab", { name: path.split("#")[1], exact: true })
        .click();
    await expect(page.locator(".layout-item:visible").first()).toBeVisible();
    const customize = page.getByRole("button", { name: "Customize layout" });
    if (await customize.count()) await customize.click();
    await expect(
      page.getByRole("button", { name: "Done arranging" }),
      path,
    ).toBeVisible();
    const fixedPanels = await page
      .locator("main .panel")
      .evaluateAll((nodes) =>
        nodes
          .filter(
            (node) =>
              !node.closest(".layout-item") &&
              node.getBoundingClientRect().height > 0 &&
              !node.classList.contains("app-skeleton"),
          )
          .map(
            (node) => node.querySelector("h2")?.textContent || node.className,
          ),
      );
    expect.soft(fixedPanels, `${path}: cards outside layout`).toEqual([]);
    const technicalStorage = page.locator(
      "details.technical-disclosure > summary",
    );
    if (await technicalStorage.count()) await technicalStorage.click();
    await expect(page.getByLabel("Columns", { exact: true })).toHaveValue("0");
    const cards = page.locator(".layout-item.is-arranging");
    const count = await cards.count();
    expect(await page.locator(".layout-width select").count(), path).toBe(
      count,
    );
    for (let index = 0; index < count; index++) {
      const card = cards.nth(index);
      await card
        .locator(":scope > .layout-item-tools .layout-width select")
        .selectOption("33");
      const ratio = await card.evaluate(
        (node) =>
          node.getBoundingClientRect().width /
          node.parentElement!.getBoundingClientRect().width,
      );
      expect(
        ratio,
        `${path}: ${await card.getAttribute("data-layout-title")}`,
      ).toBeGreaterThan(0.29);
      expect(ratio, path).toBeLessThan(0.35);
      const overflowing = await card.evaluate((node) =>
        [
          ...node.querySelectorAll<HTMLElement>(
            ".panel, .phase-content, .security-card, .seedbox-client-summary",
          ),
        ]
          .filter(
            (content) =>
              content.clientWidth > 0 &&
              content.scrollWidth > content.clientWidth + 1,
          )
          .map(
            (content) =>
              `${node.getAttribute("data-layout-title")}: ${content.className}: ${content.clientWidth}/${content.scrollWidth}: ${[...content.children].map((child) => `${child.className}=${child.getBoundingClientRect().width}`).join(",")}`,
          ),
      );
      expect(overflowing, path).toEqual([]);
      const resizeHandle = card.locator(":scope > .resize-bottom");
      await resizeHandle.focus();
      await resizeHandle.press("ArrowDown");
      const dimensions = await card.evaluate((node) => {
        const content = node.querySelector<HTMLElement>(
          ":scope > .layout-item-content > *",
        )!;
        return {
          card: node.getBoundingClientRect().height,
          content: content.getBoundingClientRect().height,
        };
      });
      expect(
        dimensions.content,
        `${path}: resized border follows content`,
      ).toBeCloseTo(dimensions.card, 0);
      await card
        .locator(":scope > .layout-item-tools button")
        .filter({ has: page.locator("svg.lucide-rotate-ccw") })
        .click();
    }
    for (const group of await page.locator(".layout-group").all()) {
      // A dashboard section containing its own grid is a fixed container, not a draggable card.
      if (await group.locator(":scope > .layout-item:not(.is-arranging)").count()) continue;
      const groupCards = group.locator(":scope > .layout-item");
      if ((await groupCards.count()) < 2) continue;
      const keys = await groupCards.evaluateAll((nodes) =>
        nodes.map((node) => node.getAttribute("data-layout-item")!),
      );
      for (const key of keys.reverse()) {
        const move = group.locator(
          `:scope > .layout-item[data-layout-item="${key}"] > .layout-drag-surface`,
        );
        const index = await groupCards.evaluateAll(
          (nodes, key) =>
            nodes.findIndex(
              (node) => node.getAttribute("data-layout-item") === key,
            ),
          key,
        );
        for (let step = index; step > 0; step--) await move.press("ArrowUp");
        await expect(
          groupCards.first(),
          `${path}: ${key} can reach the first position`,
        ).toHaveAttribute("data-layout-item", key);
      }
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      path,
    ).toBe(true);
  }
  expect(errors).toEqual([]);
});

test("VPN width changes persist and content follows the card instead of the viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/apps/seedbox?section=vpn");
  await expect(
    page.getByRole("heading", { name: "VPN Location", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Customize layout" }).click();
  const vpn = page.locator('.layout-item[data-layout-title="VPN Location"]');
  const width = vpn.locator(".layout-width select");
  const originalWidth = (await vpn.boundingBox())!.width;
  await width.selectOption("33");
  expect((await vpn.boundingBox())!.width).toBeLessThan(originalWidth * 0.35);
  // Page columns affect default card widths; an explicit width works independently.
  await page.getByLabel("Columns", { exact: true }).selectOption("1");
  expect((await vpn.boundingBox())!.width).toBeLessThan(originalWidth * 0.35);
  await page.getByRole("button", { name: "Done arranging" }).click();
  await expect(
    page.getByRole("combobox", { name: "Country", exact: true }),
  ).toBeEnabled();
  expect(
    await vpn
      .locator(".panel")
      .evaluate((node) => node.scrollWidth <= node.clientWidth),
  ).toBe(true);
  await page.reload();
  await page.getByRole("button", { name: "Customize layout" }).click();
  await expect(width).toHaveValue("33");
  await page.screenshot({
    path: "../.qa/vpn-width-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  await width.selectOption("100");
  expect((await vpn.boundingBox())!.width).toBeGreaterThan(
    originalWidth * 0.98,
  );
  await width.selectOption("25");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(async () => {
      const box = (await page.locator(".sidebar").boundingBox())!;
      return box.x + box.width;
    })
    .toBeLessThanOrEqual(1);
  expect(
    await vpn.evaluate(
      (node) =>
        node.getBoundingClientRect().width /
        node.parentElement!.getBoundingClientRect().width,
    ),
  ).toBeGreaterThan(0.98);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../.qa/vpn-width-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "Reset this page" }).click();
  await expect(width).toHaveValue("-1");
  expect((await vpn.boundingBox())!.width).toBeGreaterThan(
    originalWidth * 0.98,
  );
});

test("whole cards move, hide, restore and persist without extra heading rows", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1200 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Ongoing torrents" }),
  ).toBeVisible();
  await expect(page.locator(".dashboard-torrent")).toHaveCount(2);
  await expect(page.getByText("Paused torrent", { exact: true })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Customize layout" }).click();
  const cards = page.locator(".dashboard-grid > .layout-item");
  const before = await cards.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-layout-title")),
  );
  const torrents = page.locator(
    '.layout-item[data-layout-title="Ongoing torrents"]',
  );
  const surface = torrents.locator(".layout-drag-surface");
  // Keep both cards on screen: dragTo scrolling after pointer-down can change
  // the element beneath the pointer before Chromium starts the native drag.
  await cards
    .first()
    .evaluate((node) => node.scrollIntoView({ block: "start" }));
  const cardBox = (await torrents.boundingBox())!;
  const dragBox = (await surface.boundingBox())!;
  expect(Math.abs(cardBox.height - dragBox.height)).toBeLessThan(2);
  const toolsBox = (await torrents
    .locator(".layout-item-tools")
    .boundingBox())!;
  expect(toolsBox.y).toBeGreaterThan(cardBox.y);
  expect(toolsBox.y + toolsBox.height).toBeLessThan(cardBox.y + cardBox.height);
  // Dropping on a nested service surface also reaches the enclosing Apps card.
  const targetBox = (await cards
    .first()
    .locator(".layout-drag-surface")
    .last()
    .boundingBox())!;
  await page.mouse.move(dragBox.x + 100, dragBox.y + cardBox.height - 30);
  await page.mouse.down();
  await page.mouse.move(targetBox.x + 100, targetBox.y + 80, { steps: 8 });
  await page.mouse.up();
  await expect(cards.first()).toHaveAttribute(
    "data-layout-title",
    "Ongoing torrents",
  );
  const placedPosition = await torrents.evaluate((node) => ({
    column: getComputedStyle(node).gridColumnStart,
    row: getComputedStyle(node).gridRowStart,
  }));
  await torrents.getByRole("button", { name: "Hide Ongoing torrents" }).click();
  await expect(torrents).toHaveCount(0);
  await page.getByText("Choose cards", { exact: true }).click();
  await page.getByLabel("Ongoing torrents", { exact: true }).check();
  await expect(torrents).toBeVisible();
  await page.getByLabel("Recent activity", { exact: true }).check();
  await expect(
    page.locator("h2").filter({ hasText: /^Recent activity$/ }),
  ).toBeVisible();
  await page.getByText("Choose cards", { exact: true }).click();
  await page.getByRole("button", { name: "Done arranging" }).click();
  await page.reload();
  expect(
    await torrents.evaluate((node) => ({
      column: getComputedStyle(node).gridColumnStart,
      row: getComputedStyle(node).gridRowStart,
    })),
  ).toEqual(placedPosition);
  await expect(
    page.locator("h2").filter({ hasText: /^Recent activity$/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Customize layout" }).click();
  await page.getByLabel("Columns", { exact: true }).selectOption("3");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(torrents).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await expect
    .poll(async () => {
      const box = (await page.locator(".sidebar").boundingBox())!;
      return box.x + box.width;
    })
    .toBeLessThanOrEqual(1);
  await page.screenshot({
    path: "../.qa/layout-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: "../.qa/layout-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Reset this page" }).click();
  await expect(cards).toHaveCount(before.length);
  await expect(cards.first()).toHaveAttribute("data-layout-title", before[0]!);
  expect(errors).toEqual([]);
});

test("runtime headings stay above VPN cards and nested pages have no enclosing draggable card", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/apps/seedbox?section=vpn");
  await expect(
    page.getByRole("heading", { name: "VPN Location", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Customize layout" }).click();
  const heading = page.getByRole("heading", { name: "Seedbox", exact: true });
  expect(await heading.evaluate((node) => !!node.closest(".layout-item"))).toBe(
    false,
  );
  const summary = (await heading.boundingBox())!;
  const vpn = page.locator('.layout-item[data-layout-title="VPN Location"]');
  expect((await vpn.boundingBox())!.y).toBeGreaterThan(summary.y);
  await vpn.getByRole("button", { name: "Hide VPN Location" }).click();
  await page.getByText("Choose cards", { exact: true }).click();
  await page.getByLabel("VPN Location", { exact: true }).check();
  await page.getByText("Choose cards", { exact: true }).click();
  await page.getByRole("button", { name: "Done arranging" }).click();
  await expect(
    page.getByRole("combobox", { name: "Country", exact: true }),
  ).toBeEnabled();
  await page.goto("/apps/seedbox?section=torrents");
  await expect(
    page.getByRole("heading", { name: "Torrents", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Customize layout" }).click();
  await expect(page.locator(".layout-item .layout-item")).toHaveCount(0);
  const torrentCard = page.locator(
    '.layout-item[data-layout-title="Torrents"]',
  );
  await torrentCard
    .getByRole("button", { name: "Move Torrents later" })
    .click();
  const torrentOrder = await page
    .locator(".torrent-panels > .layout-item")
    .evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("data-layout-title")),
    );
  expect(torrentOrder.indexOf("Your feeds")).toBeLessThan(
    torrentOrder.indexOf("Torrents"),
  );
  await expect(
    page.getByRole("heading", { name: "Seedbox", exact: true }),
  ).toBeVisible();
  for (const path of [
    "/apps",
    "/hosts",
    "/integrations",
    "/activity",
    "/logs",
    "/settings",
  ]) {
    await page.goto(path);
    await page.getByRole("button", { name: "Customize layout" }).click();
    await expect(page.locator(".layout-drag-surface").first()).toBeVisible();
    await expect(page.locator(".layout-item .layout-item")).toHaveCount(0);
    await page.setViewportSize({ width: 390, height: 844 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.setViewportSize({ width: 1440, height: 1000 });
  }
  expect(errors).toEqual([]);
});

test("single cards occupy empty grid columns and retain placement after reload", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/settings#Agent");
  await page.getByRole("button", { name: "Customize layout" }).click();
  const card = page.locator(".layout-item").first();
  await card.locator(".layout-width select").selectOption("33");
  const group = card.locator("..");
  async function placeAt(column: number) {
    const box = (await card.boundingBox())!;
    const grid = (await group.boundingBox())!;
    await page.mouse.move(box.x + 80, box.y + 50);
    await page.mouse.down();
    await page.mouse.move(
      grid.x + ((column - 1) * (grid.width + 16)) / 12 + 80,
      box.y + 50,
      { steps: 8 },
    );
    await page.mouse.up();
    await expect
      .poll(() =>
        card.evaluate((node) => getComputedStyle(node).gridColumnStart),
      )
      .toBe(String(column));
  }
  await placeAt(5);
  await placeAt(9);
  await page.getByRole("button", { name: "Done arranging" }).click();
  await page.reload();
  await expect
    .poll(() => card.evaluate((node) => getComputedStyle(node).gridColumnStart))
    .toBe("9");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "Customize layout" }).click();
  await placeAt(1);
});

test("held cards permit wheel scrolling, retain content and cancel without saving", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 700 });
  await page.goto("/apps/seedbox?section=torrents");
  await page.getByRole("button", { name: "Customize layout" }).click();
  const card = page.locator(".layout-item").first();
  await card.scrollIntoViewIfNeeded();
  const before = await page.evaluate(() => JSON.stringify(localStorage));
  const box = (await card.boundingBox())!;
  await page.mouse.move(box.x + 60, Math.max(120, box.y + 60));
  await page.mouse.down();
  await page.mouse.move(box.x + 80, 300, { steps: 8 });
  await expect(card).toHaveClass(/is-pointer-dragging/);
  const y = await page.evaluate(() => scrollY);
  await page.mouse.wheel(0, 300);
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(y);
  await expect(card.locator(".layout-item-content")).toBeVisible();
  const wheelY = await page.evaluate(() => scrollY);
  await page.mouse.move(box.x + 80, 695, { steps: 4 });
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(wheelY);
  await page.keyboard.press("Escape");
  await page.mouse.up();
  await expect(card).not.toHaveClass(/is-pointer-dragging/);
  expect(await page.evaluate(() => JSON.stringify(localStorage))).toBe(before);
});

test("positioned cards resize without overlapping their neighbours and keep panel borders aligned", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1400 });
  await page.goto("/apps/seedbox?section=vpn");
  await page.getByRole("button", { name: "Customize layout" }).click();
  const card = page.locator('.layout-item[data-layout-title="VPN Location"]');
  await card.locator(".layout-width select").selectOption("33");
  const group = card.locator("..");
  const box = (await card.boundingBox())!;
  const grid = (await group.boundingBox())!;
  await page.mouse.move(box.x + 80, box.y + 50);
  await page.mouse.down();
  await page.mouse.move(grid.x + 80, grid.y + 50, { steps: 8 });
  await page.mouse.up();
  await card.locator(".layout-width select").selectOption("100");
  await expect
    .poll(() => card.evaluate((node) => getComputedStyle(node).gridColumnStart))
    .toBe("1");
  await expect
    .poll(async () => {
      const selected = (await card.boundingBox())!;
      const others = await group
        .locator(":scope > .layout-item")
        .evaluateAll((nodes) =>
          nodes.map((node) => ({
            title: (node as HTMLElement).dataset.layoutTitle,
            top: node.getBoundingClientRect().top,
            bottom: node.getBoundingClientRect().bottom,
          })),
        );
      return others.every(
        (other) =>
          other.title === "VPN Location" ||
          other.bottom <= selected.y ||
          other.top >= selected.y + selected.height,
      );
    })
    .toBe(true);
  const handle = card.locator(".resize-bottom");
  await handle.scrollIntoViewIfNeeded();
  const edge = (await handle.boundingBox())!;
  await page.mouse.move(edge.x + edge.width / 2, edge.y + edge.height / 2);
  await page.mouse.down();
  await page.mouse.move(
    edge.x + edge.width / 2,
    edge.y + edge.height / 2 - 120,
    { steps: 8 },
  );
  await page.mouse.up();
  const panel = (await card.locator(".panel").first().boundingBox())!;
  expect(
    Math.abs(panel.height - (await card.boundingBox())!.height),
  ).toBeLessThan(2);
  await page.screenshot({
    path: "../.qa/free-grid-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Done arranging" }).click();
  await page.reload();
  expect(
    (await card.boundingBox())!.width / (await group.boundingBox())!.width,
  ).toBeGreaterThan(0.98);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page
        .locator("aside.sidebar")
        .evaluate((node) => node.getBoundingClientRect().right),
    )
    .toBeLessThanOrEqual(1);
  await page.screenshot({
    path: "../.qa/free-grid-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});

test("three RSS cards retain matching borders through edit mode with long feed content and saved sizes", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.route("**/api/v1/seedbox/rss/feeds", (route) =>
    route.fulfill({
      json: {
        data: {
          intervalSeconds: 60,
          feeds: Array.from({ length: 10 }, (_, i) => ({
            id: `feed-${i}`,
            name: `Test feed ${i}`,
            automatic: true,
            storageId: "downloads",
            downloadLocationId: "root",
            checkedAt: 1700000000,
            error: "",
            added: 10,
            pending: 0,
            baselineCount: 0,
            items: [],
            automaticHistory: [],
          })),
        },
      },
    }),
  );
  await page.goto("/apps/seedbox?section=torrents");
  await page.getByRole("button", { name: "Customize layout" }).click();
  const titles = ["Add Torrent", "Add feed", "Your feeds"];
  for (const title of titles)
    await page
      .locator(
        `.layout-item[data-layout-title="${title}"] .layout-width select`,
      )
      .selectOption("33");
  // Match saved custom heights from older layout versions rather than starting only with auto height.
  for (const title of titles) {
    const card = page.locator(`.layout-item[data-layout-title="${title}"]`);
    const handle = card.locator(".resize-bottom");
    await handle.focus();
    await handle.press("ArrowDown");
  }
  const group = page.locator(".torrent-panels");
  const feed = page.locator('.layout-item[data-layout-title="Your feeds"]');
  await expect(feed.locator(".rss-feed-card")).toHaveCount(10);
  async function aligned() {
    for (const title of titles) {
      const card = page.locator(`.layout-item[data-layout-title="${title}"]`);
      const dimensions = await card.evaluate((node) => {
        const border = node
          .querySelector(":scope > .layout-item-content > .panel")!
          .getBoundingClientRect();
        const outer = node.getBoundingClientRect();
        return {
          height: outer.height,
          borderHeight: border.height,
          width: outer.width,
          borderWidth: border.width,
        };
      });
      expect(dimensions.borderHeight, title).toBeCloseTo(dimensions.height, 0);
      expect(dimensions.borderWidth, title).toBeCloseTo(dimensions.width, 0);
    }
  }
  await aligned();
  await page.getByRole("button", { name: "Done arranging" }).click();
  await aligned();
  await page.reload();
  await aligned();
  await page.getByRole("button", { name: "Customize layout" }).click();
  await aligned();
  await group.screenshot({
    path: "../.qa/rss-three-cards-checked.png",
    animations: "disabled",
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page
    .locator('.layout-item[data-layout-title="Add feed"] .layout-drag-surface')
    .focus();
  await page.keyboard.press("Alt+ArrowRight");
  await aligned();
  for (const title of titles) {
    await page
      .locator(`.layout-item[data-layout-title="${title}"]`)
      .getByRole("button", { name: "Restore automatic height" })
      .click();
  }
  await aligned();
  await page.getByRole("button", { name: "Done arranging" }).click();
  await aligned();
  expect(errors).toEqual([]);
});

test("Danish maintenance cards translate dynamic health messages", async ({
  page,
}) => {
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        data: {
          id: "layout-qa",
          username: "qa",
          role: "admin",
          csrf: "qa",
          language: "da",
        },
      },
    }),
  );
  await page.route("**/api/v1/health", (route) =>
    route.fulfill({ json: { data: { status: "healthy", version: "0.4.29" } } }),
  );
  await page.route("**/api/v1/runtime", (route) =>
    route.fulfill({
      json: { data: { connected: true, hostname: "mediahub" } },
    }),
  );
  await page.route("**/api/v1/storage/locations", (route) =>
    route.fulfill({
      json: { data: [{ id: "qa", name: "QA", exists: true, readable: true }] },
    }),
  );
  await page.goto("/settings");
  await page.getByRole("tab", { name: "Vedligeholdelse", exact: true }).click();
  const cards = page.locator(".maintenance-card");
  await expect(
    cards.getByText("Version 0.4.29 svarer.", { exact: true }),
  ).toBeVisible();
  await expect(
    cards.getByText("mediahub er tilsluttet.", { exact: true }),
  ).toBeVisible();
  await expect(
    cards.getByText("1 af 1 placeringer er tilg?ngelige.", { exact: true }),
  ).toBeVisible();
  await expect(
    cards.getByText("1 app er sund.", { exact: true }),
  ).toBeVisible();
});

for (const width of [1440, 1366, 390]) {
  test(`dashboard edit toggles preserve original and saved geometry (${width}px)`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/");
    await expect(page.locator(".dashboard-torrent")).toHaveCount(2);
    async function geometry() {
      return page.locator("main .layout-item").evaluateAll(async (nodes) => {
        await new Promise(requestAnimationFrame);
        await new Promise(requestAnimationFrame);
        const origin = document
          .querySelector("main .layout-group")!
          .getBoundingClientRect();
        return nodes
          .filter((node) => node.getBoundingClientRect().height > 0)
          .map((node) => {
            const rect = node.getBoundingClientRect();
            return {
              id: node.getAttribute("data-layout-item"),
              x: rect.left - origin.left,
              y: rect.top - origin.top,
              width: rect.width,
              height: rect.height,
            };
          });
      });
    }
    async function unchanged(expected: Awaited<ReturnType<typeof geometry>>) {
      await expect
        .poll(async () => {
          const actual = await geometry();
          return (
            actual.length === expected.length &&
            actual.every(
              (card, index) =>
                card.id === expected[index].id &&
                (["x", "y", "width", "height"] as const).every(
                  (key) => Math.abs(card[key] - expected[index][key]) < 0.5,
                ),
            )
          );
        })
        .toBe(true);
    }
    const original = await geometry();
    await page.getByRole("button", { name: "Customize layout" }).click();
    await unchanged(original);
    const originalEdges = await page
      .locator(".layout-group")
      .evaluateAll((groups) =>
        groups.flatMap((group) => {
          const guides = [
            ...group.querySelectorAll<HTMLElement>(
              ":scope > .layout-grid-guides > span",
            ),
          ]
            .filter((node) => node.getBoundingClientRect().width > 0)
            .map((node) => node.getBoundingClientRect());
          return [...group.querySelectorAll(":scope > .layout-item")]
            .filter((node) => {
              const rect = node.getBoundingClientRect();
              return (
                !guides.some(
                  (guide) => Math.abs(guide.left - rect.left) < 0.5,
                ) ||
                !guides.some(
                  (guide) => Math.abs(guide.right - rect.right) < 0.5,
                )
              );
            })
            .map((node) => node.getAttribute("data-layout-title"));
        }),
      );
    expect(originalEdges).toEqual([]);
    await page.getByRole("button", { name: "Done arranging" }).click();
    await unchanged(original);
    await page.getByRole("button", { name: "Customize layout" }).click();
    await page.getByLabel("Columns", { exact: true }).selectOption("3");
    const first = page.locator(".layout-item.is-arranging").first();
    await first
      .locator(":scope > .layout-item-tools .layout-width select")
      .selectOption("50");
    await first.locator(":scope > .resize-bottom").press("ArrowDown");
    if (width > 760) {
      await first.locator(":scope > .layout-drag-surface").press("Alt+ArrowRight");
      await expect(first).toHaveAttribute("data-layout-positioned", "true");
    }
    if (width === 390) {
      const handle = first.locator(":scope > .resize-bottom");
      await handle.scrollIntoViewIfNeeded();
      const before = (await first.boundingBox())!.height;
      const box = (await handle.boundingBox())!;
      const touch = await page.context().newCDPSession(page);
      const x = box.x + box.width / 2;
      const y = box.y + box.height / 2;
      await touch.send("Input.dispatchTouchEvent", {
        type: "touchStart",
        touchPoints: [{ x, y }],
      });
      await touch.send("Input.dispatchTouchEvent", {
        type: "touchMove",
        touchPoints: [{ x, y: y + 72 }],
      });
      await touch.send("Input.dispatchTouchEvent", {
        type: "touchEnd",
        touchPoints: [],
      });
      await touch.detach();
      await expect
        .poll(async () => (await first.boundingBox())!.height)
        .toBe(before + 72);
    }
    const saved = await geometry();
    const misaligned = await page
      .locator(".layout-group.layout-custom-grid")
      .evaluateAll((groups) =>
        groups.flatMap((group) => {
          const guides = [
            ...group.querySelectorAll<HTMLElement>(
              ":scope > .layout-grid-guides > span",
            ),
          ]
            .filter((node) => node.getBoundingClientRect().width > 0)
            .map((node) => node.getBoundingClientRect());
          return [...group.querySelectorAll(":scope > .layout-item")]
            .filter((node) => {
              const rect = node.getBoundingClientRect();
              return (
                !guides.some(
                  (guide) => Math.abs(guide.left - rect.left) < 0.5,
                ) ||
                !guides.some(
                  (guide) => Math.abs(guide.right - rect.right) < 0.5,
                )
              );
            })
            .map((node) => node.getAttribute("data-layout-title"));
        }),
      );
    expect(misaligned).toEqual([]);
    await page.getByRole("button", { name: "Done arranging" }).click();
    await unchanged(saved);
    await page.reload();
    await expect(page.locator(".dashboard-torrent")).toHaveCount(2);
    await unchanged(saved);
    await page.getByRole("button", { name: "Customize layout" }).click();
    await unchanged(saved);
    await page.getByRole("button", { name: "Done arranging" }).click();
    await unchanged(saved);
    await page.getByRole("button", { name: "Customize layout" }).click();
    await page.getByRole("button", { name: "Reset this page" }).click();
    await unchanged(original);
    await page.getByRole("button", { name: "Done arranging" }).click();
    await unchanged(original);
    expect(errors).toEqual([]);
  });
}

test("Choose cards retains scroll, label order and checkbox focus after visibility updates", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 260 });
  await page.goto("/");
  await expect(page.locator(".layout-item").first()).toBeVisible();
  await page.getByRole("button", { name: "Customize layout" }).click();
  await page.getByText("Choose cards", { exact: true }).click();
  const menu = page.locator(".layout-card-picker > div");
  expect(await menu.locator("input").count()).toBeGreaterThan(5);
  const state = await menu.evaluate((node) => {
    node.scrollTop = Math.min(70, node.scrollHeight - node.clientHeight);
    const rect = node.getBoundingClientRect();
    const input = [...node.querySelectorAll<HTMLInputElement>("input")].find(
      (input) => {
        const box = input.getBoundingClientRect();
        return box.top > rect.top + 8 && box.bottom < rect.bottom - 8;
      },
    )!;
    input.focus({ preventScroll: true });
    return {
      top: node.scrollTop,
      labels: [...node.querySelectorAll("label")].map(
        (label) => label.textContent,
      ),
      index: [...node.querySelectorAll("input")].indexOf(input),
    };
  });
  expect(state.top).toBeGreaterThan(0);
  const checkbox = menu.locator("input").nth(state.index);
  await checkbox.click();
  expect(await menu.evaluate((node) => node.scrollTop)).toBe(state.top);
  expect(await menu.locator("label").allTextContents()).toEqual(state.labels);
  await expect(checkbox).toBeFocused();
  await checkbox.press("Space");
  expect(await menu.evaluate((node) => node.scrollTop)).toBe(state.top);
  await expect(checkbox).toBeFocused();
});

test("asynchronous FjordFlix cards retain geometry and picker identity through editing", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.addInitScript(() => {
    document.addEventListener("DOMContentLoaded", () => {
      document.documentElement.style.zoom = "0.9";
    });
  });
  let release!: () => void;
  const ready = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/integrations", async (route) => {
    await ready;
    await route.fulfill({
      json: {
        data: [
          {
            id: "layout-fixture",
            name: "Local fixture",
            baseUrl: "https://fixture.invalid",
            enabled: true,
            tokenConfigured: true,
            snapshot: {
              status: "online",
              stale: false,
              apps: [],
              fjordflix: {
                ok: true,
                library_count: 10,
                items: Array.from({ length: 10 }, (_, i) => ({
                  id: String(i),
                  title: "Long title and description ".repeat(12),
                  overview: "Long description ".repeat(30),
                  genres: ["Drama"],
                })),
                streams: [
                  {
                    id: "stream",
                    title: "A long playing title ".repeat(30),
                    user: "Synthetic viewer",
                    state: "playing",
                    mode: "Direct Play",
                  },
                ],
              },
            },
          },
        ],
      },
    });
  });
  await page.goto("/");
  await expect(page.locator(".dashboard-torrent")).toHaveCount(2);
  await expect(page.locator(".fjordflix-service-tile")).toHaveCount(0);
  await page.getByRole("button", { name: "Customize layout" }).click();
  await page.getByText("Choose cards", { exact: true }).click();
  const menu = page.locator(".layout-card-picker > div");
  const first = menu.locator("input").first();
  await first.focus();
  const labels = await menu.locator("label").allTextContents();
  release();
  await expect(page.locator(".fjordflix-service-tile")).toBeVisible();
  await expect(first).toBeFocused();
  const after = await menu.locator("label").allTextContents();
  expect(after.filter((title) => labels.includes(title))).toEqual(labels);
  await page.getByText("Choose cards", { exact: true }).click();
  async function rects() {
    return page.locator("main .layout-item").evaluateAll(async (nodes) => {
      await new Promise(requestAnimationFrame);
      await new Promise(requestAnimationFrame);
      const origin = document
        .querySelector("main .layout-group")!
        .getBoundingClientRect();
      return nodes.map((node) => {
        const box = node.getBoundingClientRect();
        return [
          box.left - origin.left,
          box.top - origin.top,
          box.width,
          box.height,
        ];
      });
    });
  }
  const editing = await rects();
  await page.getByRole("button", { name: "Done arranging" }).click();
  const viewing = await rects();
  expect(viewing).toHaveLength(editing.length);
  for (let i = 0; i < editing.length; i++)
    for (let j = 0; j < 4; j++)
      expect(viewing[i][j]).toBeCloseTo(editing[i][j], 0);
  await page.getByRole("button", { name: "Customize layout" }).click();
  const reentered = await rects();
  for (let i = 0; i < editing.length; i++)
    for (let j = 0; j < 4; j++)
      expect(reentered[i][j]).toBeCloseTo(editing[i][j], 0);
});
