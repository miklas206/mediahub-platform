import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import type { AppInfo, Metrics, Storage } from "../src/contracts";
import type { Torrent } from "../src/torrent-list";
import type { RetentionRule } from "../src/torrent-retention";
import danish from "../src/locales/da.json" with { type: "json" };

// These examples use isolated browser fixtures; production never receives demo data.
const gib = 1024 ** 3;
const mib = 1024 ** 2;
const examples = "../.qa/redesign";
const designAppLists = new WeakMap<Page, AppInfo[]>();
const designTorrentLists = new WeakMap<Page, Torrent[]>();
const translated = (source: string, values: Record<string, string> = {}) =>
  (danish[source as keyof typeof danish] || source).replace(
    /\{(\w+)\}/g,
    (placeholder, key: string) => values[key] ?? placeholder,
  );

// Original abstract poster illustrations, used only by these isolated preview fixtures.
const posterExamples = [
  { id: "101", title: "Solstice", colors: ["#271a58", "#fa9363", "#b82a7d"] },
  { id: "102", title: "Orbital", colors: ["#082044", "#39b8f7", "#274ec5"] },
  { id: "103", title: "North", colors: ["#161a46", "#b18cfb", "#6650d0"] },
  { id: "104", title: "Deep Blue", colors: ["#081524", "#518ba8", "#154167"] },
  { id: "105", title: "Horizon", colors: ["#163239", "#91d4bc", "#2c767d"] },
  { id: "106", title: "Afterlight", colors: ["#2c142a", "#e09b78", "#70477c"] },
  { id: "107", title: "Nightfall", colors: ["#151b3c", "#728bde", "#384584"] },
  { id: "108", title: "Beyond", colors: ["#172a43", "#6ad7ec", "#416bb5"] },
];

function posterIllustration(index: number) {
  const { colors, title } = posterExamples[index];
  const scene =
    index % 4 === 0
      ? `<circle cx="80" cy="105" r="44" fill="url(#light)"/><path d="M0 159 42 132 82 162 126 140 160 157V240H0Z" fill="#162138"/><path d="m0 181 45-29 62 41 53-23v70H0Z" fill="#10172b"/>`
      : index % 4 === 1
        ? `<circle cx="159" cy="141" r="100" fill="url(#light)"/><circle cx="170" cy="128" r="90" fill="${colors[0]}"/><path d="M0 197c53-5 48-83 112-88-66 17-34 101-112 105Z" fill="${colors[1]}" opacity=".45"/>`
        : index % 4 === 2
          ? `<path d="m80 64 58 104H22Z" fill="url(#light)" opacity=".15"/><path d="m80 76 49 88H31Z" fill="none" stroke="${colors[1]}" stroke-width="2"/><path d="m80 104 22 42H58Z" fill="${colors[1]}" opacity=".35"/><path d="M0 206 47 169 90 187 126 173 160 198V240H0Z" fill="#10182f"/>`
          : `<path d="M0 116c57-47 71 48 160-4v128H0Z" fill="url(#light)"/><path d="M0 142c80 38 86-39 160 12v86H0Z" fill="${colors[2]}"/><path d="M0 190c73-62 81 17 160-22v72H0Z" fill="#101b31"/>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 240"><defs><linearGradient id="bg" x2="0" y2="1"><stop stop-color="${colors[0]}"/><stop offset="1" stop-color="#080e1d"/></linearGradient><linearGradient id="light" x2=".3" y2="1"><stop stop-color="${colors[1]}"/><stop offset="1" stop-color="${colors[2]}"/></linearGradient></defs><rect width="160" height="240" fill="url(#bg)"/>${scene}<text x="80" y="222" text-anchor="middle" fill="#e0e9fa" font-family="sans-serif" font-size="10" letter-spacing="2">${title.toUpperCase()}</text></svg>`;
}

