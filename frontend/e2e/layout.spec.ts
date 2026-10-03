import { expect, test } from "@playwright/test";

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
    if (path === "/updates/summary") data = { count: 0 };
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

test("whole cards move, hide, restore and persist without extra heading rows", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
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
  const cardBox = (await torrents.boundingBox())!;
  const dragBox = (await surface.boundingBox())!;
  expect(Math.abs(cardBox.height - dragBox.height)).toBeLessThan(2);
  const toolsBox = (await torrents
    .locator(".layout-item-tools")
    .boundingBox())!;
  expect(toolsBox.y).toBeGreaterThan(cardBox.y);
  expect(toolsBox.y + toolsBox.height).toBeLessThan(cardBox.y + cardBox.height);
  await surface.dragTo(cards.first().locator(".layout-drag-surface"), {
    sourcePosition: { x: 100, y: cardBox.height - 30 },
    targetPosition: { x: 100, y: 80 },
  });
  await expect(cards.first()).toHaveAttribute(
    "data-layout-title",
    "Ongoing torrents",
  );
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
  await expect(cards.first()).toHaveAttribute(
    "data-layout-title",
    "Ongoing torrents",
  );
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
  await expect(
    page.locator(".torrent-panels > .layout-item").first(),
  ).toHaveAttribute("data-layout-title", "Your feeds");
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
