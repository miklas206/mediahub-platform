// Native shortcuts need static exports; inline UI marks retain live theme colors.
import {chromium} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const browser=await chromium.launch({executablePath:process.env.MEDIAHUB_ICON_BROWSER||undefined});
try {const page=await browser.newPage({deviceScaleFactor:1});
 for(const [size,file] of [[180,'apple-touch-icon.png'],[192,'icon-192.png'],[512,'icon-512.png']]){
  await page.setViewportSize({width:size,height:size});const mark=readFileSync(root+'public/brand/mediahub.svg','utf8').replace('width="32" height="32"',`width="${size*.8}" height="${size*.8}"`);
  await page.setContent(`<style>body{margin:0;background:#101923;display:grid;place-items:center;width:100vw;height:100vh}</style>${mark}`);await page.screenshot({path:root+'public/'+file});
 }
}finally{await browser.close();}
