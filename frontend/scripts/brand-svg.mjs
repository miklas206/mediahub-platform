import {readFileSync} from 'node:fs';
export const marks=JSON.parse(readFileSync(new URL('../src/brand-marks.json',import.meta.url),'utf8'));
export const navMarks=JSON.parse(readFileSync(new URL('../src/nav-marks.json',import.meta.url),'utf8'));
export const brandCSS=readFileSync(new URL('../src/brand-icons.css',import.meta.url),'utf8');
let serial=0;
export function svg(kind,size=32,inline=false){
 const id='prisme-'+kind+'-'+serial++;
 const defs=['front','back','fold','light'].map(t=>`<linearGradient id="${id}-${t}" class="prisme-${t}" gradientUnits="userSpaceOnUse" x1="5" y1="4" x2="28" y2="30"><stop offset="0" class="prisme-start"/><stop offset=".48" class="prisme-mid"/><stop offset="1" class="prisme-end"/></linearGradient>`).join('')+`<radialGradient id="${id}-orb" cx="30%" cy="25%" r="75%"><stop offset="0" class="prisme-orb-light"/><stop offset=".42" class="prisme-mid"/><stop offset="1" class="prisme-end"/></radialGradient>`;
 return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="${size}" height="${size}" class="brand-mark" data-brand="${kind}" data-brand-version="prisme-1" aria-hidden="true"><defs>${defs}</defs>${inline?'':`<style>${brandCSS}</style>`}${marks[kind].map(p=>`<path d="${p.d}" fill="url(#${id}-${p.tone})" fill-rule="evenodd"/>`).join('')}</svg>`;
}
