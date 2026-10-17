import { test } from 'node:test';
import assert from 'node:assert/strict';
import { simulate } from '../../scripts/sim-race.mjs';
import { TRACKS } from '../../src/data/tracks.js';
import { DT, makeTrack, makeCar } from './helpers.js';
import { RaceManager, computeRewards, CHECKPOINTS } from '../../src/race/raceManager.js';
import { stepCar } from '../../src/vehicle/carPhysics.js';

for (const t of TRACKS) {
  test(`full 6-car AI race completes on ${t.id}`, () => {
    const { race, resets } = simulate(t.id, { difficulty: 'normal' });
    const res = race.results();
    assert.equal(res.length, 6);
    for (const r of race.racers) {
      assert.ok(r.finished, `${r.name} did not finish`);
      assert.equal(r.lapTimes.length, race.laps);
      assert.ok(r.bestLap > 20 && r.bestLap < 90, `${r.name} best lap ${r.bestLap}`);
    }
    // finishing order is consistent with times
    for (let i = 1; i < res.length; i++) assert.ok(res[i].time >= res[i - 1].time);
    assert.ok(resets <= 2, `too many AI resets: ${resets}`);
  });
}

test('difficulty changes rival pace (easy slower than hard)', () => {
  const easy = simulate('downtown', { difficulty: 'easy', cars: 3 }).race;
  const hard = simulate('downtown', { difficulty: 'hard', cars: 3 }).race;
  const avg = (r) => r.racers.reduce((a, x) => a + x.finishTime, 0) / r.racers.length;
  assert.ok(avg(easy) > avg(hard) * 1.03, `${avg(easy)} vs ${avg(hard)}`);
});

test('checkpoints fire in order and a lap needs the full distance', () => {
  const tr = makeTrack('downtown');
  const race = new RaceManager(tr, { laps: 1, countdown: 0 });
  const car = makeCar();
  const r = race.addRacer(car, { isPlayer: true });
  race.setupGrid();
  const seen = [];
  // Teleport the car along the centerline in small steps (simulates perfect driving).
  let s = tr.wrapS(r.lastS);
  race.update(DT); // countdown -> running
  for (let k = 0; k < tr.length / 1.5 + 40; k++) {
    s = tr.wrapS(s + 1.5);
    const f = tr.frameAt(s);
    car.x = f.x; car.z = f.z; car.yaw = f.heading;
    car.vx = f.tx * 20; car.vz = f.tz * 20; car.speed = 20;
    car._loc = tr.locate(car.x, car.z, car.trackIndex);
    car.trackIndex = car._loc.index;
    race.update(DT);
    for (const e of race.events) if (e.type === 'checkpoint' || e.type === 'finish') seen.push(e.type === 'finish' ? 'F' : e.index);
  }
  assert.deepEqual(seen, [...Array.from({ length: CHECKPOINTS - 1 }, (_, i) => i + 1), 'F']);
  assert.ok(r.finished);
});

test('driving backwards triggers WRONG WAY and does not count progress', () => {
  const tr = makeTrack('downtown');
  const race = new RaceManager(tr, { laps: 3, countdown: 0 });
  const car = makeCar();
  const r = race.addRacer(car, { isPlayer: true });
  race.setupGrid();
  race.update(DT);
  car.yaw += Math.PI; // turn around
  const d0 = r.dist;
  let ww = false;
  for (let t = 0; t < 4; t += DT) {
    car.input.throttle = 1;
    stepCar(car, DT, tr);
    race.update(DT);
    if (r.wrongWay) ww = true;
  }
  assert.ok(ww, 'wrong way not detected');
  assert.ok(r.dist < d0, 'progress should go down when driving backwards');
});

test('reset puts the car back on the centerline facing the right way', () => {
  const tr = makeTrack('harbor');
  const race = new RaceManager(tr, { laps: 3, countdown: 0 });
  const car = makeCar();
  const r = race.addRacer(car, { isPlayer: true });
  race.setupGrid();
  race.update(DT);
  car.yaw += 2;
  car.vx = 5;
  race.resetRacer(r);
  const loc = tr.locate(car.x, car.z);
  assert.ok(Math.abs(loc.lateral) < tr.halfWidth * 0.5);
  const dot = Math.sin(car.yaw) * tr.tx[loc.index] + Math.cos(car.yaw) * tr.tz[loc.index];
  assert.ok(dot > 0.95);
  assert.equal(car.vx, 0);
  assert.ok(car.ghostTimer > 0);
});

test('rewards scale with result and are never negative', () => {
  const win = computeRewards({ mode: 'race', position: 1, racers: 6, driftScore: 5000, cleanRace: true, difficulty: 'normal' });
  const last = computeRewards({ mode: 'race', position: 6, racers: 6, driftScore: 0, cleanRace: false, difficulty: 'normal' });
  assert.ok(win.total > last.total);
  assert.ok(last.total > 0);
  const hard = computeRewards({ mode: 'race', position: 1, racers: 6, driftScore: 0, cleanRace: false, difficulty: 'hard' });
  const easy = computeRewards({ mode: 'race', position: 1, racers: 6, driftScore: 0, cleanRace: false, difficulty: 'easy' });
  assert.ok(hard.total > easy.total);
});

test('countdown announces 3, 2, 1 then GO', () => {
  const race = new RaceManager(makeTrack('downtown'), { laps: 1, countdown: 3 });
  race.addRacer(makeCar(), { isPlayer: true });
  race.setupGrid();
  const seen = [];
  for (let k = 0; k < 3.2 / DT; k++) {
    race.update(DT);
    for (const e of race.events) if (e.type === 'count' || e.type === 'go') seen.push(e.type === 'go' ? 'GO' : e.value);
  }
  assert.deepEqual(seen, [3, 2, 1, 'GO']);
});

test('racers finishing on the same step keep their crossing order', () => {
  const race = new RaceManager(makeTrack('downtown'), { laps: 1, countdown: 0 });
  const a = race.addRacer(makeCar(), { name: 'A' });
  const b = race.addRacer(makeCar(), { name: 'B', isPlayer: true });
  race.setupGrid();
  // Same finish time, B crossed first.
  for (const r of [b, a]) {
    r.finished = true;
    r.finishTime = 60;
    race.finishOrder.push(r);
  }
  race.updatePositions();
  assert.equal(b.position, 1);
  assert.equal(a.position, 2);
  assert.deepEqual(race.results().map((x) => x.racer.name), ['B', 'A']);
});
