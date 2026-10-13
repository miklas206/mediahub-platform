import {expect,test,type Page} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {themePresets} from '../src/theme-presets';
async function mockHub(page: Page, appearance: unknown) {
  const configured = false, username = "Designer";
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
    else if (path === "/system/status") data = { version: "beta-test" };
    await route.fulfill({ json: { data } });
  });
  return { writes };
}


for(const width of [1440,390,320]) for(const theme of themePresets.filter(p=>p.id!=='classic')) test(`Logs select follows ${theme.id} at ${width}px`,async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setViewportSize({width,height:900});await mockHub(page,theme.value);
 await page.goto('/settings?section=Logs');
 const select=page.getByLabel('Log source');await expect(select).toBeVisible();
 expect(await select.evaluate(el=>getComputedStyle(el).appearance)).toBe('base-select');
 await select.click();await expect(select).toHaveJSProperty('value','core');
 expect(await select.evaluate(el=>el.matches(':open'))).toBe(true);
 await expect(page.getByRole('option',{name:'MediaHub Core'})).toBeVisible();
 await page.screenshot({path:test.info().outputPath(`${theme.id}-${width}-open.png`)});
 await page.keyboard.press('Escape');expect(await select.evaluate(el=>el.matches(':open'))).toBe(false);
 await expect(select).toBeFocused();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);expect(errors).toEqual([]);
});
for(const mode of ['dark','light']) test(`native themed picker retains keyboard, form and disabled semantics in ${mode}`,async({page})=>{
 const css=readFileSync(new URL('../src/select-controls.css',import.meta.url),'utf8');
 await page.setContent(`<html data-appearance-mode="${mode}" data-look="precision-terminal"><head><style>:root{--surface:${mode==='dark'?'#152530':'#ffffff'};--raised:${mode==='dark'?'#233442':'#eff4fa'};--text:${mode==='dark'?'#eeeeee':'#102030'};--line:#567;--accent:#169cbf;--accent-bg:#16809822;--accent-line:#169cbf;--muted:#89a;} body{padding:20px;} select{width:280px;} ${css}</style></head><body><form><label>Source<select name="source" required><option value="first">First source</option><option disabled value="disabled">Unavailable</option><option value="second">Second source</option><option hidden value="hidden">Hidden source</option><optgroup label="Other"><option value="long">A much longer source label that must remain readable on narrow screens</option></optgroup></select></label><button type="button">Outside</button></form></body></html>`);
 const select=page.getByLabel('Source');await select.focus();await page.keyboard.press('Space');
 expect(await select.evaluate(el=>el.matches(':open'))).toBe(true);
 await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter');
 await expect(select).toHaveValue('second');expect(await page.locator('form').evaluate(el=>new FormData(el as HTMLFormElement).get('source'))).toBe('second');
 await select.click();await expect(page.getByRole('option',{name:'Hidden source'})).toBeHidden();
 await page.screenshot({path:test.info().outputPath(`picker-${mode}.png`)});
 await page.keyboard.press('Escape');await expect(select).toHaveValue('second');
 await select.click();await page.getByRole('button',{name:'Outside'}).click();expect(await select.evaluate(el=>el.matches(':open'))).toBe(false);
});
