// AI opponent driver. AI cars use exactly the same physics as the player — they
// only produce inputs (throttle / brake / steer / nitro). No speed cheats beyond
// a gentle, documented catch-up factor (max ±4%).
//
// Planning: a per-car "speed profile" is precomputed for the whole track from
// the curvature and that car's steering authority, then a backwards pass adds
// braking zones. At runtime the AI follows a look-ahead point offset towards the
// inside of upcoming corners, overtakes by switching lanes, and uses nitro on
// long straights.

import { clamp, lerp, wrapAngle, rng } from '../core/util.js';
import { turnRateAt } from '../vehicle/carPhysics.js';

export const DIFFICULTY = {
  easy: { pace: 0.84, noise: 0.08, nitroUse: 0.4 },
  normal: { pace: 0.93, noise: 0.04, nitroUse: 0.75 },
  hard: { pace: 0.995, noise: 0.015, nitroUse: 1.0 },
};

export function buildSpeedProfile(track, p, margin = 0.82, decel = 17) {
  const n = track.count;
  const prof = new Float64Array(n);
  const vMaxAbs = p.topSpeed;
  // Smooth curvature over ~ +/-6 m to avoid over-reacting to sample noise.
  for (let i = 0; i < n; i++) {
    let k = 0;
    for (let o = -3; o <= 3; o++) k = Math.max(k, Math.abs(track.curvature[track.idx(i + o)]));
    if (k < 1e-4) {
      prof[i] = vMaxAbs;
      continue;
    }
    let lo = 6, hi = vMaxAbs;
    for (let it = 0; it < 22; it++) {
      const mid = (lo + hi) / 2;
      if ((turnRateAt(p, mid) * margin) / mid >= k) lo = mid;
      else hi = mid;
    }
    prof[i] = lo;
  }
  // Backward pass for braking distances (two laps to handle wrap-around).
  const ds = track.spacing;
  for (let pass = 0; pass < 2; pass++) {
    for (let i = n - 1; i >= 0; i--) {
      const next = prof[(i + 1) % n];
      const lim = Math.sqrt(next * next + 2 * decel * ds);
      if (prof[i] > lim) prof[i] = lim;
    }
  }
  return prof;
}

export class AIDriver {
  constructor(car, track, opts = {}) {
    this.car = car;
    this.track = track;
    const diff = DIFFICULTY[opts.difficulty || 'normal'];
    this.rand = rng(opts.seed || 7);
    // Personality: each rival is slightly different.
    this.pace = diff.pace * (opts.paceScale ?? 1) * (0.975 + this.rand() * 0.035);
    this.noise = diff.noise;
    this.nitroUse = diff.nitroUse;
    this.aggression = 0.4 + this.rand() * 0.6;
    this.laneBias = (this.rand() - 0.5) * 0.5;
    this.profile = buildSpeedProfile(track, car.p);
    this.lane = this.laneBias;
    this.overtakeSide = 0;
    this.overtakeTimer = 0;
    this.noiseVal = 0;
    this.noiseTimer = 0;
    this.catchUp = 1;
    this._f = {};
    this.wasStraight = false;
    this.nitroPlan = false;
  }

