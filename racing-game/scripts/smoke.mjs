import { openGame } from '../test/e2e/browser.mjs';
const { browser, page, errors } = await openGame();
await page.waitForTimeout(2500);
await page.screenshot({ path: process.argv[2] || '/tmp/shot-menu.png' });
console.log(await page.evaluate(() => JSON.stringify(window.__neonRush.game.getDebugInfo())));
console.log('errors', errors);
await browser.close();
