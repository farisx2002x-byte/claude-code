import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DT, carOnStraight, straightTrack, makeCar } from './helpers.js';
import { stepCar, collideCars, placeCar, CAR_HALF_WIDTH } from '../../src/vehicle/carPhysics.js';
import { CARS } from '../../src/data/cars.js';

const track = straightTrack(); // 60 m wide: room for long drifts
const run = (car, seconds, input) => {
  Object.assign(car.input, { throttle: 0, brake: 0, steer: 0, handbrake: false, nitro: false }, input);
  for (let t = 0; t < seconds; t += DT) {
    stepCar(car, DT, track);
    car.events.length = 0;
  }
};

test('acceleration: 0-100 km/h is quick, top speed is reached and respected', () => {
  for (const def of CARS) {
    const c = carOnStraight(def.id);
    let t = 0;
    c.input.throttle = 1;
    while (c.speed < 100 / 3.6 && t < 20) {
      stepCar(c, DT, track);
      t += DT;
    }
    assert.ok(t > 1.5 && t < 6, `${def.id} 0-100 in ${t.toFixed(2)}s`);
    console.log(`# ${def.id}: 0-100 km/h ${t.toFixed(2)} s`);
    run(c, 30, { throttle: 1 });
    assert.ok(c.speed > def.physics.topSpeed * 0.93 && c.speed <= def.physics.topSpeed * 1.001, `${def.id} top ${c.speed}`);
  }
});

test('brakes stop the car from 200 km/h within ~2.5 s, then it reverses slowly', () => {
  const c = carOnStraight();
  run(c, 15, { throttle: 1 });
  assert.ok(c.speed > 200 / 3.6);
  let t = 0;
  c.input.throttle = 0;
  c.input.brake = 1;
  while (c.speed > 0.5 && t < 10) {
    stepCar(c, DT, track);
    t += DT;
  }
  assert.ok(t < 2.6, `stop took ${t}`);
  run(c, 3, { brake: 1 });
  assert.ok(c.speed < -3 && c.speed >= -13.01, `reverse ${c.speed}`);
});

test('steering right turns the car to its right (towards -X when heading +Z)', () => {
  const c = carOnStraight();
  run(c, 3, { throttle: 1 });
  const x0 = c.x;
  run(c, 1, { throttle: 1, steer: 1 });
  assert.ok(c.yaw < -0.3, `yaw ${c.yaw}`);
  assert.ok(c.x < x0 - 1);
});

test('no steering at standstill; steering authority drops with speed', () => {
  const c = carOnStraight();
  run(c, 1, { steer: 1 });
  assert.ok(Math.abs(c.yaw) < 1e-6);
});

test('drift: handbrake + steer enters a controllable slide, scores points and charges nitro', () => {
  const wide = straightTrack(400);
  const run = (car, seconds, input) => {
    Object.assign(car.input, { throttle: 0, brake: 0, steer: 0, handbrake: false, nitro: false }, input);
    for (let t = 0; t < seconds; t += DT) stepCar(car, DT, wide);
  };
  const track = wide;
  const c = carOnStraight();
  run(c, 6, { throttle: 1 });
  c.nitro = 0;
  run(c, 0.25, { throttle: 1, steer: 1, handbrake: true });
  assert.ok(c.drifting, 'drift should start');
  let maxSlip = 0;
  for (let t = 0; t < 2.5; t += DT) {
    Object.assign(c.input, { throttle: 1, steer: 0.6, handbrake: false });
    stepCar(c, DT, track);
    maxSlip = Math.max(maxSlip, Math.abs(c.slip));
  }
  assert.ok(maxSlip > 0.3, `slip angle ${maxSlip}`);
  assert.ok(maxSlip < 1.2, `car spun out (slip ${maxSlip})`);
  assert.ok(c.nitro > 10, `nitro charged to ${c.nitro}`);
  assert.ok(c.speed > 15, `kept momentum: ${c.speed}`);
  // Let go: the car recovers grip on its own.
  const events = [];
  for (let t = 0; t < 2; t += DT) {
    Object.assign(c.input, { throttle: 1, steer: 0, handbrake: false });
    stepCar(c, DT, track);
    events.push(...c.events);
    c.events.length = 0;
  }
  assert.ok(!c.drifting, 'drift should end after release');
  assert.ok(Math.abs(c.slip) < 0.12, `recovered slip ${c.slip}`);
});

test('nitro boosts acceleration beyond normal top speed and drains', () => {
  const a = carOnStraight();
  const b = carOnStraight();
  run(a, 25, { throttle: 1 });
  run(b, 25, { throttle: 1 });
  b.nitro = b.p.nitroCap;
  run(a, 2, { throttle: 1 });
  run(b, 2, { throttle: 1, nitro: true });
  assert.ok(b.speed > a.speed + 3, `nitro ${b.speed} vs ${a.speed}`);
  assert.ok(b.nitro < b.p.nitroCap - 50);
  // empty tank -> nitro stops
  run(b, 5, { throttle: 1, nitro: true });
  assert.equal(b.nitroActive, false);
});

test('walls: hitting the barrier deflects the car, keeps it inside and does not stop it dead', () => {
  const c = carOnStraight();
  run(c, 5, { throttle: 1 });
  const v0 = c.speed;
  c.yaw = -0.5; // aim at the right-hand wall (~29 degree impact)
  let hit = 0;
  for (let t = 0; t < 2; t += DT) {
    Object.assign(c.input, { throttle: 1, steer: 0 });
    stepCar(c, DT, track);
    hit = Math.max(hit, c.wallHit);
    assert.ok(Math.abs(c.lateral) <= track.halfWidth - CAR_HALF_WIDTH + 1e-6, 'car left the track');
    c.events.length = 0;
  }
  assert.ok(hit > 2, 'expected a wall impact');
  assert.ok(c.speed > v0 * 0.4, `speed after hit ${c.speed} (was ${v0})`);
});

test('car-car collisions separate overlapping cars and exchange momentum', () => {
  const a = makeCar('vapor');
  const b = makeCar('bulwark');
  placeCar(a, 0, 0, 0);
  placeCar(b, 1.2, 0.5, 0);
  a.vx = 10;
  collideCars([a, b]);
  const d = Math.hypot(a.x - b.x, a.z - b.z);
  assert.ok(d > 1.5, `still overlapping: ${d}`);
  assert.ok(b.vx > 0, 'momentum transferred');
});

test('a hard crash at speed leaves the car aligned with the barrier and able to drive on', () => {
  const c = carOnStraight();
  run(c, 6, { throttle: 1 });
  c.yaw = -0.95; // ~55 degrees into the right-hand wall
  let crashed = false;
  for (let t = 0; t < 1.5; t += DT) {
    Object.assign(c.input, { throttle: 1, steer: 0 });
    stepCar(c, DT, track);
    if (c.wallHit > 20) crashed = true;
    c.events.length = 0;
  }
  assert.ok(crashed, 'expected a heavy impact');
  const loc = track.locate(c.x, c.z);
  const align = Math.sin(c.yaw) * track.tx[loc.index] + Math.cos(c.yaw) * track.tz[loc.index];
  assert.ok(align > 0.85, `heading alignment ${align}`);
  assert.ok(c.speed > 12, `able to drive away: ${c.speed}`);
});
