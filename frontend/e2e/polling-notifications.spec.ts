import { expect, test } from "@playwright/test";

test("expired healthy Plex observations stay neutral while genuine failures remain visible", async ({
  page,
}) => {
  await page.clock.install();
  await page.addInitScript(() => {
    window.EventSource = class extends EventTarget {
      close() {}
    } as unknown as typeof EventSource;
  });
  let runtimeReads = 0,
    hold = false;
  let finish: ((value: string) => void) | undefined;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(
      /^\/api(?:\/v1)?/,
      "",
    );
    let data: unknown = [];
    if (path === "/auth/status") data = { needsSetup: false };
    else if (path === "/auth/me")
      data = {
        id: "synthetic",
        username: "tester",
        role: "administrator",
        csrf: "synthetic",
        language: "en",
      };
    else if (path === "/setup/status") data = { setup_required: false };
    else if (path === "/settings")
      data = {
        display_name: "MediaHub",
        theme: "dark",
        visible_navigation: ["/", "/settings"],
        dashboard_sections: [],
      };
    else if (path === "/updates/summary")
      data = { count: 0, items: [], notifications: [] };
    else if (path === "/apps")
      data = [
        {
          id: "plex-stable",
          packageId: "org.mediahub.plex",
          name: "Plex",
          state: "running",
          isMock: false,
          version: "1",
          detailPath: "/apps/plex-stable",
          health: { status: "healthy", summary: "Ready", checks: [] },
        },
      ];
    else if (path === "/apps/plex-stable/runtime") {
      runtimeReads++;
      const health = !hold
        ? "healthy"
        : await new Promise<string>((resolve) => {
            finish = resolve;
          });
      data = {
        view: "plex",
        report: {
          available: true,
          health,
          cached: false,
          agentOnline: true,
          checks: [
            {
              name: "storage",
              status: health === "healthy" ? "healthy" : "critical",
              message:
                health === "healthy"
                  ? "Storage ready"
                  : "Synthetic storage failure",
            },
          ],
          plex: {
            running: true,
            claimed: true,
            version: "1",
            libraries: [],
            activeStreams: 0,
            memoryBytes: null,
            cpuPercent: null,
          },
        },
      };
    } else if (path === "/apps/plex-stable/plex/recent-media")
      data = { supported: true, items: [] };
    else if (path === "/plex/account")
      data = { claimed: true, operation: { state: "idle", message: "" } };
    else if (path === "/vpn-gateway")
      data = { configured: false, enabled: false, zones: [], routes: [] };
    else if (path === "/app-settings/org.mediahub.plex")
      data = {
        name: "Plex",
        packageId: "org.mediahub.plex",
        running: true,
        controls: { actions: [], logs: false, updateCheck: false },
      };
    else if (path === "/events/stream")
      return route.fulfill({
        contentType: "text/event-stream",
        body: ": connected\n\n",
      });
    await route.fulfill({ json: { data } });
  });
  await page.goto("/apps/plex-stable");
  await expect(page.locator(".runtime-summary")).toBeVisible();
  await expect(page.locator(".runtime-issues")).toHaveCount(0);
  const baseline = runtimeReads;
  hold = true;
  for (let cycle = 0; cycle < 3; cycle++) {
    await page.clock.runFor(10100);
    await expect.poll(() => runtimeReads).toBe(baseline + cycle + 1);
    await expect(page.locator(".runtime-health").first()).toContainText(
      "Last observation:",
    );
    await expect(page.locator(".runtime-issues")).toHaveCount(0);
    await expect(page.locator(".notification-popup.danger")).toHaveCount(0);
    finish?.("healthy");
    await expect(page.locator(".runtime-health").first()).not.toContainText(
      "Last observation:",
    );
  }
  await page.clock.runFor(10100);
  await expect.poll(() => runtimeReads).toBe(baseline + 4);
  finish?.("critical");
  await expect(page.locator(".runtime-issues")).toContainText(
    "Synthetic storage failure",
  );
});

test("repeated polling retains one error incident, allows slow reads and clears state on a real recovery", async ({
  page,
}) => {
  test.setTimeout(60000);
  let mode: "failed" | "healthy" | "slow" = "failed",
    reads = 0,
    finish: (() => void) | undefined;
  let slowHandled = false;
  await page.route("**/api/**", async (route) => {
    if (new URL(route.request().url()).pathname.endsWith("/test/polling")) {
      const requestMode = mode;
      reads++;
      if (mode === "failed")
        return route.fulfill({
          status: 503,
          json: { error: { message: "Synthetic persistent failure" } },
        });
      if (mode === "slow")
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
      await route.fulfill({
        json: { data: requestMode === "slow" ? "obsolete" : "healthy" },
      });
      if (requestMode === "slow") slowHandled = true;
      return;
    }
    await route.fulfill({ json: { data: { needsSetup: true } } });
  });
  await page.goto("/");
  await page.evaluate(async () => {
    const load = (path: string) => import(/* @vite-ignore */ path);
    const React = (await load("/node_modules/.vite/deps/react.js")).default;
    const client = (await load("/node_modules/.vite/deps/react-dom_client.js"))
      .default;
    const { useData } = await load("/src/use-data.ts");
    const { NotificationProvider, NotificationPopup } = await load(
      "/src/notification-popup.tsx",
    );
    document.querySelector<HTMLElement>("#root")!.style.display = "none";
    const host = document.createElement("div");
    document.body.append(host);
    function Probe() {
      const state = useData("/test/polling");
      return React.createElement(
        React.Fragment,
        null,
        state.error &&
          React.createElement(
            NotificationPopup,
            { tone: "danger" },
            state.error,
          ),
        React.createElement("output", { id: "probe-error" }, state.error),
        React.createElement("output", { id: "probe-data" }, state.data || ""),
        React.createElement(
          "button",
          { id: "probe-refresh", onClick: state.poll },
          "Poll",
        ),
        React.createElement(
          "button",
          { id: "probe-force", onClick: state.reload },
          "Reload after action",
        ),
      );
    }
    client
      .createRoot(host)
      .render(
        React.createElement(
          NotificationProvider,
          null,
          React.createElement(Probe),
        ),
      );
  });
  const error = page.locator("#probe-error");
  await expect(error).toHaveText("Synthetic persistent failure", {
    timeout: 8000,
  });
  const popup = page.locator(".notification-popup.danger");
  await expect(popup).toHaveCount(1);
  await popup.hover();
  for (let cycle = 0; cycle < 2; cycle++) {
    const previous = reads;
    await page.locator("#probe-refresh").click();
    await expect(error).toHaveText("Synthetic persistent failure");
    await expect.poll(() => reads, { timeout: 8000 }).toBe(previous + 3);
    await expect(popup).toHaveCount(1);
  }
  mode = "healthy";
  await page.locator("#probe-refresh").click();
  await expect(error).toBeEmpty();
  await expect(page.locator("#probe-data")).toHaveText("healthy");
  mode = "slow";
  const before = reads;
  await page.locator("#probe-refresh").click();
  await expect.poll(() => reads).toBe(before + 1);
  await page.locator("#probe-refresh").click({ clickCount: 4 });
  await page.waitForTimeout(100);
  expect(reads).toBe(before + 1);
  const oldFinish = finish;
  mode = "healthy";
  await page.locator("#probe-force").click();
  await expect.poll(() => reads).toBe(before + 2);
  await expect(page.locator("#probe-data")).toHaveText("healthy");
  oldFinish?.();
  await expect.poll(() => slowHandled).toBe(true);
  await expect(page.locator("#probe-data")).toHaveText("healthy");
  await expect(error).toBeEmpty();
});
