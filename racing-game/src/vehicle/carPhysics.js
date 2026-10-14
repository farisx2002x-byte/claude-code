// Arcade vehicle model.
//
// The car is simulated on the ground plane (x, z) with a heading (yaw) and a
// world-space velocity. Each fixed step:
//   1. steering sets a target yaw rate (speed sensitive, stronger while drifting)
//   2. the velocity is split into forward / lateral parts relative to the heading
//   3. lateral velocity is damped by "grip" (high = on rails, low = sliding)
//   4. engine / brakes / nitro / drag act on the forward part
//   5. walls of the track push the car back and redirect it along the barrier
// No rigid-body solver means no flips, no getting wedged in geometry, and fully
// predictable handling — the priorities for an arcade racer.
//
// Coordinate conventions: forward = (sin yaw, cos yaw), right = (-cos yaw, sin yaw).
// steer = +1 means "turn right" (yaw decreases).

import { clamp, damp, sign, approach } from '../core/util.js';

export const CAR_HALF_WIDTH = 1.0;
export const CAR_COLLIDER_R = 1.05; // two circles per car, at +/- COLLIDER_OFFSET
export const CAR_COLLIDER_OFFSET = 1.2;

const GEAR_SPLITS = [0, 0.16, 0.31, 0.47, 0.63, 0.8, 1.01];

export function createCarState(params) {
  return {
    p: params,
    x: 0, z: 0, yaw: 0,
    vx: 0, vz: 0,
    yawRate: 0,
    prevX: 0, prevZ: 0, prevYaw: 0,
    speed: 0, // signed forward speed (m/s)
    slip: 0, // slip angle (rad), + = sliding to the right
    input: { throttle: 0, brake: 0, steer: 0, handbrake: false, nitro: false },
    steer: 0, // smoothed steering actually applied
    nitro: params.nitroCap * 0.35,
    nitroActive: false,
    nitroLock: false,
    drifting: false,
    driftDir: 0,
    driftFactor: 0,
    driftCombo: 0,
    driftTime: 0,
    wallHit: 0, // impact strength of last wall hit this step (m/s)
    wallContact: false,
    carHit: 0,
    ghostTimer: 0, // > 0: ignores car-car collisions (after a reset)
    gear: 1,
    rpm: 0.2,
    wheelSpin: 0,
    roll: 0,
    pitch: 0,
    // track tracking
    trackIndex: -1,
    lateral: 0,
    events: [], // consumed by game each frame: {type, value}
  };
}

export function placeCar(car, x, z, yaw) {
  car.x = car.prevX = x;
  car.z = car.prevZ = z;
  car.yaw = car.prevYaw = yaw;
  car.vx = car.vz = 0;
  car.yawRate = 0;
  car.speed = 0;
  car.slip = 0;
  car.steer = 0;
  car.drifting = false;
  car.driftFactor = 0;
  car.driftCombo = 0;
  car.nitroActive = false;
  car.trackIndex = -1;
}

export function driftTurnRateAt(p, speed) {
  const v = Math.abs(speed);
  return p.maxTurn * clamp(v / 5, 0, 1) / (1 + v / 55);
}

// Speed-sensitive maximum yaw rate. Also used by the AI to plan corner speeds.
export function turnRateAt(p, speed) {
  const v = Math.abs(speed);
  const low = clamp(v / 5, 0, 1);
  const high = 1 / (1 + v / 34);
  return p.maxTurn * low * high;
}

/**
 * Advance one car by dt. `track` is a TrackPath (used for barriers).
 */
