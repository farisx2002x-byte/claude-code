// Can a human with only digital keyboard input (steer -1/0/+1, gas/brake on/off)
// drive these cars around the tracks? A "keyboard bot" quantises the AI's
// decisions to key presses and must complete clean laps at a competitive pace.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DT, makeTrack, makeCar } from './helpers.js';
import { AIDriver } from '../../src/ai/aiDriver.js';
import { RaceManager } from '../../src/race/raceManager.js';
import { stepCar } from '../../src/vehicle/carPhysics.js';

function lapWith(trackId, carId, digital) {
  const tr = makeTrack(trackId);
  const race = new RaceManager(tr, { laps: 2, countdown: 0 });
  const car = makeCar(carId);
  const r = race.addRacer(car, { isPlayer: true });
  race.setupGrid();
  const ai = new AIDriver(car, tr, { difficulty: 'hard', seed: 5 });
  let walls = 0;
  race.update(DT);
  while (!r.finished && race.time < 200) {
    ai.update(DT, [car], 0);
    if (digital) {
      const i = car.input;
      i.steer = Math.abs(i.steer) > 0.22 ? Math.sign(i.steer) : 0;
      i.throttle = i.throttle > 0.5 ? 1 : 0;
      i.brake = i.brake > 0.25 ? 1 : 0;
      i.nitro = false;
    }
    stepCar(car, DT, tr);
    if (car.wallHit > 3) walls++;
    car.events.length = 0;
    race.update(DT);
  }
  return { finished: r.finished, best: r.bestLap, walls };
}

for (const [trackId, carId] of [['downtown', 'vapor'], ['downtown', 'kite'], ['harbor', 'bulwark'], ['harbor', 'phantom']]) {
  test(`keyboard-only driving completes ${trackId} in the ${carId}`, () => {
    const analog = lapWith(trackId, carId, false);
    const keys = lapWith(trackId, carId, true);
    assert.ok(keys.finished, 'did not finish');
    assert.ok(keys.best < analog.best * 1.08, `keyboard lap ${keys.best.toFixed(2)} vs analog ${analog.best.toFixed(2)}`);
    assert.ok(keys.walls <= 4, `wall hits ${keys.walls}`);
    console.log(`# ${trackId}/${carId}: analog ${analog.best.toFixed(2)}s, keyboard ${keys.best.toFixed(2)}s, wall hits ${keys.walls}`);
  });
}
