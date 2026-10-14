// Shared Playwright helper: launches Chromium with software WebGL (SwiftShader)
// and opens the built game from dist/.
import { chromium } from 'playwright';
import { pathToFileURL } from 'node:url';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '../..');

export async function openGame({ width = 1280, height = 720, quality } = {}) {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--autoplay-policy=no-user-gesture-required', '--ignore-gpu-blocklist'],
  });
  const page = await browser.newPage({ viewport: { width, height } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  if (quality) {
    await page.addInitScript((q) => {
      const s = JSON.parse(localStorage.getItem('neonrush.settings.v1') || '{}');
      s.quality = q;
      localStorage.setItem('neonrush.settings.v1', JSON.stringify(s));
    }, quality);
  }
  await page.goto(pathToFileURL(join(root, 'dist/index.html')).href);
  await page.waitForFunction(() => window.__neonRush && window.__neonRush.game, null, { timeout: 30000 });
  return { browser, page, errors };
}