export function stepCar(car, dt, track) {
  const p = car.p;
  const inp = car.input;
  car.prevX = car.x;
  car.prevZ = car.z;
  car.prevYaw = car.yaw;
  car.wallHit = 0;
  if (car.ghostTimer > 0) car.ghostTimer -= dt;

  let fx = Math.sin(car.yaw), fz = Math.cos(car.yaw);
  let rx = -fz, rz = fx;
  let vF = car.vx * fx + car.vz * fz;
  const absV = Math.hypot(car.vx, car.vz);

  // --- Steering -------------------------------------------------------------
  // Steering wheel slew: quick to turn in, quicker to return to center.
  const steerTarget = clamp(inp.steer, -1, 1);
  const returning = Math.abs(steerTarget) < Math.abs(car.steer) || sign(steerTarget) !== sign(car.steer);
  const slew = (returning ? 9 : 6) * (1 - 0.35 * clamp(absV / p.topSpeed, 0, 1));
  car.steer = approach(car.steer, steerTarget, slew * dt);

  // --- Drift state machine ------------------------------------------------------
  const slipAbs = Math.abs(car.slip);
  if (!car.drifting) {
    if (inp.handbrake && Math.abs(car.steer) > 0.25 && vF > 13) {
      car.drifting = true;
      car.driftDir = sign(car.steer);
      car.driftCombo = 0;
      car.driftTime = 0;
      // Kick the tail out so the drift starts immediately and predictably.
      car.yawRate += -sign(car.steer) * 0.9;
      car.events.push({ type: 'driftStart' });
    }
  } else {
    const holding = inp.handbrake || Math.abs(car.steer) > 0.2;
    const settled = car.driftTime > 0.35; // grace period while the slide builds up
    if ((settled && ((!holding && slipAbs < 0.2) || slipAbs < 0.06)) || absV < 9 || vF < 0) {
      endDrift(car, true);
    }
  }
  // Classic arcade drift: tap the handbrake to break traction, then the slide is
  // held for as long as you keep steering into the corner. Straightening or
  // counter-steering restores grip progressively.
  let driftTarget = 0;
  if (car.drifting) {
    const into = sign(car.steer) === car.driftDir && Math.abs(car.steer) > 0.3;
    driftTarget = inp.handbrake ? 1 : into ? 0.88 : 0.3;
  }
  car.driftFactor = damp(car.driftFactor, driftTarget, car.drifting ? 9 : 4.5, dt);

  // --- Yaw ------------------------------------------------------------------------
  const dirSign = vF >= -0.5 ? 1 : -1; // steering inverts when reversing
  // While drifting the car rotates much more freely (less high-speed steering
  // damping), which is what lets a slide take a corner tighter than grip would.
  const gripTurn = turnRateAt(p, vF);
  const driftTurn = driftTurnRateAt(p, vF) * p.driftSteer;
  let targetYaw = -car.steer * (gripTurn + (driftTurn - gripTurn) * car.driftFactor) * dirSign;
  const yawResp = 11 - 5 * car.driftFactor;
  car.yawRate = damp(car.yawRate, targetYaw, yawResp, dt);
  // Anti-spin assist: past ~48 degrees of slip, rotate the nose back towards travel.
  if (slipAbs > 0.84 && absV > 5) {
    car.yawRate -= sign(car.slip) * (slipAbs - 0.84) * 55 * dt;
  }
  car.yaw += car.yawRate * dt;

  fx = Math.sin(car.yaw);
  fz = Math.cos(car.yaw);
  rx = -fz;
  rz = fx;
  vF = car.vx * fx + car.vz * fz;
  let vR = car.vx * rx + car.vz * rz;

  // --- Lateral grip --------------------------------------------------------------
  const grip = p.grip + (p.driftGrip - p.grip) * car.driftFactor;
  const newVR = vR * Math.exp(-grip * dt);
  const lost = Math.abs(vR) - Math.abs(newVR);
  vR = newVR;
  // While drifting, part of the scrubbed sideways speed is pushed forward so a good
  // drift keeps its momentum instead of bleeding speed.
  if (vF > 0) vF += lost * 0.35 * car.driftFactor;
  // ...but a big slide still scrubs speed, so drifting is a cornering tool, not a free boost.
  vF = approach(vF, 0, Math.abs(Math.atan2(vR, Math.max(Math.abs(vF), 1))) * 7 * car.driftFactor * dt);

  // --- Nitro ----------------------------------------------------------------------
  // Once the tank runs dry the button must be released before nitro fires again
  // (prevents a stuttering on/off boost on the passive trickle charge).
  if (!inp.nitro) car.nitroLock = false;
  const wantsNitro = inp.nitro && !car.nitroLock && vF > 2 && (car.nitroActive ? car.nitro > 0 : car.nitro > p.nitroCap * 0.05);
  if (wantsNitro && !car.nitroActive) car.events.push({ type: 'nitroStart' });
  car.nitroActive = wantsNitro;
  if (car.nitroActive) {
    car.nitro = Math.max(0, car.nitro - 30 * dt);
    if (car.nitro <= 0) car.nitroLock = true;
  }

  // --- Longitudinal --------------------------------------------------------------
  const top = p.topSpeed * (car.nitroActive ? p.nitroTop : 1);
  if (inp.throttle > 0 && vF > -0.5) {
    const ratio = clamp(vF / top, 0, 1.2);
    const curve = Math.max(0, 1 - Math.pow(ratio, 1.7));
    let a = p.accel * curve * inp.throttle * (1 - 0.45 * car.driftFactor); // wheelspin while sliding
    if (car.nitroActive) a += p.nitroAccel * Math.max(0, 1 - ratio * 0.85);
    vF += a * dt;
  } else if (car.nitroActive) {
    vF += p.nitroAccel * 0.7 * dt;
  }
  if (inp.brake > 0) {
    if (vF > 0.8) vF = Math.max(0, vF - p.brake * inp.brake * dt);
    else if (inp.throttle <= 0) vF = Math.max(-13, vF - 9 * inp.brake * dt); // reverse
  }
  if (inp.throttle > 0 && vF < -0.5) vF = Math.min(0, vF + p.brake * dt); // brake out of reverse
  if (inp.handbrake) vF = approach(vF, 0, (car.drifting ? 1.6 : 9) * dt);
  // Rolling resistance + aero drag + engine braking when off the throttle.
  // (On throttle these losses are already part of the engine's power curve,
  // so every car really reaches its rated top speed.)
  if (!(inp.throttle > 0)) vF = approach(vF, 0, (0.9 + 0.00055 * vF * vF + 2.4) * dt);
  // Bleed off speed above the current top speed (e.g. when nitro ends).
  if (vF > top) vF = approach(vF, top, 6 * dt);

  // --- Integrate ----------------------------------------------------------------
  car.vx = fx * vF + rx * vR;
  car.vz = fz * vF + rz * vR;
  car.x += car.vx * dt;
  car.z += car.vz * dt;

  // --- Track barriers --------------------------------------------------------
  car.wallContact = false;
  if (track) collideWalls(car, track, dt);

  // --- Derived values ---------------------------------------------------------------
  fx = Math.sin(car.yaw);
  fz = Math.cos(car.yaw);
  vF = car.vx * fx + car.vz * fz;
  vR = car.vx * -fz + car.vz * fx;
  const prevSpeed = car.speed;
  car.speed = vF;
  car.slip = Math.hypot(car.vx, car.vz) > 3 ? Math.atan2(vR, Math.max(Math.abs(vF), 0.1)) : 0;

  // Nitro charging: drifting is the main source, plus a slow trickle.
  let charge = 1.2;
  if (car.drifting && Math.abs(car.slip) > 0.18 && vF > 12) charge += p.nitroCharge * clamp(Math.abs(car.slip) / 0.5, 0.4, 1.2);
  if (!car.nitroActive) car.nitro = Math.min(p.nitroCap, car.nitro + charge * dt);

  // Drift scoring.
  if (car.drifting) {
    car.driftTime += dt;
    if (Math.abs(car.slip) > 0.15 && vF > 10) car.driftCombo += Math.abs(car.slip) * vF * dt * 12;
  }

  // Gearbox (for audio + HUD).
  const frac = clamp(Math.abs(vF) / p.topSpeed, 0, 1);
  let g = 1;
  while (g < GEAR_SPLITS.length - 1 && frac > GEAR_SPLITS[g]) g++;
  if (g !== car.gear) car.events.push({ type: 'gear', value: g });
  car.gear = g;
  const lo = GEAR_SPLITS[g - 1], hi = GEAR_SPLITS[g];
  const inGear = clamp((frac - lo) / (hi - lo), 0, 1);
  const rpmTarget = inp.throttle > 0 && vF < 2 ? 0.55 + 0.1 * Math.random() : 0.25 + 0.72 * inGear;
  car.rpm = damp(car.rpm, car.drifting ? Math.max(rpmTarget, 0.75) : rpmTarget, 12, dt);

  // Visual-only body motion.
  const longAcc = (vF - prevSpeed) / dt;
  const latAcc = car.yawRate * vF;
  car.roll = damp(car.roll, clamp(latAcc * 0.006, -0.09, 0.09), 6, dt);
  car.pitch = damp(car.pitch, clamp(-longAcc * 0.0035, -0.05, 0.05), 6, dt);
  car.wheelSpin += (vF / (p.wheelR || 0.36)) * dt;
}