async function designFixtures(page: Page) {
  const now = Date.now();
  const observedAt = now / 1000;
  const preferences: {
    language: "da" | "en";
    appearance: {
      accent: string;
      secondary: string;
      background: string;
      depth: number;
    } | null;
  } = { language: "da", appearance: null };
  const metrics: Metrics = {
    hostname: "mediahub-core",
    version: "0.4.29",
    timestamp: new Date(now).toISOString(),
    uptimeSeconds: 24 * 86400 + 6 * 3600,
    coreUptimeSeconds: 12 * 86400 + 7 * 3600,
    environment: "container",
    cpu: { percent: 18.4, cores: 8, scope: "container" },
    ram: {
      totalBytes: 16 * gib,
      usedBytes: 4.6 * gib,
      availableBytes: 11.4 * gib,
      cacheBytes: 1.2 * gib,
      percent: 28.8,
      scope: "container",
    },
    disk: {
      totalBytes: 64 * gib,
      usedBytes: 18 * gib,
      freeBytes: 46 * gib,
      percent: 28.1,
      scope: "container",
    },
    network: {
      downloadBytesPerSecond: 12.4 * mib,
      uploadBytesPerSecond: 3.2 * mib,
    },
  };
  const samples = Array.from({ length: 48 }, (_, i) => ({
    ...metrics,
    timestamp: new Date(now - (47 - i) * 5000).toISOString(),
    cpu: { ...metrics.cpu, percent: 16 + Math.sin(i * 0.42) * 5 + (i % 7) },
    ram: { ...metrics.ram, percent: 27.5 + Math.sin(i * 0.16) * 2 },
    network: {
      downloadBytesPerSecond: (8.5 + Math.sin(i * 0.5) * 3 + (i % 4)) * mib,
      uploadBytesPerSecond: (2.5 + Math.sin(i * 0.31) * 1.2) * mib,
    },
  }));
  samples[samples.length - 1] = metrics;
  await page.addInitScript((samples) => {
    class DesignEventSource {
      private timers: number[] = [];
      addEventListener(
        name: string,
        callback: (event: { data: string }) => void,
      ) {
        if (name !== "system.status") return;
        this.timers = samples.map((sample, index) =>
          window.setTimeout(
            () => {
              callback({ data: JSON.stringify(sample) });
              if (index === samples.length - 1)
                document.documentElement.dataset.designSamples = "ready";
            },
            200 + index * 25,
          ),
        );
      }
      close() {
        this.timers.forEach(window.clearTimeout);
      }
    }
    Object.defineProperty(window, "EventSource", { value: DesignEventSource });
  }, samples);

  const apps: AppInfo[] = [
    {
      id: "plex",
      name: "Plex",
      packageId: "org.mediahub.plex",
      version: "1.42.1",
    },
    {
      id: "seedbox",
      name: "Seedbox",
      packageId: "org.mediahub.seedbox",
      version: "0.1.0",
    },
    {
      id: "cloudflare",
      name: "Cloudflare Tunnel",
      packageId: "org.mediahub.cloudflared",
      version: "0.4.0",
    },
  ].map((app) => ({
    ...app,
    state: "running",
    isMock: false,
    detailPath: `/apps/${app.id}`,
    health: {
      status: "healthy",
      summary:
        app.id === "cloudflare"
          ? "Tunnel and configured public routes are reachable"
          : "Remote app: healthy",
      lastChecked: new Date(now).toISOString(),
      checks: [],
    },
  }));
  designAppLists.set(page, apps);
  const storage: Storage[] = [
    {
      id: "media",
      name: "Mediebibliotek",
      kind: "media",
      path: "/srv/media",
      exists: true,
      readable: true,
      writable: true,
      totalBytes: 8 * 1024 * gib,
      freeBytes: 4.8 * 1024 * gib,
      filesystem: "nfs4",
    },
    {
      id: "downloads",
      name: "Downloads",
      kind: "downloads",
      path: "/srv/media/downloads",
      exists: true,
      readable: true,
      writable: true,
      totalBytes: 8 * 1024 * gib,
      freeBytes: 4.8 * 1024 * gib,
      filesystem: "nfs4",
    },
  ];
  const torrents = [
    {
      hash: "a".repeat(40),
      name: "Ubuntu 24.04.3 Desktop amd64.iso",
      progress: 0.72,
      state: "downloading",
      dlspeed: 8.4 * mib,
      upspeed: 0.6 * mib,
      ratio: 0.28,
      eta: 720,
      size: 5.9 * gib,
      actionsAllowed: true,
      num_seeds: 42,
      num_leechs: 8,
    },
    {
      hash: "b".repeat(40),
      name: "Blender Open Movies · 4K Collection",
      progress: 0.36,
      state: "downloading",
      dlspeed: 4 * mib,
      upspeed: 0.4 * mib,
      ratio: 0.12,
      eta: 1680,
      size: 12 * gib,
      actionsAllowed: true,
      num_seeds: 21,
      num_leechs: 4,
    },
    {
      hash: "c".repeat(40),
      name: "Debian 13.0.0 amd64 netinst.iso",
      progress: 1,
      state: "uploading",
      dlspeed: 0,
      upspeed: 2.2 * mib,
      ratio: 2.4,
      eta: 8640000,
      size: 768 * mib,
      actionsAllowed: true,
      num_seeds: 18,
      num_leechs: 7,
      seeding_time: 72000,
    },
  ];
  designTorrentLists.set(page, torrents);
  const cloudflare = {
    configured: true,
    status: "healthy",
    checkedAt: observedAt,
    cached: false,
    metricsReachable: true,
    connections: 4,
    totalRequests: 68997,
    requestErrors: 0,
    version: "2026.9.1",
    message: "Tunnel and configured public routes are reachable",
    tunnelName: "Homelab",
    routeCount: 2,
    statusUrlConfigured: true,
    routes: ["media.example.test", "home.example.test"].map((hostname) => ({
      url: `https://${hostname}`,
      hostname,
      reachable: true,
      statusCode: 200,
      latencyMs: 32,
      message: "Route reached Cloudflare/origin",
    })),
  };
  const seedbox = {
    health: "healthy",
    available: true,
    observedAt,
    cached: false,
    agentOnline: true,
    dockerHealthy: true,
    checks: [],
    qBittorrent: {
      healthy: true,
      running: true,
      version: "5.1.2",
      apiAuthenticated: true,
      bindingVerified: true,
      namespaceVerified: true,
      downloadSpeed: 12.4 * mib,
      uploadSpeed: 3.2 * mib,
      torrents: 3,
      downloading: 2,
      seeding: 1,
      paused: 0,
      errors: 0,
    },
    vpn: {
      verified: true,
      externalIp: "198.51.100.24",
      provider: "ProtonVPN",
      protocol: "WireGuard",
      connectedSince: new Date(now - 3 * 86400000).toISOString(),
      lastVerified: observedAt,
      countryCode: "DK",
    },
    portForwarding: {
      status: "healthy",
      currentPort: 48124,
      lastRenewed: observedAt,
      expiresAt: observedAt + 3600,
      qBittorrentVerified: true,
      listenerVerified: true,
      listenerCheckSupported: true,
      lastError: null,
    },
    storage: {
      mounted: true,
      appWritable: true,
      source: "/srv/media",
      filesystem: "nfs4",
      totalBytes: 8 * 1024 * gib,
      usedBytes: 3.2 * 1024 * gib,
      freeBytes: 4.8 * 1024 * gib,
      verifiedAt: observedAt,
    },
    host: {
      cpuPercent: 14.2,
      cpuCores: 4,
      ramTotalBytes: 4 * gib,
      ramUsedBytes: 1.4 * gib,
      ramAvailableBytes: 2.6 * gib,
      uptimeSeconds: 24 * 86400,
    },
    control: {
      desiredRunning: true,
      manualIntervention: [],
      operation: { state: "idle", action: null },
      events: [],
    },
  };
  const activities = [
    {
      id: "1",
      source: "Seedbox",
      event: "torrent.completed",
      severity: "info",
      message: "Debian 13.0.0 er færdighentet og seeder.",
      timestamp: new Date(now - 8 * 60000).toISOString(),
    },
    {
      id: "2",
      source: "Plex",
      event: "app.health.changed",
      severity: "info",
      message: "Plex er online. Mediebiblioteket er klar.",
      timestamp: new Date(now - 22 * 60000).toISOString(),
    },
    {
      id: "3",
      source: "MediaHub",
      event: "backup.created",
      severity: "info",
      message: "Den automatiske sikkerhedskopi er fuldført.",
      timestamp: new Date(now - 57 * 60000).toISOString(),
    },
  ];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const posterIndex = posterExamples.findIndex(
      (poster) => path === `/apps/plex/plex/artwork/${poster.id}`,
    );
    if (posterIndex >= 0) {
      await route.fulfill({
        contentType: "image/svg+xml",
        body: posterIllustration(posterIndex),
      });
      return;
    }
    let data: unknown = [];
    if (path === "/auth/status") data = { needsSetup: false };
    if (path === "/setup/status") data = { setup_required: false };
    if (path === "/auth/me")
      data = {
        id: "design-example",
        username: "abekat",
        role: "admin",
        csrf: "design-example",
        ...preferences,
      };
    if (path === "/auth/preferences") {
      if (route.request().method() === "PUT") {
        const patch = route.request().postDataJSON() as Partial<
          typeof preferences
        >;
        if (patch.language === "da" || patch.language === "en") {
          preferences.language = patch.language;
        }
        if (Object.prototype.hasOwnProperty.call(patch, "appearance")) {
          preferences.appearance = patch.appearance ?? null;
        }
      }
      data = { ...preferences };
    }
    if (path === "/settings")
      data = {
        display_name: "MediaHub",
        theme: "dark",
        advanced_mode: false,
        activity_page_size: 25,
        release_repository: null,
        update_check_interval_hours: 24,
        visible_navigation: [
          "/",
          "/apps",
          "/store",
          "/storage",
          "/hosts",
          "/activity",
          "/updates",
          "/backups",
          "/integrations",
          "/settings",
        ],
        dashboard_sections: [
          "apps",
          "system",
          "storage",
          "torrents",
          "activity",
        ],
      };
    if (path === "/system/status") data = metrics;
    if (path === "/apps") data = apps;
    if (path === "/storage" || path === "/storage/locations") data = storage;
    if (/^\/storage\/locations\/[^/]+\/files$/.test(path))
      data = {
        location: storage[0],
        path: "/srv/media",
        parent: null,
        truncated: false,
        items: [
          {
            name: "Film",
            path: "/srv/media/Film",
            type: "folder",
            sizeBytes: 1.9 * 1024 * gib,
            sizeComplete: true,
            modifiedAt: observedAt - 3600,
          },
          {
            name: "Serier",
            path: "/srv/media/Serier",
            type: "folder",
            sizeBytes: 1.1 * 1024 * gib,
            sizeComplete: true,
            modifiedAt: observedAt - 7200,
          },
          {
            name: "Downloads",
            path: "/srv/media/downloads",
            type: "folder",
            sizeBytes: 200 * gib,
            sizeComplete: true,
            modifiedAt: observedAt - 1800,
          },
        ],
      };
    if (path === "/events/history") data = activities;
    if (path === "/hosts")
      data = [
        {
          id: "core",
          name: "MediaHub Core",
          address: "http://mediahub.local",
          local: true,
          status: "online",
          capabilities: ["docker"],
        },
      ];
    if (path === "/runtime")
      data = {
        connected: true,
        version: "0.4.29",
        hostname: "mediahub-core",
        docker: { available: true, version: "28.4.0", composeAvailable: true },
      };
    if (path === "/apps/seedbox/runtime")
      data = { view: "seedbox", report: seedbox };
    if (path === "/apps/plex/runtime")
      data = {
        view: "plex",
        report: {
          health: "healthy",
          available: true,
          observedAt,
          cached: false,
          agentOnline: true,
          dockerHealthy: true,
          checks: [],
          plex: {
            running: true,
            version: "1.42.1",
            startedAt: new Date(now - 12 * 86400000).toISOString(),
            activeStreams: 2,
            transcodingStreams: 0,
            directStreams: 2,
            memoryBytes: 768 * mib,
            cpuPercent: 4.2,
            libraries: [
              { id: "1", name: "Film", type: "movie", count: 486 },
              { id: "2", name: "Serier", type: "show", count: 124 },
            ],
          },
          vpn: { ...seedbox.vpn, externalIp: "198.51.100.25" },
          portForwarding: {
            ...seedbox.portForwarding,
            currentPort: 32400,
            plexVerified: true,
          },
          storage: { ...seedbox.storage, appWritable: false },
          host: seedbox.host,
        },
      };
    if (path === "/apps/plex/plex/recent-media")
      data = {
        supported: true,
        items: posterExamples.map(({ id, title }, index) => ({
          id,
          title,
          type: "movie",
          year: 2026 - (index % 3),
          thumbnailUrl: `/api/v1/apps/plex/plex/artwork/${id}`,
        })),
      };
    if (path === "/apps/cloudflare/runtime")
      data = {
        view: "cloudflare",
        report: {
          health: "healthy",
          available: true,
          observedAt,
          cached: false,
          agentOnline: true,
          cloudflare,
        },
      };
    if (path === "/cloudflare/status") data = cloudflare;
    if (path === "/cloudflare/config") data = { values: {}, secrets: {} };
    if (path === "/seedbox/torrents")
      data = {
        items: torrents,
        storageId: "downloads",
        limit: 100,
        downloadLocations: [{ id: "root", label: "Top folder" }],
        retentionSupported: false,
      };
    if (path === "/seedbox/locations")
      data = {
        provider: "ProtonVPN",
        available: true,
        countries: ["Denmark", "Netherlands", "Sweden"],
        servers: [],
        current: {
          country: "Denmark",
          server: "dk-01",
          countryEvidence: "GeoIP",
          externalIp: "198.51.100.24",
        },
        operation: { state: "idle", step: null },
        automaticDescription:
          "Compares download and upload through up to 3 P2P servers. Keeps the current server unless the combined measured speed improves by 25%. Tests interrupt torrent connections and use up to 30 MiB. Measurements include current network load; torrent speeds may differ.",
        automation: { enabled: false, intervalHours: 0, message: "" },
      };
    if (path === "/seedbox/port-reachability")
      data = {
        status: "reachable",
        message:
          "TCP connection to the VPN torrent port succeeded from MediaHub Core",
        checkedAt: observedAt,
        address: "198.51.100.24",
        port: 48124,
      };
    if (path === "/seedbox/rss/feeds")
      data = { feeds: [], intervalSeconds: 300 };
    if (path === "/seedbox/rss/feeds/settings") data = { intervalSeconds: 300 };
    if (path === "/updates/summary")
      data = {
        count: 2,
        checkedAt: observedAt,
        intervalHours: 24,
        lastError: null,
        items: [
          ...apps.map((app) => ({
            id: app.id,
            name: app.name,
            packageId: app.packageId,
            installedVersion: app.version,
            latestVersion:
              app.id === "seedbox"
                ? "0.1.1"
                : app.id === "cloudflare"
                  ? "0.4.1"
                  : app.version,
            updateAvailable: app.id !== "plex",
            message: app.id === "plex" ? "Up to date" : "Update available",
          })),
          {
            id: "docker",
            name: "Docker",
            installedVersion: "28.4.0",
            latestVersion: "28.4.0",
            updateAvailable: false,
            message: "Up to date",
          },
          {
            id: "core",
            name: "MediaHub Core",
            installedVersion: "0.4.29",
            latestVersion: "0.4.29",
            updateAvailable: false,
            message: "Up to date",
          },
        ],
        notifications: [],
      };
    if (path === "/updates/platform")
      data = {
        configured: true,
        repository: "mediahub/platform",
        installedVersion: "0.4.29",
        latestVersion: "0.4.29",
        updateAvailable: false,
        assets: {},
        installReady: false,
        privateAccessConfigured: true,
        message: "Up to date",
      };
    if (path.endsWith("/operation") || path === "/updates/queue")
      data = {
        enabled: false,
        state: "idle",
        message: "",
        logs: [],
        items: [],
        progress: 0,
      };
    if (path === "/backups")
      data = { includes: ["Configuration"], excludes: ["Media"] };
    if (path === "/security")
      data = {
        totpEnabled: true,
        requireTotp: false,
        recoveryCodesRemaining: 8,
      };
    if (path === "/network")
      data = {
        pending: {
          listen_host: "0.0.0.0",
          port: 18766,
          base_url: "http://mediahub.local",
          trusted_proxies: [],
          allowed_origins: [],
        },
      };
    await route.fulfill({ json: { data } });
  });
}

async function contained(page: Page) {
  const result = await page.evaluate(() => ({
    contained: document.documentElement.scrollWidth <= window.innerWidth + 1,
    width: window.innerWidth,
    actual: document.documentElement.scrollWidth,
    overflow: Array.from(document.querySelectorAll("body *"))
      .map((node) => ({
        tag: node.tagName,
        class: node.getAttribute("class"),
        right: Math.round(node.getBoundingClientRect().right),
      }))
      .filter((node) => node.right > window.innerWidth + 1)
      .slice(0, 15),
  }));
  if (!result.contained)
    await page.screenshot({
      path: `${examples}/overflow-${Date.now()}.png`,
      fullPage: true,
    });
  expect(result.contained, JSON.stringify(result)).toBe(true);
}

async function appearanceColors(page: Page) {
  return page.evaluate(() => {
    const style = getComputedStyle(document.documentElement);
    const values = Object.fromEntries(
      [
        "accent",
        "indigo",
        "bg",
        "surface",
        "raised",
        "text",
        "healthy",
        "warning",
        "danger",
      ].map((name) => [name, style.getPropertyValue(`--${name}`).trim()]),
    );
    return {
      ...values,
      valid: Object.values(values).every((value) =>
        CSS.supports("color", value),
      ),
    } as Record<string, string | boolean>;
  });
}

