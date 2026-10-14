import { openGame } from '../test/e2e/browser.mjs';
const out = process.argv[2];
const { browser, page, errors } = await openGame();
await page.waitForTimeout(500);
await page.evaluate(() => {
  const { game } = window.__neonRush;
  game.startEvent({ mode: 'race', trackId: 'downtown', carId: 'vapor' });
  game.updateMenu = () => {};
  game.updateRace = () => {};
  const p = game.world.path; const f = p.frameAt(p.length - 20);
  game.camera.position.set(f.x + 60, 90, f.z - 40); game.camera.lookAt(f.x, 0, f.z);
});
await page.waitForTimeout(2500);
await page.screenshot({ path: `${out}/top.png` });
console.log(errors);
await browser.close();
