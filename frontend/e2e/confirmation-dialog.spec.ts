import { expect, test, type Page } from "@playwright/test";

async function mockHub(page: Page, language = "en") {
  let deletes = 0;
  await page.addInitScript(() => {
    class MockSource extends EventTarget {
      onopen: (() => void) | null = null;
      close() {}
      constructor() {
        super();
        (window as unknown as { testLiveSource: MockSource }).testLiveSource =
          this;
      }
      emit(type: string) {
        this.dispatchEvent(new Event(type));
        if (type === "open") this.onopen?.();
      }
    }
    window.EventSource = MockSource as unknown as typeof EventSource;
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(
      /^\/api(?:\/v1)?/,
      "",
    );
    let data: unknown = [];
    if (path === "/auth/status") data = { needsSetup: false };
    else if (path === "/auth/me")
      data = {
        id: "test",
        username: "tester",
        role: "administrator",
        csrf: "test",
        language,
      };
    else if (path === "/setup/status") data = { setup_required: false };
    else if (path === "/settings")
      data = {
        display_name: "MediaHub",
        theme: "dark",
        advanced_mode: false,
        visible_navigation: ["/", "/settings"],
        dashboard_sections: [],
      };
    else if (path === "/updates/summary")
      data = { count: 0, items: [], notifications: [] };
    else if (path === "/fjordhub/deployment") data = null;
    else if (path === "/users")
      data = [
        {
          id: "alex",
          username: "Alex",
          role: "user",
          language: "en",
          createdAt: "2026-10-01T12:00:00Z",
          appRoles: {},
        },
      ];
    else if (path === "/users/alex" && route.request().method() === "DELETE") {
      deletes += 1;
      data = {};
    }
    await route.fulfill({ json: { data } });
  });
  return () => deletes;
}

for (const width of [1440, 390, 320]) {
  test(`MediaHub confirmation protects actions and fits ${width}px`, async ({
    page,
  }) => {
    const deletes = await mockHub(page);
    const errors: string[] = [];
    const nativeDialogs: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("dialog", async (dialog) => {
      nativeDialogs.push(dialog.type());
      await dialog.dismiss();
    });
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/settings?section=Users");
    const trigger = page.getByRole("button", {
      name: "Delete Alex",
      exact: true,
    });
    await trigger.click();
    const dialog = page.getByRole("dialog", {
      name: "Delete user?",
      exact: true,
    });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Delete user Alex?");
    await expect(
      dialog.getByRole("button", { name: "Cancel", exact: true }),
    ).toBeFocused();
    expect(deletes()).toBe(0);
    for (let index = 0; index < 5; index++) {
      await page.keyboard.press("Tab");
      expect(
        await dialog.evaluate((element) =>
          element.contains(document.activeElement),
        ),
      ).toBe(true);
    }
    const bounds = await dialog.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(16);
    expect(bounds!.y).toBeGreaterThanOrEqual(16);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    expect(
      await dialog.evaluate(
        (element) => element.scrollWidth <= element.clientWidth,
      ),
    ).toBe(true);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
    expect(deletes()).toBe(0);
    await trigger.click();
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    expect(deletes()).toBe(0);
    await trigger.click();
    await expect(dialog).toBeVisible();
    await page.screenshot({
      path: `test-results/confirmation-${width}.png`,
      animations: "disabled",
    });
    await dialog
      .getByRole("button", { name: "Delete user", exact: true })
      .click();
    await expect.poll(deletes).toBe(1);
    await expect(dialog).toHaveCount(0);
    expect(nativeDialogs).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test("refresh waits for the live connection; actual failures still warn", async ({
  page,
}) => {
  await mockHub(page);
  const warning = page.locator(".notification-popup.warning");
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.goto("/settings?section=Users");
    await expect(
      page.getByRole("button", { name: "Delete Alex", exact: true }),
    ).toBeVisible();
    await expect(warning).toHaveCount(0);
    await page.evaluate(() =>
      (
        window as unknown as { testLiveSource: { emit(type: string): void } }
      ).testLiveSource.emit("open"),
    );
    await expect(page.locator(".sidebar-connection")).toHaveClass(/healthy/);
    await expect(warning).toHaveCount(0);
  }
  await page.evaluate(() =>
    (
      window as unknown as { testLiveSource: { emit(type: string): void } }
    ).testLiveSource.emit("error"),
  );
  await expect(warning).toContainText("Live connection interrupted");
  await page.evaluate(() =>
    (
      window as unknown as { testLiveSource: { emit(type: string): void } }
    ).testLiveSource.emit("open"),
  );
  await expect(page.locator(".sidebar-connection")).toHaveClass(/healthy/);
});

test("MediaHub update starts only after confirming the in-app dialog", async ({
  page,
}) => {
  await mockHub(page);
  let installs = 0;
  await page.route("**/api/v1/updates/check", (route) =>
    route.fulfill({
      json: {
        data: { items: [], count: 0, notifications: [], lastError: null },
      },
    }),
  );
  await page.route("**/api/v1/updates/platform**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown;
    if (path.endsWith("/install")) {
      installs += 1;
      data = {
        state: "building",
        progress: 20,
        message: "Building update",
        steps: [],
        logs: [],
      };
    } else if (path.endsWith("/operation")) {
      data = {
        state: installs ? "building" : "idle",
        progress: 20,
        message: "Building update",
        steps: [],
        logs: [],
      };
    } else if (path.endsWith("/credentials")) {
      data = { configured: false };
    } else {
      data = {
        configured: true,
        installedVersion: "0.5.7",
        latestVersion: "0.5.7",
        latestCommit: "abcdef1",
        updateAvailable: true,
        installReady: true,
        updateMethod: "source",
        fastUpdateAvailable: true,
        message: "Update available",
        repository: "mediahub/test",
      };
    }
    await route.fulfill({ json: { data } });
  });
  await page.route("**/api/v1/updates/queue", (route) =>
    route.fulfill({ json: { data: { state: "idle", items: [], logs: [] } } }),
  );
  await page.goto("/settings?section=Updates");
  const install = page.getByRole("button", {
    name: "Install update",
    exact: true,
  });
  await expect(install).toBeEnabled();
  await install.click();
  const dialog = page.getByRole("dialog", {
    name: "Install MediaHub update?",
    exact: true,
  });
  await expect(dialog).toContainText("Configuration is backed up first");
  expect(installs).toBe(0);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(installs).toBe(0);
  await install.click();
  await dialog
    .getByRole("button", { name: "Install update", exact: true })
    .click();
  await expect.poll(() => installs).toBe(1);
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("progressbar", { name: "Install MediaHub update" }),
  ).toBeVisible();
});

test("confirmation translates and cancels when its page is unmounted", async ({
  page,
}) => {
  const deletes = await mockHub(page, "da");
  await page.goto("/settings?section=Users");
  await page.getByRole("button", { name: "Slet Alex", exact: true }).click();
  const dialog = page.getByRole("dialog", {
    name: "Slet bruger?",
    exact: true,
  });
  await expect(dialog).toContainText("Slet brugeren Alex?");
  await expect(dialog.getByRole("button", { name: "Annuller" })).toBeFocused();
  // Programmatic navigation can unmount the owner even while the modal is open.
  await page.evaluate(() => {
    window.history.pushState({}, "", "/settings?section=General");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(dialog).toHaveCount(0);
  expect(deletes()).toBe(0);
});
