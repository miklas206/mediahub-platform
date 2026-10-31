import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
const runtime=readFileSync(new URL('../public/brand/brand-icons.js',import.meta.url),'utf8');
const css=readFileSync(new URL('../src/brand-icons.css',import.meta.url),'utf8');
test('old standalone template upgrades safely; dynamic tabs and theme changes stay idempotent',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent(`<style>${css}</style><link rel="icon" data-brand-favicon="mediaseed"><svg class="brand-mark" data-brand="mediaseed" width="34"><path d="M0 0"/></svg><button data-view="downloads"><span class="app-nav-icon"><svg/></span><span class="app-nav-label">Downloads</span></button>`);
 await page.addScriptTag({content:runtime});await expect(page.locator('[data-prisme-live]')).toHaveCount(1);await expect(page.locator('button .prisme-nav-icon')).toHaveCount(1);
 await page.evaluate(()=>{const clone=document.querySelector('svg.brand-mark')!.cloneNode(true) as SVGElement;clone.removeAttribute('data-prisme-live');document.body.append(clone);const tab=document.createElement('button');tab.dataset.view='conversions';tab.textContent='Konvertering';document.body.append(tab);});
 await expect(page.locator('button .prisme-nav-icon')).toHaveCount(2);await expect(page.locator('[data-prisme-live]')).toHaveCount(2);
 const ids=await page.locator('[id]').evaluateAll(nodes=>nodes.map(n=>n.id));expect(new Set(ids).size).toBe(ids.length);
 for(const color of ['#25c9ed','#f6ce73','#7ce3b6']){await page.evaluate(c=>document.documentElement.style.setProperty('--accent',c),color);await expect.poll(async()=>decodeURIComponent(await page.locator('link').getAttribute('href')||'')).toContain('fill="'+color+'"');}
 await page.waitForTimeout(100);await expect(page.locator('.prisme-nav-icon')).toHaveCount(2);expect(errors).toEqual([]);
});
test('shared favicon runtime leaves React-owned brand elements untouched',async({page})=>{
 await page.setContent('<div id="root"><svg class="brand-mark" data-brand="mediahub"><path id="react-owned"/></svg></div>');await page.addScriptTag({content:runtime});await page.waitForTimeout(80);await expect(page.locator('#react-owned')).toHaveCount(1);
});
test('real standalone app shell keeps one icon per tab and original click handlers',async({page})=>{
 await page.setContent(`<header class="topbar"><div class="brand"></div><button id="logout">Log ud</button></header><section id="workspace"><nav><button data-view="downloads">Downloads</button><button data-view="uploader">Upload</button></nav></section><section id="app-settings"><div class="app-settings-panel"></div></section>`);
 await page.evaluate(()=>{document.querySelector('[data-view="uploader"]')!.addEventListener('click',()=>document.body.dataset.clicked='yes');});
 await page.addScriptTag({content:runtime});
 // Exercise early hydration as well as shell-created nav wrappers.
 await expect(page.locator('[data-view="downloads"] .prisme-nav-icon')).toHaveCount(1);
 const shell=readFileSync(new URL('../../docker/bundled/mediaseed/mediaseed/static/app-shell.js',import.meta.url),'utf8');
 await page.addScriptTag({content:shell});
 await expect(page.locator('[data-view="downloads"] .prisme-nav-icon')).toHaveCount(1);await expect(page.locator('[data-view="uploader"] .prisme-nav-icon')).toHaveCount(1);
 await page.locator('[data-view="uploader"]').click();await expect(page.locator('body')).toHaveAttribute('data-clicked','yes');await expect(page.locator('[data-view="uploader"] .app-nav-label')).toHaveText('Upload');
});
