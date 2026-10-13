// Render new static installation icons; live UI and browser favicons use SVG.
import {chromium} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const marks=JSON.parse(readFileSync(root+'src/brand-marks.json','utf8')).mediahub;
const browser=await chromium.launch({executablePath:process.env.MEDIAHUB_ICON_BROWSER||undefined});
try {
 const page=await browser.newPage({deviceScaleFactor:1});
 for(const [size,file] of [[180,'apple-touch-icon.png'],[192,'icon-192.png'],[512,'icon-512.png']]) {
  await page.setViewportSize({width:size,height:size});
  const paths=marks.map(p=>`<path d="${p.d}"${p.fill?' fill="currentColor"':''}/>`).join('');
  await page.setContent(`<style>body{margin:0}</style><svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 32 32"><rect width="32" height="32" fill="#101923"/><g transform="translate(4.8 4.8) scale(.7)" fill="none" stroke="#25c9ed" color="#25c9ed" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">${paths}</g></svg>`);
  await page.screenshot({path:root+'public/'+file});
 }
} finally {await browser.close();}
