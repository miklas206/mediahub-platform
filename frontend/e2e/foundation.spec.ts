import { prepareCompatibilityPages } from "./compatibility-page";
import { expect, test } from "@playwright/test";

test("login, dashboard, SSE, mock lifecycle, settings and logout", async ({
  page,
}) => {
  test.setTimeout(180_000);
  page.setDefaultTimeout(15000);
  page.setDefaultNavigationTimeout(45000);
  await prepareCompatibilityPages(page);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page
    .getByLabel("Username", { exact: true })
    .fill(process.env.MEDIAHUB_QA_USER!);
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.MEDIAHUB_QA_PASSWORD!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Apps & Services" }),
  ).toBeVisible();
  await page.goto("/overview");
  await expect(
    page.getByRole("region", { name: "System status" }),
  ).toBeVisible();
  await expect(
    page.getByRole("progressbar", { name: "CPU", exact: true }),
  ).toBeVisible();
  await page.goto("/__qa-components?view=apps");
  await expect(
    page.getByRole("heading", { name: "Foundation Test App" }),
  ).toBeVisible();
  const sample = await page.evaluate(async () => {
    const response = await fetch("/api/v1/system/status");
    return (await response.json()).data;
  });
  expect(sample.ram.totalBytes).toBeGreaterThan(0);
  const updated = await page.evaluate(
    () =>
      new Promise<boolean>((resolve, reject) => {
        const source = new EventSource("/api/v1/events/stream");
        const timer = setTimeout(() => {
          source.close();
          reject(new Error("No live metrics"));
        }, 8000);
        const samples: string[] = [];
        source.addEventListener("system.status", (e) => {
          samples.push(JSON.parse((e as MessageEvent).data).timestamp);
          if (
            samples.length > 1 &&
            samples[0] !== samples[samples.length - 1]
          ) {
            source.close();
            clearTimeout(timer);
            resolve(true);
          }
        });
      }),
  );
  expect(updated).toBe(true);
  await page.setViewportSize({ width: 1440, height: 1000 });
  let deployment: Record<string, unknown> | null = null;
  let deploymentPosts = 0;
  await page.route("**/api/v1/fjordhub/deployment**", async (route) => {
    if (route.request().url().endsWith("/fingerprint")) {
      await route.fulfill({
        json: { data: { fingerprint: "SHA256:" + "A".repeat(43) } },
      });
      return;
    }
    if (route.request().method() === "POST") {
      deploymentPosts++;
      const body = route.request().postDataJSON();
      expect(body.config.cores).toBe("4");
      expect(body.config.memory).toBe("10240");
      expect(body.script).toBeUndefined();
      deployment = {
        id: body.requestId,
        host: body.host,
        config: body.config,
        state: "running",
        message: "Building FjordHub",
        logs: ["Created LXC 210", "Building FjordHub"],
      };
    }
    await route.fulfill({ json: { data: deployment } });
  });
  await page.goto("/store/fjordhub");
  await page
    .getByRole("button", { name: /^Continue to / })
    .first()
    .click();
  await expect(page.getByLabel("Installation target")).toHaveValue("lxc");
  await page
    .getByLabel("Container ID (empty = next free ID)", { exact: true })
    .fill("210");
  await page
    .getByLabel("Container disk storage", { exact: true })
    .fill("ssd-test");
  await page.getByLabel("Direct FjordHub port").fill("9090");
  await page.getByLabel("Network configuration").selectOption("static");
  await expect(
    page.getByRole("button", { name: /^Continue to / }).first(),
  ).toBeDisabled();
  await page.getByLabel("IPv4 address/prefix").fill("192.168.1.50/24");
  await page.getByLabel("IPv4 gateway").fill("192.168.1.1");
  await page
    .getByRole("button", { name: /^Continue to / })
    .first()
    .click();
  await expect(
    page.getByLabel("Automatic FjordHub installation"),
  ).toBeVisible();
  await expect(page.getByLabel("FjordHub installation commands")).toHaveCount(
    0,
  );
  await expect(page.getByRole("button", { name: "Copy commands" })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "Download script" }),
  ).toHaveCount(0);
  await page.screenshot({
    path: "../.qa/fjordhub-commands-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "../.qa/fjordhub-commands-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const installButton = page.getByRole("button", {
    name: "Create LXC and install FjordHub",
    exact: true,
  });
  await expect(installButton).toBeDisabled();
  await page.getByLabel("SSH server IP").fill("192.168.1.126");
  await page.getByLabel("Root SSH password").fill("qa-fake-password");
  await page.getByRole("button", { name: "Check SSH connection" }).click();
  await page
    .getByLabel("I recognize and trust this server fingerprint.")
    .check();
  await installButton.click();
  await expect(page.getByLabel("FjordHub installation console")).toContainText(
    "Created LXC 210",
  );
  await expect(page.getByLabel("Root SSH password")).toHaveValue("");
  await page.reload();
  await expect(page.getByLabel("FjordHub installation console")).toContainText(
    "Building FjordHub",
  );
  expect(deploymentPosts).toBe(1);
  await page.goto("/");
  await page.screenshot({
    path: "../.qa/dashboard-desktop.png",
    fullPage: true,
  });
  await expect(page.locator(".sidebar nav a[href='/apps']")).toHaveCount(0);
  await expect(page.locator(".sidebar nav a[href='/store']")).toBeVisible();
  await page.goto("/__qa-components?view=apps");
  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await expect(
    page.getByText("Mock adapter: stopped", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await expect(
    page.getByText("Mock adapter: running", { exact: true }),
  ).toBeVisible();
  await page.goto("/activity");
  await expect(
    page.getByRole("cell", { name: /app.health.changed/ }).first(),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Storage", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Storage", exact: true }),
  ).toBeVisible();
  await page.goto("/__qa-components?view=files");
  await expect(
    page.getByRole("heading", { name: "No media folders registered" }),
  ).toBeVisible();
  await page.goto("/store");
  await page.getByRole("link", { name: "Updates", exact: true }).click();
  let checkResult = {
    count: 0,
    items: [],
    lastError: "Release source unavailable",
  };
  await page.route("**/api/v1/updates/check", (route) =>
    route.fulfill({ json: { data: checkResult } }),
  );
  const checkAll = page.getByRole("button", {
    name: "Check all now",
    exact: true,
  });
  await checkAll.click();
  await expect(
    page
      .getByRole("alert")
      .filter({
        hasText: "Update check incomplete: Release source unavailable",
      })
      .first(),
  ).toBeVisible();
  await expect(
    page.getByText("Everything checked is up to date.", { exact: true }),
  ).toHaveCount(0);
  await page.locator(".updates-console > details > summary").click();
  const consolePanel = page.getByRole("region", {
    name: "Console",
    exact: true,
  });
  checkResult = {
    count: 1,
    items: [],
    lastError: "Release source unavailable",
  };
  await checkAll.click();
  await expect(consolePanel).toContainText("1 verified updates available");
  await expect(consolePanel).toContainText(
    "Update check incomplete: Release source unavailable",
  );
  checkResult = { count: 0, items: [], lastError: "" };
  await checkAll.click();
  await expect(consolePanel).toContainText("Everything checked is up to date.");
  await expect(page.getByRole("alert")).toHaveCount(0, { timeout: 15000 });
  await page.unroute("**/api/v1/updates/check");
  const githubCheck = page.getByRole("button", {
    name: "Check GitHub",
    exact: true,
  });
  await page.route("**/api/v1/updates/platform", (route) =>
    route.fulfill({
      json: {
        data: {
          configured: true,
          repository: "example/mediahub",
          installedVersion: "0.4.19",
          latestVersion: "0.4.19",
          installedCommit: "a".repeat(40),
          latestCommit: "a".repeat(40),
          installReady: false,
          updateAvailable: false,
          message: "QA repository is up to date.",
        },
      },
    }),
  );
  await expect(githubCheck).toBeEnabled();
  await githubCheck.click();
  await expect(consolePanel).toContainText("QA repository is up to date.");
  await expect(consolePanel).toContainText("GET /updates/platform");
  const updateCards = page.locator(
    ".updates-components .update-component-card",
  );
  await expect(updateCards).toHaveCount(1);
  const updateCardHeights = await updateCards.evaluateAll((cards) =>
    cards.map((card) => card.getBoundingClientRect().height),
  );
  expect(
    Math.max(...updateCardHeights) - Math.min(...updateCardHeights),
  ).toBeLessThan(2);
  await page.screenshot({
    path: "../.qa/updates-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  // Exercise update polling locally; no host update is submitted.
  const buildStatus = {
    enabled: true,
    state: "building",
    progress: 62,
    message: "Building core",
    updateMode: "fast",
    updateReason:
      "Agent build inputs are unchanged; only Core needs rebuilding.",
    changedServices: ["core"],
    steps: [{ label: "Build on this server", state: "running" }],
    logs: ["#1 CACHED", "#2 RUN pnpm build"],
  };
  await page.route("**/api/v1/updates/platform", (route) =>
    route.fulfill({
      json: {
        data: {
          configured: true,
          repository: "example/mediahub",
          installedVersion: "0.4.19",
          latestVersion: "0.4.20",
          updateAvailable: true,
          installReady: true,
          updateMethod: "source",
          fastUpdateAvailable: true,
          assets: {},
          message: "QA release",
        },
      },
    }),
  );
  await page.route("**/api/v1/updates/platform/install", (route) =>
    route.fulfill({ json: { data: buildStatus } }),
  );
  let pollState = "offline";
  await page.route("**/api/v1/updates/platform/operation", (route) =>
    pollState === "offline"
      ? route.fulfill({
          status: 503,
          json: { error: { message: "Temporarily unavailable" } },
        })
      : route.fulfill({
          json: {
            data: {
              ...buildStatus,
              state: "succeeded",
              progress: 100,
              message: "QA update complete",
              steps: [{ label: "Build on this server", state: "complete" }],
              logs: [...buildStatus.logs, "#3 DONE"],
            },
          },
        }),
  );
  await page.getByRole("button", { name: "Check GitHub", exact: true }).click();
  await page
    .getByRole("button", { name: "Install update", exact: true })
    .click();
  const confirmation = page.getByRole("dialog");
  await expect(confirmation).toContainText(
    "Fast update is selected automatically",
  );
  await confirmation
    .getByRole("button", { name: "Install update", exact: true })
    .click();
  await expect(page.getByText(/Connection interrupted/i).first()).toBeVisible();
  await expect(
    page.getByText("Build on this server", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("progressbar", { name: "Install MediaHub update" }),
  ).not.toHaveAttribute("aria-valuenow");
  await expect(
    page.getByRole("progressbar", { name: "Install MediaHub update" }),
  ).toHaveAttribute(
    "aria-valuetext",
    "Last known progress: 62%. Waiting for connection.",
  );
  await expect(consolePanel.locator(":scope > details")).toHaveAttribute(
    "open",
    "",
  );
  await expect(consolePanel.getByLabel("Update console")).toContainText(
    "#1 CACHED",
  );
  pollState = "success";
  await expect(consolePanel).toContainText("QA update complete", {
    timeout: 15000,
  });
  await expect(consolePanel.getByLabel("Update console")).toContainText(
    "#3 DONE",
  );
  await expect(
    consolePanel.getByText("Fast update · QA update complete", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../.qa/update-console-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "../.qa/update-console-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("link", { name: "App Store", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "App Store", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "FjordHub" })).toBeVisible();
  const storeCards = page.locator("[data-app-id]");
  await expect(storeCards.first()).toBeVisible();
  for (const id of [
    "org.mediahub.seedbox",
    "org.mediahub.plex",
    "org.mediahub.jellyfin",
    "org.mediahub.fjordhub",
  ]) {
    await expect(page.locator(`[data-app-id="${id}"]`)).toBeVisible();
  }
  const storeCardHeights = await storeCards.evaluateAll((cards) =>
    cards.map((card) => card.getBoundingClientRect().height),
  );
  expect(
    Math.max(...storeCardHeights) - Math.min(...storeCardHeights),
  ).toBeLessThan(2);
  await page.goto("/store/cloudflare");
  await expect(
    page.getByRole("heading", { name: "Independent VPN app" }),
  ).toBeVisible();
  await page.goto("/__qa-components?view=cloudflare");
  await expect(
    page.getByText("Assisted Cloudflare setup", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Tunnel name").fill("QA home tunnel");
  await page.getByRole("button", { name: /Continue/ }).click();
  await page.getByLabel("Public hostnames").fill("media.example.com");
  await expect(page.getByLabel("CA Pool path on cloudflared host")).toHaveValue(
    "/etc/cloudflared/mediahub-ca.pem",
  );
  await page.getByRole("button", { name: /Continue/ }).click();
  await expect(page.getByLabel("Private metrics URL")).toBeVisible();
  await page.getByRole("button", { name: /Continue/ }).click();
  const setupReview = page.locator(".setup-review-grid");
  await expect(
    setupReview.getByText("Published routes", { exact: true }),
  ).toBeVisible();
  await expect(setupReview.getByText("1", { exact: true })).toBeVisible();
  await page.goto("/store");
  const activeStoreNavigation = page.locator(
    '.sidebar nav a.active[href="/store"]',
  );
  const navigationGroup = page.locator(".sidebar nav");
  await expect(activeStoreNavigation).toBeVisible();
  const [activeNavigationBox, navigationBox] = await Promise.all([
    activeStoreNavigation.boundingBox(),
    navigationGroup.boundingBox(),
  ]);
  const inset = await navigationGroup.evaluate((el) => {
    const css = getComputedStyle(el);
    return parseFloat(css.paddingLeft) + parseFloat(css.paddingRight);
  });
  expect(activeNavigationBox?.width).toBeCloseTo(
    (navigationBox?.width || 0) - inset,
    0,
  );
  await page
    .locator(".sidebar")
    .getByRole("link", { name: "Settings", exact: true })
    .click();
  let maintenanceStarted = false;
  await page.route("**/api/v1/maintenance", async (route) => {
    if (route.request().method() === "POST") maintenanceStarted = true;
    await route.fulfill({
      json: {
        data: {
          operationId: "qa-cleanup",
          state: maintenanceStarted ? "succeeded" : "idle",
          message: "QA cleanup complete",
          reclaimedBytes: 1024,
        },
      },
    });
  });
  await page.getByRole("tab", { name: "Healthcheck", exact: true }).click();
  const refresh = page.waitForResponse(
    (r) => r.url().endsWith("/api/v1/health") && r.ok(),
  );
  await page.getByRole("button", { name: "Refresh health checks" }).click();
  await refresh;
  await page.getByRole("button", { name: "Check and clean up" }).click();
  await expect(
    page.getByRole("progressbar", { name: "Maintenance", exact: true }),
  ).toHaveAttribute("aria-valuenow", "100", { timeout: 15000 });
  expect(maintenanceStarted).toBe(true);
  await expect(
    page.getByText("Technical details", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("MediaHub Core", { exact: true })).toBeVisible();
  await expect(page.getByText("Media stays protected")).toBeVisible();
  await page.getByRole("tab", { name: "General", exact: true }).click();
  await page.goto("/__qa-components?view=preferences");
  await page.getByLabel("Workspace name").fill("Test workspace");
  await page.getByRole("button", { name: "Save preferences" }).click();
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "Your view has been saved." })
      .first(),
  ).toContainText("Your view has been saved.");
  await page.reload();
  await expect(page.getByLabel("Workspace name")).toHaveValue("Test workspace");
  await page.goto("/overview");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page
        .locator(".sidebar")
        .evaluate((el) => el.getBoundingClientRect().right),
    )
    .toBeLessThanOrEqual(0);
  await page.screenshot({
    path: "../.qa/dashboard-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page
    .locator(".sidebar")
    .getByRole("button", { name: "Sign out" })
    .click();
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
