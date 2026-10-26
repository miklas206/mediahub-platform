import {expect,test} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../../docker/bundled/mediaseed/mediaseed/static/',import.meta.url));
for(const width of [1440,768,390,320]) test(`Duck Pond boards at the VPN hop at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:1000});const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{localStorage.setItem('mediahub-app-theme-v2','duck-pond');});
 await page.route('https://boarding.example/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.startsWith('/api/')){
   let data:unknown=[];
   if(path==='/api/auth/status')data={needsSetup:false};
   else if(path==='/api/auth/me')data={username:'synthetic',role:'administrator',language:'en',csrf:'synthetic'};
   else if(path==='/api/storage')data={locations:[]};
   else if(path==='/api/status')data={downloadsEnabled:true,downloadFolderReady:true};
   return route.fulfill({json:data});
  }
  if(path.includes('events'))return route.fulfill({contentType:'text/event-stream',body:''});
  const file=path==='/'?'index.html':path.replace('/static/','');
  return route.fulfill({body:readFileSync(root+file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'text/html'});
 });
 await page.goto('https://boarding.example/');
 await page.waitForFunction('!!globalThis.MediaSeedWorkspace');
 const sample=(active=true,age=0)=>page.evaluate(`downloadsEnabled=${active};torrentSnapshotValid=true;lastTorrentSample=Date.now()-${age};torrents=[{hash:'a'.repeat(40),name:'Synthetic traffic',state:'downloading',dlspeed:1e6,upspeed:1e6}];document.querySelector('#connection-flow').dataset.state='${active?'active':'blocked'}';MediaSeedWorkspace.render();`);
 await sample();
 const crossing=await page.evaluate(()=>{
  const icons=document.querySelectorAll('.download-route .route-icon');
  const f=icons[0].getBoundingClientRect(),v=icons[1].getBoundingClientRect(),l=icons[3].getBoundingClientRect();
  return (v.left+v.width/2-f.left-f.width/2+20)/(l.left+l.width/2-f.left-f.width/2+40);
 });
 for(const lane of ['download','upload']){
  const frame=(fraction:number)=>page.evaluate(async({lane,fraction})=>{
   const p=document.querySelector('.packet-lane-'+lane+' .traffic-packet')!;
   for(const a of p.getAnimations({subtree:true})){
    const timing=a.effect!.getTiming();a.pause();a.currentTime=Number(timing.delay)+Number(timing.duration)*(lane==='upload'?1-fraction:fraction);
   }
   await new Promise(requestAnimationFrame);
   return {y:new DOMMatrix(getComputedStyle(p,'::before').transform).m42,leaf:Number(getComputedStyle(p,'::after').opacity)};
  },{lane,fraction});
  const before=await frame(crossing+(lane==='download'?-.05:.05));expect(before.y).toBeCloseTo(0,0);expect(before.leaf).toBeLessThan(.05);
  expect((await frame(crossing)).y).toBeLessThan(-10);
  const after=await frame(crossing+(lane==='download'?.06:-.06));expect(after.y).toBeCloseTo(-5,0);expect(after.leaf).toBeGreaterThan(.95);
 }
 await page.locator('.pond-motion').click();
 expect(await page.locator('.traffic-packet').first().evaluate(p=>getComputedStyle(p,'::after').animationPlayState)).toBe('paused');
 await page.emulateMedia({reducedMotion:'reduce'});
 for(const pseudo of ['::before','::after'])expect(await page.locator('.traffic-packet').first().evaluate((p,pseudo)=>getComputedStyle(p,pseudo).animationName,pseudo)).toBe('none');
 await sample(false);await expect(page.locator('.traffic-packet')).toHaveCount(0);
 await sample(true,31000);await expect(page.locator('.traffic-packet')).toHaveCount(0);
 await page.emulateMedia({reducedMotion:'no-preference'});await sample();
 await page.evaluate("MediaAppTheme.apply('midnight-glass')");
 await expect(page.locator('.route-packets')).toBeHidden();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);expect(errors).toEqual([]);
});
