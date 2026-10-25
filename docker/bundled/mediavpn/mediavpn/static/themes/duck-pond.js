/* Andedammen: decorative, local SVG artwork. No API, media or account writes. */
(() => {
  if (globalThis.MediaHubDuckPond) return;
  const root=document.documentElement, motion=matchMedia('(prefers-reduced-motion: reduce)');
  let scene=null,button=null,paused=false;
  const storageKey='mediahub-duck-pond-paused';
  try{paused=localStorage.getItem(storageKey)==='true';}catch{}
  const duck='<svg viewBox="0 0 180 140" fill="none" aria-hidden="true"><ellipse cx="86" cy="119" rx="62" ry="9" fill="#60b9a8" opacity=".17"/><path d="M29 83 10 67c1 37 20 51 67 51 39 0 66-15 65-37-1-13-11-22-26-25l-13 19Z" fill="#efb63e"/><path d="M25 81c8 34 101 48 112 6l-30-12-44-4Z" fill="#ffdc72"/><path d="M84 76c-4-12-12-18-11-35C74 20 90 8 108 11c21 3 31 23 24 41-4 11-10 17-9 33Z" fill="#ffda68"/><path d="m131 43 27 8c4 2 3 7-1 9l-29 5-4-13Z" fill="#f28a3e"/><path d="m134 53 22 1" stroke="#d86a2c" stroke-width="2" stroke-linecap="round"/><circle cx="119" cy="36" r="4.5" fill="#193832"/><circle cx="120" cy="35" r="1.3" fill="#fff7db"/><path d="M49 83c10-8 33-8 47 2-3 18-32 22-47 9" fill="#f8c44e"/><path d="M48 82c11-8 28-6 39-1M87 25c5-6 12-9 20-8" stroke="#fff0b0" stroke-width="4" stroke-linecap="round"/></svg>';
  function mount(){
    scene=document.createElement('div');scene.className='duck-pond-scene';scene.setAttribute('aria-hidden','true');scene.inert=true;
    const sky=document.createElement('div');sky.className='pond-moon';scene.append(sky);
    const shimmer=document.createElement('div');shimmer.className='pond-shimmer';scene.append(shimmer);
    for(const [i,[x,y,size,duration,delay,reverse]] of [[21,80,140,31,-12,false],[68,82,180,39,-20,true],[43,37,90,47,-5,false],[84,55,110,36,-15,true],[40,87,70,34,-8,false]].entries()){
      const lane=document.createElement('div');lane.className='pond-duck-lane';lane.style.cssText=`left:${x}%;top:${y}%;--duck-size:${size}px;--swim-duration:${duration}s;--swim-delay:${delay}s;--duck-facing:${reverse?-1:1}`;
      const bird=document.createElement('div');bird.className='pond-duck';bird.innerHTML=duck;
      const ripple=document.createElement('span');ripple.className='pond-ripple';lane.append(ripple,bird);scene.append(lane);
    }
    for(const [i,[x,y]] of [[8,86],[78,91],[92,63],[31,58],[61,78]].entries()){
      const pad=document.createElement('i');pad.className='pond-lily';pad.style.cssText=`left:${x}%;top:${y}%;--pad-rotation:${i*47}deg`;scene.append(pad);
    }
    for(let i=0;i<12;i++){
      const light=document.createElement('i');light.className='pond-firefly';light.style.cssText=`left:${(i*37+9)%98}%;top:${(i*19+12)%91}%;animation-delay:-${i*1.7}s;animation-duration:${6+i%5}s`;scene.append(light);
    }
    for(const side of ['left','right']){
      const reeds=document.createElement('div');reeds.className='pond-reeds pond-reeds-'+side;
      reeds.innerHTML='<svg viewBox="0 0 250 330" fill="none"><path d="M35 330Q80 170 22 23M62 330Q105 168 88 69M82 330Q137 196 144 102M18 330Q25 202 6 155" stroke="#538d72" stroke-width="5"/><path d="M40 330Q31 196 86 153 66 268 40 330M64 330Q158 231 189 230 161 284 64 330M19 330Q-8 245 4 206 25 244 19 330" fill="#386a56"/><path d="m22 25-2-21M88 70l-1-22M144 103l4-21" stroke="#ba9a57" stroke-width="10" stroke-linecap="round"/></svg>';scene.append(reeds);
    }
    document.body.prepend(scene);
    button=document.createElement('button');button.type='button';button.className='pond-motion';
    button.addEventListener('click',()=>{paused=!paused;try{localStorage.setItem(storageKey,String(paused));}catch{}sync();});
    document.body.append(button);
  }
  function sync(){
    if(root.dataset.look!=='duck-pond'){
      scene?.remove();button?.remove();scene=null;button=null;return;
    }
    if(!scene)mount();
    const reduced=motion.matches||root.dataset.reducedMotion==='true';
    scene.dataset.paused=String(paused||reduced||document.hidden);
    const da=root.lang.startsWith('da'),off=paused||reduced;
    button.textContent=off?(da?'▶ Start dammen':'▶ Animate pond'):(da?'Ⅱ Pause dammen':'Ⅱ Pause pond');
    button.setAttribute('aria-pressed',String(off));button.disabled=reduced;
    button.title=reduced?(da?'Reduceret bevægelse er slået til':'Reduced motion is enabled'):button.textContent;
  }
  globalThis.MediaHubDuckPond={sync};
  new MutationObserver(sync).observe(root,{attributes:true,attributeFilter:['data-look','data-reduced-motion','lang']});
  document.addEventListener('visibilitychange',sync);motion.addEventListener('change',sync);
  window.addEventListener('storage',event=>{if(event.key===storageKey){paused=event.newValue==='true';sync();}});
  sync();
})();