async function personalizedDashboardReady(page: Page) {
  await expect(page.locator("html")).toHaveAttribute(
    "data-design-samples",
    "ready",
  );
  await expect(page.locator(".service-download")).toHaveCount(2);
  await expect(page.locator(".vpn-country")).toContainText("Danmark");
  await expect(page.locator(".dashboard-update-row")).toHaveCount(4);
  await expect(page.locator(".resource-chart .chart-area")).toHaveCount(3);
  await expect
    .poll(() =>
      page
        .locator(".plex-posters img")
        .first()
        .evaluate(
          (image: HTMLImageElement) => image.complete && image.naturalWidth > 0,
        ),
    )
    .toBe(true);
}

async function captureAppearancePanel(page: Page, filename: string) {
  const viewport = page.viewportSize();
  const stableScroll = await page.addStyleTag({
    content:
      "html, body, * { scroll-behavior: auto !important; transition: none !important; animation: none !important; }",
  });
  try {
    await page.setViewportSize({ width: 1440, height: 1400 });
    await page.evaluate(() =>
      window.scrollTo({ top: 0, left: 0, behavior: "instant" }),
    );
    await page.waitForFunction(async () => {
      const panel = document.querySelector(".appearance-settings");
      if (!panel) return false;
      const before = panel.getBoundingClientRect();
      await new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      );
      const after = panel.getBoundingClientRect();
      return (
        after.top >= 0 &&
        after.bottom <= innerHeight &&
        after.width > 0 &&
        before.x === after.x &&
        before.y === after.y &&
        before.width === after.width &&
        before.height === after.height
      );
    });
    await page.locator(".appearance-settings").screenshot({
      path: `${examples}/${filename}`,
      animations: "disabled",
    });
  } finally {
    await stableScroll.evaluate((node) => node.remove());
    if (viewport) await page.setViewportSize(viewport);
  }
}

test.beforeEach(async ({ page }) => {
  await designFixtures(page);
});

test("complete desktop control center and consistent workspace examples", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", "da");
  await expect(page.locator("html")).toHaveAttribute(
    "data-design-samples",
    "ready",
  );
  await expect(page.locator(".control-summary")).toBeVisible();
  await expect(page.locator(".service-overview")).toBeVisible();
  await expect(page.locator(".resource-trends")).toBeVisible();
  await expect(page.locator(".sidebar .service-mark-plex")).toBeVisible();
  await expect(
    page.locator(".sidebar .service-mark-qbittorrent"),
  ).toBeVisible();
  await expect(page.locator(".topbar .account-copy strong")).toHaveText(
    "abekat",
  );
  await expect(page.locator(".topbar .account-copy small")).toHaveText(
    "MediaHub",
  );
  const date = page.locator(".dashboard-status-stack time");
  await expect(date).toBeVisible();
  expect(
    Number.isFinite(Date.parse((await date.getAttribute("datetime")) || "")),
  ).toBe(true);
  await expect(date).toContainText(
    /mandag|tirsdag|onsdag|torsdag|fredag|lørdag|søndag/,
  );
  await expect(page.locator(".control-summary .summary-status")).toHaveCount(4);
  await expect(
    page.locator(".control-summary .summary-status.healthy"),
  ).toHaveCount(4);
  await expect(page.locator(".download-service-tile .badge")).toHaveText(
    translated("Downloading"),
  );
  const areas = page.locator(".resource-chart .chart-area");
  await expect(areas).toHaveCount(3);
  const chartAreas = await areas.evaluateAll((nodes) =>
    nodes.map((node) => {
      const fillId = node.getAttribute("fill")?.match(/^url\(#(.+)\)$/)?.[1];
      const gradient = fillId ? document.getElementById(fillId) : null;
      return {
        d: node.getAttribute("d") || "",
        fillId,
        validGradient:
          gradient?.tagName.toLowerCase() === "lineargradient" &&
          node.closest("svg")?.contains(gradient),
      };
    }),
  );
  expect(new Set(chartAreas.map((area) => area.fillId)).size).toBe(3);
  for (const area of chartAreas) {
    expect(area.d).toMatch(/^M.+Z$/);
    expect(area.d).not.toMatch(/NaN|Infinity/);
    expect(area.validGradient).toBe(true);
  }
  await expect(
    page.getByText("Ubuntu 24.04.3 Desktop amd64.iso").first(),
  ).toBeVisible();
  const healthyColor = await page
    .locator(".service-overview .badge.healthy")
    .first()
    .evaluate((node) => getComputedStyle(node).color);
  const activeColor = await page
    .locator(".sidebar a.active")
    .first()
    .evaluate((node) => getComputedStyle(node).color);
  expect(healthyColor).not.toBe(activeColor);
  const [red, green, blue] = healthyColor.match(/[\d.]+/g)!.map(Number);
  expect(green).toBeGreaterThan(red);
  expect(green).toBeGreaterThan(blue);
  await contained(page);
  await page.screenshot({
    path: `${examples}/dashboard-desktop.png`,
    fullPage: true,
  });
  await page.screenshot({ path: `${examples}/dashboard-desktop-viewport.png` });
  for (const [path, name] of [
    ["/apps", "services"],
    ["/storage", "storage"],
    ["/settings", "settings"],
    ["/apps/plex", "plex"],
    ["/apps/seedbox?section=torrents", "downloads"],
    ["/apps/seedbox?section=vpn", "vpn"],
    ["/updates", "updates"],
  ]) {
    await page.goto(path);
    await expect(page.locator("main h1")).toBeVisible();
    await expect(page.locator("main")).not.toContainText("Loading MediaHub");
    await page.waitForLoadState("networkidle");
    await contained(page);
    await page.screenshot({
      path: `${examples}/${name}-desktop.png`,
      fullPage: true,
    });
  }
  expect(errors).toEqual([]);
});

test("mobile control center, navigation and narrow content remain usable", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute(
    "data-design-samples",
    "ready",
  );
  await expect(page.locator(".control-summary")).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Hurtig navigation" }),
  ).toBeVisible();
  await expect(page.locator(".mobile-dock")).toBeVisible();
  await contained(page);
  await page.screenshot({
    path: `${examples}/dashboard-mobile.png`,
    fullPage: true,
  });
  await page.screenshot({ path: `${examples}/dashboard-mobile-viewport.png` });
  await page
    .getByRole("button", { name: "Åbn navigation", exact: true })
    .click();
  await expect(page.locator("aside.sidebar")).toBeVisible();
  await page
    .locator("aside.sidebar")
    .getByRole("link", { name: "Lager", exact: false })
    .click();
  await expect(page).toHaveURL(/\/storage$/);
  await contained(page);
  await page.screenshot({
    path: `${examples}/storage-mobile.png`,
    fullPage: true,
  });
  for (const [path, name] of [
    ["/apps", "services"],
    ["/settings", "settings"],
    ["/apps/seedbox?section=torrents", "downloads"],
    ["/apps/seedbox?section=vpn", "vpn"],
  ]) {
    await page.goto(path);
    await expect(page.locator("main h1")).toBeVisible();
    await page.waitForLoadState("networkidle");
    await contained(page);
    await page.screenshot({
      path: `${examples}/${name}-mobile.png`,
      fullPage: true,
    });
  }
  expect(errors).toEqual([]);
});

test("global search supports the keyboard, navigation and focus restoration", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  const trigger = page.getByRole("button", {
    name: "Søg efter sider og services",
    exact: true,
  });
  await trigger.focus();
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.locator("input")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
  await page.keyboard.press("Control+k");
  await dialog.locator("input").fill("Plex");
  await page.screenshot({ path: `${examples}/search-dialog-desktop.png` });
  await dialog.getByRole("link").filter({ hasText: "Plex" }).first().click();
  await expect(page).toHaveURL(/\/apps\/plex$/);
  await expect(dialog).not.toBeVisible();
  await expect(page.locator("main h1")).toBeVisible();
  expect(errors).toEqual([]);
});

