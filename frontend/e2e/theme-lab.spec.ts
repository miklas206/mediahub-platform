import { expect, test, type Page } from "@playwright/test";

const themes = [
  ["Midnight Glass", "midnight-glass", "dark"],
  ["Soft Orbit", "soft-orbit", "dark"],
  ["Precision Terminal", "precision-terminal", "dark"],
  ["Floating Layers", "floating-layers", "dark"],
  ["Edge Signal", "edge-signal", "dark"],
] as const;

async function mockHub(page: Page, configured = false, username = "Designer") {
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
        username,
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
    else if (path.startsWith("/managed-install/")) data = {planDigest:"a".repeat(64),alreadyRunning:false,operation:{state:"idle"}};
    else if (path === "/system/status") data = { version: "beta-test" };
    await route.fulfill({ json: { data } });
  });
  return { writes };
}

test('shared VPN profile and per-app selection stay usable on desktop and mobile', async ({page}) => {
  await mockHub(page, true);
  let gateway = {enabled:false,ready:false,profileId:'synthetic-profile',publicIp:null as string|null,profiles:[{id:'synthetic-profile',name:'My VPN'}],message:null};
  const apps = [{id:'jellyfin',name:'Jellyfin',hostId:'paired-host',enabled:false,ready:false,phase:'idle'}];
  const writes: unknown[] = [];
  await page.route('**/api/v1/managed-install/org.mediahub.mediavpn', route => route.fulfill({json:{data:{planDigest:'a'.repeat(64),alreadyRunning:true,operation:{state:'idle'}},error:null}}));
  await page.route('**/api/v1/shared-vpn**', async route => {
    if(route.request().method() === 'PUT') {
      const body = route.request().postDataJSON(); writes.push(body);
      if(route.request().url().endsWith('/gateway')) gateway = {...gateway,enabled:body.enabled,ready:body.enabled,publicIp:body.enabled?'8.8.8.8':null};
      else apps[0] = {...apps[0],enabled:body.enabled,ready:body.enabled,phase:'ready'};
    }
    return route.fulfill({json:{data:{gateway,apps},error:null}});
  });
  await page.goto('/store/mediavpn');
  await expect(page.getByRole('heading',{name:'Shared VPN',exact:true})).toBeVisible();
  await expect(page.getByRole('checkbox',{name:'Use shared VPN'})).toBeDisabled();
  await page.getByRole('button',{name:'Enable shared VPN',exact:true}).click();
  await expect(page.getByRole('checkbox',{name:'Use shared VPN'})).toBeEnabled();
  await page.getByRole('checkbox',{name:'Use shared VPN'}).check();
  await expect(page.getByRole('checkbox',{name:'Use shared VPN'})).toBeChecked();
  expect(writes).toEqual([{enabled:true,profileId:'synthetic-profile'},{enabled:true}]);
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByRole('button',{name:'Stop shared VPN',exact:true})).toBeVisible();
  const panel = page.locator('.panel').filter({has:page.getByRole('heading',{name:'Shared VPN',exact:true})});
  const width = await panel.evaluate(element => element.getBoundingClientRect().width);
  expect(width).toBeLessThanOrEqual(390);
});