export function endDrift(car, bank) {
  if (!car.drifting) return;
  car.drifting = false;
  const pts = Math.round(car.driftCombo);
  if (bank && pts >= 50 && car.driftTime > 0.5) car.events.push({ type: 'driftEnd', value: pts });
  else if (!bank && pts > 0) car.events.push({ type: 'driftFail', value: pts });
  car.driftCombo = 0;
  car.driftTime = 0;
}

function alignToWall(car, track, i, amount) {
  let wallYaw = Math.atan2(track.tx[i], track.tz[i]);
  if (Math.cos(car.yaw - wallYaw) < 0) wallYaw += Math.PI;
  let d = wallYaw - car.yaw;
  d = Math.atan2(Math.sin(d), Math.cos(d));
  car.yaw += d * amount;
  car.yawRate *= 1 - amount * 0.8;
  // Re-project velocity so it keeps flowing along the wall in the nose direction.
  const sp = Math.hypot(car.vx, car.vz);
  const fx = Math.sin(car.yaw), fz = Math.cos(car.yaw);
  const along = car.vx * fx + car.vz * fz;
  if (along > 0) {
    const k = amount * 0.5;
    car.vx += (fx * sp - car.vx) * k;
    car.vz += (fz * sp - car.vz) * k;
  }
}

