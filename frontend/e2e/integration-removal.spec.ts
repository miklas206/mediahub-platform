import { expect, test } from "@playwright/test";
import type { Integration } from "../src/integrations";

for (const width of [1440, 390]) {
  test(`Danish integration removal cancel, error and selected success at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() => {
      window.EventSource = class {
        addEventListener() {}
        close() {}
      } as unknown as typeof EventSource;
    });
    let items: Integration[] = [
      {
        id: "unused-one",
        name: "Unused FjordHub",
        baseUrl: "http://192.168.1.20:8888",
        enabled: false,
        allowHttp: true,
        tokenConfigured: false,
        snapshot: { status: "disconnected" },
        nextSync: 0,
        lastSuccessfulSync: null,
      },
      {
        id: "unused-two",
        name: "Other FjordHub",
        baseUrl: "http://192.168.1.21:8888",
        enabled: false,
        allowHttp: true,
        tokenConfigured: false,
        snapshot: { status: "disconnected" },
        nextSync: 0,
        lastSuccessfulSync: null,
      },
      {
        id: "active",
        name: "Active FjordHub",
        baseUrl: "http://192.168.1.22:8888",
        enabled: true,
        allowHttp: true,
        tokenConfigured: true,
        snapshot: { status: "online" },
        nextSync: 0,
        lastSuccessfulSync: null,
      },
      {
        id: "environment",
        name: "Environment FjordHub",
        baseUrl: "http://192.168.1.23:8888",
        enabled: false,
        allowHttp: true,
        tokenConfigured: false,
        managedByEnvironment: true,
        snapshot: { status: "disconnected" },
        nextSync: 0,
        lastSuccessfulSync: null,
      },
    ];
    const deletes: string[] = [];
    let failRemoval = true;
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname.replace(
        /^\/api\/v1/,
        "",
      );
      let data: unknown = [];
      if (path === "/auth/status") data = { needsSetup: false };
      if (path === "/setup/status") data = { setup_required: false };
      if (path === "/auth/me")
        data = {
          id: "admin",
          username: "tester",
          role: "administrator",
          csrf: "fixture-csrf",
          language: "da",
          appearance: null,
        };
      if (path === "/auth/preferences")
        data = { language: "da", appearance: null };
      if (path === "/settings")
        data = {
          display_name: "MediaHub",
          theme: "dark",
          advanced_mode: false,
          visible_navigation: ["/integrations", "/apps"],
          dashboard_sections: [],
        };
      if (path === "/integrations") data = items;
      if (path === "/integrations/fjordhub/defaults") data = { baseUrl: null };
      if (path === "/updates/summary") data = { count: 0 };
      if (route.request().method() === "DELETE") {
        deletes.push(path);
        expect(route.request().headers()["x-mediahub-csrf"]).toBe(
          "fixture-csrf",
        );
        if (failRemoval) {
          await route.fulfill({
            status: 409,
            json: {
              error: {
                code: "fixture_error",
                message: "Removal failed safely",
              },
            },
          });
          return;
        }
        expect(path).toBe("/integrations/unused-one");
        items = items.filter((row) => row.id !== "unused-one");
        data = { id: "unused-one", removed: true };
      }
      await route.fulfill({ json: { data } });
    });
    await page.goto("/integrations");
    const panel = page.locator(".panel").filter({
      has: page.getByRole("heading", {
        name: "Unused FjordHub",
        exact: true,
      }),
    });
    const remove = panel.getByRole("button", {
      name: "Fjern integration permanent",
      exact: true,
    });
    await expect(remove).toBeEnabled();
    for (const name of ["Active FjordHub", "Environment FjordHub"]) {
      await expect(
        page
          .locator(".panel")
          .filter({ has: page.getByRole("heading", { name, exact: true }) })
          .getByRole("button", {
            name: "Fjern integration permanent",
            exact: true,
          }),
      ).toBeDisabled();
    }
    await remove.click();
    const dialog = page.getByRole("dialog", {
      name: "Fjern integrationen permanent?",
    });
    await expect(dialog).toContainText("Unused FjordHub");
    await expect(dialog).toContainText("http://192.168.1.20:8888");
    await expect(dialog).toContainText(
      "bliver ikke afinstalleret eller ændret",
    );
    await dialog.getByRole("button", { name: "Annuller", exact: true }).click();
    await expect(dialog).not.toBeVisible();
    expect(deletes).toEqual([]);
    await expect(remove).toBeFocused();
    await remove.click();
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    expect(deletes).toEqual([]);
    await remove.click();
    await dialog
      .getByRole("button", { name: "Fjern integration permanent", exact: true })
      .click();
    await expect(dialog).toContainText("Removal failed safely");
    await expect(panel).toBeVisible();
    failRemoval = false;
    await dialog
      .getByRole("button", { name: "Fjern integration permanent", exact: true })
      .click();
    await expect(dialog).not.toBeVisible();
    await expect(panel).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "Other FjordHub", exact: true }),
    ).toBeVisible();
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "Integrationen er fjernet permanent" }),
    ).toContainText("Integrationen er fjernet permanent");
    expect(deletes).toEqual([
      "/integrations/unused-one",
      "/integrations/unused-one",
    ]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "Unused FjordHub", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "Other FjordHub", exact: true }),
    ).toBeVisible();
    expect(errors).toEqual([]);
  });
}
