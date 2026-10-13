import { expect, test, type Page } from "@playwright/test";

const themes = [
  ["Midnight Glass", "midnight-glass", "dark"],
  ["Soft Orbit", "soft-orbit", "light"],
  ["Precision Terminal", "precision-terminal", "dark"],
  ["Floating Layers", "floating-layers", "dark"],
  ["Edge Signal", "edge-signal", "dark"],
] as const;

async function mockHub(page: Page) {
  let appearance: unknown = null;
  const writes: unknown[] = [];
  await page.addInitScript(() => {
    class Source extends EventTarget {
      onopen: (() => void) | null = null;
      timer = window.setTimeout(() => {
        this.dispatchEvent(new Event("open"));
        this.onopen?.();
      }, 0);
      close() {
        window.clearTimeout(this.timer);
      }
    }
    window.EventSource = Source as unknown as typeof EventSource;
  });
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
        id: "theme-user",
        username: "Designer",
        role: "administrator",
        csrf: "test",
        language: "en",
        appearance,
      };
    else if (path === "/auth/preferences") {
      if (route.request().method() === "PUT") {
        const patch = route.request().postDataJSON();
        appearance = patch.appearance;
        writes.push(patch);
      }
      data = { language: "en", appearance };
    } else if (path === "/settings")
      data = {
        theme: "dark",
        display_name: "MediaHub",
        advanced_mode: false,
        visible_navigation: ["/", "/overview", "/settings"],
        dashboard_sections: [],
      };
    else if (path === "/updates/summary")
      data = { count: 0, items: [], notifications: [] };
    else if (path === "/fjordhub/deployment") data = null;
    else if (path === "/mediaseed/status" || path === "/mediavpn/status")
      data = { configured: false, available: false };
    else if (path === "/catalog")
      data = [
        "seedbox",
        "plex",
        "jellyfin",
        "cloudflared",
        "fjordhub",
        "mediavpn",
      ].map((id) => ({
        id: `org.mediahub.${id}`,
        name: id,
        availability: "available",
      }));
    else if (path === "/system/status") data = { version: "beta-test" };
    await route.fulfill({ json: { data } });
  });
  return { writes };
}

for (const width of [1440, 390, 320]) {
  test(`five beta themes preview, save and survive refresh at ${width}px`, async ({
    page,
  }) => {
    const { writes } = await mockHub(page);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width, height: 1000 });
    for (const [name, id, mode] of themes) {
      await page.goto("/settings?section=General");
      const panel = page.locator(".appearance-settings");
      await panel.locator(".theme-choice").filter({ hasText: name }).click();
      await expect(page.locator("html")).toHaveAttribute("data-look", id);
      await expect(page.locator("html")).toHaveAttribute(
        "data-appearance-mode",
        mode,
      );
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await panel
        .getByRole("button", { name: "Preview dialog", exact: true })
        .click();
      const dialog = page.getByRole("dialog", {
        name: "Theme preview",
        exact: true,
      });
      await expect(dialog).toBeVisible();
      const bounds = await dialog.boundingBox();
      expect(bounds!.x).toBeGreaterThanOrEqual(16);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
      await page.screenshot({
        path: `test-results/theme-${id}-dialog-${width}.png`,
        animations: "disabled",
      });
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
      await panel
        .getByRole("button", { name: "Preview notification", exact: true })
        .click();
      await expect(
        page.locator(".notification-popup.info").last(),
      ).toContainText("Theme preview");
      await panel
        .getByRole("button", { name: "Save colors", exact: true })
        .click();
      await expect(
        panel.getByRole("button", { name: "Save colors", exact: true }),
      ).toBeDisabled();
      await page.goto("/");
      await expect(page.locator("html")).toHaveAttribute("data-look", id);
      await expect(page.locator(".hub-app-card").first()).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: `test-results/theme-${id}-home-${width}.png`,
        animations: "disabled",
      });
    }
    expect(writes).toHaveLength(5);
    expect(errors).toEqual([]);
  });
}

test("discard restores saved theme and palette changes retain its layout and motion settings", async ({
  page,
}) => {
  await mockHub(page);
  await page.goto("/settings?section=General");
  const panel = page.locator(".appearance-settings");
  await panel
    .locator(".theme-choice")
    .filter({ hasText: "Soft Orbit" })
    .click();
  await panel.getByRole("checkbox", { name: "Reduce motion" }).check();
  await panel
    .getByLabel("Layout density", { exact: true })
    .selectOption("compact");
  await panel.getByRole("button", { name: "Violet", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-look", "soft-orbit");
  await expect(page.locator("html")).toHaveAttribute(
    "data-reduced-motion",
    "true",
  );
  await expect(page.locator("html")).toHaveAttribute("data-density", "compact");
  await panel.getByRole("button", { name: "Save colors", exact: true }).click();
  await expect(
    panel.getByRole("button", { name: "Save colors", exact: true }),
  ).toBeDisabled();
  await panel
    .locator(".theme-choice")
    .filter({ hasText: "Edge Signal" })
    .click();
  await panel
    .getByRole("button", { name: "Discard changes", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("data-look", "soft-orbit");
  await panel
    .locator(".theme-choice")
    .filter({ hasText: "Midnight Glass" })
    .click();
  await page.getByRole("link", { name: "Home", exact: true }).first().click();
  await expect(page.locator("html")).toHaveAttribute("data-look", "soft-orbit");
  await expect(page.locator("html")).toHaveAttribute(
    "data-reduced-motion",
    "true",
  );
});
