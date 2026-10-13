import { existsSync, readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { expect, it } from 'vitest';
import { appearanceTokens, defaultAppearance } from './appearance-tokens';
import { themePresets } from './theme-presets';
it('independent app bundles generate exactly the same colors as MediaHub', () => {
  const context: { MediaHubAppearance?: { appearanceTokens: typeof appearanceTokens } } = {};
  const bundled = readFileSync(new URL('../public/themes/appearance-tokens.js', import.meta.url), 'utf8');
  runInNewContext(bundled, context);
  for (const preset of [...themePresets.map(p => p.value || defaultAppearance), {...defaultAppearance, accent:'#d044e8', background:'#491826',depth:90}]) {
    for (const dark of [false,true]) expect(context.MediaHubAppearance!.appearanceTokens(preset,dark)).toEqual(appearanceTokens(preset,dark));
  }
});
it('matches sibling app bundles when their source checkouts are available', (context) => {
  const roots = ['../../../', '../../../../'];
  const siblingRoot = roots.find(root => ['mediaseed', 'mediavpn'].every(app => existsSync(new URL(root + app + '/' + app + '/static/themes/appearance-tokens.js', import.meta.url))));
  if (!siblingRoot) { context.skip(); return; }
  const bundled = readFileSync(new URL('../public/themes/appearance-tokens.js', import.meta.url), 'utf8');
  for (const app of ['mediaseed','mediavpn']) {
    expect(readFileSync(new URL(siblingRoot+app+'/'+app+'/static/themes/appearance-tokens.js',import.meta.url),'utf8')).toBe(bundled);
    expect(readFileSync(new URL(siblingRoot+app+'/'+app+'/static/themes/select-controls.css',import.meta.url),'utf8')).toBe(readFileSync(new URL('./select-controls.css',import.meta.url),'utf8'));
  }
});
