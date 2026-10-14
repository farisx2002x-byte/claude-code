// Bundles the game into dist/ (single classic script, works from file:// in
// Electron and in any modern browser).
import * as esbuild from 'esbuild';
import { cpSync, mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(root, 'dist');
const watch = process.argv.includes('--watch');
rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });
cpSync(join(root, 'src/index.html'), join(dist, 'index.html'));
cpSync(join(root, 'src/style.css'), join(dist, 'style.css'));
cpSync(join(root, 'node_modules/three/LICENSE'), join(dist, 'THREE_LICENSE.txt'));

const opts = {
  entryPoints: [join(root, 'src/main.js')],
  bundle: true,
  format: 'iife',
  target: ['chrome110'],
  outfile: join(dist, 'game.js'),
  minify: !watch,
  sourcemap: watch ? 'inline' : false,
  legalComments: 'eof',
  logLevel: 'info',
};
if (watch) {
  const ctx = await esbuild.context(opts);
  await ctx.watch();
} else {
  await esbuild.build(opts);
}
