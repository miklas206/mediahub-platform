import type { SVGProps } from 'react';
import marks from './nav-marks.json';
const aliases:Record<string,string>={maintenance:'healthcheck',store:'apps',hosts:'network',backups:'files',insights:'overview',general:'settings',home:'apps','/':'apps','/overview':'overview','/settings':'settings',connection:'vpn',cloudflare:'domains','ratio-scout':'ratio',conversions:'convert',uploader:'uploads',storage:'files',folder:'files'};
export function NavIcon({name,size=19,className,...props}:SVGProps<SVGSVGElement>&{name:string;size?:number|string}){
 const normalized=name.toLowerCase().replace(/^\//,'')||'home';
 const key=aliases[normalized]||normalized;
 const paths=marks[key as keyof typeof marks]||marks.apps;
 return <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={['prisme-nav-icon',className].filter(Boolean).join(' ')} aria-hidden={props['aria-label']?undefined:true} {...props}>{paths.map((d,i)=><path key={i} d={d}/>)}</svg>;
}
