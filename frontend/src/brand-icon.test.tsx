import {expect,it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {BrandIcon} from './brand-icon';
import {ServiceIcon} from './service-icon';
import {existsSync,readFileSync} from 'node:fs';
it('first party marks use theme color, distinct paths and accessible labels',()=>{
 for(const [id,brand] of [['mediahub','mediahub'],['org.mediahub.core','mediahub'],['org.mediahub.seedbox','mediaseed'],['org.mediahub.mediaseed','mediaseed'],['org.mediahub.mediavpn','mediavpn']]) {
  const html=renderToStaticMarkup(<ServiceIcon packageId={id} size={16} aria-label={brand}/>);
  expect(html).toContain('data-brand="'+brand+'"');expect(html).toContain('currentColor');expect(html).not.toContain('<image');expect(html).not.toContain('#');expect(html).toContain('role="img"');
 }
 expect(renderToStaticMarkup(<BrandIcon brand="mediahub"/>)).toContain('aria-hidden="true"');
});
it('apps share the generated favicon updater and branded SVG styles',(context)=>{
 const siblingRoot=['../../../','../../../../'].find(root=>['mediaseed','mediavpn'].every(app=>existsSync(new URL(root+app+'/'+app+'/static/themes/brand-icons.js',import.meta.url))));
 if(!siblingRoot){context.skip();return;}
 const runtime=readFileSync(new URL('../public/brand/brand-icons.js',import.meta.url),'utf8');
 const css=readFileSync(new URL('./brand-icons.css',import.meta.url),'utf8');
 for(const app of ['mediaseed','mediavpn']) {
  expect(readFileSync(new URL(siblingRoot+app+'/'+app+'/static/themes/brand-icons.js',import.meta.url),'utf8')).toBe(runtime);
  expect(readFileSync(new URL(siblingRoot+app+'/'+app+'/static/themes/brand-icons.css',import.meta.url),'utf8')).toBe(css);
 }
});
