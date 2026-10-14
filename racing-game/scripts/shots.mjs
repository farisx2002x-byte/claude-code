import { openGame } from '../test/e2e/browser.mjs';
const out = process.argv[2];
const track = process.argv[3] || 'downtown';
const q = process.argv[4] || 'medium';
const { browser, page, errors } = await openGame({ quality: q });
await page.waitForTimeout(800);
await page.keyboard.press('Enter'); // RACE
await page.waitForTimeout(1500);
await page.screenshot({ path: `${out}/event.png` });
await page.evaluate((t) => { window.__neonRush.ui.event.trackId = t; }, track);
await page.keyboard.press('Enter'); // choose car
await page.waitForTimeout(1500);
await page.screenshot({ path: `${out}/garage.png` });
await page.keyboard.press('Enter'); // start
await page.waitForTimeout(1200);
await page.screenshot({ path: `${out}/countdown.png` });
await page.evaluate(() => { const g = window.__neonRush.game; g.debug.autopilot = true; g.fastForward(14); });
await page.waitForTimeout(1200);
await page.screenshot({ path: `${out}/race1.png` });
await page.evaluate(() => { window.__neonRush.game.fastForward(9); });
await page.waitForTimeout(1200);
await page.screenshot({ path: `${out}/race2.png` });
console.log(await page.evaluate(() => JSON.stringify(window.__neonRush.game.getDebugInfo())));
console.log('errors', errors);
await browser.close();
