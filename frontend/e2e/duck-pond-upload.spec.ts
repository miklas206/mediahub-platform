import {expect,test} from '@playwright/test';
import {existsSync,readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../../../../MediaUpload/mediaupload/static/',import.meta.url));
for(const width of [1440,390,320])test(`MediaUpload pond preserves the preparation screen at ${width}px`,async({page})=>{
 test.skip(!existsSync(root),'Independent MediaUpload source is not present');
 const errors:string[]=[];let writes=0;page.on('pageerror',e=>errors.push(e.message));
 await page.setViewportSize({width,height:1000});
 await page.route('https://upload.example/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname;
  if(path.includes('/api/')){
   if(request.method()!=='GET')writes++;
   let data:unknown={configured:false};
   if(path.endsWith('/auth/me'))data={csrf:'synthetic'};
   else if(path.endsWith('/storage'))data={locations:[{id:'demo',label:'Synthetic media'}]};
   else if(path.endsWith('/storage/folders'))data={folders:[]};
   else if(path.endsWith('/destinations'))data={configured:false,locations:[]};
   else if(path.endsWith('/upload-helper/files'))data={files:[],subtitles:[]};
   else if(path.endsWith('/upload-helper'))data={jobs:[],tools:{}};
   return route.fulfill({json:data});
  }
  const file=path==='/'?'index.html':path.replace('/static/','');
  return route.fulfill({headers:{'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"},body:readFileSync(root+file),contentType:file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':'text/html'});
 });
 await page.goto('https://upload.example/');await expect(page.locator('#message')).toContainText('Klar.');
 await page.locator('.upload-theme-picker select').selectOption('duck-pond');
 await expect(page.locator('.pond-duck')).toHaveCount(5);
 await expect(page.locator('#step-1')).toBeVisible();expect(writes).toBe(0);
 await page.reload();await expect(page.locator('html')).toHaveAttribute('data-look','duck-pond');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)).toBe(false);
 await page.locator('.upload-theme-picker select').selectOption('default');await expect(page.locator('.duck-pond-scene')).toHaveCount(0);
 expect(errors).toEqual([]);expect(writes).toBe(0);
});
