import { expect, test } from "@playwright/test";
import { textOutsideCards } from "./text-containment";

for (const name of ["MediaSeed", "MediaVPN"])
  for (const width of [1440, 390, 320])
    test(`${name} home stop and status controls ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      const packageId =
        name === "MediaSeed"
          ? "org.mediahub.mediaseed"
          : "org.mediahub.mediavpn";
      const cardId = name === "MediaSeed" ? "org.mediahub.seedbox" : packageId;
      let running = true;
      const actions: string[] = [];
      await page.route("**/api/**", async (route) => {
        const path = new URL(route.request().url()).pathname.replace(
          /^\/api(?:\/v1)?/,
          "",
        );
        let data: unknown = [];
        const app = {
          id: "owned-app",
          packageId,
          name,
          isMock: false,
          state: running ? "running" : "stopped",
          version: "1",
          running,
          startedAt: new Date(Date.now() - 50000).toISOString(),
          observedAt: Date.now() / 1000,
          localUrl: "https://192.168.1.50:18803",
          externalUrl: "https://app.example.com",
          controls: {
            actions: ["start", "stop", "restart"],
            logs: true,
            updateCheck: true,
            updatePath: "/settings?section=Updates",
          },
          health: { status: "healthy", summary: "Running", checks: [] },
        };
        if (path === "/auth/status") data = { needsSetup: false };
        else if (path === "/setup/status") data = { setup_required: false };
        else if (path === "/auth/me")
          data = {
            id: "admin",
            username: "tester",
            role: "administrator",
            csrf: "test",
            language: "en",
          };
        else if (path === "/settings")
          data = {
            display_name: "MediaHub",
            theme: "dark",
            visible_navigation: ["/", "/settings"],
            dashboard_sections: [],
          };
        else if (path === "/updates/summary")
          data = { count: 0, items: [], notifications: [] };
        else if (path === "/catalog")
          data = [
            {
              id: "org.mediahub.seedbox",
              name: "MediaSeed",
              availability: "available",
            },
          ];
        else if (path === "/apps") data = [app];
        else if (path === "/fjordhub/deployment") data = null;
        else if (path === "/mediaseed/status" || path === "/mediavpn/status")
          data = {
            configured: path.includes(name.toLowerCase()),
            available: true,
            url: "https://192.168.1.50:18803",
          };
        else if (path === "/app-settings/" + packageId)
          data = {
            ...app,
            installationId: app.id,
            ssoManaged: true,
            configurationPath: null,
          };
        else if (path.startsWith("/apps/owned-app/actions/")) {
          const action = path.split("/").at(-1)!;
          actions.push(action);
          running = action !== "stop";
          data = { state: running ? "running" : "stopped" };
        } else if (path === "/apps/owned-app/logs")
          data = {
            entries: [
              {
                timestamp: Date.now() / 1000,
                message: "Recorded app control event",
              },
            ],
          };
        else if (path === "/apps/owned-app/update-check")
          data = { message: "Bundled app is current" };
        else if (path === "/events/stream")
          return route.fulfill({
            contentType: "text/event-stream",
            body: ": connected\n\n",
          });
        await route.fulfill({ json: { data } });
      });
      await page.goto("/");
      const card = page.locator(`[data-app-id="${cardId}"]`);
      const footer = card.locator(".hub-card-footer");
      const stop = footer.getByRole("button", {
        name: `Stop ${name}`,
        exact: true,
      });
      await expect(stop).toBeVisible();
      const openBox = await footer.locator(".hub-card-action").boundingBox();
      const stopBox = await stop.boundingBox();
      const settingsBox = await footer
        .locator(".hub-card-settings")
        .boundingBox();
      expect(Math.abs(openBox!.y - stopBox!.y)).toBeLessThan(2);
      expect(Math.abs(settingsBox!.y - stopBox!.y)).toBeLessThan(2);
      expect(stopBox!.width).toBeLessThan(130);
      await page.screenshot({
        path: test.info().outputPath("compact-stop-home.png"),
        fullPage: true,
      });
      await card
        .getByRole("button", { name: `Stop ${name}`, exact: true })
        .click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      if (name === "MediaVPN")
        await expect(dialog).toContainText("public domains will lose access");
      expect(actions).toEqual([]);
      await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
      expect(actions).toEqual([]);
      await card
        .getByRole("button", { name: `Stop ${name}`, exact: true })
        .click();
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "Continue", exact: true })
        .click();
      await expect.poll(() => actions).toEqual(["stop"]);
      await expect(
        card.getByRole("button", { name: `Stop ${name}`, exact: true }),
      ).toBeDisabled();
      await card
        .getByRole("link", { name: `Settings: ${name}`, exact: true })
        .click();
      const controls = page.locator(".app-control-panel");
      await expect(controls).toBeVisible();
      await controls
        .getByRole("button", { name: `Start ${name}`, exact: true })
        .click();
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "Continue", exact: true })
        .click();
      await expect.poll(() => actions).toEqual(["stop", "start"]);
      await controls
        .getByRole("button", { name: "View logs", exact: true })
        .click();
      await expect(controls).toContainText("Recorded app control event");
      await controls
        .getByRole("button", { name: "Check for updates", exact: true })
        .click();
      await expect(
        page.getByText("Bundled app is current", { exact: true }),
      ).toBeVisible();
      await expect(
        controls.getByRole("link", { name: "Update app", exact: true }),
      ).toHaveAttribute("href", "/settings?section=Updates");
      expect(await textOutsideCards(page)).toEqual([]);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: test.info().outputPath("runtime-controls.png"),
        fullPage: true,
      });
    });