  /** @param {Array} others other car states; @param {number} playerGap meters (AI - player) */
  update(dt, others, playerGap = 0) {
    const car = this.car;
    const tr = this.track;
    const inp = car.input;
    if (car.trackIndex < 0) tr.locate(car.x, car.z, -1, 0, car._loc || (car._loc = {}));
    const loc = car._loc || tr.locate(car.x, car.z);
    const s = loc.s;
    const v = car.speed;

    // --- Lane choice ----------------------------------------------------------
    const kAhead = this.signedCurvatureAhead(s + 10 + v * 0.6, 40);
    const usable = tr.halfWidth - 2.6;
    let desired = clamp(-kAhead * 220, -1, 1) * 0.75 + this.laneBias;

    // Traffic: look for cars ahead in our lane and pick a side to pass.
    this.overtakeTimer -= dt;
    let blockerSpeed = Infinity;
    for (const o of others) {
      if (o === car || !o._loc) continue;
      const ahead = tr.deltaS(s, o._loc.s);
      if (ahead < 0 || ahead > 18 + v * 0.4) continue;
      const latDiff = o._loc.lateral - loc.lateral;
      if (Math.abs(latDiff) < 3.2) {
        if (this.overtakeTimer <= 0) {
          const roomLeft = o._loc.lateral + tr.halfWidth;
          const roomRight = tr.halfWidth - o._loc.lateral;
          this.overtakeSide = roomRight > roomLeft ? 1 : -1;
          this.overtakeTimer = 1.5;
        }
        if (ahead < 9) blockerSpeed = Math.min(blockerSpeed, o.speed);
      }
    }
    if (this.overtakeTimer > 0 && this.overtakeSide !== 0) desired = this.overtakeSide * 0.8;
    this.lane = lerp(this.lane, clamp(desired, -1, 1), 1 - Math.exp(-1.8 * dt));
    const offset = this.lane * usable;

    // --- Steering ---------------------------------------------------------------
    const look = 7 + Math.abs(v) * 0.42;
    const f = tr.frameAt(s + look, this._f);
    const tx = f.x + f.rx * offset;
    const tz = f.z + f.rz * offset;
    const desiredYaw = Math.atan2(tx - car.x, tz - car.z);
    const err = wrapAngle(desiredYaw - car.yaw);
    this.noiseTimer -= dt;
    if (this.noiseTimer <= 0) {
      this.noiseVal = (this.rand() - 0.5) * 2 * this.noise;
      this.noiseTimer = 0.4 + this.rand() * 0.6;
    }
    inp.steer = clamp(-err * 2.4 + car.yawRate * 0.12 + this.noiseVal, -1, 1);

    // --- Speed ------------------------------------------------------------------
    // Gentle catch-up: AIs far behind the player push a little, far ahead ease off.
    const targetCatch = playerGap < -150 ? 1.04 : playerGap > 180 ? 0.96 : 1;
    this.catchUp = lerp(this.catchUp, targetCatch, 1 - Math.exp(-0.5 * dt));
    const i0 = Math.floor(tr.wrapS(s) / tr.spacing);
    const span = Math.max(3, Math.round((Math.abs(v) * 0.35) / tr.spacing));
    let target = Infinity;
    for (let o = 0; o <= span; o++) target = Math.min(target, this.profile[tr.idx(i0 + o)]);
    target *= this.pace * this.catchUp;
    if (blockerSpeed < target && this.aggression < 0.7) target = Math.max(blockerSpeed - 0.5, target * 0.85);
    // Slow down when far off the intended line (after a hit) to recover.
    if (Math.abs(err) > 0.6) target = Math.min(target, 18);

    if (v < target - 0.5) {
      inp.throttle = 1;
      inp.brake = 0;
    } else if (v > target + 1.5) {
      inp.throttle = 0;
      inp.brake = clamp((v - target) / 7, 0.2, 1);
    } else {
      inp.throttle = 0.35;
      inp.brake = 0;
    }
    inp.handbrake = false;

    // --- Nitro on straights -------------------------------------------------
    let straight = true;
    for (let o = 0; o < 70; o += 5) {
      if (this.profile[tr.idx(i0 + o)] < car.p.topSpeed * 0.97) {
        straight = false;
        break;
      }
    }
    if (straight && !this.wasStraight) this.nitroPlan = this.rand() < this.nitroUse;
    this.wasStraight = straight;
    const nitroFrac = car.nitro / car.p.nitroCap;
    inp.nitro = straight && this.nitroPlan && Math.abs(err) < 0.15 && nitroFrac > 0.1 &&
      (car.nitroActive || nitroFrac > 0.4);
  }

  signedCurvatureAhead(s, dist) {
    const tr = this.track;
    const start = Math.floor(tr.wrapS(s) / tr.spacing);
    const steps = Math.ceil(dist / tr.spacing);
    let best = 0;
    for (let o = 0; o <= steps; o++) {
      const k = tr.curvature[tr.idx(start + o)];
      if (Math.abs(k) > Math.abs(best)) best = k;
    }
    return best;
  }
}
