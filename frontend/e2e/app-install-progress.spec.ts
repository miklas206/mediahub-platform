import { expect, test, type Page, type Route } from "@playwright/test";

test.use({ channel: "chromium" });

async function mockHub(
  page: Page,
  handler: (path: string, route: Route) => Promise<unknown> | unknown,
  language = "en",
) {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(
      /^\/api(?:\/v1)?/,
      "",
    );
    if (path === "/events/stream") {
      await route.fulfill({
        contentType: "text/event-stream",
        body: "retry: 60000\n\n",
      });
      return;
    }
    const defaults: Record<string, unknown> = {
      "/auth/status": { needsSetup: false },
      "/setup/status": { setup_required: false },
      "/auth/me": {
        id: "admin",
        username: "tester",
        role: "administrator",
        csrf: "test",
        language,
      },
      "/settings": {
        display_name: "MediaHub",
        theme: "dark",
        visible_navigation: ["/", "/overview", "/settings"],
        dashboard_sections: [],
      },
      "/updates/summary": { count: 0, items: [], notifications: [] },
      "/fjordhub/deployment": null,
      "/hosts": [{ id: "local", name: "Local host" }],
    };
    const data = await handler(path, route);
    if (data === "handled") return;
    await route.fulfill({
      json: {
        data: data === undefined ? (defaults[path] ?? []) : data,
        error: null,
      },
    });
  });
}

for (const language of ["en", "da"])
  for (const width of [1440, 390, 320]) {
    test(`Plex follows background phases, reload and reconnect (${language}, ${width}px)`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 950 });
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      let operation: Record<string, unknown> = { state: "idle" };
      let disconnected = false;
      let posts = 0;
      await mockHub(
        page,
        async (path, route) => {
          if (path === "/plex/install-options")
            return {
              hostId: "local",
              storage: [
                { id: "movies", label: "Films", kind: "movies" },
                { id: "config", label: "App disk", kind: "appdata" },
              ],
            };
          if (path === "/plex/install-plan")
            return { planDigest: "a".repeat(64) };
          if (path === "/plex/install") {
            posts++;
            operation = {
              action: "install",
              state: "running",
              phase: "download",
              progress: 10,
              indeterminate: true,
              message: "Downloading app image",
            };
            return { state: "accepted" };
          }
          if (path === "/plex/install-status") {
            if (disconnected) {
              await route.fulfill({
                status: 503,
                json: {
                  data: null,
                  error: { message: "Synthetic connection loss" },
                },
              });
              return "handled";
            }
            return { operation };
          }
        },
        language,
      );
      await page.goto("/apps/install/plex");
      await page.getByRole("checkbox").check();
      await page.getByRole("combobox").selectOption("config");
      await page
        .getByRole("button", {
          name:
            language === "da" ? "Gennemgå installationen" : "Review installation",
          exact: true,
        })
        .click();
      await page
        .getByRole("button", {
          name: language === "da" ? "Installer Plex" : "Install Plex",
          exact: true,
        })
        .click();
      const bar = page.getByRole("progressbar");
      await expect(bar).toBeVisible();
      await expect(bar).not.toHaveAttribute("aria-valuenow");
      await page.reload();
      await expect(bar).toBeVisible();
      if (language === "da" && width === 320)
        await page.screenshot({path: test.info().outputPath("plex-progress-da-320.png"), fullPage: true});
      operation = {
        ...operation,
        phase: "container",
        progress: 80,
        indeterminate: false,
        message: "Creating app container",
      };
      await expect(bar).toHaveAttribute("aria-valuenow", "80");
      disconnected = true;
      await expect(bar).not.toHaveAttribute("aria-valuenow");
      await expect(bar).toHaveAttribute("aria-valuetext", /80/);
      disconnected = false;
      operation = {
        ...operation,
        state: "succeeded",
        phase: "complete",
        progress: 100,
        message: "Plex started; account and libraries are being checked",
      };
      await expect(bar).toHaveAttribute("aria-valuenow", "100");
      expect(posts).toBe(1);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
      ).toBe(true);
      expect(errors).toEqual([]);
    });
  }

