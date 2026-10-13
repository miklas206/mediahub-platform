import { expect, test } from "@playwright/test";

const themes = ["midnight-glass", "soft-orbit", "precision-terminal", "floating-layers", "edge-signal"];
for (const width of [1440, 390, 320]) for (const app of ["mediaseed", "mediavpn"]) {
  test(`${app} redesigned workspace and five environments at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    const writes: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.setViewportSize({ width, height: 1000 });
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname.replace("/api/", "");
      if (route.request().method() !== "GET") writes.push(path);
      const vpn = { provider: "mediavpn", ready: false, downloadsEnabled: false, integrationAvailable: true, profiles: [], checkedAt: Date.now()/1000, reason: "No verified tunnel" };
      let data: unknown = [];
      if (path === "auth/status") data = { needsSetup: false, managed: false };
      else if (path === "auth/me") data = { csrf: "synthetic", username: "Designer", role: "administrator", language: "en" };
      else if (path === "dashboard") data = { runtime: vpn, torrents: null, queue: null };
      else if (path === "vpn") data = vpn;
      else if (path === "runtime") data = { enabled: false, mediaSeedConnected: false };
      else if (path === "storage") data = { freeBytes: 12e9, totalBytes: 24e9, writable: true };
      else if (path === "client") data = { name: "qBittorrent", version: "test" };
      await route.fulfill({ json: data });
    });
    const port = app === "mediaseed" ? 15175 : 15176;
    await page.goto(`http://127.0.0.1:${port}/static/index.html?mediahub_theme=edge-signal`);
    await expect(page.locator("#workspace")).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-look", "edge-signal");
    const selector = page.getByRole("combobox", { name: "Theme / Tema", exact: true });
    for (const theme of themes) {
      await selector.selectOption(theme);
      await expect(page.locator("html")).toHaveAttribute("data-look", theme);
      const scene = await page.evaluate(() => getComputedStyle(document.body, "::before").backgroundImage);
      expect(scene).not.toBe("none");
      expect(scene).not.toContain("url(");
      await page.evaluate(async () => {
        const background = getComputedStyle(document.body, "::before").backgroundImage;
        await Promise.all([...background.matchAll(/url\("([^"]+)"\)/g)].map(async match => {
          const image = new Image(); image.src = match[1]; await image.decode();
        }));
      });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: `test-results/ui-v2-${app}-${theme}-${width}.png`, animations: "disabled" });
    }
    if (app === "mediaseed") {
      await expect(page.locator("#connection-flow")).toHaveAttribute("data-state", "blocked");
      for (const view of ["feeds", "trackers", "vpn", "downloads"]) {
        await page.locator(`[data-view="${view}"]`).click();
        await expect(page.locator(`#${view}`)).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/ui-v2-mediaseed-${view}-${width}.png`, animations: "disabled" });
      }
      await page.locator("[data-view=feeds]").click();
      await expect(page.locator("#feed-form")).toBeVisible();
      await expect(page.locator("#feed-list")).toBeVisible();
      await page.locator("[data-view=vpn]").click();
      await expect(page.locator("#vpn-downloads")).toContainText("Blocked");
    } else {
      await expect(page.locator("#profiles .empty")).toContainText("No connections yet");
      await page.locator("#add").click();
      await expect(page.locator("#profile-dialog")).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.locator("#profile-dialog")).not.toBeVisible();
    }
    await page.reload();
    await expect(selector).toHaveValue("edge-signal");
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test("Seedbox measured stats and RSS rail never fabricate missing client data", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  let available = true;
  const row = { hash: "a".repeat(40), name: "Synthetic long torrent title for layout validation", progress: .71, size: 4e9, dlspeed: 1024, upspeed: 2048, ratio: .4, state: "downloading", seeding_time: 0 };
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/", "");
    let data: unknown = [];
    if (path === "auth/status") data = { needsSetup: false, managed: false };
    if (path === "auth/me") data = { csrf: "synthetic", username: "Designer", role: "administrator", language: "en" };
    if (path === "dashboard") data = { runtime: { ready: false, downloadsEnabled: false }, torrents: available ? [row] : null, queue: null };
    if (path === "client") data = { name: "qBittorrent", version: "test" };
    if (path === "feeds") data = [{ id: "synthetic", name: "Documentaries", paused: true, folder: "releases", ratio: 1 }];
    await route.fulfill({ json: data });
  });
  await page.goto("http://127.0.0.1:15175/static/index.html");
  await expect(page.locator("#seed-download-speed")).toHaveText("1.0 KiB/s");
  await expect(page.locator("#seed-upload-speed")).toHaveText("2.0 KiB/s");
  await expect(page.locator("#seed-torrent-count")).toHaveText("1");
  await expect(page.locator("#feed-preview")).toContainText("Documentaries");
  await page.screenshot({ path: "test-results/seedbox-compact-populated.png", animations: "disabled" });
  await page.locator("#open-rss").click();
  await expect(page.locator("#feeds")).toBeVisible();
  await page.locator('[data-view="downloads"]').click();
  available = false;
  await page.locator("#refresh").click();
  await expect(page.locator("#seed-download-speed")).toHaveText("\u2014");
  await expect(page.locator("#seed-torrent-count")).toHaveText("\u2014");
});
