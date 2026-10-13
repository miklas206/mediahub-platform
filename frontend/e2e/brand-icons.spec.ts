import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {themePresets} from '../src/theme-presets';
import {appearanceTokens,defaultAppearance,contrastRatio} from '../src/appearance-tokens';
test('new marks stay readable at small sizes across themes and custom colors',async({page})=>{
 const cases=themePresets.filter(p=>p.id!=='classic').flatMap(p=>[false,true].map(dark=>({name:p.name+(dark?' / Dark':' / Light'),value:p.value!,dark})));
 for(const accent of ['#000000','#ffffff','#ff0088'])for(const dark of [false,true])cases.push({name:accent+(dark?' / Dark':' / Light'),value:{...defaultAppearance,accent},dark});
 const glyphs=['mediahub','mediaseed','mediavpn'].map(kind=>readFileSync(new URL('../public/brand/'+kind+'.svg',import.meta.url),'utf8').replace('color="#25c9ed"','class="brand-mark"'));
 const css=readFileSync(new URL('../src/brand-icons.css',import.meta.url),'utf8');
 const rows=cases.map(c=>{const tokens=appearanceTokens(c.value,c.dark);expect(contrastRatio(tokens['--accent'],tokens['--surface'])).toBeGreaterThanOrEqual(4.5);return `<section style="${Object.entries(tokens).map(([k,v])=>k+':'+v).join(';')}"><header>${c.name}</header>${glyphs.map(svg=>`<article>${[16,24,48].map(size=>svg.replace('width="32" height="32"',`width="${size}" height="${size}"`)).join('')}</article>`).join('')}</section>`;}).join('');
 await page.setViewportSize({width:1000,height:1000});
 await page.setContent(`<html><head><link rel="icon" data-brand-favicon="mediahub"><style>${css} *{box-sizing:border-box} body{margin:0;background:#0b1620;color:white;font:14px 'Segoe UI',sans-serif;padding:24px} h1{margin:0 0 4px} p{color:#aabbcc;margin-bottom:24px} .heads,section{display:grid;grid-template-columns:220px repeat(3,1fr);align-items:center;gap:16px;padding:12px 18px} section{background:var(--surface);color:var(--text);margin-bottom:4px;border:1px solid var(--line);border-radius:6px;min-height:100px} article{display:flex;gap:16px;align-items:center} header{font-weight:600}</style></head><body><h1>MediaHub / New theme-aware marks</h1><p>One silhouette. Theme colors. 16 / 24 / 48 px.</p><div class="heads"><span>Theme / color</span><strong>MediaHub</strong><strong>MediaSeed</strong><strong>MediaVPN</strong></div>${rows}</body></html>`);
 await page.screenshot({path:test.info().outputPath('brand-family.png'),fullPage:true});
 await page.addScriptTag({content:readFileSync(new URL('../public/brand/brand-icons.js',import.meta.url),'utf8')});
 for(const color of ['#25c9ed','#ff0088','#ffffff']){
  await page.evaluate(color=>{document.documentElement.style.setProperty('--accent',color);document.documentElement.style.setProperty('--surface','#101923');},color);
  await expect.poll(async()=>decodeURIComponent(await page.locator('link[rel="icon"]').getAttribute('href')||'').includes(`stroke="${color}"`)).toBe(true);
 }
});
