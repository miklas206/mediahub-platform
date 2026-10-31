import { useId, type SVGProps } from 'react';
import marks from './brand-marks.json';
export type BrandMark = keyof typeof marks;
export function BrandIcon({brand,size=32,className,...props}: SVGProps<SVGSVGElement> & {brand:BrandMark;size?:number|string}) {
 const id='prisme-'+useId().replace(/[^a-zA-Z0-9_-]/g,'');
 return <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 32 32" fill="none" className={['brand-mark',className].filter(Boolean).join(' ')} data-brand={brand} data-brand-version="prisme-1" aria-hidden={props['aria-label']?undefined:true} role={props['aria-label']?'img':undefined} {...props}>
  <defs>{['front','back','fold','light'].map(tone=><linearGradient key={tone} id={`${id}-${tone}`} className={`prisme-${tone}`} gradientUnits="userSpaceOnUse" x1="5" y1="4" x2="28" y2="30"><stop offset="0" className="prisme-start"/><stop offset=".48" className="prisme-mid"/><stop offset="1" className="prisme-end"/></linearGradient>)}<radialGradient id={`${id}-orb`} cx="30%" cy="25%" r="75%"><stop offset="0" className="prisme-orb-light"/><stop offset=".42" className="prisme-mid"/><stop offset="1" className="prisme-end"/></radialGradient></defs>
  {marks[brand].map((path,index)=><path key={index} d={path.d} fill={`url(#${id}-${path.tone})`} fillRule="evenodd" />)}
 </svg>;
}
