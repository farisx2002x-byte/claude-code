// End-to-end test of the built game in Chromium (software WebGL).
// Drives the real UI with the keyboard/mouse, plays races (using the in-game
// autopilot + fastForward test hook so a 3-lap race doesn't take minutes in a
// software renderer) and checks results, progression, settings and presets.
//
// Usage: npm run test:e2e   (screenshots -> test/e2e/out/)

import { openGame } from './browser.mjs';
import { mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const outDir = join(dirname(fileURLToPath(import.meta.url)), 'out');
mkdirSync(outDir, { recursive: true });
const results = [];
let failed = 0;

async function step(name, fn) {
  const t0 = Date.now();
  try {
    const info = await fn();
    results.push({ name, ok: true, ms: Date.now() - t0, info });
    console.log(`  ok  ${name}${info ? ' — ' + JSON.stringify(info) : ''}`);
  } catch (e) {
    failed++;
    results.push({ name, ok: false, error: e.message });
    console.log(`  FAIL ${name}: ${e.message}`);
  }
}

const assert = (c, msg) => {
  if (!c) throw new Error(msg);
};

const frames = (page, n = 3) => page.evaluate((n) => new Promise((r) => {
  let k = 0;
  const f = () => (++k >= n ? r() : requestAnimationFrame(f));
  requestAnimationFrame(f);
}), n);

const G = (page, fn, arg) => page.evaluate(fn, arg);

async function finishRace(page) {
  await G(page, () => {
    const g = window.__neonRush.game;
    g.debug.autopilot = true;
    for (let i = 0; i < 60 && !g.session.resultsShown; i++) {
      g.fastForward(5);
      // results are triggered from the render loop a few seconds after the finish
      if (g.session.race.state === 'finished' && g.session.race.postFinishTimer > 5) g.finishEvent();
    }
    g.debug.autopilot = false;
  });
  await page.waitForFunction(() => window.__neonRush.ui.current === 'results', null, { timeout: 20000 });
}

console.log('Neon Rush e2e');
const { browser, page, errors } = await openGame({ width: 1280, height: 720 });
await G(page, () => localStorage.clear());
await page.reload();
await page.waitForFunction(() => window.__neonRush?.game);
await frames(page, 3);

await step('boots to the title menu without errors', async () => {
  const s = await G(page, () => ({ screen: window.__neonRush.ui.current, credits: document.querySelector('.credits')?.textContent, webgl: !!window.__neonRush.game.renderer.getContext() }));
  assert(s.screen === 'title', 'not on title: ' + s.screen);
  assert(s.webgl, 'no WebGL context');
  assert(errors.length === 0, errors.join('\n'));
  await page.screenshot({ path: join(outDir, '01-title.png') });
  return s;
});

await step('keyboard navigation: arrows + Enter + Esc', async () => {
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('ArrowDown'); // How to play
  const focused = await G(page, () => document.activeElement.textContent.trim().toLowerCase());
  assert(focused.startsWith('how to play'), 'focus on ' + focused);
  await page.keyboard.press('Enter');
  await frames(page);
  assert((await G(page, () => window.__neonRush.ui.current)) === 'help', 'help not opened');
  await page.screenshot({ path: join(outDir, '02-help.png') });
  await page.keyboard.press('Escape');
  await frames(page);
  assert((await G(page, () => window.__neonRush.ui.current)) === 'title', 'Esc did not go back');
});

await step('settings: change preset, toggles and volume persist', async () => {
  await page.click('[data-act=settings]');
  await frames(page);
  await page.click('[data-set=quality][data-val=low]');
  await page.click('[data-toggle=showFps]');
  await page.click('[data-set=units][data-val=mph]');
  await page.$eval('[data-range=musicVolume]', (el) => { el.value = '0.2'; el.dispatchEvent(new Event('input')); el.dispatchEvent(new Event('change')); });
  await page.screenshot({ path: join(outDir, '03-settings.png') });
  const saved = await G(page, () => JSON.parse(localStorage.getItem('neonrush.settings.v1')));
  assert(saved.quality === 'low' && saved.showFps === true && saved.units === 'mph' && saved.musicVolume === 0.2, JSON.stringify(saved));
  await page.click('[data-set=quality][data-val=medium]');
  await page.click('[data-set=units][data-val=kmh]');
  await page.click('[data-act=back]');
  await frames(page);
  return { quality: 'low->medium', showFps: saved.showFps };
});

await step('locked tracks show requirements and cannot be selected', async () => {
  await page.click('[data-act=race]');
  await frames(page);
  await page.click('[data-track=harbor]');
  await frames(page);
  const st = await G(page, () => ({ track: window.__neonRush.ui.event.trackId, modal: !!document.querySelector('#screen-event .modal') }));
  assert(st.track === 'downtown' && st.modal, JSON.stringify(st));
  await page.keyboard.press('Enter'); // close modal
  await page.screenshot({ path: join(outDir, '04-event.png') });
});

await step('garage from event flow starts a street race with 6 cars', async () => {
  await page.click('[data-act=next]');
  await frames(page);
  await page.screenshot({ path: join(outDir, '05-garage.png') });
  await page.click('[data-act=start]');
  await frames(page, 4);
  const s = await G(page, () => {
    const g = window.__neonRush.game;
    return { state: g.state, cars: g.session.cars.length, race: g.session.race.state, hud: document.getElementById('hud').classList.contains('active') };
  });
  assert(s.state === 'race' && s.cars === 6 && s.race === 'countdown' && s.hud, JSON.stringify(s));
  await page.screenshot({ path: join(outDir, '06-countdown.png') });
  return s;
});

await step('cars are held during the countdown, then GO', async () => {
  // The real-time loop keeps running between steps; rewind the countdown so the
  // check doesn't depend on how fast the software renderer is.
  const before = await G(page, () => { const g = window.__neonRush.game; g.session.race.countdown = 3; const c = g.session.player; return [c.x, c.z]; });
  await page.keyboard.down('KeyW');
  await G(page, () => window.__neonRush.game.fastForward(2));
  const mid = await G(page, () => { const g = window.__neonRush.game; return { p: [g.session.player.x, g.session.player.z], st: g.session.race.state }; });
  assert(mid.st === 'countdown' && Math.hypot(mid.p[0] - before[0], mid.p[1] - before[1]) < 0.01, 'moved during countdown');
  await G(page, () => window.__neonRush.game.fastForward(1.3));
  const st = await G(page, () => window.__neonRush.game.session.race.state);
  assert(st === 'running', 'race not running: ' + st);
});

await step('keyboard driving: throttle accelerates the player car', async () => {
  await G(page, () => window.__neonRush.game.fastForward(3));
  const v = await G(page, () => window.__neonRush.game.session.player.speed);
  assert(v > 15, 'speed ' + v);
  await frames(page, 2);
  await page.screenshot({ path: join(outDir, '07-driving.png') });
  return { speedKmh: Math.round(v * 3.6) };
});

await step('nitro (Shift) boosts and drains the tank', async () => {
  const n0 = await G(page, () => { const c = window.__neonRush.game.session.player; c.nitro = c.p.nitroCap; return c.nitro; });
  await page.keyboard.down('ShiftLeft');
  const r = await G(page, () => {
    const g = window.__neonRush.game;
    let active = false;
    for (let i = 0; i < 60; i++) { g.fastForward(1 / 60); active ||= g.session.player.nitroActive; }
    return { active, nitro: g.session.player.nitro };
  });
  await frames(page, 2);
  await page.screenshot({ path: join(outDir, '08-nitro.png') });
  await page.keyboard.up('ShiftLeft');
  assert(r.active && r.nitro < n0 - 15, JSON.stringify(r));
  return r;
});

await step('drift (Space + steer) starts a slide', async () => {
  await G(page, () => { const g = window.__neonRush.game; g.debug.autopilot = true; g.fastForward(2); g.debug.autopilot = false; });
  await page.keyboard.down('KeyD');
  await page.keyboard.down('Space');
  const r = await G(page, () => {
    const g = window.__neonRush.game;
    let drift = false, maxSlip = 0;
    for (let i = 0; i < 40; i++) { g.fastForward(1 / 60); drift ||= g.session.player.drifting; maxSlip = Math.max(maxSlip, Math.abs(g.session.player.slip)); }
    return { drift, maxSlip: +maxSlip.toFixed(2) };
  });
  await frames(page, 2);
  await page.screenshot({ path: join(outDir, '09-drift.png') });
  await page.keyboard.up('Space');
  await page.keyboard.up('KeyD');
  await page.keyboard.up('KeyW');
  assert(r.drift, JSON.stringify(r));
  return r;
});

await step('R resets the car onto the track', async () => {
  await page.keyboard.press('KeyR');
  await frames(page, 2);
  const r = await G(page, () => { const g = window.__neonRush.game; const pr = g.session.playerRacer; const loc = g.world.path.locate(g.session.player.x, g.session.player.z); return { resets: pr.resets, lateral: loc.lateral, half: g.world.path.halfWidth }; });
  assert(r.resets >= 1 && Math.abs(r.lateral) < r.half, JSON.stringify(r));
});

await step('Esc pauses the race (simulation frozen) and Esc resumes', async () => {
  await page.keyboard.press('Escape');
  await frames(page, 3);
  const p = await G(page, () => ({ paused: window.__neonRush.game.paused, screen: window.__neonRush.ui.current, t: window.__neonRush.game.session.race.time }));
  assert(p.paused && p.screen === 'pause', JSON.stringify(p));
  await page.screenshot({ path: join(outDir, '10-pause.png') });
  await frames(page, 5);
  const t2 = await G(page, () => window.__neonRush.game.session.race.time);
  assert(t2 === p.t, 'time advanced while paused');
  await page.keyboard.press('Escape');
  await frames(page, 3);
  const q = await G(page, () => ({ paused: window.__neonRush.game.paused, screen: window.__neonRush.ui.current }));
  assert(!q.paused && q.screen === null, JSON.stringify(q));
});

let creditsBefore;
await step('street race can be completed: results, positions, rewards', async () => {
  creditsBefore = await G(page, () => window.__neonRush.game.save.credits);
  await finishRace(page);
  await frames(page, 3);
  await page.screenshot({ path: join(outDir, '11-results.png') });
  const r = await G(page, () => ({ rows: document.querySelectorAll('table.res tr').length - 1, credits: window.__neonRush.game.save.credits, pos: window.__neonRush.ui.lastResults.position, laps: window.__neonRush.ui.lastResults.player.lapTimes.length }));
  assert(r.rows === 6, 'rows ' + r.rows);
  assert(r.laps === 3, 'laps ' + r.laps);
  assert(r.credits > creditsBefore, 'no credits earned');
  return { position: r.pos, earned: r.credits - creditsBefore };
});

await step('"Race again" restarts the same event cleanly', async () => {
  await page.click('[data-act=again]');
  await frames(page, 3);
  const s = await G(page, () => { const g = window.__neonRush.game; return { state: g.session.race.state, time: g.session.race.time, ui: window.__neonRush.ui.current, cars: g.session.cars.length }; });
  assert(s.state === 'countdown' && s.time === 0 && s.ui === null && s.cars === 6, JSON.stringify(s));
});

await step('quit to menu from the pause menu (with confirm)', async () => {
  await page.keyboard.press('Escape');
  await frames(page, 3);
  await page.click('[data-act=quit]');
  await page.click('.modal [data-yes]');
  await frames(page, 3);
  const s = await G(page, () => ({ ui: window.__neonRush.ui.current, session: !!window.__neonRush.game.session, state: window.__neonRush.game.state }));
  assert(s.ui === 'title' && !s.session && s.state === 'menu', JSON.stringify(s));
});

await step('time trial: solo, best lap + ghost saved, ghost appears next time', async () => {
  await G(page, () => { const { ui } = window.__neonRush; ui.event.mode = 'timetrial'; ui.event.trackId = 'downtown'; ui.startRace(); });
  await frames(page, 2);
  const cars = await G(page, () => window.__neonRush.game.session.cars.length);
  assert(cars === 1, 'cars ' + cars);
  await finishRace(page);
  const saved = await G(page, () => { const s = JSON.parse(localStorage.getItem('neonrush.save.v1')); return { ghost: !!s.ghosts.downtown, frames: s.ghosts.downtown?.frames.length, best: s.best['downtown:timetrial'] }; });
  assert(saved.ghost && saved.frames > 300 && saved.best.lap > 0, JSON.stringify(saved));
  await page.click('[data-act=again]');
  await frames(page, 2);
  await G(page, () => window.__neonRush.game.fastForward(10));
  await frames(page, 2);
  await page.screenshot({ path: join(outDir, '12-timetrial-ghost.png') });
  const g = await G(page, () => !!window.__neonRush.game.session.ghost);
  assert(g, 'ghost not loaded');
  return { bestLap: +saved.best.lap.toFixed(2), ghostFrames: saved.frames };
});

await step('drift attack: 2 laps, drift score + results', async () => {
  await G(page, () => { const { ui, game } = window.__neonRush; game.quitToMenu(); ui.event.mode = 'drift'; ui.event.trackId = 'downtown'; ui.startRace(); });
  await frames(page, 2);
  const laps = await G(page, () => window.__neonRush.game.session.race.laps);
  assert(laps === 2, 'laps ' + laps);
  // Score some drifting with keyboard input, then let the autopilot finish.
  await G(page, () => window.__neonRush.game.fastForward(3.2));
  await page.keyboard.down('KeyW');
  await G(page, () => window.__neonRush.game.fastForward(4));
  await page.keyboard.down('KeyA');
  await page.keyboard.down('Space');
  await G(page, () => window.__neonRush.game.fastForward(0.3));
  await page.keyboard.up('Space');
  await G(page, () => window.__neonRush.game.fastForward(1.2));
  await page.keyboard.up('KeyA');
  await G(page, () => window.__neonRush.game.fastForward(1.5));
  await page.keyboard.up('KeyW');
  await finishRace(page);
  await page.screenshot({ path: join(outDir, '13-drift-results.png') });
  const r = await G(page, () => ({ mode: window.__neonRush.ui.lastResults.mode, drift: window.__neonRush.ui.lastResults.player.drift }));
  assert(r.mode === 'drift', JSON.stringify(r));
  // Esc on the results screen returns to the main menu.
  await page.keyboard.press('Escape');
  await frames(page, 2);
  const after = await G(page, () => ({ screen: window.__neonRush.ui.current, session: !!window.__neonRush.game.session }));
  assert(after.screen === 'title' && !after.session, 'Esc on results: ' + JSON.stringify(after));
  return r;
});

await step('progression: podium unlocks Harbor Highway', async () => {
  await G(page, () => { const g = window.__neonRush.game; g.save.best['downtown:race'] = { position: 2 }; g.persist(); g.quitToMenu(); window.__neonRush.ui.show('event'); });
  await frames(page, 2);
  const locked = await G(page, () => !!document.querySelector('[data-track=harbor][data-locked]'));
  assert(!locked, 'harbor still locked');
  await page.click('[data-track=harbor]');
  await frames(page, 3);
  const t = await G(page, () => ({ id: window.__neonRush.ui.event.trackId, world: window.__neonRush.game.world.def.id }));
  assert(t.id === 'harbor' && t.world === 'harbor', JSON.stringify(t));
  await page.screenshot({ path: join(outDir, '14-harbor-menu.png') });
});

await step('garage: buy a car, paint it, buy an upgrade (credits spent, saved)', async () => {
  await G(page, () => { const g = window.__neonRush.game; g.save.credits = 12000; g.persist(); const ui = window.__neonRush.ui; ui.garageMode = 'browse'; ui.garageIndex = 2; ui.show('garage'); });
  await frames(page, 2);
  await page.click('[data-act=buy]');
  await page.click('.modal [data-yes]');
  await frames(page, 2);
  await page.click('[data-paint="#2ee59d"]');
  await page.click('[data-tab=upgrades]');
  await page.click('[data-upg=engine]');
  await frames(page, 2);
  await page.screenshot({ path: join(outDir, '15-garage-upgrade.png') });
  const s = await G(page, () => JSON.parse(localStorage.getItem('neonrush.save.v1')));
  assert(s.owned.includes('bulwark'), 'not owned');
  assert(s.cars.bulwark.paint === '#2ee59d', 'paint');
  assert(s.cars.bulwark.upgrades.engine === 1, 'upgrade');
  assert(s.credits === 12000 - 8000 - 1500, 'credits ' + s.credits);
  return { credits: s.credits };
});

await step('insufficient credits are refused with a message', async () => {
  await G(page, () => { const ui = window.__neonRush.ui; ui.garageIndex = 3; ui.render('garage'); });
  const disabled = await G(page, () => document.querySelector('[data-act=buy]').disabled);
  assert(disabled, 'buy button should be disabled');
});

await step('no runtime errors during the whole session', async () => {
  assert(errors.length === 0, errors.join('\n'));
});
await browser.close();

// Quality presets: each must render races on both themes without errors.
for (const quality of ['low', 'medium', 'high']) {
  await step(`quality preset "${quality}" renders both tracks`, async () => {
    const { browser, page, errors } = await openGame({ quality, width: 1280, height: 720 });
    const out = {};
    for (const trackId of ['downtown', 'harbor']) {
      await G(page, (t) => window.__neonRush.game.startEvent({ mode: 'race', trackId: t, carId: 'vapor' }), trackId);
      await G(page, () => { const g = window.__neonRush.game; g.debug.autopilot = true; g.fastForward(8); });
      await frames(page, 4);
      const d = await G(page, () => window.__neonRush.game.getDebugInfo());
      out[trackId] = { drawCalls: d.drawCalls, triangles: d.triangles, geometries: d.geometries, textures: d.textures };
      await page.screenshot({ path: join(outDir, `16-${quality}-${trackId}.png`) });
    }
    await browser.close();
    assert(errors.length === 0, errors.join('\n'));
    return out;
  });
}

// HUD/menus at 1080p.
await step('1080p layout renders HUD and menus', async () => {
  const { browser, page, errors } = await openGame({ width: 1920, height: 1080 });
  await page.screenshot({ path: join(outDir, '17-title-1080p.png') });
  await G(page, () => window.__neonRush.game.startEvent({ mode: 'race', trackId: 'downtown', carId: 'vapor' }));
  await G(page, () => { const g = window.__neonRush.game; g.debug.autopilot = true; g.fastForward(12); });
  await frames(page, 4);
  await page.screenshot({ path: join(outDir, '18-race-1080p.png') });
  await browser.close();
  assert(errors.length === 0, errors.join('\n'));
});

console.log(`\n${results.length - failed}/${results.length} e2e checks passed`);
import('node:fs').then((fs) => fs.writeFileSync(join(outDir, 'results.json'), JSON.stringify(results, null, 2)));
process.exitCode = failed ? 1 : 0;
