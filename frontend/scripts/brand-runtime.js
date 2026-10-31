// Registry injected by sync-brand-icons.mjs. Geometry is trusted build-time data.
(() => {
 const marks=__BRAND_MARKS__,navMarks=__NAV_MARKS__;
 const root=document.documentElement,ns='http://www.w3.org/2000/svg';let serial=0,scheduled=false,previous='';
 const node=(name,attributes={})=>{const element=document.createElementNS(ns,name);for(const [key,value] of Object.entries(attributes))element.setAttribute(key,value);return element;};
 function draw(kind,size=32){
  if(!marks[kind])return null;const id='prisme-live-'+serial++;
  const svg=node('svg',{viewBox:'0 0 32 32',width:size,height:size,class:'brand-mark','data-brand':kind,'data-brand-version':'prisme-1','aria-hidden':'true'}),defs=node('defs');
  for(const tone of ['front','back','fold','light']){const gradient=node('linearGradient',{id:id+'-'+tone,class:'prisme-'+tone,gradientUnits:'userSpaceOnUse',x1:5,y1:4,x2:28,y2:30});for(const [offset,key] of [['0','start'],['.48','mid'],['1','end']])gradient.append(node('stop',{offset,class:'prisme-'+key}));defs.append(gradient);}
  const orb=node('radialGradient',{id:id+'-orb',cx:'30%',cy:'25%',r:'75%'});for(const [offset,key] of [['0','orb-light'],['.42','mid'],['1','end']])orb.append(node('stop',{offset,class:'prisme-'+key}));defs.append(orb);
  svg.append(defs);for(const mark of marks[kind])svg.append(node('path',{d:mark.d,fill:'url(#'+id+'-'+mark.tone+')','fill-rule':'evenodd'}));return svg;
 }
 const aliases={general:'settings',home:'apps',connection:'vpn',cloudflare:'domains',insights:'overview','ratio-scout':'ratio',conversions:'convert',uploader:'uploads',storage:'files',folder:'files'};
 function nav(name,size=19){const key=aliases[name]||name;const svg=node('svg',{viewBox:'0 0 24 24',width:size,height:size,fill:'none',stroke:'currentColor','stroke-width':1.8,'stroke-linecap':'round','stroke-linejoin':'round',class:'prisme-nav-icon','aria-hidden':'true'});for(const d of navMarks[key]||navMarks.apps)svg.append(node('path',{d}));return svg;}
 function hydrate(){
  // Static template logos and shell clones get unique gradient IDs once.
  for(const svg of document.querySelectorAll('svg.brand-mark[data-brand]:not([data-prisme-live])')){const next=draw(svg.dataset.brand,svg.getAttribute('width')||32);if(!next||svg.closest('#root'))continue;next.dataset.prismeLive='true';next.setAttribute('class',svg.getAttribute('class'));if(svg.hasAttribute('aria-label')){next.removeAttribute('aria-hidden');next.setAttribute('aria-label',svg.getAttribute('aria-label'));next.setAttribute('role','img');}svg.replaceWith(next);}
  for(const button of document.querySelectorAll('button[data-view],button[data-vpn-tab],[data-nav-mark],.app-settings-button')){
   const name=button.dataset.navMark||button.dataset.view||button.dataset.vpnTab||'settings';
   const holder=button.querySelector('.app-nav-icon');
   if(holder){if(holder.dataset.prisme===name)continue;holder.replaceChildren(nav(name));holder.dataset.prisme=name;for(const duplicate of button.querySelectorAll('.app-nav-label .prisme-nav-icon'))duplicate.remove();}
   else if(!button.querySelector(':scope > .prisme-nav-icon')){const old=button.querySelector(':scope > svg');if(old)old.replaceWith(nav(name));else button.prepend(nav(name));button.dataset.prismeNav=name;}
  }
 }
 function update(){
  scheduled=false;hydrate();const link=document.querySelector('link[data-brand-favicon]'),kind=link?.dataset.brandFavicon;if(!marks[kind])return;
  const styles=getComputedStyle(root),color=styles.getPropertyValue('--accent').trim()||'#25c9ed',secondary=styles.getPropertyValue('--indigo').trim()||'#8d9cff',surface=styles.getPropertyValue('--surface').trim()||'#102030';
  const key=kind+color+secondary+surface;if(key===previous)return;previous=key;
  const svg=node('svg',{viewBox:'0 0 32 32'});svg.append(node('rect',{width:32,height:32,rx:7,fill:surface}));
  const group=node('g',{transform:'translate(3 3) scale(.8125)'});
  // Solid small-size variant has predictable contrast in browser chrome.
  for(const mark of marks[kind])group.append(node('path',{d:mark.d,fill:color,'fill-rule':'evenodd'}));svg.append(group);
  link.type='image/svg+xml';link.href='data:image/svg+xml,'+encodeURIComponent(new XMLSerializer().serializeToString(svg));
 }
 function schedule(){if(!scheduled){scheduled=true;requestAnimationFrame(update);}}
 new MutationObserver(schedule).observe(root,{attributes:true,attributeFilter:['style','class','data-look','data-appearance-mode','data-theme']});
 // Only added nodes can introduce navigation or logos; updates are idempotent.
 if(!document.getElementById('root'))new MutationObserver(records=>{if(records.some(r=>r.addedNodes.length))schedule();}).observe(document.body,{childList:true,subtree:true});
 globalThis.MediaBrandIcons={update,draw,nav};schedule();
})();
