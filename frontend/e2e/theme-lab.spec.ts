import { expect, test, type Page } from "@playwright/test";

const themes = [
  ["Midnight Glass", "midnight-glass", "dark"],
  ["Soft Orbit", "soft-orbit", "dark"],
  ["Precision Terminal", "precision-terminal", "dark"],
  ["Floating Layers", "floating-layers", "dark"],
  ["Edge Signal", "edge-signal", "dark"],
] as const;

async function mockHub(page: Page, configured = false) {
  let appearance: unknown = null;
  const writes: unknown[] = [];
  await page.addInitScript(() => {
    class Source extends EventTarget {
      onopen: (() => void) | null = null;
      timer = window.setTimeout(() => {
        this.dispatchEvent(new Event("open"));
        this.onopen?.();
        this.dispatchEvent(new MessageEvent("system.status", { data: JSON.stringify({ hostname:"synthetic", version:"beta-test", coreUptimeSeconds:124000, cpu:{percent:8,cores:8,scope:"core"}, ram:{percent:19.4,usedBytes:3.1e9,totalBytes:16e9}, disk:{percent:30,usedBytes:2.4e12,totalBytes:8e12}, network:{uploadBytesPerSecond:0,downloadBytesPerSecond:0} }) }));
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
      data = configured && path === "/mediaseed/status" ? {configured:true,available:true,url:"https://synthetic.invalid",openUrl:"https://synthetic.invalid"} : { configured: false, available: false };
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
    else if (path === "/apps") data = configured ? [{ id:"jellyfin-test",name:"Jellyfin",packageId:"org.mediahub.jellyfin",version:"test",state:"running",isMock:false,removable:true,detailPath:"/apps/jellyfin-test",health:{status:"healthy",summary:"Synthetic",checks:[],lastChecked:new Date().toISOString()} },{ id:"mediaseed-test",name:"MediaSeed",packageId:"org.mediahub.mediaseed",version:"test",state:"running",isMock:false,removable:true,health:{status:"healthy",summary:"Synthetic",checks:[],lastChecked:new Date().toISOString()} }] : [];
    else if (path === "/app-overview") data = { mediaseed:{status:"ok",data:{ready:true,checkedAt:Date.now()/1000,torrents:[{hash:"a".repeat(40),name:"Synthetic download",progress:.71,state:"downloading",dlspeed:12e6,upspeed:0}]}},mediavpn:{status:"unconfigured"} };
    else if (path === "/events/history") data = [{id:"test-event",timestamp:new Date().toISOString(),source:"System",event:"synthetic",message:"Synthetic activity for layout verification",severity:"info"}];
    else if (path.endsWith("/uninstall")) data = {state:"ready",installationId:"synthetic-installation",message:"Synthetic uninstall preview"};
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
      await page.goto("/settings?section=Appearance");
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
      await panel.locator(".appearance-advanced").evaluate((node: HTMLDetailsElement) => { node.open = true; });
      const interaction = await page.evaluate(() => {
        const button = document.querySelector('.theme-try-actions button')!;
        return { radius: getComputedStyle(button).borderRadius, feedback: getComputedStyle(document.documentElement).getPropertyValue('--toast-enter').trim() };
      });
      expect(interaction.feedback).toBe(({ 'midnight-glass': 'feedback-glass', 'soft-orbit': 'feedback-soft', 'precision-terminal': 'feedback-terminal', 'floating-layers': 'feedback-float', 'edge-signal': 'feedback-edge' })[id]);
      expect(interaction.radius).not.toBe('0px');
      await panel.locator(".appearance-advanced").evaluate((node: HTMLDetailsElement) => { node.open = false; });
      await page.screenshot({ path: `test-results/theme-${id}-appearance-${width}.png`, animations: "disabled" });
      await panel.locator(".appearance-advanced").evaluate((node: HTMLDetailsElement) => { node.open = true; });
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
      ).toHaveCount(0);
      await page.goto("/");
      await expect(page.locator("html")).toHaveAttribute("data-look", id);
      await expect(page.locator(".hub-app-card").first()).toBeVisible();
      await page.evaluate(async () => {
        const background = getComputedStyle(document.body, "::before").backgroundImage;
        await Promise.all([...background.matchAll(/url\("([^"]+)"\)/g)].map(async match => {
          const image = new Image(); image.src = match[1]; await image.decode();
        }));
      });
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
  await page.goto("/settings?section=Appearance");
  const panel = page.locator(".appearance-settings");
  await panel
    .locator(".theme-choice")
    .filter({ hasText: "Soft Orbit" })
    .click();
  await panel.getByRole("checkbox", { name: "Reduce motion" }).check();
  await panel.locator(".appearance-advanced").evaluate((node: HTMLDetailsElement) => { node.open = true; });
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
  ).toHaveCount(0);
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

for (const width of [1440, 390, 320]) test(`reference apps, overview, Light and uninstall preview at ${width}px`, async ({ page }) => {
  const { writes } = await mockHub(page, true);
  await page.setViewportSize({ width, height: 1000 });
  await page.goto("/");
  await expect(page.getByRole("heading", {name:"Apps & Services",exact:true})).toBeVisible();
  await expect(page.getByRole("button", {name:"Uninstall: Jellyfin",exact:true})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path:`test-results/reference-apps-${width}.png`, animations:"disabled" });
  await page.getByRole("button", {name:"Uninstall: Jellyfin",exact:true}).click();
  await expect(page.getByRole("dialog", {name:"Remove Jellyfin",exact:true})).toContainText("Media files and app data will be kept");
  await page.goto("/overview");
  await expect(page.locator(".reference-overview")).toBeVisible();
  await expect(page.locator(".overview-resource-row")).toContainText("8.0%");
  await expect(page.locator(".overview-activity")).toContainText("Synthetic activity");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path:`test-results/reference-overview-${width}.png`, animations:"disabled" });
  await page.goto("/settings?section=General");
  await expect(page.getByRole("combobox", {name:"Language",exact:true})).toBeVisible();
  await expect(page.locator(".appearance-entry")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:`test-results/general-clean-${width}.png`,animations:"disabled"});
  await page.getByRole("tab", {name:"Appearance",exact:true}).click();
  await expect(page.getByRole("heading", {name:"Appearance",exact:true})).toBeVisible();
  await page.locator(".theme-light-choice").click();
  await expect(page.locator("html")).toHaveAttribute("data-appearance-mode","light");
  await page.getByRole("button",{name:"Save colors",exact:true}).click();
  await expect(page.getByRole("button",{name:"Save colors",exact:true})).toHaveCount(0);
  await page.reload();
  await expect(page.locator(".theme-light-choice")).toHaveAttribute("aria-pressed","true");
  expect(writes).toHaveLength(1);
});

test("interface switches have the intended compact switch geometry", async ({page}) => {
 await mockHub(page); await page.goto("/settings?section=Appearance");
 const input=page.getByRole("checkbox",{name:/Compact layout/});
 const shape = await input.evaluate(el => {const s=getComputedStyle(el); return {width:s.width,height:s.height,radius:s.borderRadius};});
 expect(shape).toEqual({width:"32px",height:"18px",radius:"99px"});
 await expect(input).toBeVisible();
 const before = await page.locator(".theme-choice").first().evaluate(el => el.getBoundingClientRect().height);
 await input.check();
 const after = await page.locator(".theme-choice").first().evaluate(el => el.getBoundingClientRect().height);
 expect(after).toBeLessThan(before);
 await page.getByRole("checkbox",{name:/Reduce motion/}).check();
 expect(await page.evaluate(() => getComputedStyle(document.body,"::before").animationName)).toBe("none");
});
