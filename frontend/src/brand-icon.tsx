import type { SVGProps } from 'react';
import marks from './brand-marks.json';
export type BrandMark = keyof typeof marks;
export function BrandIcon({brand,size=32,className,...props}: SVGProps<SVGSVGElement> & {brand:BrandMark;size?:number|string}) {
 return <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" className={['brand-mark',className].filter(Boolean).join(' ')} data-brand={brand} aria-hidden={props['aria-label']?undefined:true} role={props['aria-label']?'img':undefined} {...props}>
  {marks[brand].map((path,index)=><path key={index} d={path.d} fill={'fill' in path && path.fill?'currentColor':'none'} />)}
 </svg>;
}
