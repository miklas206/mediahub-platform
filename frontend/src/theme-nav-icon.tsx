import type { LucideIcon } from 'lucide-react';
import { NavIcon } from './nav-icon';
/** Geometry stays recognisable while the active theme controls its color. */
export function ThemeNavIcon({path}:{path:string;fallback:LucideIcon}){
 return <NavIcon name={path} size={19}/>;
}