for (const app of ["jellyfin", "prowlarr", "radarr", "sonarr", "autobrr"]) {
  test(`${app} retains installation progress after reload`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 320, height: 950 });
    let accepted = false;
    let installation: unknown;
    let phase = "download";
    await mockHub(page, (path, route) => {
      if (path === "/apps")
        return accepted
          ? [
              {
                id: app,
                packageId: `org.mediahub.${app}`,
                state: "starting",
                isMock: false,
              },
            ]
          : [];
      if (path === `/container-apps/${app}/install-options`)
        return {
          hostId: "local",
          port: 8096,
          slots: [{ id: "appdata", required: true }],
          storage: [{ id: "config", label: "App disk", kind: "appdata" }],
        };
      if (path === "/container-apps/install-plan") {
        installation = route.request().postDataJSON();
        return {
          planDigest: "a".repeat(64),
          installation,
          mounts: [],
          url: "http://192.0.2.1:8096",
        };
      }
      if (path === "/container-apps/install") {
        accepted = true;
        return { state: "accepted" };
      }
      if (path === `/container-apps/${app}/status`)
        return {
          state: phase === "complete" ? "running" : "installing",
          installation,
          operation: {
            state: phase === "complete" ? "installed" : "installing",
            phase,
            progress: phase === "complete" ? 100 : 10,
            indeterminate: phase === "download",
          },
        };
    });
    await page.goto(`/apps/install/${app}`);
    await page
      .getByLabel("App data storage", { exact: false })
      .selectOption("config");
    await page
      .getByRole("button", { name: "Review installation", exact: true })
      .click();
    await page.getByRole("button", { name: /^Install / }).click();
    const bar = page.getByRole("progressbar");
    await expect(bar).toBeVisible();
    await expect(bar).not.toHaveAttribute("aria-valuenow");
    await page.reload();
    await expect(bar).toBeVisible();
    phase = "complete";
    await expect(bar).toHaveAttribute("aria-valuenow", "100");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBe(true);
  });
}

for (const app of ["mediaseed", "mediavpn"]) {
  test(`${app} polling recovers after an exhausted status request`, async ({
    page,
  }) => {
    let accepted = false;
    let failures = 0;
    let complete = false;
    await mockHub(page, async (path, route) => {
      if (path === "/managed-install/prerequisites") return { state: "ready" };
      if (path === `/managed-install/org.mediahub.${app}`) {
        const operation = {
          operationId: accepted ? "test-job" : undefined,
          state: complete ? "succeeded" : accepted ? "running" : "idle",
          phase: complete ? "registering" : "containers",
          progress: complete ? 100 : 35,
        };
        if (route.request().method() === "POST") {
          accepted = true;
          return { ...operation, operationId: "test-job", state: "accepted" };
        }
        if (accepted && failures < 3) {
          failures++;
          await route.fulfill({
            status: 503,
            json: {
              data: null,
              error: { message: "Synthetic connection loss" },
            },
          });
          return "handled";
        }
        return {
          planDigest: "a".repeat(64),
          alreadyRunning: complete,
          operation,
        };
      }
    });
    await page.goto(`/store/${app}`);
    await page.getByRole("button", { name: /^Install Media/ }).click();
    await expect(page.getByRole("progressbar")).toBeVisible();
    await expect.poll(() => failures).toBe(3);
    complete = true;
    await expect(page.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "100",
      { timeout: 12000 },
    );
  });
}

