import { expect, test, type Page } from "@playwright/test";
test.use({ channel: "chromium" });
test.beforeEach(() => {
  test.skip(
    !process.env.MEDIAVPN_QA_URL,
    "Requires isolated MediaVPN static server",
  );
});
const profile = {
  id: "a".repeat(24),
  name: "Mediahub",
  state: "connected",
  healthy: true,
  country: "Sweden",
  publicIp: "198.51.100.8",
  forwardedPort: 45000,
  endpoint: "192.0.2.1",
  port: 51820,
  port_forwarding: true,
};
async function mock(
  page: Page,
  language = "en",
  plex = false,
  gate?: Promise<void>,
) {
  const writes: Array<{ path: string; body: unknown }> = [];
  const gateway = {
    configured: true,
    enabled: true,
    profileId: profile.id,
    accountId: "b".repeat(32),
    apps: [
      { packageId: "mediahub", name: "MediaHub" },
      ...(plex ? [{ packageId: "org.mediahub.plex", name: "Plex" }] : []),
    ],
    zones: [{ id: "c".repeat(32), name: "example.com" }],
    routes: [
      {
        id: "d".repeat(32),
        packageId: "mediahub",
        zoneId: "c".repeat(32),
        label: "hub",
        hostname: "hub.example.com",
        httpsVerified: true,
      },
    ],
    gateway: {
      providerReady: true,
      ready: true,
      publicIp: profile.publicIp,
      prerequisites: [],
    },
    checks: [
      {
        id: "tun",
        state: "ready",
        message: "TUN character device is readable and writable",
      },
    ],
    issues: [],
    plexPort: { available: plex, enabled: false, ready: false },
  };
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = {};
    if (path === "/api/auth/status")
      data = { managed: true, needsSetup: false };
    else if (path === "/api/auth/me")
      data = { id: "admin", role: "administrator", language, csrf: "test" };
    else if (path === "/api/runtime")
      data = { enabled: true, mediaSeedConnected: true };
    else if (path === "/api/profiles") data = [profile];
    else if (path === "/api/hub-apps")
      data = {
        gateway: {
          enabled: true,
          ready: true,
          profileId: profile.id,
          profiles: [profile],
        },
        apps: plex
          ? [{ id: "plex", name: "Plex", enabled: true, ready: true }]
          : [],
      };
    else if (path.startsWith("/api/hub-web-gateway")) {
      if (path === "/api/hub-web-gateway" && gate) await gate;
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON();
        writes.push({ path, body });
        if (path.endsWith("/plex-port"))
          gateway.plexPort = {
            ...gateway.plexPort,
            enabled: body.enabled,
            ready: false,
          };
      }
      data = gateway;
    }
    await route.fulfill({ json: data });
  });
  return writes;
}
for (const width of [1440, 390, 320])
  for (const language of ["en", "da"])
    test(`compact MediaVPN tabs ${width}px ${language}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 950 });
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await mock(page, language);
      await page.goto(process.env.MEDIAVPN_QA_URL! + "/");
      await expect(page.locator("#profiles h2")).toHaveText("Mediahub");
      await expect(page.locator("#panel-connection")).toBeVisible();
      await expect(page.locator("#panel-apps")).toBeHidden();
      await expect(page.locator(".profile-more")).not.toHaveAttribute("open");
      await page.locator("#tab-apps").click();
      await expect(page.locator(".compact-route")).toContainText(
        "hub.example.com",
      );
      await expect(page.locator("#panel-connection")).toBeHidden();
      await expect(page.locator(".plex-port-card input")).toBeDisabled();
      if (language === "da" && width !== 320)
        await page.screenshot({
          path: test.info().outputPath("apps-tabs.png"),
          fullPage: true,
        });
      await page.locator("#tab-settings").click();
      await expect(page.locator("#panel-settings #web-gateway")).toBeVisible();
      await page.locator("#tab-connection").focus();
      await page.keyboard.press("ArrowRight");
      await expect(page.locator("#tab-apps")).toHaveAttribute(
        "aria-selected",
        "true",
      );
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      expect(errors).toEqual([]);
    });
test("profiles render while the gateway request is still pending", async ({
  page,
}) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await mock(page, "en", false, gate);
  await page.goto(process.env.MEDIAVPN_QA_URL! + "/");
  await expect(page.locator("#profiles h2")).toHaveText("Mediahub", {
    timeout: 2000,
  });
  await expect(page.locator("#panel-connection .app-connections")).toHaveCount(0);
  await page.locator("#tab-apps").click();
  await expect(page.locator(".gateway-loading")).toBeVisible();
  release();
  await expect(page.locator(".compact-route")).toBeVisible();
  await page.locator("#tab-connection").click();
  await expect(page.locator("#panel-connection .app-connections")).toHaveCount(0);
});
test("Plex port choice sends only an enable flag and stays pending until verified", async ({
  page,
}) => {
  const writes = await mock(page, "en", true);
  await page.goto(process.env.MEDIAVPN_QA_URL! + "/");
  await page.locator("#tab-apps").click();
  const toggle = page.locator(".plex-port-card input");
  await expect(toggle).toBeEnabled();
  await toggle.check();
  await expect(toggle).toBeChecked();
  expect(writes).toEqual([
    { path: "/api/hub-web-gateway/plex-port", body: { enabled: true } },
  ]);
  await expect(page.locator(".plex-port-card")).toContainText(
    "Waiting for a separate verified Plex TCP port",
  );
  await toggle.uncheck();
  await expect(toggle).not.toBeChecked();
});
