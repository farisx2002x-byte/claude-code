// Race rules: countdown, distance-based progress, checkpoints, laps, positions,
// wrong-way / stuck detection, finish and rewards. Pure logic (no rendering),
// so a whole race can be simulated in unit tests.
//
// Progress model: each racer accumulates `dist`, the signed distance travelled
// along the centerline (wrap-around handled with TrackPath.deltaS). Driving
// backwards reduces it, so laps can't be faked; checkpoints are fixed fractions
// of a lap and must be crossed in order because `dist` is continuous.

import { placeCar } from '../vehicle/carPhysics.js';

export const CHECKPOINTS = 6; // gates per lap (the last one is the finish line)

export class RaceManager {
  /**
   * @param {TrackPath} track
   * @param {object} opts { laps, mode, countdown }
   */
  constructor(track, opts = {}) {
    this.track = track;
    this.laps = opts.laps ?? 3;
    this.mode = opts.mode || 'race';
    this.countdownTime = opts.countdown ?? 3;
    this.racers = [];
    this.state = 'countdown'; // countdown | running | finished
    this.countdown = this.countdownTime;
    this.time = 0;
    this.finishOrder = [];
    this.events = [];
    this.postFinishTimer = 0;
  }

  addRacer(car, info = {}) {
    const r = {
      car,
      id: info.id ?? this.racers.length,
      name: info.name || `CAR ${this.racers.length + 1}`,
      isPlayer: !!info.isPlayer,
      dist: 0,
      lastS: 0,
      lap: 0, // completed laps
      nextCheckpoint: 1,
      lapStart: 0,
      lapTimes: [],
      bestLap: Infinity,
      finished: false,
      finishTime: Infinity,
      position: this.racers.length + 1,
      wrongWayTimer: 0,
      wrongWay: false,
      stuckTimer: 0,
      driftScore: 0,
      wallHits: 0,
      resets: 0,
    };
    this.racers.push(r);
    return r;
  }

  /**
   * Put every racer on a 2-wide staggered grid behind the start line.
   * Player goes at `playerSlot` (0 = pole).
   */
  setupGrid() {
    const tr = this.track;
    const f = {};
    this.racers.forEach((r, i) => {
      const row = Math.floor(i / 2);
      const col = i % 2 === 0 ? -1 : 1;
      const back = 9 + row * 9 + (i % 2) * 3.5;
      const s = tr.wrapS(-back);
      tr.frameAt(s, f);
      const lat = col * tr.halfWidth * 0.42;
      placeCar(r.car, f.x + f.rx * lat, f.z + f.rz * lat, f.heading);
      const loc = tr.locate(r.car.x, r.car.z);
      r.car.trackIndex = loc.index;
      r.car._loc = { ...loc };
      r.lastS = loc.s;
      r.dist = -back;
    });
  }

  get player() {
    return this.racers.find((r) => r.isPlayer);
  }

  update(dt) {
    this.events.length = 0;
    if (this.state === 'countdown') {
      const before = Math.ceil(this.countdown);
      this.countdown -= dt;
      const after = Math.ceil(this.countdown);
      if (after !== before && after > 0) this.events.push({ type: 'count', value: after });
      if (this.countdown <= 0) {
        this.state = 'running';
        this.events.push({ type: 'go' });
        for (const r of this.racers) r.lapStart = 0;
      }
      return;
    }
    this.time += dt;
    const tr = this.track;
    const L = tr.length;
    const cpLen = L / CHECKPOINTS;

    for (const r of this.racers) {
      const car = r.car;
      const loc = car._loc || tr.locate(car.x, car.z);
      const ds = tr.deltaS(r.lastS, loc.s);
      r.lastS = loc.s;
      if (r.finished) continue;
      r.dist += ds;

      // Checkpoints / laps.
      while (r.dist >= r.lap * L + r.nextCheckpoint * cpLen) {
        if (r.nextCheckpoint >= CHECKPOINTS) {
          const lapTime = this.time - r.lapStart;
          r.lapTimes.push(lapTime);
          const isBest = lapTime < r.bestLap;
          if (isBest) r.bestLap = lapTime;
          r.lap++;
          r.nextCheckpoint = 1;
          r.lapStart = this.time;
          this.events.push({ type: 'lap', racer: r, value: lapTime, best: isBest });
          if (r.lap >= this.laps) {
            r.finished = true;
            r.finishTime = this.time;
            this.finishOrder.push(r);
            this.events.push({ type: 'finish', racer: r, position: this.finishOrder.length });
            break;
          }
        } else {
          this.events.push({ type: 'checkpoint', racer: r, index: r.nextCheckpoint, time: this.time - r.lapStart });
          r.nextCheckpoint++;
        }
      }

      // Wrong way: moving against the track direction.
      const i = loc.index;
      const along = car.vx * tr.tx[i] + car.vz * tr.tz[i];
      const facing = Math.sin(car.yaw) * tr.tx[i] + Math.cos(car.yaw) * tr.tz[i];
      if ((along < -3 || (facing < -0.5 && Math.abs(car.speed) > 2 && along < 0)) && !r.finished) r.wrongWayTimer += dt;
      else r.wrongWayTimer = Math.max(0, r.wrongWayTimer - dt * 2);
      const ww = r.wrongWayTimer > 1.2;
      if (ww !== r.wrongWay) {
        r.wrongWay = ww;
        this.events.push({ type: 'wrongWay', racer: r, value: ww });
      }

      // Stuck detection (used for AI auto-reset and the player's reset hint).
      if (Math.abs(car.speed) < 2 || r.wrongWayTimer > 4) r.stuckTimer += dt;
      else r.stuckTimer = 0;
    }

    this.updatePositions();

    const p = this.player;
    if (this.state === 'running' && p && p.finished) {
      this.state = 'finished';
      this.postFinishTimer = 0;
    }
    if (this.state === 'finished') this.postFinishTimer += dt;
  }

