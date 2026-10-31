import {readFileSync,writeFileSync,mkdirSync,existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {resolve,dirname} from 'node:path';
import {createHash} from 'node:crypto';
import {marks,navMarks,brandCSS,svg} from './brand-svg.mjs';
const root=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(root,'..'),projects=resolve(repo,'../..');
const runtime=readFileSync(new URL('./brand-runtime.js',import.meta.url),'utf8').replace('__BRAND_MARKS__',JSON.stringify(marks)).replace('__NAV_MARKS__',JSON.stringify(navMarks));
const write=(file,text)=>{mkdirSync(dirname(file),{recursive:true});writeFileSync(file,text);};
write(root+'public/brand/brand-icons.js',runtime);
for(const kind of Object.keys(marks)){write(root+'public/brand/'+kind+'.svg',svg(kind)+'\n');write(root+'public/assets/services/'+kind+'.svg',svg(kind)+'\n');}
write(root+'public/favicon.svg',svg('mediahub')+'\n');
function install(dir,kind,asset,local=false){
 if(!existsSync(dir))return;
 write(dir+'/'+asset,svg(kind)+'\n');const prefix=local?'':'themes/';write(dir+'/'+prefix+'brand-icons.js',runtime);write(dir+'/'+prefix+'brand-icons.css',brandCSS);
 const file=dir+'/index.html';if(!existsSync(file))return;let html=readFileSync(file,'utf8');
 html=html.replace(new RegExp('<svg[^>]*data-brand="'+kind+'"[^>]*>[\\s\\S]*?<\\/svg>','g'),m=>svg(kind,Number(m.match(/width="(\d+)"/)?.[1]||34),true));
 if(kind==='mediaupload')html=html.replace(/<span class="mark" aria-hidden="true">↑<\/span>/,svg(kind,42,true));
 if(!html.includes('brand-icons.js'))html=html.replace('</head>',`<link rel="stylesheet" href="static/brand-icons.css?v=prisme-1"><script src="static/brand-icons.js?v=prisme-1" defer></script><link rel="icon" data-brand-favicon="${kind}" href="static/${asset}?v=prisme-1"></head>`);
 html=html.replaceAll('v=brand-1','v=prisme-1');write(file,html);
}
for(const [app,asset] of [['mediaseed','mediaseed.svg'],['mediavpn','icon.svg']]){
 install(resolve(repo,'docker/bundled',app,app,'static'),app,asset);
 if(process.argv.includes('--workspace'))install(resolve(projects,app==='mediaseed'?'MediaSeed':'MediaVPN',app,'static'),app,asset);
}
if(process.argv.includes('--workspace')){
 install(resolve(projects,'MediaUpload/mediaupload/static'),'mediaupload','icon.svg',true);
 const desktop=resolve(projects,'VideoDownloaderExtension/desktop/ui');
 write(desktop+'/brand-icons.css',brandCSS);write(desktop+'/brand-icons.js',runtime);
 const index=desktop+'/index.html';let html=readFileSync(index,'utf8');html=html.replace(/<img class="mark"[^>]*>/,svg('videodownloader',42,true)).replace(/<svg[^>]*data-brand="videodownloader"[^>]*>[\s\S]*?<\/svg>/,svg('videodownloader',42,true));if(!html.includes('brand-icons.js'))html=html.replace('</head>','<link rel="stylesheet" href="brand-icons.css"><script src="brand-icons.js" defer></script></head>');write(index,html);
 write(resolve(projects,'VideoDownloaderExtension/src/assets/prisme.json'),JSON.stringify({marks:marks.videodownloader,nav:navMarks.settings},null,2));
 write(resolve(projects,'VideoDownloaderExtension/src/popup/brand-icons.css'),brandCSS);write(desktop+'/icon.svg',svg('videodownloader',128));
 write(resolve(projects,'VideoDownloaderExtension/branding/icon.svg'),svg('videodownloader',512));
}
const manifestFile=resolve(repo,'docker/bundled/source-manifest.json');if(existsSync(manifestFile)){
 const manifest=JSON.parse(readFileSync(manifestFile,'utf8'));
 for(const kind of ['mediaseed','mediavpn'])for(const name of ['static/index.html','static/themes/brand-icons.js','static/themes/brand-icons.css',kind==='mediaseed'?'static/mediaseed.svg':'static/icon.svg']){
  const key=kind+'/'+kind+'/'+name;manifest[key]=createHash('sha256').update(readFileSync(resolve(repo,'docker/bundled',key),'utf8').replaceAll('\r\n','\n')).digest('hex');
 }write(manifestFile,JSON.stringify(manifest,null,2)+'\n');
}