test("failed service report remains unknown instead of claiming healthy", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/v1/apps/seedbox/runtime", (route) =>
    route.fulfill({
      status: 503,
      json: {
        error: {
          code: "unavailable",
          message: "MediaHub is temporarily unavailable",
        },
      },
    }),
  );
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute(
    "data-design-samples",
    "ready",
  );
  const service = page.locator(".service-tile").filter({
    has: page.getByRole("heading", { name: "qBittorrent", exact: true }),
  });
  await expect(service.locator(".badge.unknown")).toBeVisible();
  await expect(service.locator(".badge")).toHaveText(translated("Unknown"));
  await expect(service.locator(".badge")).not.toContainText(
    translated("Downloading"),
  );
  await expect(service.locator(".badge.healthy")).toHaveCount(0);
  await expect(page.locator(".vpn-service-tile .badge.unknown")).toBeVisible();
  await expect(page.locator(".control-status.healthy")).toHaveCount(0);
  for (const title of ["Services online", "Active downloads"]) {
    const summary = page.locator(`.summary-tile[data-layout-title="${title}"]`);
    await expect(summary.locator(".summary-status.unknown")).toBeVisible();
    await expect(summary.locator(".summary-status.healthy")).toHaveCount(0);
  }
  await contained(page);
  await page.screenshot({
    path: `${examples}/service-unavailable-desktop.png`,
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("reference dashboard loads local country flags and Plex covers with usable carousel", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute(
    "data-design-samples",
    "ready",
  );
  const flag = page.locator(".vpn-service-tile img.country-flag");
  await expect(flag).toHaveAttribute("src", "/assets/flags/dk.svg");
  await expect
    .poll(() => flag.evaluate((image: HTMLImageElement) => image.naturalWidth))
    .toBeGreaterThan(0);
  await expect(page.locator(".vpn-country")).toContainText("Danmark");
  await expect(
    page.locator(".plex-service-tile .service-mark-plex"),
  ).toBeVisible();
  await expect(
    page.locator(".download-service-tile .service-mark-qbittorrent"),
  ).toBeVisible();

  const rail = page.locator(".plex-service-tile .plex-posters");
  const covers = rail.locator(".plex-poster img");
  await expect(covers).toHaveCount(posterExamples.length);
  await expect
    .poll(() =>
      covers.first().evaluate((image: HTMLImageElement) => image.naturalWidth),
    )
    .toBeGreaterThan(0);
  await expect(covers.first()).toHaveAttribute("alt", "Solstice");
  await expect(covers.first()).toHaveAttribute(
    "src",
    "/api/v1/apps/plex/plex/artwork/101",
  );
  const next = page.getByRole("button", {
    name: translated("Show more covers"),
    exact: true,
  });
  await expect(next).toBeVisible();
  await next.click();
  await expect
    .poll(() => rail.evaluate((node) => node.scrollLeft))
    .toBeGreaterThan(0);
  await rail.evaluate((node) => {
    node.scrollLeft = node.scrollWidth;
  });
  await next.click();
  await expect.poll(() => rail.evaluate((node) => node.scrollLeft)).toBe(0);
  await contained(page);
  expect(errors).toEqual([]);
});

test("a failed Plex artwork request shows its readable title without a broken image", async ({
  page,
}) => {
  await page.route("**/api/v1/apps/plex/plex/artwork/101", (route) =>
    route.fulfill({ status: 503, body: "Artwork unavailable" }),
  );
  await page.goto("/");
  const first = page.locator(".plex-posters .plex-poster").first();
  await expect(first.locator(".plex-poster-fallback")).toContainText(
    "Solstice",
  );
  await expect(first.locator("img")).toHaveCount(0);
  await expect(page.locator(".plex-posters .plex-poster img")).toHaveCount(
    posterExamples.length - 1,
  );
  await first.click();
  await expect(page).toHaveURL(/\/apps\/plex$/);
});

test("unavailable Plex media keeps the service status and offers a clear cover fallback", async ({
  page,
}) => {
  await page.route("**/api/v1/apps/plex/plex/recent-media", (route) =>
    route.fulfill({
      status: 503,
      json: {
        error: {
          code: "plex_unavailable",
          message: "Plex is temporarily unavailable",
        },
      },
    }),
  );
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute(
    "data-design-samples",
    "ready",
  );
  const plex = page.locator(".plex-service-tile");
  await expect(plex.locator(".plex-covers-empty")).toHaveText(
    translated("Covers are temporarily unavailable"),
  );
  await expect(plex.locator(".plex-poster")).toHaveCount(0);
  await expect(plex.locator(".badge.healthy")).toBeVisible();
});

test("an older Plex Agent shows the upgrade explanation instead of fabricated covers", async ({
  page,
}) => {
  await page.route("**/api/v1/apps/plex/plex/recent-media", (route) =>
    route.fulfill({ json: { data: { supported: false, items: [] } } }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const plex = page.locator(".plex-service-tile");
  await expect(plex.locator(".plex-covers-empty")).toHaveText(
    translated("Update the Plex Agent to show covers"),
  );
  await expect(plex.locator(".plex-poster")).toHaveCount(0);
  await contained(page);
});

test("Plex and Seedbox app pages show loaded flags and covers at desktop and mobile sizes", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/apps/plex");
  const preview = page.locator(".plex-library-preview");
  await expect(preview.locator(".plex-poster")).toHaveCount(
    posterExamples.length,
  );
  await expect
    .poll(() =>
      preview
        .locator("img")
        .first()
        .evaluate((image: HTMLImageElement) => image.naturalWidth),
    )
    .toBeGreaterThan(0);
  const plexCountry = page
    .locator(".runtime-row")
    .filter({ has: page.locator("dt").filter({ hasText: /^Land$/ }) });
  await expect(plexCountry).toContainText("Danmark");
  await expect(plexCountry.locator("img.country-flag")).toHaveAttribute(
    "src",
    "/assets/flags/dk.svg",
  );
  await expect
    .poll(() =>
      plexCountry
        .locator("img")
        .evaluate((image: HTMLImageElement) => image.naturalWidth),
    )
    .toBeGreaterThan(0);
  await page
    .getByRole("button", { name: translated("Customize layout"), exact: true })
    .click();
  const heading = page.locator(".runtime-summary h1");
  expect(
    await heading.evaluate((node) => node.closest(".layout-item") === null),
  ).toBe(true);
  expect((await preview.boundingBox())!.y).toBeGreaterThan(
    (await heading.boundingBox())!.y,
  );
  await page
    .getByRole("button", { name: translated("Done arranging"), exact: true })
    .click();
  await page.setViewportSize({ width: 390, height: 844 });
  await contained(page);
  await expect(preview.locator(".plex-posters")).toBeVisible();

  await page.goto("/apps/seedbox?section=vpn");
  const currentCountry = page.locator(".seedbox-daily .country-label");
  await expect(currentCountry).toHaveText("Danmark");
  await expect(currentCountry.locator("img")).toHaveAttribute(
    "src",
    "/assets/flags/dk.svg",
  );
  await expect
    .poll(() =>
      currentCountry
        .locator("img")
        .evaluate((image: HTMLImageElement) => image.naturalWidth),
    )
    .toBeGreaterThan(0);
  const countries = page.getByRole("combobox", { name: "Land", exact: true });
  await expect(countries).toHaveValue("Denmark");
  await countries.selectOption("Netherlands");
  await expect(countries).toHaveValue("Netherlands");
  await expect(countries.locator("option:checked")).toHaveText("Nederlandene");
  // Choosing a new destination does not claim that the current VPN has moved.
  await expect(currentCountry).toHaveText("Danmark");
  await contained(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await contained(page);
  expect(errors).toEqual([]);
});

test("individual service cards resize reorder hide and restore persistently without moving the page header", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute(
    "data-design-samples",
    "ready",
  );
  const group = page.locator(".service-overview");
  const cards = page.locator(".service-overview > .layout-item");
  const plex = cards.filter({ has: page.locator(".plex-service-tile") });
  const vpn = cards.filter({ has: page.locator(".vpn-service-tile") });
  await expect(cards).toHaveCount(4);
  await expect(cards.first()).toHaveAttribute("data-layout-title", "Plex");
  await page
    .getByRole("button", { name: translated("Customize layout"), exact: true })
    .click();
  const heading = page.locator("main h1").first();
  expect(
    await heading.evaluate((node) => node.closest(".layout-item") === null),
  ).toBe(true);
  const dragSurface = plex.locator(".layout-drag-surface");
  const cardBox = (await plex.boundingBox())!;
  const surfaceBox = (await dragSurface.boundingBox())!;
  expect(Math.abs(cardBox.width - surfaceBox.width)).toBeLessThan(2);
  expect(Math.abs(cardBox.height - surfaceBox.height)).toBeLessThan(2);

  await plex.getByRole("combobox").selectOption("50");
  const width =
    (await plex.boundingBox())!.width / (await group.boundingBox())!.width;
  expect(width).toBeGreaterThan(0.47);
  expect(width).toBeLessThan(0.51);
  await dragSurface.focus();
  await page.keyboard.press("ArrowRight");
  await expect(cards.first()).toHaveAttribute(
    "data-layout-title",
    "qBittorrent",
  );
  await expect(cards.nth(1)).toHaveAttribute("data-layout-title", "Plex");
  await vpn
    .getByRole("button", {
      name: translated("Hide {title}", { title: "VPN" }),
      exact: true,
    })
    .click();
  await expect(vpn).toHaveCount(0);
  await page
    .getByRole("button", { name: translated("Done arranging"), exact: true })
    .click();
  await page.reload();
  await expect(cards).toHaveCount(3);
  await expect(cards.first()).toHaveAttribute(
    "data-layout-title",
    "qBittorrent",
  );
  await expect(vpn).toHaveCount(0);
  await page
    .getByRole("button", { name: translated("Customize layout"), exact: true })
    .click();
  await expect(plex.getByRole("combobox")).toHaveValue("50");
  await page.getByText(translated("Choose cards"), { exact: true }).click();
  await page.getByRole("checkbox", { name: "VPN", exact: true }).check();
  await expect(vpn).toBeVisible();
  await page.getByText(translated("Choose cards"), { exact: true }).click();
  await page
    .getByRole("button", { name: translated("Done arranging"), exact: true })
    .click();
  await page.reload();
  await expect(cards).toHaveCount(4);
  await expect(vpn).toBeVisible();
  expect((await group.boundingBox())!.y).toBeGreaterThan(
    (await heading.boundingBox())!.y,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await contained(page);
  expect(
    (await plex.boundingBox())!.width / (await group.boundingBox())!.width,
  ).toBeGreaterThan(0.98);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page
    .getByRole("button", { name: translated("Customize layout"), exact: true })
    .click();
  await page
    .getByRole("button", {
      name: translated("Reset this page").trim(),
      exact: true,
    })
    .click();
  await expect(plex.getByRole("combobox")).toHaveValue("-1");
  await expect(cards.first()).toHaveAttribute("data-layout-title", "Plex");
  // Native pointer drag starts in the body of the card, away from its heading.
  const downloads = cards.filter({
    has: page.locator(".download-service-tile"),
  });
  await group.evaluate((node) => node.scrollIntoView({ block: "center" }));
  const sourceBody = (await plex.boundingBox())!;
  const targetBody = (await downloads.boundingBox())!;
  await dragSurface.dragTo(downloads.locator(".layout-drag-surface"), {
    sourcePosition: { x: sourceBody.width / 2, y: sourceBody.height * 0.55 },
    targetPosition: { x: targetBody.width / 2, y: targetBody.height * 0.55 },
  });
  await expect(cards.first()).toHaveAttribute(
    "data-layout-title",
    "qBittorrent",
  );
  await expect(cards.nth(1)).toHaveAttribute("data-layout-title", "Plex");
  expect(errors).toEqual([]);
});

test("reference dashboard stays contained at narrow phone and tablet widths", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute(
    "data-design-samples",
    "ready",
  );
  for (const width of [320, 360, 768, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    await contained(page);
    if (width < 760) await expect(page.locator(".mobile-brand")).toBeVisible();
    const overflow = await page
      .locator(".topbar, .service-tile, .summary-tile, .resource-plot")
      .evaluateAll((nodes) =>
        nodes
          .filter((node) => node.scrollWidth > node.clientWidth + 1)
          .map((node) => ({
            className: node.className,
            available: node.clientWidth,
            content: node.scrollWidth,
          })),
      );
    expect(
      overflow,
      `Unexpected card or topbar overflow at ${width}px`,
    ).toEqual([]);
    await expect(page.locator(".service-overview > .layout-item")).toHaveCount(
      4,
    );
  }
  expect(errors).toEqual([]);
});

test("appearance previews cancel cleanly and invalid hex never reaches CSS or the account", async ({
  page,
}) => {
  const errors: string[] = [];
  const writes: unknown[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (
      request.method() === "PUT" &&
      request.url().endsWith("/auth/preferences")
    )
      writes.push(request.postDataJSON());
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/settings");
  const panel = page.locator(".appearance-settings");
  await expect(
    panel.getByRole("heading", { name: translated("Colors and shades") }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: translated("Save colors"), exact: true }),
  ).toBeDisabled();
  const original = await appearanceColors(page);
  expect(original.valid).toBe(true);
  await captureAppearancePanel(page, "appearance-default-desktop.png");
  await panel.getByRole("button", { name: "Violet", exact: true }).click();
  await expect
    .poll(async () => (await appearanceColors(page)).accent)
    .not.toBe(original.accent);
  const violet = await appearanceColors(page);
  expect(violet.valid).toBe(true);
  for (const semantic of ["healthy", "warning", "danger"])
    expect(violet[semantic]).toBe(original[semantic]);
  await expect(panel.locator("#appearance-accent")).toHaveValue("#b899ff");
  await captureAppearancePanel(page, "appearance-violet-desktop.png");
  await panel.locator("#appearance-depth").focus();
  await page.keyboard.press("End");
  await expect(panel.locator("#appearance-depth")).toHaveValue("100");
  await expect
    .poll(async () => (await appearanceColors(page)).bg)
    .not.toBe(violet.bg);
  const beforeInvalid = await appearanceColors(page);
  const accentHex = panel.getByRole("textbox", {
    name: translated("{name} (hex)", { name: translated("Accent color") }),
  });
  await accentHex.fill("#gggggg");
  await expect(accentHex).toHaveAttribute("aria-invalid", "true");
  await expect(
    panel.getByRole("button", { name: translated("Save colors"), exact: true }),
  ).toBeDisabled();
  await expect(panel.locator(".field-error")).toBeVisible();
  expect(await appearanceColors(page)).toEqual(beforeInvalid);
  await panel
    .getByRole("button", { name: translated("Discard changes"), exact: true })
    .click();
  await expect.poll(() => appearanceColors(page)).toEqual(original);
  await expect(accentHex).toHaveAttribute("aria-invalid", "false");
  await panel.getByRole("button", { name: "Violet", exact: true }).click();
  await page
    .locator(".sidebar")
    .getByRole("link", { name: translated("Dashboard"), exact: true })
    .click();
  await expect(page).toHaveURL(/\/$/);
  await expect.poll(() => appearanceColors(page)).toEqual(original);
  await page
    .locator(".sidebar")
    .getByRole("link", { name: translated("Settings"), exact: true })
    .click();
  await expect(
    panel.getByRole("button", { name: translated("Save colors"), exact: true }),
  ).toBeDisabled();
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("saved appearance survives navigation reload and language changes in dark light and system modes", async ({
  page,
}) => {
  const errors: string[] = [];
  const writes: unknown[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (
      request.method() === "PUT" &&
      request.url().endsWith("/auth/preferences")
    )
      writes.push(request.postDataJSON());
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/settings");
  const panel = page.locator(".appearance-settings");
  await panel.getByRole("button", { name: "Violet", exact: true }).click();
  await panel.locator("#appearance-accent").fill("#c1a4ff");
  await panel
    .getByRole("button", { name: translated("Save colors"), exact: true })
    .click();
  await expect(panel.locator(".appearance-actions [role=status]")).toHaveText(
    translated("Your colors have been saved."),
  );
  await expect(
    panel.getByRole("button", { name: translated("Save colors"), exact: true }),
  ).toBeDisabled();
  expect(writes).toEqual([
    {
      appearance: {
        accent: "#c1a4ff",
        secondary: "#ed88c0",
        background: "#342451",
        depth: 35,
      },
    },
  ]);
  const dark = await appearanceColors(page);
  expect(dark.valid).toBe(true);
  await page
    .locator(".sidebar")
    .getByRole("link", { name: translated("Dashboard"), exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute(
    "data-design-samples",
    "ready",
  );
  await expect.poll(() => appearanceColors(page)).toEqual(dark);
  await personalizedDashboardReady(page);
  await contained(page);
  await page.screenshot({
    path: `${examples}/personalized-dashboard-desktop.png`,
    fullPage: true,
  });
  await page
    .locator(".sidebar")
    .getByRole("link", { name: translated("App Store"), exact: true })
    .click();
  await expect.poll(() => appearanceColors(page)).toEqual(dark);
  await page.goto("/settings");
  await expect(panel.locator("#appearance-accent")).toHaveValue("#c1a4ff");
  await expect.poll(() => appearanceColors(page)).toEqual(dark);
  await page
    .getByRole("combobox", { name: translated("Language"), exact: true })
    .selectOption("en");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  expect(writes.at(-1)).toEqual({ language: "en" });
  await expect.poll(() => appearanceColors(page)).toEqual(dark);
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(panel.locator("#appearance-accent")).toHaveValue("#c1a4ff");
  await expect.poll(() => appearanceColors(page)).toEqual(dark);
  await page
    .getByRole("combobox", { name: "Language", exact: true })
    .selectOption("da");
  await expect(page.locator("html")).toHaveAttribute("lang", "da");
  await page
    .locator(".sidebar")
    .getByRole("link", { name: translated("Dashboard"), exact: true })
    .click();
  await page.evaluate(() => {
    document.documentElement.dataset.theme = "light";
  });
  await expect
    .poll(async () => (await appearanceColors(page)).bg)
    .not.toBe(dark.bg);
  const light = await appearanceColors(page);
  expect(light.valid).toBe(true);
  expect(light.text).not.toBe(dark.text);
  await personalizedDashboardReady(page);
  await contained(page);
  await page.screenshot({
    path: `${examples}/personalized-light-desktop.png`,
    fullPage: true,
  });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.evaluate(() => {
    document.documentElement.dataset.theme = "system";
  });
  await expect.poll(() => appearanceColors(page)).toEqual(dark);
  await page.emulateMedia({ colorScheme: "light" });
  await expect.poll(() => appearanceColors(page)).toEqual(light);
  expect(errors).toEqual([]);
});

test("appearance failures preserve saved colors and restoring defaults requires an explicit save", async ({
  page,
}) => {
  const errors: string[] = [];
  const writes: unknown[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (
      request.method() === "PUT" &&
      request.url().endsWith("/auth/preferences")
    )
      writes.push(request.postDataJSON());
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/settings");
  const panel = page.locator(".appearance-settings");
  await expect(panel).toBeVisible();
  const original = await appearanceColors(page);
  await panel.getByRole("button", { name: "Violet", exact: true }).click();
  await panel
    .getByRole("button", { name: translated("Save colors"), exact: true })
    .click();
  await expect(panel.locator(".appearance-actions [role=status]")).toHaveText(
    translated("Your colors have been saved."),
  );
  const saved = await appearanceColors(page);
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await contained(page);
    expect(
      await panel.evaluate((node) => node.scrollWidth <= node.clientWidth + 1),
    ).toBe(true);
    expect(
      await panel
        .locator(".appearance-depth label")
        .evaluate((node) => getComputedStyle(node).flexDirection),
    ).toBe("row");
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: `${examples}/appearance-mobile.png`,
    fullPage: true,
  });
  await page.screenshot({ path: `${examples}/appearance-mobile-viewport.png` });
  const panelHeight = Math.ceil(
    await panel.evaluate((node) => node.getBoundingClientRect().height),
  );
  await page.setViewportSize({ width: 390, height: panelHeight + 180 });
  await panel.screenshot({
    path: `${examples}/appearance-mobile-card.png`,
    style: ".mobile-dock { visibility: hidden !important; }",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/v1/auth/preferences", (route) =>
    route.fulfill({
      status: 503,
      json: {
        error: {
          code: "unavailable",
          message: "MediaHub is temporarily unavailable",
        },
      },
    }),
  );
  await panel
    .getByRole("button", { name: translated("Rose"), exact: true })
    .click();
  await panel
    .getByRole("button", { name: translated("Save colors"), exact: true })
    .click();
  await expect(panel.getByRole("alert")).toBeVisible();
  await panel
    .getByRole("button", { name: translated("Discard changes"), exact: true })
    .click();
  await expect.poll(() => appearanceColors(page)).toEqual(saved);
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await page.reload();
  await expect(panel.locator("#appearance-accent")).toHaveValue("#b899ff");
  await expect.poll(() => appearanceColors(page)).toEqual(saved);
  const writesBeforeReset = writes.length;
  await panel
    .getByRole("button", { name: translated("MediaHub defaults"), exact: true })
    .click();
  await expect.poll(() => appearanceColors(page)).toEqual(original);
  expect(writes).toHaveLength(writesBeforeReset);
  await page.reload();
  await expect(panel.locator("#appearance-accent")).toHaveValue("#b899ff");
  await expect.poll(() => appearanceColors(page)).toEqual(saved);
  await page.unroute("**/api/v1/auth/preferences");
  await panel
    .getByRole("button", { name: translated("MediaHub defaults"), exact: true })
    .click();
  await panel
    .getByRole("button", { name: translated("Save colors"), exact: true })
    .click();
  await expect(panel.locator(".appearance-actions [role=status]")).toHaveText(
    translated("Your colors have been saved."),
  );
  expect(writes.at(-1)).toEqual({ appearance: null });
  await page.reload();
  await expect(panel.locator("#appearance-accent")).toHaveValue("#25c9ed");
  await expect.poll(() => appearanceColors(page)).toEqual(original);
  await expect(
    panel.getByRole("button", { name: translated("Save colors"), exact: true }),
  ).toBeDisabled();
  expect(errors).toEqual([]);
});

for (const destination of ["dashboard", "logout"] as const) {
  test(`delayed appearance save is applied only to the active account after ${destination}`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let release!: () => void;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route("**/api/v1/auth/preferences", async (route) => {
      await pending;
      await route.fallback();
    });
    try {
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto("/settings");
      const panel = page.locator(".appearance-settings");
      await expect(panel).toBeVisible();
      const original = await appearanceColors(page);
      await panel.getByRole("button", { name: "Violet", exact: true }).click();
      await expect
        .poll(async () => (await appearanceColors(page)).accent)
        .not.toBe(original.accent);
      const preview = await appearanceColors(page);
      const requested = page.waitForRequest(
        (request) =>
          request.method() === "PUT" &&
          request.url().endsWith("/auth/preferences"),
      );
      await panel
        .getByRole("button", { name: translated("Save colors"), exact: true })
        .click();
      await requested;
      if (destination === "dashboard") {
        await page
          .locator(".sidebar")
          .getByRole("link", { name: translated("Dashboard"), exact: true })
          .click();
        await expect(page).toHaveURL(/\/$/);
        await page
          .locator(".sidebar")
          .getByRole("link", { name: translated("Settings"), exact: true })
          .click();
        await expect(panel).toBeVisible();
        await expect(panel.locator('button[type="submit"]')).toBeDisabled();
        await expect(
          panel.getByRole("button", { name: "Violet", exact: true }),
        ).toBeDisabled();
        await expect(panel.locator("#appearance-depth")).toBeDisabled();
        expect(
          await panel
            .locator(".appearance-presets button, .appearance-controls input")
            .evaluateAll((nodes) =>
              nodes.every(
                (node) =>
                  (node as HTMLInputElement | HTMLButtonElement).disabled,
              ),
            ),
        ).toBe(true);
      } else {
        await page
          .locator(".sidebar")
          .getByRole("button", { name: translated("Sign out"), exact: true })
          .click();
        await expect(page.locator(".login-screen")).toBeVisible();
      }
      await expect.poll(() => appearanceColors(page)).toEqual(original);
      const response = page.waitForResponse(
        (result) =>
          result.request().method() === "PUT" &&
          result.url().endsWith("/auth/preferences"),
      );
      release();
      await response;
      await page.waitForLoadState("networkidle");
      await expect
        .poll(() => appearanceColors(page))
        .toEqual(destination === "dashboard" ? preview : original);
      if (destination === "logout") {
        expect(
          await page.evaluate(() =>
            document.documentElement.style.getPropertyValue("--accent"),
          ),
        ).toBe("");
        await expect(page.locator(".login-screen")).toBeVisible();
      } else {
        await expect(
          panel.getByRole("button", { name: "Violet", exact: true }),
        ).toBeEnabled();
      }
      expect(errors).toEqual([]);
    } finally {
      release();
    }
  });
}

test("empty and failed storage have readable mobile states", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/v1/storage/locations", (route) =>
    route.fulfill({ json: { data: [] } }),
  );
  await page.goto("/storage");
  await expect(
    page.getByText("Intet læsbart medielager konfigureret endnu."),
  ).toBeVisible();
  await contained(page);
  await expect(page.locator("html")).toHaveAttribute(
    "data-design-samples",
    "ready",
  );
  await page.screenshot({
    path: `${examples}/empty-mobile.png`,
    fullPage: true,
  });
  await page.route("**/api/v1/storage/locations", (route) =>
    route.fulfill({
      status: 503,
      json: {
        error: { code: "storage_unavailable", message: "Storage unavailable" },
      },
    }),
  );
  await page.reload();
  await expect(page.getByRole("alert").first()).toBeVisible();
  await contained(page);
  await expect(page.locator("html")).toHaveAttribute(
    "data-design-samples",
    "ready",
  );
  await page.screenshot({
    path: `${examples}/error-mobile.png`,
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

type WindowsShareExample = {
  server: string;
  shareName: string;
  username: string;
  driveLetter: string;
};
const windowsShareExample: WindowsShareExample = {
  server: "192.168.10.20",
  shareName: "MediaHub",
  username: "media-upload",
  driveLetter: "M",
};

async function windowsShareFixtures(
  page: Page,
  configuration: WindowsShareExample | null = null,
) {
  const state = {
    configuration,
    configurationError: false,
    statusError: false,
    saveError: false,
    reachable: true,
    writes: [] as WindowsShareExample[],
    downloads: [] as string[],
    checks: 0,
  };
  const failure = {
    error: {
      code: "windows_share_unavailable",
      message: "Check the connection to MediaHub and try again.",
    },
  };
  const report = () => ({
    configured: !!state.configuration,
    status: !state.configuration
      ? "not_configured"
      : state.reachable
        ? "reachable"
        : "unreachable",
    checkedAt: state.configuration ? new Date().toISOString() : null,
    checkedFrom: "mediahub-core",
    server: state.configuration?.server ?? null,
    port: 445,
    tcpReachable: state.configuration ? state.reachable : null,
    latencyMs: state.configuration && state.reachable ? 2.4 : null,
    shareAccessVerified: false,
    windowsAccessVerified: false,
    cached: false,
    message: !state.configuration
      ? "Save a private Windows share connection to begin"
      : state.reachable
        ? "TCP 445 is reachable from MediaHub Core. Windows sign-in and folder access have not been verified."
        : "TCP 445 could not be reached from MediaHub Core. This does not determine whether your Windows PC can access the share.",
  });
  await page.route("**/api/v1/windows-share/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split("/").pop();
    let data: unknown;
    if (path === "configuration") {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON() as WindowsShareExample;
        state.writes.push(body);
        if (state.saveError) {
          await route.fulfill({ status: 503, json: failure });
          return;
        }
        state.configuration = { ...body };
      } else if (state.configurationError) {
        await route.fulfill({ status: 503, json: failure });
        return;
      }
      data = {
        configured: !!state.configuration,
        appId: state.configuration ? "windows-share" : null,
        configuration: state.configuration,
      };
    } else if (path === "status" || path === "check") {
      if (path === "check") {
        expect(route.request().method()).toBe("POST");
        state.checks += 1;
      }
      if (state.statusError) {
        await route.fulfill({ status: 503, json: failure });
        return;
      }
      data = report();
    } else if (path === "connect.ps1" || path === "diagnostics.ps1") {
      state.downloads.push(path);
      // Download fixtures are comments only and are never executed by these tests.
      await route.fulfill({
        contentType: "application/octet-stream",
        headers: { "Content-Disposition": `attachment; filename="${path}"` },
        body: Buffer.from(
          `\ufeff# MediaHub browser fixture: ${path}\r\n# No executable commands.\r\n`,
          "utf8",
        ),
      });
      return;
    } else {
      await route.fulfill({ status: 404, json: failure });
      return;
    }
    await route.fulfill({ json: { data } });
  });
  await page.route("**/api/v1/apps", (route) =>
    route.fulfill({
      json: {
        data: [
          ...(designAppLists.get(page) ?? []),
          ...(state.configuration
            ? [
                {
                  id: "windows-share",
                  name: "Windows folder access",
                  packageId: "org.mediahub.windows-share",
                  version: "0.1.0",
                  state: "configured",
                  isMock: false,
                  detailPath: "/apps/windows-share",
                  health: {
                    status: state.reachable ? "unknown" : "degraded",
                    summary: report().message,
                    lastChecked: new Date().toISOString(),
                    checks: [],
                  },
                },
              ]
            : []),
        ],
      },
    }),
  );
  await page.route("**/api/v1/catalog", (route) =>
    route.fulfill({
      json: {
        data: [
          {
            id: "org.mediahub.windows-share",
            name: "Windows folder access",
            description:
              "Connect Windows Explorer to your existing media share, with guided drive mapping and clear diagnostics from your PC.",
            category: "storage",
          },
          {
            id: "org.mediahub.fjordhub",
            name: "FjordHub",
            description:
              "Deploy or connect FjordHub through a guided flow, then read its app and Docker resource status through a least-privilege Access Token.",
            category: "media-platform",
          },
        ].map((app) => ({
          ...app,
          version: "0.1.0",
          maintainer: { name: "MediaHub contributors" },
          availability: "available",
          requiredRuntime: "none",
          recommendedIsolation: "shared-host",
          hostCapabilities: [],
          images: {},
          services: {},
          storageRequirements: [],
          secrets: [],
          dependencies: [],
          healthChecks: [],
          capabilities: [],
          configFields: [],
          installGuide: [],
        })),
      },
    }),
  );
  return state;
}

async function windowsShareReady(page: Page) {
  await expect(
    page.locator(".windows-share-form fieldset input").first(),
  ).toBeEnabled();
  await expect(page.locator(".windows-share-card")).toHaveCount(4);
  await expect(page.locator(".windows-share-intro .badge")).not.toContainText(
    translated("Loading connection…"),
  );
}

async function captureWindowsShare(
  page: Page,
  filename: string,
  fullPage = true,
) {
  await expect(page.locator("html")).toHaveAttribute(
    "data-design-samples",
    "ready",
  );
  const stable = await page.addStyleTag({
    content:
      "html, body, * { scroll-behavior: auto !important; transition: none !important; animation: none !important; }",
  });
  try {
    await page.evaluate(async () => {
      await document.fonts.ready;
      window.scrollTo({ top: 0, left: 0, behavior: "instant" });
      await new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      );
    });
    await page.screenshot({
      path: `${examples}/${filename}`,
      fullPage,
      animations: "disabled",
      // The separate viewport image preserves mobile navigation. In a stitched
      // long-page image its fixed position otherwise covers the middle of a form.
      style: fullPage
        ? ".mobile-dock { visibility: hidden !important; }"
        : undefined,
    });
  } finally {
    await stable.evaluate((node) => node.remove());
  }
}

test("Windows folder app installs through the store, persists its saved path and downloads inspectable helpers", async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const state = await windowsShareFixtures(page);
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/store");
  const storeCard = page.locator(".store-card").filter({
    has: page.getByRole("heading", {
      name: translated("Windows folder access"),
      exact: true,
    }),
  });
  await expect(storeCard).toBeVisible();
  await expect(storeCard.locator(".app-icon svg")).toBeVisible();
  await expect(
    storeCard.getByRole("link", {
      name: translated("Set up Windows access →"),
      exact: true,
    }),
  ).toBeVisible();
  await captureWindowsShare(page, "windows-share-store-desktop.png");
  await storeCard
    .getByRole("link", {
      name: translated("Set up Windows access →"),
      exact: true,
    })
    .click();
  await expect(page).toHaveURL(/\/store\/windows-share$/);
  await windowsShareReady(page);
  await expect(page.locator(".windows-share-intro .badge")).toHaveText(
    translated("Not configured"),
  );
  await expect(
    page.locator('.windows-share-page input[type="password"]'),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", {
      name: translated("Download Windows diagnostic helper"),
      exact: true,
    }),
  ).toBeDisabled();
  await captureWindowsShare(page, "windows-share-setup-desktop.png");
  await page
    .getByLabel(translated("Server private IPv4 address"), { exact: false })
    .fill("8.8.8.8");
  await page
    .getByRole("button", { name: translated("Save and continue"), exact: true })
    .click();
  await expect(
    page.locator(".windows-share-feedback[role=alert]"),
  ).toContainText(
    translated(
      "Enter the SMB server's private IPv4 address, such as 192.168.1.10.",
    ),
  );
  expect(state.writes).toEqual([]);
  await page
    .getByLabel(translated("Server private IPv4 address"), { exact: false })
    .fill(windowsShareExample.server);
  await page
    .getByLabel(translated("Share name"), { exact: false })
    .fill("../Film");
  await page
    .getByRole("button", { name: translated("Save and continue"), exact: true })
    .click();
  await expect(
    page.locator(".windows-share-feedback[role=alert]"),
  ).toContainText(
    translated(
      "Enter the published share name without a folder path or special command characters.",
    ),
  );
  expect(state.writes).toEqual([]);
  await page
    .getByLabel(translated("Share name"), { exact: false })
    .fill(windowsShareExample.shareName);
  await page
    .getByLabel(translated("SMB username (optional)"), { exact: true })
    .fill(windowsShareExample.username);
  await page
    .getByLabel(translated("Windows drive letter"), { exact: false })
    .selectOption("M");
  await page
    .getByRole("button", { name: translated("Save and continue"), exact: true })
    .click();
  await expect(
    page.getByLabel(translated("Saved network path"), { exact: false }),
  ).toHaveValue("\\\\192.168.10.20\\MediaHub");
  expect(state.writes).toEqual([windowsShareExample]);
  expect(Object.keys(state.writes[0]).sort()).toEqual([
    "driveLetter",
    "server",
    "shareName",
    "username",
  ]);
  await page
    .getByRole("button", { name: translated("Check from Core"), exact: true })
    .click();
  await expect(page.locator(".windows-share-check-heading .badge")).toHaveText(
    translated("Port reachable"),
  );
  await captureWindowsShare(page, "windows-share-connected-desktop.png");
  await page
    .getByText(translated("Optional: use the Windows connection helper"), {
      exact: true,
    })
    .click();
  await expect(
    page.locator(".windows-share-command").filter({ hasText: "connect.ps1" }),
  ).toHaveText(
    'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\\Downloads\\connect.ps1"',
  );
  await page
    .getByText(translated("How to run the Windows diagnostic helper"), {
      exact: true,
    })
    .click();
  await expect(
    page
      .locator(".windows-share-command")
      .filter({ hasText: "diagnostics.ps1" }),
  ).toHaveText(
    'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\\Downloads\\diagnostics.ps1"',
  );
  await page
    .getByText(
      translated("PowerShell blocks the script or reports PSSecurityException"),
      { exact: true },
    )
    .click();
  await expect(
    page.getByText("Get-ExecutionPolicy -List", { exact: true }),
  ).toBeVisible();
  for (const [kind, label] of [
    ["connect", "Download Windows connection helper"],
    ["diagnostics", "Download Windows diagnostic helper"],
  ]) {
    const downloadEvent = page.waitForEvent("download");
    await page
      .getByRole("button", { name: translated(label), exact: true })
      .click();
    const download = await downloadEvent;
    expect(download.suggestedFilename()).toBe(`${kind}.ps1`);
    const path = testInfo.outputPath(`${kind}.ps1`);
    await download.saveAs(path);
    const content = await readFile(path);
    expect([...content.subarray(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
    expect(content.toString("utf8")).toContain("No executable commands.");
  }
  expect(state.downloads).toEqual(["connect.ps1", "diagnostics.ps1"]);
  await page.goto("/apps");
  const installed = page.locator(".app-detail").filter({
    has: page.getByRole("heading", {
      name: translated("Windows folder access"),
      exact: true,
    }),
  });
  await expect(installed).toBeVisible();
  await expect(installed).toContainText(
    translated("Installed · Windows setup and connection checks"),
  );
  await page.locator('.sidebar a[href="/apps/windows-share"]').click();
  await expect(page).toHaveURL(/\/apps\/windows-share$/);
  await windowsShareReady(page);
  await page.reload();
  await windowsShareReady(page);
  await expect(
    page.getByLabel(translated("Saved network path"), { exact: false }),
  ).toHaveValue("\\\\192.168.10.20\\MediaHub");
  await expect(
    page.getByLabel(translated("SMB username (optional)"), { exact: true }),
  ).toHaveValue("media-upload");
  await contained(page);
  expect(errors).toEqual([]);
});

test("Windows connection checks remain honest about TCP and failed edits preserve the saved target", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const state = await windowsShareFixtures(page, { ...windowsShareExample });
  state.reachable = false;
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/apps/windows-share");
  await windowsShareReady(page);
  await page
    .getByRole("button", { name: translated("Check from Core"), exact: true })
    .click();
  expect(state.checks).toBe(1);
  await expect(page.locator(".windows-share-check-heading .badge")).toHaveText(
    translated("Port unavailable"),
  );
  await expect(page.locator(".windows-share-check-heading .badge")).toHaveClass(
    /degraded/,
  );
  await expect(
    page.getByText(
      translated(
        "This checks TCP port 445 from Core. It does not verify the share, your Windows connection, credentials or file permissions.",
      ),
      { exact: true },
    ),
  ).toBeVisible();
  for (const symptom of [
    "The drive is disconnected or Windows reports error 53",
    "Windows asks for credentials again or reports error 1219",
    "Windows shows the wrong amount of free space",
  ]) {
    const detail = page
      .locator(".windows-share-troubleshooting details")
      .filter({ has: page.getByText(translated(symptom), { exact: true }) });
    await detail.locator("summary").click();
    await expect(detail).toHaveAttribute("open", "");
  }
  await expect(
    page.getByText(
      translated(
        "Windows displays the capacity reported by the SMB server. Compare it with MediaHub storage, then check NAS quotas or whether Samba reports the correct media filesystem instead of its system disk.",
      ),
      { exact: true },
    ),
  ).toBeVisible();
  await captureWindowsShare(page, "windows-share-troubleshooting-desktop.png");
  state.saveError = true;
  await page
    .getByLabel(translated("Share name"), { exact: false })
    .fill("DifferentShare");
  await page
    .getByRole("button", {
      name: translated("Save share details"),
      exact: true,
    })
    .click();
  await expect(
    page.locator(".windows-share-feedback[role=alert]"),
  ).toContainText(
    translated("Check the connection to MediaHub and try again."),
  );
  await expect(
    page.getByLabel(translated("Saved network path"), { exact: false }),
  ).toHaveValue("\\\\192.168.10.20\\MediaHub");
  await expect(
    page.getByRole("button", {
      name: translated("Download Windows diagnostic helper"),
      exact: true,
    }),
  ).toBeDisabled();
  expect(state.configuration).toEqual(windowsShareExample);
  await page.reload();
  await windowsShareReady(page);
  await expect(
    page.getByLabel(translated("Share name"), { exact: false }),
  ).toHaveValue("MediaHub");
  expect(errors).toEqual([]);
});

test("Windows setup protects unavailable configuration and recovers independently from a failed Core status", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const state = await windowsShareFixtures(page, { ...windowsShareExample });
  state.configurationError = true;
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/windows-share/configuration", async (route) => {
    await pending;
    await route.fallback();
  });
  await page.goto("/apps/windows-share");
  const save = page.locator(".windows-share-form button[type=submit]");
  await expect(save).toBeDisabled();
  await expect(
    page.locator(".windows-share-form fieldset input").first(),
  ).toBeDisabled();
  release();
  await expect(
    page.locator(".windows-share-feedback[role=alert]"),
  ).toBeVisible();
  await expect(save).toBeDisabled();
  await expect(
    page.locator(".windows-share-form fieldset input").first(),
  ).toBeDisabled();
  await expect(page.locator(".windows-share-intro .badge")).toHaveText(
    translated("Connection unavailable"),
  );
  await expect(
    page.getByRole("button", {
      name: translated("Download Windows diagnostic helper"),
      exact: true,
    }),
  ).toBeDisabled();
  expect(state.writes).toEqual([]);
  state.configurationError = false;
  state.statusError = true;
  await page
    .getByRole("button", { name: translated("Try again"), exact: true })
    .click();
  await windowsShareReady(page);
  await expect(save).toBeEnabled();
  await expect(
    page.getByLabel(translated("Saved network path"), { exact: false }),
  ).toHaveValue("\\\\192.168.10.20\\MediaHub");
  await expect(page.locator(".windows-share-card [role=alert]")).toBeVisible();
  state.statusError = false;
  await page
    .getByRole("button", { name: translated("Check from Core"), exact: true })
    .click();
  await expect(page.locator(".windows-share-check-heading .badge")).toHaveText(
    translated("Port reachable"),
  );
  await expect(page.locator(".windows-share-card [role=alert]")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("Windows helper downloads reject a proxy error instead of saving HTML as PowerShell", async ({
  page,
}) => {
  await windowsShareFixtures(page, { ...windowsShareExample });
  await page.route("**/api/v1/windows-share/diagnostics.ps1", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<html><body>Proxy unavailable</body></html>",
    }),
  );
  const downloaded: string[] = [];
  page.on("download", (download) =>
    downloaded.push(download.suggestedFilename()),
  );
  await page.goto("/apps/windows-share");
  await windowsShareReady(page);
  await page
    .getByRole("button", {
      name: translated("Download Windows diagnostic helper"),
      exact: true,
    })
    .click();
  await expect(
    page.locator(".windows-share-feedback[role=alert]"),
  ).toContainText(
    translated("The Windows helper could not be downloaded. Try again."),
  );
  expect(downloaded).toEqual([]);
  await expect(
    page.getByLabel(translated("Saved network path"), { exact: false }),
  ).toHaveValue("\\\\192.168.10.20\\MediaHub");
});

test("Windows cards follow resized borders and move by dragging their content", async ({
  page,
}) => {
  await windowsShareFixtures(page, null);
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/apps/windows-share");
  await windowsShareReady(page);
  await page
    .getByRole("button", { name: translated("Customize layout"), exact: true })
    .click();
  const group = page.locator(".windows-share-grid");
  const cards = group.locator(":scope > .layout-item");
  const card = cards.nth(1);
  const before = await card.getAttribute("data-layout-item");
  const handle = card.locator(":scope > .resize-bottom");
  const box = (await handle.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 - 150, {
    steps: 8,
  });
  await page.mouse.up();
  const outline = (await card.boundingBox())!;
  const panel = (await card.locator(".windows-share-card").boundingBox())!;
  expect(panel.height).toBeCloseTo(outline.height, 0);
  await card
    .locator(":scope > .layout-drag-surface")
    .dragTo(cards.first().locator(":scope > .layout-drag-surface"), {
      sourcePosition: { x: 100, y: 100 },
      targetPosition: { x: 100, y: 100 },
    });
  await expect(cards.first()).toHaveAttribute("data-layout-item", before!);
  for (const key of await cards.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-layout-item")!),
  )) {
    const current = group.locator(
      `:scope > .layout-item[data-layout-item="${key}"]`,
    );
    await current.locator(":scope > .resize-bottom").press("ArrowDown");
    const bounds = (await current.boundingBox())!;
    expect(
      (await current.locator(".windows-share-card").boundingBox())!.height,
    ).toBeCloseTo(bounds.height, 0);
    await current.locator(":scope > .layout-drag-surface").press("ArrowUp");
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../.qa/windows-layout-fixed-desktop.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: translated("Done arranging"), exact: true })
    .click();
  await page.reload();
  await windowsShareReady(page);
  const resized = group.locator(
    `:scope > .layout-item[data-layout-item="${before}"]`,
  );
  expect(
    (await resized.locator(".windows-share-card").boundingBox())!.height,
  ).toBeCloseTo((await resized.boundingBox())!.height, 0);
  await page.setViewportSize({ width: 390, height: 844 });
  await contained(page);
  await captureWindowsShare(page, "windows-layout-fixed-mobile.png");
});

test("every runtime card can move above cards from formerly separate groups", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  for (const path of [
    "/apps/plex",
    "/apps/cloudflare",
    "/apps/seedbox?section=torrents",
    "/apps/seedbox?section=settings",
  ]) {
    await page.goto(path);
    await expect(page.locator("main .layout-item").first()).toBeVisible();
    await page
      .getByRole("button", {
        name: translated("Customize layout"),
        exact: true,
      })
      .click();
    const missing = await page
      .locator("main .panel")
      .evaluateAll((nodes) =>
        nodes
          .filter(
            (node) =>
              !node.closest(".layout-item") &&
              node.getBoundingClientRect().height > 0,
          )
          .map((node) => node.querySelector("h2")?.textContent),
      );
    expect(missing, path).toEqual([]);
    const groups = page
      .locator("main .layout-group")
      .filter({ has: page.locator(".layout-item") });
    await expect(groups, path).toHaveCount(1);
    const group = groups.first();
    const cards = group.locator(":scope > .layout-item");
    for (const key of await cards.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("data-layout-item")!),
    )) {
      const surface = group.locator(
        `:scope > .layout-item[data-layout-item="${key}"] > .layout-drag-surface`,
      );
      const index = await cards.evaluateAll(
        (nodes, key) =>
          nodes.findIndex(
            (node) => node.getAttribute("data-layout-item") === key,
          ),
        key,
      );
      for (let step = index; step > 0; step--) await surface.press("ArrowUp");
      await expect(cards.first()).toHaveAttribute("data-layout-item", key);
    }
    await page
      .getByRole("button", { name: translated("Done arranging"), exact: true })
      .click();
    await page.reload();
    await expect(cards.first()).toBeVisible();
    await contained(page);
  }
});

