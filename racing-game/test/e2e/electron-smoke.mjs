// Launches the *packaged* Electron app (release/NeonRush-<platform>-x64) and checks
// that the game boots, the native bridge is present and a race can start.
// Linux CI/dev: run under xvfb-run. Windows: run directly after `npm run package:win`.
import { _electron as electron } from 'playwright';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { existsSync } from 'node:fs';

const root = join(dirname(fileURLToPath(import.meta.url)), '../..');
const exe = process.platform === 'win32' ? join(root, 'release/NeonRush-win32-x64/NeonRush.exe') : join(root, 'release/NeonRush-linux-x64/NeonRush');
if (!existsSync(exe)) throw new Error('Packaged app not found: ' + exe);
const shot = process.argv[2];
const app = await electron.launch({ executablePath: exe, args: process.platform === 'linux' ? ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : [] });
const page = await app.firstWindow();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
await page.waitForFunction(() => window.__neonRush?.game, null, { timeout: 30000 });
const info = await page.evaluate(() => ({
  native: typeof window.neonRushNative?.setWindowMode === 'function',
  title: document.title,
  screen: window.__neonRush.ui.current,
  quitButton: !!document.querySelector('[data-act=quit]'),
}));
await page.evaluate(() => window.__neonRush.game.startEvent({ mode: 'race', trackId: 'downtown', carId: 'vapor' }));
await page.waitForTimeout(1500);
const state = await page.evaluate(() => window.__neonRush.game.state);
// Window-mode IPC round trip
await page.evaluate(() => window.neonRushNative.setWindowMode({ width: 1600, height: 900, fullscreen: false }));
await page.waitForTimeout(500);
const size = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getContentSize());
if (shot) await page.screenshot({ path: shot });
await app.close();
console.log(JSON.stringify({ ...info, raceState: state, contentSize: size, errors }));
if (!info.native || state !== 'race' || errors.length) process.exit(1);