for (const width of [1440, 390, 320]) {
  test(`five beta themes preview, save and survive refresh at ${width}px`, async ({
    page,
  }) => {
    const { writes } = await mockHub(page);
    const backgrounds = new Set<string>();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width, height: 1000 });
    for (const [name, id, mode] of themes) {
      await page.goto("/settings?section=Appearance");
      const panel = page.locator(".appearance-settings");
      await panel.locator(".theme-choice").filter({ hasText: name }).click();
      await expect(page.locator("html")).toHaveAttribute("data-look", id);
      backgrounds.add(await page.evaluate(() => getComputedStyle(document.body,"::before").backgroundImage + getComputedStyle(document.body,"::after").backgroundImage));
      await expect(page.locator("html")).toHaveAttribute(
        "data-appearance-mode",
        mode,
      );
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await expect(panel.locator(".theme-gallery > .theme-choice")).toHaveCount(5);
      await panel.locator(".appearance-advanced").evaluate((node: HTMLDetailsElement) => { node.open = true; });
      const interaction = await page.evaluate(() => {
        const button = document.querySelector('.theme-try-actions button')!;
        return { radius: getComputedStyle(button).borderRadius, feedback: getComputedStyle(document.documentElement).getPropertyValue('--toast-enter').trim() };
      });
      expect(interaction.feedback).toBe(({ 'midnight-glass': 'feedback-glass', 'soft-orbit': 'feedback-soft', 'precision-terminal': 'feedback-terminal', 'floating-layers': 'feedback-float', 'edge-signal': 'feedback-edge' })[id]);
      expect(interaction.radius).not.toBe('0px');
      await panel.locator(".appearance-advanced").evaluate((node: HTMLDetailsElement) => { node.open = false; });
      await expect(page.getByRole("tablist", {name:"Settings",exact:true})).toBeVisible();
      await expect(page.getByRole("tab", {name:"Appearance",exact:true})).toHaveAttribute("aria-selected","true");
      const cardShape = await panel.locator(".theme-choice").first().evaluate(el => ({radius:parseFloat(getComputedStyle(el).borderTopLeftRadius),width:el.clientWidth}));
      expect(cardShape.radius).toBeLessThan(cardShape.width / 3);
      if (width === 1440) {
        const expectedClass = id === "midnight-glass" ? "nav-icon-default" : `nav-icon-${id}`;
        await expect(page.locator('.sidebar > nav a[aria-current="page"] .'+expectedClass)).toBeVisible();
      }
      const selectedNav = page.locator('.sidebar > nav a[aria-current="page"]');
      await expect(selectedNav).toHaveCount(1);
      await expect(selectedNav).toContainText("Settings");
      if (width === 1440) {
        await selectedNav.focus();
        await page.keyboard.press("Tab");
        await page.keyboard.press("Shift+Tab");
        expect(await selectedNav.evaluate(el => getComputedStyle(el).outlineStyle)).toBe("solid");
        await selectedNav.hover();
      }
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
        .getByRole("button", { name: "Save", exact: true })
        .click();
      await expect(
        panel.getByRole("button", { name: "Save", exact: true }),
      ).toBeDisabled();
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
    expect(backgrounds.size).toBe(5);
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
    .getByRole("checkbox", { name: /Compact layout/ })
    .check();
  await panel.getByRole("button", { name: "Violet", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-look", "soft-orbit");
  await expect(page.locator("html")).toHaveAttribute(
    "data-reduced-motion",
    "true",
  );
  await expect(page.locator("html")).toHaveAttribute("data-density", "compact");
  await panel.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    panel.getByRole("button", { name: "Save", exact: true }),
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

for (const width of [1440, 390, 320]) test(`reference apps, overview, Light and uninstall preview at ${width}px`, async ({ page }) => {
  const { writes } = await mockHub(page, true);
  await page.setViewportSize({ width, height: 1000 });
  await page.goto("/");
  await expect(page.getByRole("heading", {name:"Apps & Services",exact:true})).toBeVisible();
  await expect(page.getByRole("button", {name:"Uninstall: Jellyfin",exact:true})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path:`test-results/reference-apps-${width}.png`, animations:"disabled" });
  await page.getByRole("button", {name:"Uninstall: Jellyfin",exact:true}).click();
  await expect(page.getByRole("dialog", {name:"Remove Jellyfin",exact:true})).toContainText("App settings, accounts and VPN profiles will be removed");
  const removal = page.getByRole("dialog", {name:"Remove Jellyfin",exact:true});
  expect(await removal.evaluate(el => el.parentElement === document.body && el.matches(':modal'))).toBe(true);
  const removalBounds = (await removal.boundingBox())!;
  expect(removalBounds.x).toBeGreaterThanOrEqual(15);
  expect(removalBounds.x + removalBounds.width).toBeLessThanOrEqual(width - 15);
  expect(await removal.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  await expect(removal.getByRole('button', {name:'Cancel',exact:true})).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(removal).toHaveCount(0);
  await expect(page.getByRole("button", {name:"Uninstall: Jellyfin",exact:true})).toBeFocused();

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
  await page.getByLabel("Color mode",{exact:true}).selectOption("light");
  await expect(page.locator("html")).toHaveAttribute("data-appearance-mode","light");
  await page.getByRole("button",{name:"Save",exact:true}).click();
  await expect(page.getByRole("button",{name:"Save",exact:true})).toBeDisabled();
  await page.reload();
  await expect(page.getByLabel("Color mode",{exact:true})).toHaveValue("light");
  await page.locator(".theme-choice").filter({hasText:"Soft Orbit"}).click();
  await expect(page.locator("html")).toHaveAttribute("data-appearance-mode","light");
  await expect(page.locator(".theme-choice").filter({hasText:"Soft Orbit"})).toHaveAttribute("aria-pressed","true");
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
 expect(await page.evaluate(() => getComputedStyle(document.body,"::after").animationName)).toBe("none");
});

for (const width of [1440, 390, 320]) test(`custom accent wheel previews, cancels and saves at ${width}px`, async ({page}) => {
 const {writes}=await mockHub(page);await page.setViewportSize({width,height:1000});await page.goto("/settings?section=Appearance");
 await page.locator(".theme-choice").filter({hasText:"Midnight Glass"}).click();
 await page.getByRole("button",{name:"Choose custom color",exact:true}).click();
 const dialog=page.getByRole("dialog",{name:"Choose custom color",exact:true});await expect(dialog).toBeVisible();
 await page.getByRole("textbox",{name:"Hex color",exact:true}).fill("#123456");
 await expect(page.locator('input[aria-label="Accent color"]')).toHaveValue("#123456");
 await page.keyboard.press("Escape");await expect(dialog).toHaveCount(0);await expect(page.locator('input[aria-label="Accent color"]')).toHaveValue("#25c9ed");
 await page.getByRole("button",{name:"Choose custom color",exact:true}).click();
 const wheel=page.getByRole("group",{name:"Color wheel",exact:true});await wheel.click({position:{x:150,y:90}});
 await expect(page.getByRole("textbox",{name:"Hex color",exact:true})).not.toHaveValue("#25c9ed");
 await page.getByRole("slider",{name:"Brightness",exact:true}).focus();await page.keyboard.press("Home");await expect(page.getByRole("textbox",{name:"Hex color",exact:true})).toHaveValue("#000000");
 await page.getByRole("textbox",{name:"Hex color",exact:true}).fill("invalid");await expect(page.getByRole("button",{name:"Done",exact:true})).toBeDisabled();
 await page.getByRole("textbox",{name:"Hex color",exact:true}).fill("#123456");await page.screenshot({path:`test-results/custom-color-wheel-${width}.png`,animations:"disabled"});
 await page.getByRole("button",{name:"Done",exact:true}).click();await page.getByRole("button",{name:"Save",exact:true}).click();await expect(page.getByRole("button",{name:"Save",exact:true})).toBeDisabled();
 expect(writes).toHaveLength(1);expect(writes[0]).toMatchObject({appearance:{accent:"#123456"}});
 await page.reload();await page.getByRole("button",{name:"Choose custom color",exact:true}).click();await expect(page.getByRole("textbox",{name:"Hex color",exact:true})).toHaveValue("#123456");
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

for (const width of [1440, 390, 320]) test(`appearance controls are visible and defaults save at ${width}px`, async ({page}) => {
 const {writes}=await mockHub(page);await page.setViewportSize({width,height:1000});await page.goto("/settings?section=Appearance");
 const advanced=page.locator(".appearance-advanced");await expect(advanced.locator("summary")).toHaveText("Advanced coloring");
 await expect(page.getByLabel("Layout density",{exact:true})).toHaveCount(0);
 await expect(page.getByRole("button",{name:"MediaHub Classic",exact:true})).toHaveCount(0);
 await expect(page.getByLabel("Color mode",{exact:true})).toBeVisible();
 await expect(page.getByRole("button",{name:"Preview dialog",exact:true})).toBeVisible();
 await expect(page.locator(".appearance-quick-save").getByRole("button",{name:"Defaults",exact:true})).toBeVisible();
 await page.getByRole("tab",{name:"General",exact:true}).click();
 await expect(page.getByRole("combobox",{name:"Language",exact:true})).toBeVisible();
 await page.getByRole("tab",{name:"Appearance",exact:true}).click();
 await page.getByLabel("Color mode",{exact:true}).selectOption("system");await page.getByRole("button",{name:"Save",exact:true}).click();
 await expect(page.getByRole("button",{name:"Save",exact:true})).toBeDisabled();expect(writes[0]).toMatchObject({appearance:{mode:"system"}});
 await page.getByRole("button",{name:"Defaults",exact:true}).click();await page.getByRole("button",{name:"Save",exact:true}).click();
 await expect(page.getByRole("button",{name:"Save",exact:true})).toBeDisabled();expect(writes[1]).toMatchObject({appearance:null});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

for (const width of [1440, 390, 320]) test(`themed sidebar account dock and mobile drawer at ${width}px`, async ({page}) => {
 await mockHub(page); await page.setViewportSize({width,height:800}); await page.goto("/settings?section=Appearance");
 for (const [name,id] of themes) {
  await page.locator(".theme-choice").filter({hasText:name}).click();
  if (width < 761) await page.getByRole("button",{name:"Open navigation",exact:true}).click();
  const topbar=page.locator(".topbar"), footer=page.locator(".footer");
  for (const bar of [topbar,footer]) {
    const bounds=await bar.boundingBox();expect(bounds!.x).toBeGreaterThanOrEqual(0);expect(bounds!.x+bounds!.width).toBeLessThanOrEqual(width);
    expect(await bar.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
  }
  const sidebar=page.locator(".sidebar");await expect(sidebar).toBeInViewport();
  await expect(sidebar.locator(".brand")).toContainText("MediaHub");
  await expect(sidebar.locator(".sidebar-connection")).toContainText("Core online");
  await expect(sidebar.locator(".sidebar-identity")).toContainText("Designer");
  await expect(sidebar.getByRole("button",{name:"Sign out",exact:true})).toBeVisible();
  await expect.poll(async () => Math.round((await sidebar.boundingBox())!.x)).toBeGreaterThanOrEqual(0);
  const box=await sidebar.boundingBox();expect(box!.x).toBeGreaterThanOrEqual(0);expect(box!.x+box!.width).toBeLessThanOrEqual(width);expect(box!.y+box!.height).toBeLessThanOrEqual(800);
  expect(await sidebar.evaluate(el => el.scrollWidth<=el.clientWidth)).toBe(true);
  await page.screenshot({path:`test-results/sidebar-${id}-${width}.png`,animations:"disabled"});
  if (width < 761) {await sidebar.getByRole("button",{name:"Close navigation",exact:true}).click();await expect(sidebar).not.toBeInViewport();}
 }
 if (width < 761) {await page.getByRole("button",{name:"Open navigation",exact:true}).click();await page.locator(".sidebar").getByRole("link",{name:"Home",exact:true}).click();await expect(page.locator(".sidebar")).not.toBeInViewport();}
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test("sidebar supports light mode, long account names and short screens", async ({page}) => {
 await mockHub(page,false,"An administrator with a very long account name");await page.setViewportSize({width:1440,height:480});await page.goto("/settings?section=Appearance");
 await page.getByLabel("Color mode",{exact:true}).selectOption("light");
 const sidebar=page.locator(".sidebar");await expect(sidebar.locator(".sidebar-clock")).toBeInViewport();await expect(sidebar.getByRole("button",{name:"Sign out",exact:true})).toBeInViewport();
 expect(await sidebar.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
 await expect(sidebar.locator(".sidebar-identity")).toHaveAttribute("title","An administrator with a very long account name");
 await page.screenshot({path:"test-results/sidebar-light-short.png",animations:"disabled"});
});

test("continuous frame aligns flush with the viewport in every theme", async ({page})=>{
 await mockHub(page);await page.setViewportSize({width:1440,height:900});await page.goto("/settings?section=Appearance");
 for (const [name,id] of themes) {
  await page.locator(".theme-choice").filter({hasText:name}).click();
  const sidebar=page.locator(".sidebar"), topbar=page.locator(".topbar"),footer=page.locator(".footer");
  const [s,h,f]=await Promise.all([sidebar.boundingBox(),topbar.boundingBox(),footer.boundingBox()]);
  expect(h!.y).toBe(s!.y);expect(f!.y+f!.height).toBe(s!.y+s!.height);expect(h!.x).toBe(f!.x);expect(s!.x).toBe(0);expect(h!.x-s!.x-s!.width).toBe(0);expect(h!.x+h!.width).toBe(1440);expect(f!.x+f!.width).toBe(1440);
  const radii=await Promise.all([sidebar,topbar,footer].map(el=>el.evaluate(node=>getComputedStyle(node).borderTopLeftRadius)));expect(radii).toEqual(["0px","0px","0px"]);
  for (const dock of [".sidebar-connection", ".profile"]) { expect(await sidebar.locator(dock).evaluate(el=>getComputedStyle(el).backgroundColor)).toBe("rgba(0, 0, 0, 0)"); }
  await page.screenshot({path:`test-results/shell-${id}-1440.png`,animations:"disabled"});
 }
});

for(const width of [1440,390,320]) test(`navigation layouts preview, persist and retain theme at ${width}px`,async({page})=>{
 const {writes}=await mockHub(page);await page.setViewportSize({width,height:900});await page.goto("/settings?section=Appearance");
 const errors:string[]=[];page.on("pageerror",e=>errors.push(e.message));
 for(const [id,label] of [["topbar","Top navigation"],["dock-top","Top dock"],["dock-bottom","Bottom dock"],["launcher","Compact menu"]]) {
  await page.getByRole("group",{name:"Navigation layout",exact:true}).getByRole("button",{name:new RegExp(label)}).click();
  await expect(page.locator("html")).toHaveAttribute("data-navigation",id);
  await expect(page.locator(".sidebar")).not.toBeVisible();await expect(page.locator(".shell-brand")).toBeVisible();await expect(page.locator(".shell-signout")).toBeVisible();
  if(id==="launcher") await page.locator(".shell-launcher summary").click();
  const nav=page.locator(id==="topbar"?".shell-navigation-integrated":id==="launcher"?".shell-navigation-launcher":".shell-navigation-dock");
  await expect(nav).toBeVisible();expect(await nav.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
  const box=await nav.boundingBox();expect(box!.x).toBeGreaterThanOrEqual(0);expect(box!.x+box!.width).toBeLessThanOrEqual(width);
  await page.screenshot({path:`test-results/navigation-${id}-${width}.png`,animations:"disabled"});
  await nav.getByRole("link",{name:"Overview",exact:true}).click();await expect(page).toHaveURL(/overview/);
  // Unsaved previews return to the saved layout when leaving Appearance.
  await page.goto("/settings?section=Appearance");
  await page.getByRole("group",{name:"Navigation layout",exact:true}).getByRole("button",{name:new RegExp(label)}).click();
  await page.getByRole("button",{name:"Save",exact:true}).click();await expect(page.getByRole("button",{name:"Save",exact:true})).toBeDisabled();
  await page.reload();await expect(page.locator("html")).toHaveAttribute("data-navigation",id);
  await page.locator(".theme-choice").filter({hasText:"Soft Orbit"}).click();await expect(page.locator("html")).toHaveAttribute("data-navigation",id);
 }
 expect(writes).toHaveLength(4);expect(errors).toEqual([]);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.locator(".theme-choice").filter({hasText:"Edge Signal"}).click();
 await page.getByRole("button",{name:"Discard changes",exact:true}).click();await expect(page.locator("html")).toHaveAttribute("data-navigation","launcher");
 await page.getByRole("group",{name:"Navigation layout",exact:true}).getByRole("button",{name:/Sidebar/}).click();await expect(page.locator("html")).toHaveAttribute("data-navigation","sidebar");
});

for (const width of [1440, 390, 320]) test(`MediaVPN setup card retains padding across themes at ${width}px`, async ({page}) => {
  await mockHub(page);
  await page.setViewportSize({width,height:1000});
  const errors:string[]=[]; page.on('pageerror', error=>errors.push(error.message));
  for (const [name, id] of themes) {
    await page.goto('/settings?section=Appearance');
    await page.locator('.theme-choice').filter({hasText:name}).click();
    await page.getByRole('button',{name:'Save',exact:true}).click();
    await page.goto('/store/mediavpn');
    await expect(page.locator('html')).toHaveAttribute('data-look',id);
    const card=page.locator('.managed-app-setup .panel');
    await expect(card).toContainText('Independent VPN app');
    const geometry=await card.evaluate(el=>{
      const box=el.getBoundingClientRect();
      const paragraph=el.querySelector('p')!.getBoundingClientRect();
      return {left:paragraph.left-box.left,right:box.right-paragraph.right,overflow:el.scrollWidth>el.clientWidth};
    });
    expect(geometry.left).toBeGreaterThanOrEqual(15);
    expect(geometry.right).toBeGreaterThanOrEqual(15);
    expect(geometry.overflow).toBe(false);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await expect(page.getByRole('button',{name:'Install MediaVPN',exact:true})).toBeVisible();
  }
  expect(errors).toEqual([]);
});

for (const width of [1440, 390, 320]) test(`themed removal content remains inside modal at ${width}px`, async ({page}) => {
  await mockHub(page,true);
  await page.setViewportSize({width,height:1000});
  for (const [name] of themes) {
    await page.goto('/settings?section=Appearance');
    await page.locator('.theme-choice').filter({hasText:name}).click();
    await page.getByRole('button',{name:'Save',exact:true}).click();
    await page.goto('/');
    await page.getByRole('button',{name:'Uninstall: Jellyfin',exact:true}).click();
    const modal=page.getByRole('dialog',{name:'Remove Jellyfin',exact:true});
    await expect(modal).toContainText('App settings, accounts and VPN profiles will be removed');
    const inside=await modal.evaluate(el=>{
      const r=el.getBoundingClientRect();
      return el.matches(':modal') && el.scrollWidth<=el.clientWidth && [...el.querySelectorAll('h3,p,button')].every(child=>{
        const b=child.getBoundingClientRect();return b.left>=r.left+12 && b.right<=r.right-12;
      });
    });
    expect(inside).toBe(true);
    await page.keyboard.press('Escape');
  }
});

for (const kind of ['mediaseed','mediavpn']) for (const width of [1440,320]) test(`${kind} approved installation flow at ${width}px`, async ({page})=>{
 await mockHub(page);
 await page.setViewportSize({width,height:1000});
 let state='idle'; let posts=0;
 await page.route('**/api/v1/managed-install/**',async route=>{
   if(route.request().method()==='POST') {
     expect(route.request().postDataJSON()).toEqual({planDigest:'a'.repeat(64)});
     posts++;state='succeeded';
     return route.fulfill({json:{data:{state:'accepted'}}});
   }
   return route.fulfill({json:{data:{planDigest:'a'.repeat(64),alreadyRunning:state==='succeeded',operation:{state}}}});
 });
 await page.goto('/store/'+kind);
 const name=kind==='mediaseed'?'MediaSeed':'MediaVPN';
 await page.getByRole('button',{name:'Install '+name,exact:true}).click();
 await expect(page.getByRole('status').filter({hasText:'App installed and running'})).toBeVisible();
 expect(posts).toBe(1);
 await page.reload();
 await expect(page.getByRole('button',{name:'Verify app installation',exact:true})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

for (const width of [1440,320]) test(`installation progress persists and only completes after health at ${width}px`,async({page})=>{
 await mockHub(page);
 await page.setViewportSize({width,height:1000});
 let state='idle',progress=0,phase='preparing',posts=0;
 await page.route('**/api/v1/managed-install/**',async route=>{
  if(route.request().method()==='POST') {
   posts++;state='running';progress=75;phase='health';
   return route.fulfill({json:{data:{state:'accepted',progress:0,phase:'preparing',operationId:'test-operation'}}});
  }
  return route.fulfill({json:{data:{planDigest:'a'.repeat(64),alreadyRunning:state==='succeeded',operation:{state,progress,phase,operationId:'test-operation'}}}});
 });
 await page.goto('/store/mediavpn');
 await page.getByRole('button',{name:'Install MediaVPN',exact:true}).click();
 const bar=page.getByRole('progressbar',{name:'Install MediaVPN',exact:true});
 await expect(bar).toHaveAttribute('aria-valuenow','75');
 await expect(page.locator('.operation-progress')).toContainText('Checking app health');
 await page.reload();
 await expect(bar).toHaveAttribute('aria-valuenow','75');
 expect(posts).toBe(1);
 state='succeeded';progress=100;phase='complete';
 await expect(bar).toHaveAttribute('aria-valuenow','100',{timeout:7000});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

for (const width of [1440,320]) test(`all app setup boxes are centered at ${width}px`, async({page})=>{
 await mockHub(page);
 await page.setViewportSize({width,height:1000});
 await page.route('**/api/v1/**/install-options*',async route=>route.fulfill({json:{data:{hostId:'local',port:8096,slots:[],storage:[]}}}));
 await page.route('**/api/v1/seedbox/wizard/targets',async route=>route.fulfill({json:{data:{bound:false,hosts:[]}}}));
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 for (const path of ['/store/mediavpn','/store/mediaseed','/apps/install/plex','/apps/install/jellyfin','/apps/install/prowlarr','/apps/install/radarr','/apps/install/sonarr','/apps/install/autobrr','/store/cloudflare','/store/fjordhub','/apps/install/seedbox']) {
  await page.goto(path);
  const setup=page.locator('.managed-app-setup,.app-install-page,.store-install-page,.seedbox-wizard').first();
  await expect(setup, path).toBeVisible();
  const box=(await setup.boundingBox())!;
  const main=(await page.locator('.main-content').boundingBox())!;
  expect(Math.abs(box.x+box.width/2-main.x-main.width/2),path).toBeLessThanOrEqual(2);
  expect(box.width,path).toBeLessThanOrEqual(960);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),path).toBe(true);
 }
 expect(errors).toEqual([]);
});

for (const width of [1440,320]) test(`uninstall progress and older Agent activity at ${width}px`,async({page})=>{
 await mockHub(page,true);
 await page.setViewportSize({width,height:1000});
 let state='ready'; let progress:number|undefined=undefined;
 await page.route('**/api/v1/apps/**/uninstall',async route=>{
  if(route.request().method()==='POST') {state='running'; progress=50;}
  return route.fulfill({json:{data:{state,progress,phase:'removing',installationId:'synthetic-installation'}}});
 });
 await page.goto('/');
 await page.getByRole('button',{name:'Uninstall: Jellyfin',exact:true}).click();
 await page.getByRole('button',{name:'Confirm removal',exact:true}).click();
 const modal=page.getByRole('dialog',{name:'Remove Jellyfin',exact:true});
 const bar=modal.getByRole('progressbar');
 await expect(bar).toHaveAttribute('aria-valuenow','50');
 await expect(modal).toContainText('Resetting app settings');
 await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'Uninstall: Jellyfin',exact:true}).click();
 await expect(bar).toHaveAttribute('aria-valuenow','50');
 progress=undefined;
 await expect(bar).not.toHaveAttribute('aria-valuenow',/.+/,{timeout:6000});
 await expect(modal).toContainText('Working...');
 expect(await modal.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
 state='failed';progress=80;
 await expect(bar).toHaveAttribute('aria-valuenow','80',{timeout:6000});
 await expect(modal.getByRole('button',{name:'Confirm removal',exact:true})).toBeEnabled();
});

for(const width of [1440,320]) test(`Cloudflare VPN DNS flow at ${width}px`,async({page})=>{
 await mockHub(page);await page.setViewportSize({width,height:1100});
 const state={configured:false,accountId:'',vpn:{message:null,profiles:[{id:'d'.repeat(24),name:'My VPN',publicIp:'185.111.109.2',type:'A',ready:true,forwardedPort:35458}]},vpnRecords:[] as {id:string;hostname:string;profileId:string;content:string;type:string;autoSync:boolean;status:string;message:string}[],discovery:{zones:[{id:'b'.repeat(32),name:'example.com'}],records:[{id:'c'.repeat(32),zoneId:'b'.repeat(32),name:'existing.example.com',type:'A',content:'1.1.1.1'}],tunnels:[{id:'11111111-2222-4333-8444-555555555555',name:'Existing tunnel',remote:true}],issues:[],complete:true,checkedAt:123}};
 await page.route('**/api/v1/cloudflare/manage**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(route.request().method()!=='GET'){
   const body=route.request().postDataJSON();
   expect(path).not.toContain('/tunnels');
   if(path.endsWith('/credentials')){state.configured=true;state.accountId=body.accountId;}
   else if(path.endsWith('/vpn-dns')){
    expect(body).toEqual({zoneId:'b'.repeat(32),label:'seed',profileId:'d'.repeat(24)});
    state.vpnRecords.push({id:'record-1',hostname:'seed.example.com',profileId:body.profileId,content:'185.111.109.2',type:'A',autoSync:true,status:'synced',message:'VPN DNS record is up to date'});
   }else if(path.endsWith('/sync'))state.vpnRecords[0].content='185.111.109.3';
   else if(path.endsWith('/record-1'))state.vpnRecords[0].autoSync=body.autoSync;
  }
  return route.fulfill({json:{data:state}});
 });
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/store/cloudflare');
 await page.getByLabel('Cloudflare account ID',{exact:true}).fill('a'.repeat(32));
 await page.getByLabel('Cloudflare API token',{exact:true}).fill('synthetic-test-value-12345');
 await page.getByRole('button',{name:'Connect account',exact:true}).click();
 await expect(page.getByLabel('Cloudflare API token',{exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Create tunnel',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Install connector on MediaHub',exact:true})).toHaveCount(0);
 await expect(page.getByText('Existing tunnel',{exact:true})).toBeVisible();
 await page.getByLabel('Record name',{exact:true}).fill('seed');
 await page.getByRole('button',{name:'Create DNS record',exact:true}).click();
 await expect(page.getByText('seed.example.com',{exact:true})).toBeVisible();
 await expect(page.locator('.cloudflare-profile-list').first()).toContainText('A - 185.111.109.2');
 await page.getByRole('button',{name:'Synchronize now',exact:true}).click();
 await expect(page.getByText('A - 185.111.109.3',{exact:true})).toBeVisible();
 await page.getByLabel('Follow VPN IP',{exact:true}).click();
 await expect(page.getByLabel('Follow VPN IP',{exact:true})).not.toBeChecked();
 await expect(page.getByLabel('Target address',{exact:true})).toHaveCount(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 expect(errors).toEqual([]);
});

for(const resource of ['example.com','tunnels']) test(`Cloudflare scoped permissions for ${resource}`,async({page})=>{
 await mockHub(page);await page.setViewportSize({width:320,height:1000});
 await page.route('**/api/v1/cloudflare/manage**',route=>route.fulfill({json:{data:{configured:true,accountId:'a'.repeat(32),vpn:{profiles:[{id:'d'.repeat(24),name:'VPN',ready:true,publicIp:'185.111.109.2',type:'A'}]},vpnRecords:[],discovery:{zones:[{id:'b'.repeat(32),name:'example.com'}],records:[{id:'c'.repeat(32),zoneId:'b'.repeat(32),name:'old.example.com',type:'A',content:'1.1.1.1'}],tunnels:[],complete:false,checkedAt:123,issues:[{resource,permission:resource==='tunnels'?'Account > Cloudflare Tunnel > Read':'Zone > DNS > Edit',message:'Missing permission'}]}}}}));
 await page.goto('/store/cloudflare');
 await expect(page.getByText('Required access:',{exact:false})).toBeVisible();
 await expect(page.getByText('old.example.com',{exact:true})).toBeVisible();
 if(resource==='tunnels')await expect(page.getByRole('button',{name:'Create DNS record',exact:true})).toBeEnabled();else await expect(page.getByRole('button',{name:'Create DNS record',exact:true})).toBeDisabled();
 await expect(page.getByLabel('Cloudflare account ID',{exact:true})).toHaveCount(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

for (const width of [1440,320]) test(`footer stays at viewport bottom across navigation and themes at ${width}px`,async({page})=>{
 await mockHub(page);
 await page.setViewportSize({width,height:1000});
 await page.goto('/settings?section=Appearance');
 for(const [name] of themes) for(const [navigation,label] of [['topbar','Top navigation'],['dock-top','Top dock'],['dock-bottom','Bottom dock'],['launcher','Compact menu']]) {
  await page.locator('.theme-choice').filter({hasText:name}).click();
  await page.getByRole('group',{name:'Navigation layout',exact:true}).getByRole('button',{name:new RegExp(label)}).click();
  const check=async()=>{
   const footer=await page.locator('.footer').boundingBox();
   expect(footer).not.toBeNull();
   expect(Math.abs(footer!.y+footer!.height-1000)).toBeLessThanOrEqual(1);
   expect(footer!.x).toBe(0);
   expect(footer!.width).toBe(width);
   if(navigation==='dock-bottom') {
    const dock=(await page.locator('.shell-navigation-dock').boundingBox())!;
    expect(dock.y+dock.height).toBeLessThanOrEqual(footer!.y);
   }
  };
  await expect(page.locator('html')).toHaveAttribute('data-navigation',navigation);
  await check();
  await page.evaluate(()=>{document.querySelector('main')!.style.minHeight='2000px';window.scrollTo(0,500);});
  await check();
  await page.evaluate(()=>{document.querySelector('main')!.style.minHeight='';window.scrollTo(0,0);});
 }
});

for(const width of [1440,390,320]) test(`duck pond is alive, pausable and account saved at ${width}px`,async({page})=>{
 const {writes}=await mockHub(page);const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setViewportSize({width,height:1000});await page.goto('/settings?section=Appearance');
 await page.locator('.theme-choice').filter({hasText:'Duck Pond'}).click();
 await expect(page.locator('html')).toHaveAttribute('data-look','duck-pond');
 await expect(page.locator('.pond-duck')).toHaveCount(5);
 await expect(page.locator('.duck-pond-scene')).toHaveAttribute('aria-hidden','true');
 await expect(page.locator('.duck-pond-scene')).toHaveAttribute('data-paused','false');
 const duck=page.locator('.pond-duck').first();const before=await duck.evaluate(e=>getComputedStyle(e).transform);
 await page.waitForTimeout(250);expect(await duck.evaluate(e=>getComputedStyle(e).transform)).not.toBe(before);
 await page.locator('.pond-motion').click();await expect(page.locator('.duck-pond-scene')).toHaveAttribute('data-paused','true');
 await page.locator('.pond-motion').click();
 await page.emulateMedia({reducedMotion:'reduce'});await expect(page.locator('.pond-motion')).toBeDisabled();
 expect(await duck.evaluate(e=>getComputedStyle(e).animationName)).toBe('none');
 await page.emulateMedia({reducedMotion:'no-preference'});
 await page.getByRole('button',{name:'Save',exact:true}).click();expect(writes).toHaveLength(1);
 await page.goto('/');await expect(page.locator('html')).toHaveAttribute('data-look','duck-pond');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)).toBe(false);
 await page.screenshot({path:`/tmp/mediahub-duck-pond-${width}.png`});
 await page.goto('/settings?section=Appearance');await page.locator('.theme-choice').filter({hasText:'Soft Orbit'}).click();
 await expect(page.locator('.duck-pond-scene')).toHaveCount(0);await expect(page.locator('.pond-motion')).toHaveCount(0);
 expect(errors).toEqual([]);
});