test("Windows folder guidance adapts to narrow phones and individually resized cards", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await windowsShareFixtures(page, { ...windowsShareExample });
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/apps/windows-share");
  await windowsShareReady(page);
  const group = page.locator(".windows-share-grid");
  const detailsCard = group
    .locator("> .layout-item")
    .filter({ has: page.locator("#windows-share-step-1") });
  const connectionCard = group
    .locator("> .layout-item")
    .filter({ has: page.locator("#windows-share-step-2") });
  await page
    .getByRole("button", { name: translated("Customize layout"), exact: true })
    .click();
  await detailsCard
    .locator(":scope > .layout-item-tools select")
    .selectOption("25");
  await connectionCard
    .locator(":scope > .layout-item-tools select")
    .selectOption("25");
  await page
    .getByRole("button", { name: translated("Done arranging"), exact: true })
    .click();
  expect(
    (await detailsCard.boundingBox())!.width /
      (await group.boundingBox())!.width,
  ).toBeLessThan(0.26);
  await expect
    .poll(() =>
      page
        .locator(".windows-share-form fieldset > label")
        .evaluateAll((labels) => {
          const first = labels[0].getBoundingClientRect();
          const second = labels[1].getBoundingClientRect();
          return (
            second.top >= first.bottom && Math.abs(second.left - first.left) < 1
          );
        }),
    )
    .toBe(true);
  const overflowingCards = await page
    .locator(".windows-share-card")
    .evaluateAll((cards) =>
      cards
        .filter((card) => card.scrollWidth > card.clientWidth + 1)
        .map((card) => card.textContent?.slice(0, 80)),
    );
  expect(overflowingCards).toEqual([]);
  await page.reload();
  await windowsShareReady(page);
  expect(
    (await detailsCard.boundingBox())!.width /
      (await group.boundingBox())!.width,
  ).toBeLessThan(0.26);
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await contained(page);
    const overflow = await page
      .locator(".windows-share-card")
      .evaluateAll(
        (cards) =>
          cards.filter((card) => card.scrollWidth > card.clientWidth + 1)
            .length,
      );
    expect(overflow).toBe(0);
    expect(
      (await detailsCard.boundingBox())!.width /
        (await group.boundingBox())!.width,
    ).toBeGreaterThan(0.98);
  }
  await captureWindowsShare(page, "windows-share-mobile.png");
  await captureWindowsShare(page, "windows-share-mobile-viewport.png", false);
  expect(errors).toEqual([]);
});

