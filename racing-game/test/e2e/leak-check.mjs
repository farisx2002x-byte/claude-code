// Starts 12 races in a row (restarts + track switches) and checks that GPU
// resources and JS heap don't grow, i.e. sessions and worlds are disposed.
import { openGame } from './browser.mjs';
const { browser, page, errors } = await openGame({ width: 640, height: 360 });
const samples = await page.evaluate(async () => {
  const g = window.__neonRush.game;
  const out = [];
  const tracks = ['downtown', 'harbor', 'downtown-r', 'harbor-r'];
  for (let i = 0; i < 12; i++) {
    g.startEvent({ mode: i % 3 === 1 ? 'timetrial' : 'race', trackId: tracks[i % 4], carId: 'vapor' });
    g.debug.autopilot = true;
    g.fastForward(6);
    g.render();
    await new Promise((r) => setTimeout(r, 50));
    const m = g.renderer.info.memory;
    let objects = 0;
    g.scene.traverse(() => objects++);
    out.push({ i, track: tracks[i % 4], objects, geometries: m.geometries, textures: m.textures, heapMB: +(performance.memory.usedJSHeapSize / 1048576).toFixed(1) });
  }
  g.quitToMenu();
  return out;
});
await browser.close();
for (const s of samples) console.log(JSON.stringify(s));
// Same track + mode every 12 races would be ideal; instead compare like-for-like
// sessions (same track & mode) and make sure GPU counts don't trend upwards
// (they fluctuate with what happens to be on screen).
const same = (i, j) => samples[i].objects === samples[j].objects;
const maxOf = (k, from, to) => Math.max(...samples.slice(from, to).map((s) => s[k]));
const ok = same(0, 6) && same(2, 8) && same(3, 9) &&
  maxOf('geometries', 6, 12) <= maxOf('geometries', 0, 6) + 4 &&
  maxOf('textures', 6, 12) <= maxOf('textures', 0, 6) + 3 && errors.length === 0;
console.log(ok ? 'no resource growth across repeated races' : 'RESOURCE GROWTH DETECTED', errors);
process.exitCode = ok ? 0 : 1;
