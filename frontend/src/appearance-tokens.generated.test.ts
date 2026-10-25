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
it('ships identical shared engines and pond assets in each bundled app', () => {
  for (const app of ['mediaseed','mediavpn']) for (const name of ['appearance-tokens.js','duck-pond.js','duck-pond.css','duck.svg']) {
    expect(readFileSync(new URL('../../docker/bundled/'+app+'/'+app+'/static/themes/'+name,import.meta.url),'utf8')).toBe(readFileSync(new URL('../public/themes/'+name,import.meta.url),'utf8'));
  }
});