function collideWalls(car, track, dt) {
  const loc = track.locate(car.x, car.z, car.trackIndex, car.trackIndex < 0 ? 0 : 12, car._loc || (car._loc = {}));
  car.trackIndex = loc.index;
  car.lateral = loc.lateral;
  const limit = track.halfWidth - CAR_HALF_WIDTH;
  const over = Math.abs(loc.lateral) - limit;
  if (over <= 0) return;
  const i = loc.index;
  const side = sign(loc.lateral);
  const nx = track.rx[i] * side; // outward normal
  const nz = track.rz[i] * side;
  car.x -= nx * over;
  car.z -= nz * over;
  car.lateral = side * limit;
  const vn = car.vx * nx + car.vz * nz;
  car.wallContact = true;
  if (vn > 0) {
    // Remove the into-wall velocity with a little bounce, and scrub some speed
    // proportional to how hard the hit was (glancing hits barely slow you down).
    car.vx -= nx * vn * 1.2;
    car.vz -= nz * vn * 1.2;
    const tx = car.vx * -nz + car.vz * nx; // along-wall component
    const loss = clamp(vn * 0.02, 0, 0.25);
    const keep = 1 - loss;
    car.vx *= keep;
    car.vz *= keep;
    car.wallHit = vn;
    if (vn > 2.5) car.events.push({ type: 'wall', value: vn });
    // Swing the nose to run along the barrier (whichever direction is closer to the
    // current heading) so the player is never left pointing into the wall.
    alignToWall(car, track, i, clamp(vn * 0.05, 0.25, 0.85));
    void tx;
    if (car.drifting && vn > 1.5) endDrift(car, false);
  }
  // While scraping, keep turning the nose to follow the barrier so the car slides
  // along it instead of losing all its speed to tyre scrub.
  if (Math.hypot(car.vx, car.vz) > 3) alignToWall(car, track, i, Math.min(1, 6 * dt));
  // Grinding along the wall costs a little speed.
  const f = 1 - 0.3 * dt;
  car.vx *= f;
  car.vz *= f;
}

/**
 * Car-vs-car collisions. Each car is two circles (front/back). Simple impulse
 * exchange weighted by mass; positions are separated so cars never interpenetrate.
 */
export function collideCars(cars) {
  const n = cars.length;
  for (let a = 0; a < n; a++) {
    const A = cars[a];
    if (A.ghostTimer > 0) continue;
    for (let b = a + 1; b < n; b++) {
      const B = cars[b];
      if (B.ghostTimer > 0) continue;
      const dx0 = B.x - A.x, dz0 = B.z - A.z;
      if (dx0 * dx0 + dz0 * dz0 > 36) continue;
      const afx = Math.sin(A.yaw), afz = Math.cos(A.yaw);
      const bfx = Math.sin(B.yaw), bfz = Math.cos(B.yaw);
      for (let i = -1; i <= 1; i += 2) {
        for (let j = -1; j <= 1; j += 2) {
          const ax = A.x + afx * CAR_COLLIDER_OFFSET * i, az = A.z + afz * CAR_COLLIDER_OFFSET * i;
          const bx = B.x + bfx * CAR_COLLIDER_OFFSET * j, bz = B.z + bfz * CAR_COLLIDER_OFFSET * j;
          let dx = bx - ax, dz = bz - az;
          const d2 = dx * dx + dz * dz;
          const minD = CAR_COLLIDER_R * 2;
          if (d2 >= minD * minD || d2 < 1e-6) continue;
          const d = Math.sqrt(d2);
          dx /= d;
          dz /= d;
          const pen = minD - d;
          const ma = A.p.mass, mb = B.p.mass;
          const wa = mb / (ma + mb), wb = ma / (ma + mb);
          A.x -= dx * pen * wa;
          A.z -= dz * pen * wa;
          B.x += dx * pen * wb;
          B.z += dz * pen * wb;
          const rv = (B.vx - A.vx) * dx + (B.vz - A.vz) * dz;
          if (rv < 0) {
            const jImp = (-(1 + 0.25) * rv) / (1 / ma + 1 / mb);
            A.vx -= (jImp / ma) * dx;
            A.vz -= (jImp / ma) * dz;
            B.vx += (jImp / mb) * dx;
            B.vz += (jImp / mb) * dz;
            const s = -rv;
            A.carHit = Math.max(A.carHit, s);
            B.carHit = Math.max(B.carHit, s);
            if (s > 3) {
              A.events.push({ type: 'car', value: s });
              B.events.push({ type: 'car', value: s });
              if (A.drifting && s > 5) endDrift(A, false);
              if (B.drifting && s > 5) endDrift(B, false);
            }
          }
        }
      }
    }
  }
}