test("FjordHub restores visible progress for an ongoing deployment", async ({page}) => {
  await page.setViewportSize({width: 320, height: 950});
  await mockHub(page, path => {
    if (path === "/fjordhub/deployment") return {id: "job", state: "running", host: "192.0.2.1", message: "Installing FjordHub", logs: [], config: {}};
  });
  await page.goto("/store/fjordhub");
  await expect(page.getByRole("progressbar")).toBeVisible();
  await expect(page.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  await page.reload();
  await expect(page.getByRole("progressbar")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

test("Legacy Seedbox displays observed transaction progress after reload", async ({page}) => {
  await page.setViewportSize({width: 320, height: 950});
  await mockHub(page, path => {
    if (path === "/seedbox/wizard/targets") return {bound: true, hosts: []};
    if (path === "/seedbox/wizard") return {
      revision: 1, step: 11, busy: true, steps: Array.from({length: 13}, (_, i) => `Step ${i}`),
      vpnConfigured: true, clientConfigured: true, transaction: {state: "Installing", steps: [{id: "preflight", state: "Succeeded"}, {id: "verify_api", state: "Running"}]},
    };
  });
  await page.goto("/apps/install/seedbox");
  await expect(page.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
  await page.reload();
  await expect(page.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

test("Failed Plex can be removed after a transient status failure", async ({page}) => {
  await page.setViewportSize({width: 320, height: 950});
  let removed = false;
  let statusCalls = 0;
  let posts = 0;
  await mockHub(page, async (path, route) => {
    if (path === "/catalog") return [{id: "org.mediahub.plex", name: "Plex", availability: "available"}];
    if (path === "/apps") return removed ? [] : [{id: "plex", name: "Plex", packageId: "org.mediahub.plex", state: "failed", isMock: false, removable: true, health: {status: "unknown", summary: "Failed install", checks: []}}];
    if (path === "/apps/plex/uninstall") {
      if (route.request().method() === "POST") {
        expect(route.request().postDataJSON()).toEqual({confirmedInstallationId: "plex-test"});
        posts++;
        removed = true;
        return {state: "accepted", installationId: "plex-test"};
      }
      if (statusCalls++ === 0) {
        await route.fulfill({status: 503, json: {data: null, error: {message: "Synthetic connection loss"}}});
        return "handled";
      }
      return {state: removed ? "succeeded" : "ready", installationId: "plex-test", dataPreserved: true};
    }
  });
  await page.goto("/");
  await page.getByRole("button", {name: "Uninstall: Plex", exact: true}).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  const confirm = page.getByRole("button", {name: "Confirm removal", exact: true});
  await expect(confirm).toBeEnabled({timeout: 8000});
  expect(posts).toBe(0);
  await confirm.click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", {name: "Uninstall: Plex", exact: true})).toHaveCount(0);
  expect(posts).toBe(1);
});

for (const language of ["en", "da"]) for (const width of [1440, 320]) test(`MediaVPN removal explains dependencies and exposes disconnect controls (${language}, ${width}px)`, async ({page}) => {
  await page.setViewportSize({width, height: 950});
  let connected = true;
  const writes: string[] = [];
  await mockHub(page, (path, route) => {
    if (route.request().method() !== "GET") writes.push(path);
    if (path === "/catalog") return [{id: "org.mediahub.mediavpn", availability: "available"}];
    if (path === "/apps") return [{id: "vpn", name: "MediaVPN", packageId: "org.mediahub.mediavpn", state: "running", isMock: false, removable: true}];
    if (path === "/mediavpn/status") return {configured: true, available: true, url: "https://vpn.example.test"};
    if (path === "/managed-install/prerequisites") return {state: "ready"};
    if (path === "/managed-install/org.mediahub.mediavpn") return {planDigest: "a".repeat(64), alreadyRunning: true, operation: {state: "idle"}};
    if (path === "/apps/vpn/uninstall") return connected
      ? {state: "blocked", message: "Disconnect Plex and Jellyfin from shared VPN before removing MediaVPN", configurationPath: "/store/mediavpn"}
      : {state: "ready", installationId: "verified-identity"};
    if (path === "/shared-vpn/apps/jellyfin") {
      expect(route.request().method()).toBe("PUT");
      expect(route.request().postDataJSON()).toEqual({enabled: false});
      connected = false;
      return {};
    }
    if (path === "/shared-vpn") return {
      gateway: {enabled: true, ready: true, profileId: "test-profile", profiles: [], publicIp: null, message: null},
      apps: [{id: "jellyfin", name: "Jellyfin", hostId: "local", enabled: connected, ready: connected, phase: "ready"}],
    };
  }, language);
  await page.goto("/");
  const removalName = language === "da" ? "Afinstaller: MediaVPN" : "Uninstall: MediaVPN";
  const confirmationName = language === "da" ? "Bekræft fjernelse" : "Confirm removal";
  await page.getByRole("button", {name: removalName, exact: true}).click();
  await expect(page.getByRole("button", {name: confirmationName, exact: true})).toBeDisabled();
  await expect(page.getByText(language === "da" ? "Frakobl Plex og Jellyfin fra den fælles VPN, før du afinstallerer MediaVPN" : "Disconnect Plex and Jellyfin from shared VPN before removing MediaVPN", {exact: true})).toBeVisible();
  expect(writes).toEqual([]);
  await page.getByRole("link", {name: language === "da" ? "Administrér apps' VPN-forbindelser" : "Manage app VPN connections"}).click();
  await expect(page.getByRole("heading", {name: language === "da" ? "Apps' VPN-forbindelser" : "App VPN connections"})).toBeVisible();
  await page.getByRole("checkbox", {name: language === "da" ? "Brug fælles VPN" : "Use shared VPN"}).uncheck();
  await expect.poll(() => connected).toBe(false);
  await page.goto("/");
  await page.getByRole("button", {name: removalName, exact: true}).click();
  await expect(page.getByRole("button", {name: confirmationName, exact: true})).toBeEnabled();
  expect(writes).toEqual(["/shared-vpn/apps/jellyfin"]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});
