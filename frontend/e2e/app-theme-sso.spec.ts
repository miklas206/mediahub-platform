import {textOutsideCards} from "./text-containment";
import {expect,test} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {appearanceTokens,defaultAppearance,type Appearance} from '../src/appearance-tokens';
const styles=['midnight-glass','soft-orbit','precision-terminal','floating-layers','edge-signal'] as const;
for(const app of ['mediaseed','mediavpn']) for(const width of [1440,390,320]) test(`${app} inherits per-user SSO appearance at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:1000});
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 let appearance:Appearance|null={...defaultAppearance,style:'precision-terminal',accent:'#d044e8',mode:'dark',density:'compact',reducedMotion:true};
 let managed=true,language='en',theme='dark';let reads=0;let themeOverride:string|null=null;let rejectOverride=false;
 const staticRoot=resolve(process.cwd(),'../../'+app+'/'+app+'/static');
 await page.addInitScript(()=>localStorage.setItem('mediahub-app-theme-v2','edge-signal'));
 await page.route('https://app.example/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.startsWith('/api/')) {
   let data:unknown=[];
   if(path==='/api/auth/status')data={needsSetup:false,managed,loginUrl:'https://app.example/auth/hub/start'};
   else if(path==='/api/auth/me'){reads++;data={id:'synthetic-user',csrf:'test',username:'Tester',role:'administrator',managed,language,appearance,theme,themeOverride};}
   else if(path==='/api/auth/preferences'){ if(rejectOverride)return route.fulfill({status:503,json:{detail:'Synthetic save failure'}}); themeOverride=route.request().postDataJSON().themeOverride;data={themeOverride}; }
   else if(path==='/api/runtime')data={enabled:false};
   else if(path==='/api/dashboard')data={runtime:{downloadsEnabled:false},torrents:[],queue:null};
   else if(path==='/api/storage')data={freeBytes:100000000,totalBytes:200000000};
   return route.fulfill({json:data});
  }
  const file=path==='/'?'index.html':path.replace(/^\/static\//,'');
  const types:Record<string,string>={js:'application/javascript',css:'text/css',svg:'image/svg+xml',html:'text/html',webp:'image/webp'};
  return route.fulfill({body:readFileSync(resolve(staticRoot,file)),contentType:types[file.split('.').at(-1)!]||'application/octet-stream'});
 });
 await page.goto('https://app.example/');
 await expect(page.locator('#workspace')).toBeVisible();
 await expect(page.locator('.topbar .theme-switch')).toHaveCount(0);
 await expect(page.locator('.topbar .browser-extension-link')).toHaveCount(0);
 await page.locator('.app-settings-button').click();
 await expect(page.locator('#app-settings')).toBeVisible();

 await expect(page.locator('html')).toHaveAttribute('data-theme-source','mediahub');
 const brand = page.locator(`.topbar svg[data-brand="${app}"]`);
 await expect(brand).toBeVisible();
 expect(await brand.evaluate(el=>getComputedStyle(el).stroke)).toBe(await brand.evaluate(el=>getComputedStyle(el).color));
 await expect(page.locator('link[data-brand-favicon]')).toHaveAttribute('href',/^data:image\/svg\+xml,/);

 await expect(page.locator('.theme-switch select')).toBeVisible();
 await expect(page.locator('.theme-switch select')).toHaveValue('follow-hub');
 expect(await page.locator('.theme-switch select').evaluate(el=>getComputedStyle(el).appearance)).toBe('base-select');
 await page.locator('.theme-switch select').click();
 await expect(page.getByRole('option',{name:'Follow MediaHub',exact:true})).toBeVisible();
 await page.screenshot({path:test.info().outputPath(`${app}-${width}-theme-picker.png`)});
 await page.keyboard.press('Escape');

 await expect(page.locator('.managed-theme-name')).toHaveText('From MediaHub');
 expect(await page.evaluate(()=>localStorage.getItem('mediahub-app-theme-v2'))).toBe('edge-signal');
 for(const style of styles){
  appearance={...appearance!,style};
  const previous=reads;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await expect.poll(()=>reads).toBeGreaterThan(previous);
  await expect(page.locator('html')).toHaveAttribute('data-look',style);
  const actual=await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--accent').trim());
  expect(actual).toBe(appearanceTokens(appearance,true)['--accent']);
 }
 appearance={...appearance!,mode:'system',style:'soft-orbit'};
 await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
 await page.emulateMedia({colorScheme:'light'});
 await expect(page.locator('html')).toHaveAttribute('data-appearance-mode','light');
 await page.emulateMedia({colorScheme:'dark'});
 await expect(page.locator('html')).toHaveAttribute('data-appearance-mode','dark');
 expect(await page.locator('body').evaluate(el=>getComputedStyle(el,'::after').animationName)).toBe('none');
 appearance={...appearance!,mode:'inherit',density:'comfortable',reducedMotion:false};theme='light';language='da';
 await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
 await expect(page.locator('html')).toHaveAttribute('data-appearance-mode','light');
 await expect(page.locator('html')).toHaveAttribute('data-density','comfortable');
 await expect(page.locator('.theme-switch')).toContainText('Fra MediaHub');
 // An account override wins over future hub changes and persists after reload.
 await page.locator('.theme-switch select').selectOption('edge-signal');
 await expect(page.locator('html')).toHaveAttribute('data-theme-source','override');
 expect(await brand.evaluate(el=>getComputedStyle(el).stroke)).toBe(await brand.evaluate(el=>getComputedStyle(el).color));
 await expect.poll(async()=>{const href=await page.locator('link[data-brand-favicon]').getAttribute('href');const color=await page.locator('html').evaluate(el=>getComputedStyle(el).getPropertyValue('--accent').trim());return decodeURIComponent(href||'').includes('stroke=\"'+color+'\"');}).toBe(true);

 await expect(page.locator('html')).toHaveAttribute('data-look','edge-signal');
 appearance={...appearance!,style:'precision-terminal'};
 await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
 await expect(page.locator('html')).toHaveAttribute('data-look','edge-signal');
 await page.reload();await expect(page.locator('#workspace')).toBeVisible();await page.locator('.app-settings-button').click();
 await expect(page.locator('.theme-switch select')).toHaveValue('edge-signal');
 rejectOverride=true;await page.locator('.theme-switch select').selectOption('soft-orbit');
 await expect(page.locator('.theme-switch select')).toHaveValue('edge-signal');
 await expect(page.locator('.app-settings-message')).toBeVisible();await expect(page.locator('.app-settings-message')).toContainText('Synthetic save failure');rejectOverride=false;
 await page.locator('.theme-switch select').selectOption('follow-hub');
 await expect(page.locator('html')).toHaveAttribute('data-theme-source','mediahub');
 await expect(page.locator('html')).toHaveAttribute('data-look','precision-terminal');
 // Reset and malformed data cannot retain the previous user's colors or inject CSS.
 appearance=null;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
 await expect(page.locator('html')).toHaveAttribute('data-look','midnight-glass');
 appearance={...defaultAppearance,accent:'url(https://evil.invalid)' as string};
 await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
 await expect(page.locator('html')).toHaveAttribute('data-look','midnight-glass');
 expect(await page.locator('html').getAttribute('style')).not.toContain('evil');
 // A local installation keeps the independently selected theme.
 managed=false;await page.reload();await expect(page.locator('#workspace')).toBeVisible();await page.locator('.app-settings-button').click();
 await expect(page.locator('.theme-switch select')).toBeVisible();
 await expect(page.locator('html')).toHaveAttribute('data-look','edge-signal');
 await page.locator('.theme-switch select').selectOption('soft-orbit');
 await expect(page.locator('html')).toHaveAttribute('data-look','soft-orbit');
 await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
 await expect(page.locator('html')).toHaveAttribute('data-look','soft-orbit');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:test.info().outputPath(`${app}-${width}.png`),fullPage:true});

 if(app==='mediaseed') {
  await expect(page.locator('.settings-extension-guide')).toHaveAttribute('href','/static/extensions.html');
  for(const browser of ['chromium','firefox','safari']) {
   await page.locator('.settings-extension-browser').selectOption(browser);
   const suffix=browser==='safari'?'safari-source':browser;
   await expect(page.locator('.settings-extension-download')).toHaveAttribute('href',`/static/extensions/mediaseed-${suffix}.zip`);
   const downloadPromise=page.waitForEvent('download');await page.locator('.settings-extension-download').click();
   const download=await downloadPromise;expect(download.suggestedFilename()).toBe(`mediaseed-${suffix}.zip`);
  }
 } else await expect(page.locator('.app-settings-extension')).toHaveCount(0);
 expect(await textOutsideCards(page)).toEqual([]);
 await page.screenshot({path:test.info().outputPath(`${app}-${width}-settings.png`),fullPage:true});
 await page.locator('#app-settings').screenshot({path:test.info().outputPath(`${app}-${width}-settings-dialog.png`)});
 await page.keyboard.press('Escape');await expect(page.locator('#app-settings')).toBeHidden();
 await expect(page.locator('.app-settings-button')).toBeFocused();
 await page.screenshot({path:test.info().outputPath(`${app}-${width}-header.png`),fullPage:true});
 expect(errors).toEqual([]);
});