async function torrentCleanupFixtures(page: Page) {
  const inherited: RetentionRule = {
    mode: "both",
    seedHours: 48,
    uploadRatio: 2,
    action: "delete_files",
  };
  const state = {
    items: (designTorrentLists.get(page) ?? []).map((torrent) => ({
      ...torrent,
      retention: { ...inherited },
      retentionOverride: false,
    })),
    writes: [] as { hash: string; retention: RetentionRule }[],
    failSave: false,
    listReads: 0,
  };
  await page.route("**/api/v1/seedbox/torrents", (route) => {
    expect(route.request().method()).toBe("GET");
    state.listReads += 1;
    return route.fulfill({
      json: {
        data: {
          items: state.items,
          storageId: "downloads",
          limit: 100,
          downloadLocations: [{ id: "root", label: "Top folder" }],
          retentionSupported: true,
        },
      },
    });
  });
  await page.route("**/api/v1/seedbox/torrents/retention", (route) => {
    expect(route.request().method()).toBe("POST");
    const request = route
      .request()
      .postDataJSON() as (typeof state.writes)[number];
    state.writes.push(request);
    if (state.failSave) {
      return route.fulfill({
        status: 503,
        json: {
          error: {
            code: "cleanup_unavailable",
            message: "MediaHub is temporarily unavailable",
          },
        },
      });
    }
    const selected = state.items.find(
      (torrent) => torrent.hash === request.hash,
    )!;
    selected.retention = { ...request.retention };
    selected.retentionOverride = true;
    return route.fulfill({
      json: {
        data: { retention: selected.retention, retentionOverride: true },
      },
    });
  });
  return state;
}