  updatePositions() {
    const sorted = [...this.racers].sort((a, b) => {
      if (a.finished && b.finished) return a.finishTime - b.finishTime;
      if (a.finished) return -1;
      if (b.finished) return 1;
      return b.dist - a.dist;
    });
    sorted.forEach((r, i) => (r.position = i + 1));
    this.order = sorted;
  }

  /** Move a racer back onto the track centerline at its current progress. */
  resetRacer(r) {
    const tr = this.track;
    const car = r.car;
    const loc = tr.locate(car.x, car.z, car.trackIndex);
    const s = tr.wrapS(loc.s - 4);
    const f = tr.frameAt(s);
    // Pick the less crowded half of the road.
    let lat = 0;
    for (const o of this.racers) {
      if (o === r || !o.car._loc) continue;
      if (Math.abs(tr.deltaS(s, o.car._loc.s)) < 15) lat = o.car._loc.lateral > 0 ? -tr.halfWidth * 0.4 : tr.halfWidth * 0.4;
    }
    const nitro = car.nitro;
    placeCar(car, f.x + f.rx * lat, f.z + f.rz * lat, f.heading);
    car.nitro = nitro;
    car.ghostTimer = 2;
    const nl = tr.locate(car.x, car.z);
    car.trackIndex = nl.index;
    car._loc = { ...nl };
    r.dist += tr.deltaS(r.lastS, nl.s);
    r.lastS = nl.s;
    r.stuckTimer = 0;
    r.wrongWayTimer = 0;
    r.resets++;
  }

  /** Estimated finish time for racers that didn't finish (based on average pace). */
  estimateFinish(r) {
    if (r.finished) return r.finishTime;
    const total = this.laps * this.track.length;
    const done = Math.max(1, r.dist);
    const pace = done / Math.max(1, this.time);
    return this.time + (total - r.dist) / Math.max(pace, 5);
  }

  results() {
    const list = this.racers.map((r) => ({
      racer: r,
      time: this.estimateFinish(r),
      estimated: !r.finished,
    }));
    list.sort((a, b) => a.time - b.time);
    return list;
  }
}

// Credits awarded at the end of an event. Deliberately simple and readable.
export function computeRewards({ mode, position, racers, driftScore, bestLap, prevBestLap, cleanRace, difficulty }) {
  const items = [];
  const diffMul = difficulty === 'hard' ? 1.3 : difficulty === 'easy' ? 0.75 : 1;
  if (mode === 'race') {
    const table = [1500, 1000, 700, 450, 300, 200];
    items.push({ label: `Finish P${position}/${racers}`, value: Math.round((table[position - 1] ?? 150) * diffMul) });
    if (cleanRace) items.push({ label: 'Clean race (no wall hits)', value: 300 });
  } else if (mode === 'timetrial') {
    items.push({ label: 'Time trial complete', value: 400 });
    if (isFinite(prevBestLap) && bestLap < prevBestLap) items.push({ label: 'New best lap!', value: 600 });
    else if (!isFinite(prevBestLap)) items.push({ label: 'First recorded lap', value: 300 });
  } else if (mode === 'drift') {
    items.push({ label: 'Drift attack complete', value: 300 });
  }
  if (driftScore > 0) items.push({ label: `Drift points (${driftScore.toLocaleString('en-US')})`, value: Math.round(Math.min(driftScore / 20, 2500)) });
  const total = items.reduce((a, b) => a + b.value, 0);
  return { items, total };
}

export function driftMedalTargets(trackLength) {
  const k = trackLength / 1600;
  return [['BRONZE', Math.round(2500 * k)], ['SILVER', Math.round(6000 * k)], ['GOLD', Math.round(11000 * k)]];
}

export function driftMedal(score, trackLength) {
  const k = trackLength / 1600;
  // Calibrated with a scripted driver that taps the handbrake into every corner
  // (~3,000 points on Neon Downtown): that's bronze; long linked slides get gold.
  if (score >= 11000 * k) return 'GOLD';
  if (score >= 6000 * k) return 'SILVER';
  if (score >= 2500 * k) return 'BRONZE';
  return null;
}
