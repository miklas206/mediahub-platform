import { expect, test } from "@playwright/test";

for (const width of [1440, 390]) {
  for (const operation of ["install", "rotate"] as const) {
    test(`one-time ${operation} login copying (${width}px)`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 1000 });
      const errors: string[] = [];
      const copies: unknown[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.route("**/api/**", async (route) => {
        const path = new URL(route.request().url()).pathname.replace(
          /^\/api(?:\/v1)?/,
          "",
        );
        let data: unknown = [];
        if (path === "/auth/status") data = { needsSetup: false };
        else if (path === "/setup/status") data = { setup_required: false };
        else if (path === "/auth/me")
          data = {
            id: "test",
            username: "synthetic-admin",
            role: "administrator",
            csrf: "test",
            language: "en",
            totpEnabled: true,
          };
        else if (path === "/settings")
          data = {
            display_name: "MediaHub",
            advanced_mode: false,
            visible_navigation: ["/", "/apps", "/store", "/settings"],
            dashboard_sections: [],
            theme: "dark",
          };
        else if (path === "/seedbox/wizard/targets")
          data = { bound: true, hosts: [] };
        else if (path === "/seedbox/wizard")
          data = {
            revision: 7,
            step: operation === "install" ? 7 : 12,
            steps: [
              "Overview",
              "Target Host",
              "Storage",
              "VPN Provider",
              "VPN Configuration",
              "Port Forwarding",
              "qBittorrent Configuration",
              "Credentials",
              "Review",
              "Preflight",
              "Install",
              "Verify",
              "Complete",
            ],
            busy: false,
            installation: {
              hostId: "test",
              downloadsStorageId: "downloads",
              provider: "test",
              protocol: "wireguard",
              uid: 1000,
              gid: 1000,
              webPort: 8080,
              torrentMemoryMiB: 1024,
              installationId: "test",
            },
            qBittorrent: {},
            vpnConfigured: true,
            clientConfigured: true,
            transaction: { state: "Healthy", steps: [] },
          };
        else if (path === "/seedbox/wizard/client/mediahub") {
          copies.push(route.request().postDataJSON());
          data = { accepted: true };
        } else if (path === "/events/stream") {
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
      await page.goto("/apps/install/seedbox");
      if (operation === "rotate")
        await page
          .getByText("Rotate private credentials", { exact: true })
          .click();
      await page.getByText("Use my MediaHub login", { exact: true }).click();
      await expect(
        page.getByLabel("MediaHub username", { exact: true }),
      ).toHaveValue("synthetic-admin");
      await expect(
        page.getByLabel("MediaHub username", { exact: true }),
      ).toHaveAttribute("readonly", "");
      expect(copies).toEqual([]);
      await page
        .getByLabel("Current MediaHub password", { exact: true })
        .fill("synthetic-test-password-123!");
      await page
        .getByLabel("Authenticator or recovery code", { exact: true })
        .fill("synthetic-code");
      await page
        .getByRole("button", {
          name:
            operation === "install"
              ? "Copy login for installation"
              : "Copy login & rotate qBittorrent credentials",
          exact: true,
        })
        .click();
      await expect.poll(() => copies.length).toBe(1);
      expect(copies[0]).toEqual({
        revision: 7,
        operation,
        password: "synthetic-test-password-123!",
        secondFactor: "synthetic-code",
      });
      await expect(
        page.getByLabel("Current MediaHub password", { exact: true }),
      ).toHaveValue("");
      await expect(
        page.getByLabel("Authenticator or recovery code", { exact: true }),
      ).toHaveValue("");
      await expect(
        page.getByText(
          operation === "install"
            ? "Encrypted client credentials saved for installation."
            : "Credential rotation accepted. Check Seedbox installation status for verification or recovery before using the new login.",
          { exact: true },
        ),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      expect(errors).toEqual([]);
    });
  }
}
