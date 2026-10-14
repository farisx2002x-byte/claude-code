// Headless race simulation: every car (including the "player" slot) is driven by the AI.
// Used to tune physics/AI and as the basis of the automated race-completion test.
import { TrackPath } from '../src/world/trackPath.js';
import { TRACKS } from '../src/data/tracks.js';
import { CARS, tunedPhysics } from '../src/data/cars.js';
import { createCarState, stepCar, collideCars } from '../src/vehicle/carPhysics.js';
import { AIDriver } from '../src/ai/aiDriver.js';
import { RaceManager } from '../src/race/raceManager.js';

export function simulate(trackId, { difficulty = 'normal', cars = 6, maxTime = 400, laps } = {}) {
  const t = TRACKS.find((x) => x.id === trackId);
  const tr = new TrackPath(t.points, { width: t.width, reverse: t.reverse });
  const race = new RaceManager(tr, { laps: laps ?? t.laps });
  const ais = [];
  for (let i = 0; i < cars; i++) {
    const def = CARS[i % CARS.length];
    const p = tunedPhysics(def); p.wheelR = def.body.wheelR;
    const c = createCarState(p);
    race.addRacer(c, { name: def.name + i, isPlayer: i === cars - 1 });
    ais.push(new AIDriver(c, tr, { difficulty, seed: 100 + i }));
  }
  race.setupGrid();
  const dt = 1 / 120;
  const all = race.racers.map((r) => r.car);
  let walls = 0, resets = 0, maxV = 0;
  while (race.time < maxTime) {
    race.update(dt);
    if (race.racers.every((r) => r.finished)) break;
    if (race.state !== 'countdown') {
      for (const a of ais) a.update(dt, all, 0);
      for (const c of all) { c.events.length = 0; stepCar(c, dt, tr); if (c.wallHit > 2.5) walls++; maxV = Math.max(maxV, c.speed); }
      collideCars(all);
      for (const r of race.racers) if (!r.finished && r.stuckTimer > 3) { race.resetRacer(r); resets++; }
    } else for (const c of all) c.input.throttle = 0;
  }
  return { race, walls, resets, maxV, tr };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  for (const id of process.argv.slice(2).length ? process.argv.slice(2) : TRACKS.map((t) => t.id)) {
    for (const d of ['easy', 'normal', 'hard']) {
      const { race, walls, resets, maxV, tr } = simulate(id, { difficulty: d });
      const res = race.results();
      console.log(`${id} [${d}] len=${tr.length.toFixed(0)} time=${race.time.toFixed(1)}s walls=${walls} resets=${resets} vmax=${(maxV*3.6).toFixed(0)}km/h`);
      for (const x of res) console.log(`   ${x.racer.name.padEnd(12)} ${x.time.toFixed(2)}${x.estimated ? ' (DNF est)' : ''} best=${x.racer.bestLap.toFixed(2)} laps=${x.racer.lapTimes.map(v=>v.toFixed(1)).join(',')}`);
    }
  }
}