const cleanupTrigger = (page: Page, name: string) =>
  page.getByRole("button", {
    name: translated("Cleanup settings for {name}", { name }),
    exact: true,
  });
const cleanupDialog = (page: Page) =>
  page.getByRole("dialog", {
    name: translated("Torrent cleanup settings"),
    exact: true,
  });

test("per-torrent cleanup Never overrides just the selected torrent and remains after reload", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const state = await torrentCleanupFixtures(page);
  const selected = state.items[0];
  const unchanged = structuredClone(state.items.slice(1));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/apps/seedbox?section=torrents");
  const trigger = cleanupTrigger(page, selected.name);
  await trigger.click();
  const dialog = cleanupDialog(page);
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(selected.name);
  await dialog
    .getByLabel(translated("Seeding time (hours)"), { exact: true })
    .fill("");
  await dialog
    .getByLabel(translated("When to clean up"), { exact: false })
    .selectOption("disabled");
  await expect(
    dialog.getByLabel(translated("Cleanup action"), { exact: false }),
  ).toHaveCount(0);
  await expect(page.locator("html")).toHaveAttribute(
    "data-design-samples",
    "ready",
  );
  await page.screenshot({
    path: "../.qa/retention/cleanup-desktop.png",
    animations: "disabled",
  });
  const beforeSaveReads = state.listReads;
  await dialog
    .getByRole("button", {
      name: translated("Save cleanup settings"),
      exact: true,
    })
    .click();
  await expect(dialog).toHaveCount(0);
  await expect.poll(() => state.listReads).toBeGreaterThan(beforeSaveReads);
  expect(state.writes).toMatchObject([
    { hash: selected.hash, retention: { mode: "disabled" } },
  ]);
  expect(Number.isFinite(state.writes[0].retention.seedHours)).toBe(true);
  expect(state.writes[0].retention.seedHours).toBeGreaterThanOrEqual(1);
  expect(state.items[0].retentionOverride).toBe(true);
  expect(state.items.slice(1)).toEqual(unchanged);
  await expect(trigger).toHaveAttribute(
    "title",
    new RegExp(translated("Never — keep torrent and files")),
  );
  const row = page
    .locator(".torrent-table tbody > tr")
    .filter({ has: page.getByText(selected.name, { exact: true }) });
  await expect(row.locator(".torrent-cleanup-override")).toHaveText(
    translated("Individual rule · Never"),
  );
  await expect(page.locator(".torrent-cleanup-override")).toHaveCount(1);
  await page.reload();
  await expect(trigger).toBeVisible();
  await expect(row.locator(".torrent-cleanup-override")).toHaveText(
    translated("Individual rule · Never"),
  );
  await trigger.click();
  await expect(
    dialog.getByLabel(translated("When to clean up"), { exact: false }),
  ).toHaveValue("disabled");
  await dialog
    .getByRole("button", { name: translated("Cancel"), exact: true })
    .click();
  expect(errors).toEqual([]);
});

