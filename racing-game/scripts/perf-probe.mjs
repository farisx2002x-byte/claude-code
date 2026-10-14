// Performance probe. Measures the CPU cost of the game logic per frame (physics
// for 6 cars at 120 Hz, AI, race rules, effects, camera, HUD, audio scheduling)
// and the scene complexity per quality preset. Rendering cost here is from a
// *software* rasterizer (SwiftShader) and does not represent a real GPU.
import { openGame } from '../test/e2e/browser.mjs';

const report = {};
for (const quality of ['low', 'medium', 'high']) {
  for (const trackId of ['downtown', 'harbor']) {
    const { browser, page, errors } = await openGame({ quality, width: 1280, height: 720 });
    const r = await page.evaluate(async (trackId) => {
      const g = window.__neonRush.game;
      g.startEvent({ mode: 'race', trackId, carId: 'vapor' });
      g.debug.autopilot = true;
      g.fastForward(4); // past the countdown
      // Stop the rAF loop's work so we can time things in isolation.
      const origRace = g.updateRace.bind(g);
      const origRender = g.render.bind(g);
      g.updateRace = () => {};
      g.render = () => {};
      const logic = [], render = [];
      for (let i = 0; i < 360; i++) {
        let t = performance.now();
        origRace(1 / 60);
        logic.push(performance.now() - t);
        if (i % 30 === 0) {
          t = performance.now();
          origRender();
          g.renderer.getContext().finish();
          render.push(performance.now() - t);
        }
      }
      const info = g.renderer.info;
      logic.sort((a, b) => a - b);
      const avg = (a) => a.reduce((x, y) => x + y, 0) / a.length;
      return {
        logicAvgMs: +avg(logic).toFixed(3),
        logicP95Ms: +logic[Math.floor(logic.length * 0.95)].toFixed(3),
        logicMaxMs: +logic[logic.length - 1].toFixed(3),
        swRenderAvgMs: +avg(render).toFixed(1),
        drawCalls: info.render.calls,
        triangles: info.render.triangles,
        geometries: info.memory.geometries,
        textures: info.memory.textures,
        jsHeapMB: performance.memory ? +(performance.memory.usedJSHeapSize / 1048576).toFixed(1) : null,
        raceTime: +g.session.race.time.toFixed(1),
      };
    }, trackId);
    report[`${quality}/${trackId}`] = { ...r, errors: errors.length };
    console.log(quality.padEnd(6), trackId.padEnd(9), JSON.stringify(r));
    await browser.close();
  }
}
import('node:fs').then((fs) => fs.writeFileSync(process.argv[2] || 'perf-report.json', JSON.stringify(report, null, 2)));
