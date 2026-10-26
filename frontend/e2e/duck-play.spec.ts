import {expect,test,type Page} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const assets=fileURLToPath(new URL('../public/themes/',import.meta.url));
async function pond(page:Page){
 await page.route('https://pond-play.example/**',route=>{
  const path=new URL(route.request().url()).pathname;
  const csp="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'";
  if(path==='/')return route.fulfill({headers:{'Content-Security-Policy':csp},contentType:'text/html',body:'<!doctype html><html lang="da" data-look="duck-pond"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/fixture.css"><link rel="stylesheet" href="/duck-pond.css"><script defer src="/duck-pond.js"></script></head><body><main><button id="app-button">App-knap</button></main></body></html>'});
  if(path==='/fixture.css')return route.fulfill({contentType:'text/css',body:'html{--surface:#12332e;--panel:#12332e;--text:#fff;--line:#3c6d5d;--accent:#ffd66d}body{margin:0;min-height:1800px}main{min-height:100vh}#app-button{position:fixed;left:10px;top:10px;padding:16px;z-index:2}'});
  return route.fulfill({body:readFileSync(assets+path.slice(1)),contentType:path.endsWith('.js')?'application/javascript':'text/css'});
 });
 await page.goto('https://pond-play.example/');await expect(page.locator('.pond-duck-lane')).toHaveCount(5);
 // Freeze background drift to make pointer geometry deterministic; interaction stays enabled.
 await page.locator('.pond-duck-lane').evaluateAll(lanes=>lanes.forEach(lane=>lane.getAnimations().forEach(a=>a.pause())));
}
async function point(page:Page){const r=await page.locator('.pond-duck-lane').first().boundingBox();return {x:r!.x+r!.width*.5,y:r!.y+r!.height*.5};}
for(const width of [1440,768,390,320])test(`background ducks can be picked up and thrown at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:1000});const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await pond(page);
 const p=await point(page);await page.mouse.move(p.x,p.y);await page.mouse.down();
 await expect(page.locator('.pond-toss-duck.pond-held')).toHaveCount(1);
 expect(await page.locator('.pond-held .pond-wing').first().evaluate(e=>getComputedStyle(e).animationName)).toBe('pond-wing-flap');
 await page.mouse.move(p.x+40,p.y-150,{steps:6});await page.mouse.up();
 await expect(page.locator('.pond-toss-duck.pond-held')).toHaveCount(0);
 await expect(page.locator('.pond-splash')).toHaveCount(1,{timeout:4000});
 await expect(page.locator('.pond-splash i')).toHaveCount(8);await expect(page.locator('.pond-relocated')).toHaveCount(1);
 await expect(page.locator('.pond-toss-duck')).toHaveCount(0);await expect(page.locator('.pond-away')).toHaveCount(0);
 await page.screenshot({path:`/tmp/duck-play-splash-${width}.png`});
 await expect(page.locator('.pond-splash')).toHaveCount(0,{timeout:2000});
 // A foreground button over a duck retains its own click.
 const next=await point(page);await page.locator('#app-button').evaluate((button,p)=>{button.style.left=(p.x-30)+'px';button.style.top=(p.y-20)+'px';button.addEventListener('click',()=>button.dataset.clicked='true');},next);
 await page.mouse.click(next.x,next.y);await expect(page.locator('#app-button')).toHaveAttribute('data-clicked','true');await expect(page.locator('.pond-toss-duck')).toHaveCount(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);expect(errors).toEqual([]);
});
test('keyboard play, reduced motion and theme teardown clean up the duck',async({page})=>{
 await pond(page);const control=page.locator('.pond-play-controls button').first();await control.focus();await control.press('Enter');await expect(control).toHaveAttribute('aria-pressed','true');
 const before=await page.locator('.pond-toss-duck').boundingBox();await control.press('ArrowRight');expect((await page.locator('.pond-toss-duck').boundingBox())!.x).toBeGreaterThan(before!.x);
 await page.emulateMedia({reducedMotion:'reduce'});expect(await page.locator('.pond-held .pond-wing').first().evaluate(e=>getComputedStyle(e).animationName)).toBe('none');
 await control.press('Enter');await expect(page.locator('.pond-toss-duck')).toHaveCount(0);await expect(page.locator('.pond-splash')).toHaveCount(0);await expect(control).toHaveAttribute('aria-pressed','false');
 await page.emulateMedia({reducedMotion:'no-preference'});await control.press('Enter');await page.evaluate(()=>{document.documentElement.dataset.look='classic';});
 await expect(page.locator('.pond-play-layer,.pond-play-controls,.duck-pond-scene')).toHaveCount(0);await expect(page.locator('html')).not.toHaveClass(/pond-grabbing/);
 await page.evaluate(()=>{document.documentElement.dataset.look='duck-pond';});await expect(page.locator('.pond-duck-lane')).toHaveCount(5);await expect(page.locator('.pond-play-layer')).toHaveCount(1);
});
test('touch can drag a duck while ordinary page scrolling stays available',async({browser})=>{
 const context=await browser.newContext({viewport:{width:390,height:1000},hasTouch:true,isMobile:true});const page=await context.newPage();await pond(page);const p=await point(page),cdp=await context.newCDPSession(page);
 const touch=async(type:string,x:number,y:number)=>cdp.send('Input.dispatchTouchEvent',{type,touchPoints:type==='touchEnd'?[]:[{x,y,id:1}]});
 await touch('touchStart',p.x,p.y);await expect(page.locator('.pond-held')).toHaveCount(1);await touch('touchMove',p.x+35,p.y-140);await touch('touchEnd',p.x+35,p.y-140);
 await expect(page.locator('.pond-relocated')).toHaveCount(1,{timeout:4000});expect(await page.evaluate(()=>scrollY)).toBe(0);
 await touch('touchStart',350,500);await touch('touchMove',350,200);await touch('touchEnd',350,200);await expect.poll(()=>page.evaluate(()=>scrollY)).toBeGreaterThan(0);
 await context.close();
});
test('cancelling a grab restores the duck and pausing ends a flight',async({page})=>{
 await pond(page);const p=await point(page);await page.mouse.move(p.x,p.y);await page.mouse.down();await page.evaluate(()=>document.dispatchEvent(new PointerEvent('pointercancel',{pointerId:1})));
 await expect(page.locator('.pond-toss-duck,.pond-away')).toHaveCount(0);await page.mouse.up();
 await page.mouse.move(p.x,p.y);await page.mouse.down();await page.mouse.move(p.x+50,p.y-120,{steps:4});await page.mouse.up();await page.locator('.pond-motion').click();
 await expect(page.locator('.pond-toss-duck')).toHaveCount(0);await expect(page.locator('.duck-pond-scene')).toHaveAttribute('data-paused','true');
});