test("per-torrent cleanup saves custom hours ratio and each action without changing other jobs", async ({
  page,
}) => {
  const state = await torrentCleanupFixtures(page);
  const selected = state.items[1];
  const untouched = structuredClone([state.items[0], state.items[2]]);
  await page.goto("/apps/seedbox?section=torrents");
  await cleanupTrigger(page, selected.name).click();
  const dialog = cleanupDialog(page);
  await dialog
    .getByLabel(translated("When to clean up"), { exact: false })
    .selectOption("both");
  await dialog
    .getByLabel(translated("Seeding time (hours)"), { exact: true })
    .fill("37");
  await dialog
    .getByLabel(translated("Upload ratio"), { exact: true })
    .fill("2.75");
  await dialog
    .getByLabel(translated("Cleanup action"), { exact: false })
    .selectOption("remove_job");
  await dialog
    .getByRole("button", {
      name: translated("Save cleanup settings"),
      exact: true,
    })
    .click();
  await expect(dialog).toHaveCount(0);
  expect(state.writes).toEqual([
    {
      hash: selected.hash,
      retention: {
        mode: "both",
        seedHours: 37,
        uploadRatio: 2.75,
        action: "remove_job",
      },
    },
  ]);
  await cleanupTrigger(page, selected.name).click();
  await expect(
    dialog.getByLabel(translated("Seeding time (hours)"), { exact: true }),
  ).toHaveValue("37");
  await expect(
    dialog.getByLabel(translated("Upload ratio"), { exact: true }),
  ).toHaveValue("2.75");
  await dialog
    .getByLabel(translated("Cleanup action"), { exact: false })
    .selectOption("delete_files");
  await expect(dialog.getByRole("note")).toContainText(
    translated(
      "The downloaded files will be permanently deleted from storage, including files used by Plex. Shared files or unsafe paths block deletion.",
    ),
  );
  await dialog
    .getByRole("button", {
      name: translated("Save cleanup settings"),
      exact: true,
    })
    .click();
  await expect(dialog).toHaveCount(0);
  expect(state.writes[1]).toEqual({
    hash: selected.hash,
    retention: {
      mode: "both",
      seedHours: 37,
      uploadRatio: 2.75,
      action: "delete_files",
    },
  });
  expect([state.items[0], state.items[2]]).toEqual(untouched);
  expect(state.items[1].retentionOverride).toBe(true);
});

test("per-torrent cleanup keeps failed saves open and supports keyboard cancel on mobile", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const state = await torrentCleanupFixtures(page);
  state.failSave = true;
  const selected = state.items[2];
  const original = structuredClone(selected);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/apps/seedbox?section=torrents");
  const trigger = cleanupTrigger(page, selected.name);
  await trigger.focus();
  await page.keyboard.press("Enter");
  const dialog = cleanupDialog(page);
  await expect(dialog).toBeVisible();
  await dialog
    .getByLabel(translated("When to clean up"), { exact: false })
    .selectOption("time");
  await dialog
    .getByLabel(translated("Seeding time (hours)"), { exact: true })
    .fill("73");
  await dialog
    .getByLabel(translated("Cleanup action"), { exact: false })
    .selectOption("remove_job");
  await expect(page.locator("html")).toHaveAttribute(
    "data-design-samples",
    "ready",
  );
  await page.screenshot({
    path: "../.qa/retention/cleanup-mobile.png",
    animations: "disabled",
  });
  await dialog
    .getByRole("button", {
      name: translated("Save cleanup settings"),
      exact: true,
    })
    .click();
  await expect(dialog.getByRole("alert")).toContainText(
    translated("MediaHub is temporarily unavailable"),
  );
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByLabel(translated("Seeding time (hours)"), { exact: true }),
  ).toHaveValue("73");
  expect(state.items[2]).toEqual(original);
  await contained(page);
  const box = (await dialog.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(391);
  expect(
    await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth + 1),
  ).toBe(true);
  await dialog
    .getByRole("button", { name: translated("Cancel"), exact: true })
    .focus();
  await page.keyboard.press("Tab");
  expect(
    await dialog.evaluate((node) => node.contains(document.activeElement)),
  ).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await trigger.click();
  await expect(dialog.getByRole("alert")).toHaveCount(0);
  await expect(
    dialog.getByLabel(translated("Seeding time (hours)"), { exact: true }),
  ).toHaveValue("48");
  await dialog
    .getByRole("button", { name: translated("Cancel"), exact: true })
    .click();
  await expect(dialog).toHaveCount(0);
  expect(state.writes).toHaveLength(1);
  expect(errors).toEqual([]);
});
