import {readFileSync,writeFileSync,copyFileSync,mkdirSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const marks=JSON.parse(readFileSync(root+'src/brand-marks.json','utf8'));
const svg=(kind,size=32,inline=false)=>`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" ${inline?`class="brand-mark" data-brand="${kind}" aria-hidden="true"`:'color="#25c9ed"'}>${marks[kind].map(p=>`<path d="${p.d}"${p.fill?' fill="currentColor"':''}/>`).join('')}</svg>`;
mkdirSync(root+'public/brand',{recursive:true});
for(const kind of Object.keys(marks))writeFileSync(root+'public/brand/'+kind+'.svg',svg(kind)+'\n');
writeFileSync(root+'public/favicon.svg',svg('mediahub')+'\n');
const runtime=`// Generated from brand-marks.json by sync-brand-icons.mjs.
(() => {
 const marks=${JSON.stringify(marks)};
 const root=document.documentElement, ns='http://www.w3.org/2000/svg';
 let scheduled=false,previous='';
 function update() {
  scheduled=false;
  const link=document.querySelector('link[data-brand-favicon]');
  const kind=link?.dataset.brandFavicon;if(!marks[kind])return;
  const styles=getComputedStyle(root);
  const color=styles.getPropertyValue('--accent').trim() || '#25c9ed';
  const surface=styles.getPropertyValue('--surface').trim() || '#102030';
  const key=kind+color+surface;if(key===previous)return;previous=key;
  const svg=document.createElementNS(ns,'svg');
  svg.setAttribute('viewBox','0 0 32 32');
  const bg=document.createElementNS(ns,'rect');
  for(const [k,v] of Object.entries({x:'0',y:'0',width:'32',height:'32',rx:'7',fill:surface}))bg.setAttribute(k,v);
  svg.append(bg);
  const group=document.createElementNS(ns,'g');
  for(const [k,v] of Object.entries({transform:'translate(3 3) scale(.8125)',fill:'none',stroke:color,'stroke-width':'2.4','stroke-linecap':'round','stroke-linejoin':'round'}))group.setAttribute(k,v);
  for(const mark of marks[kind]) {
   const path=document.createElementNS(ns,'path');path.setAttribute('d',mark.d);
   if(mark.fill)path.setAttribute('fill',color);
   group.append(path);
  }
  svg.append(group);link.type='image/svg+xml';link.href='data:image/svg+xml,'+encodeURIComponent(new XMLSerializer().serializeToString(svg));
 }
 function schedule(){if(!scheduled){scheduled=true;requestAnimationFrame(update);}}
 new MutationObserver(schedule).observe(root,{attributes:true,attributeFilter:['style','class','data-look','data-appearance-mode','data-theme']});
 schedule();
 globalThis.MediaBrandIcons={update};
})();
`;
writeFileSync(root+'public/brand/brand-icons.js',runtime);
for(const [app,asset] of [['mediaseed','mediaseed.svg'],['mediavpn','icon.svg']]) {
 const dir=fileURLToPath(new URL('../../../'+app+'/'+app+'/static/',import.meta.url));
 writeFileSync(dir+asset,svg(app)+'\n');
 writeFileSync(root+'public/assets/services/'+app+'.svg',svg(app)+'\n');
 copyFileSync(root+'src/brand-icons.css',dir+'themes/brand-icons.css');
 writeFileSync(dir+'themes/brand-icons.js',runtime);
 const html=readFileSync(dir+'index.html','utf8').replace(new RegExp('<svg[^>]*data-brand="'+app+'"[^>]*>.*?<\/svg>','g'),m=>svg(app,Number(m.match(/width="(\d+)"/)[1]),true));
 writeFileSync(dir+'index.html',html);
}
