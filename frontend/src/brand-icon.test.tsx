import {expect,it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {BrandIcon} from './brand-icon';
import {ServiceIcon} from './service-icon';
import {NavIcon} from './nav-icon';
import {readFileSync} from 'node:fs';
it('Prisme marks use live theme gradients with accessible labels',()=>{
 for(const [id,brand] of [['mediahub','mediahub'],['org.mediahub.core','mediahub'],['org.mediahub.seedbox','mediaseed'],['org.mediahub.mediavpn','mediavpn'],['org.mediahub.plex-gpu-transcoder','plex-transcoder'],['healthcheck','healthcheck'],['plex','plex'],['jellyfin','jellyfin'],['mediaupload','mediaupload']]){
  const html=renderToStaticMarkup(<ServiceIcon packageId={id} size={24} aria-label={brand}/>);
  expect(html).toContain('data-brand="'+brand+'"');expect(html).toContain('linearGradient');expect(html).not.toContain('<image');expect(html).toContain('role="img"');
 }
 const html=renderToStaticMarkup(<><BrandIcon brand="mediahub"/><BrandIcon brand="mediahub"/></>);
 const ids=[...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);expect(new Set(ids).size).toBe(ids.length);
 expect(html).toContain('aria-hidden="true"');expect(renderToStaticMarkup(<ServiceIcon packageId="fjordhub"/>)).not.toContain('data-brand="');
});
it('navigation preserves semantics and inherits the control color',()=>{
 for(const name of ['General','Users','Appearance','Healthcheck','/overview','downloads','conversions','uploader']){
  const html=renderToStaticMarkup(<NavIcon name={name}/>);expect(html).toContain('currentColor');expect(html).toContain('aria-hidden="true"');expect(html).not.toContain('linearGradient');
 }
});
it('fresh-install bundled apps contain the same versioned shared artwork and runtime',()=>{
 const runtime=readFileSync(new URL('../public/brand/brand-icons.js',import.meta.url),'utf8');
 const css=readFileSync(new URL('./brand-icons.css',import.meta.url),'utf8');
 for(const app of ['mediaseed','mediavpn']){
  const base=new URL('../../docker/bundled/'+app+'/'+app+'/static/',import.meta.url);
  expect(readFileSync(new URL('themes/brand-icons.js',base),'utf8')).toBe(runtime);
  expect(readFileSync(new URL('themes/brand-icons.css',base),'utf8')).toBe(css);
  const html=readFileSync(new URL('index.html',base),'utf8');expect(html).toContain('v=prisme-1');expect(html).toContain('data-brand-version="prisme-1"');
 }
});
