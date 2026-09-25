import { expect, test } from "@playwright/test";

test("login, dashboard, SSE, mock lifecycle, settings and logout", async ({
  page,
}) => {
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
    page.getByRole("heading", { name: "Everything, in view." }),
  ).toBeVisible();
  await expect(page.locator(".badge.live")).toBeVisible();
  await expect(
    page
      .locator(".app-row-name strong")
      .filter({ hasText: "Foundation Test App" }),
  ).toBeVisible();
  await page.getByText("System details", { exact: true }).click();
  await expect(page.getByText("Core CPU", { exact: true })).toBeVisible();
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
  await page.screenshot({
    path: "../.qa/dashboard-desktop.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "Apps", exact: true }).click();
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
  await page.getByRole("link", { name: "Storage", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "No media folders registered" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Updates", exact: true }).click();
  const githubCheck = page.getByRole("button", {
    name: "Check GitHub",
    exact: true,
  });
  await expect(githubCheck).toBeEnabled();
  await githubCheck.click();
  await expect(
    page.getByRole("progressbar", { name: "Check MediaHub updates" }),
  ).toHaveAttribute("aria-valuenow", "100");
  const updateCards = page.locator(".updates-grid > .panel");
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
  await page.getByRole("link", { name: "App Store", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Add only what you need." }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "FjordHub" })).toBeVisible();
  const storeCards = page.locator(".store-grid > .store-card");
  await expect(storeCards).toHaveCount(4);
  const storeCardHeights = await storeCards.evaluateAll((cards) =>
    cards.map((card) => card.getBoundingClientRect().height),
  );
  expect(
    Math.max(...storeCardHeights) - Math.min(...storeCardHeights),
  ).toBeLessThan(2);
  await page.getByRole("link", { name: "Set up Cloudflare" }).click();
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
  const activeStoreNavigation = page.locator('nav a.active[href="/store"]');
  const navigationGroup = page.locator(".sidebar nav");
  await expect(activeStoreNavigation).toBeVisible();
  const [activeNavigationBox, navigationBox] = await Promise.all([
    activeStoreNavigation.boundingBox(),
    navigationGroup.boundingBox(),
  ]);
  expect(activeNavigationBox?.width).toBeCloseTo(navigationBox?.width || 0, 0);
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page.getByRole("tab", { name: "Maintenance", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Run maintenance check" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Run maintenance check", exact: true })
    .click();
  await expect(
    page.getByRole("progressbar", { name: "Maintenance check" }),
  ).toHaveAttribute("aria-valuenow", "100");
  await expect(
    page.getByText("Technical details", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("MediaHub Core", { exact: true })).toBeVisible();
  await expect(page.getByText("Media stays protected")).toBeVisible();
  await page.getByRole("tab", { name: "General", exact: true }).click();
  await page.getByLabel("Workspace name").fill("Test workspace");
  await page.getByRole("button", { name: "Save preferences" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Your view has been saved.",
  );
  await page.reload();
  await expect(page.getByLabel("Workspace name")).toHaveValue("Test workspace");
  await page.getByRole("link", { name: "Dashboard", exact: false }).click();
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
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
