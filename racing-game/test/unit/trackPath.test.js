import { test } from 'node:test';
import assert from 'node:assert/strict';
import { makeTrack } from './helpers.js';
import { TRACKS } from '../../src/data/tracks.js';

test('every track is a valid closed loop with no overlapping sections', () => {
  for (const t of TRACKS) {
    const p = makeTrack(t.id);
    assert.ok(p.length > 1000, `${t.id} length ${p.length}`);
    // consecutive samples evenly spaced
    for (let i = 0; i < p.count; i++) {
      const j = (i + 1) % p.count;
      const d = Math.hypot(p.x[j] - p.x[i], p.z[j] - p.z[i]);
      assert.ok(Math.abs(d - p.spacing) < 0.3, `${t.id} uneven spacing at ${i}: ${d}`);
    }
    let minSep = Infinity;
    for (let i = 0; i < p.count; i += 2)
      for (let j = i + 2; j < p.count; j += 2) {
        if (Math.min(j - i, p.count - (j - i)) * p.spacing < 60) continue;
        minSep = Math.min(minSep, Math.hypot(p.x[i] - p.x[j], p.z[i] - p.z[j]));
      }
    assert.ok(minSep > t.width + 14, `${t.id} sections too close: ${minSep}`);
  }
});

test('locate() gives arc length and signed lateral offset (right = positive)', () => {
  const p = makeTrack('downtown');
  const i = 100;
  const lat = 4;
  const x = p.x[i] + p.rx[i] * lat, z = p.z[i] + p.rz[i] * lat;
  const loc = p.locate(x, z);
  assert.equal(loc.index, i);
  assert.ok(Math.abs(loc.lateral - lat) < 0.05);
  assert.ok(Math.abs(loc.s - i * p.spacing) < 0.5);
  // windowed search agrees with the global search
  const loc2 = p.locate(x, z, i + 5, 24);
  assert.equal(loc2.index, i);
});

test('deltaS wraps around the start line', () => {
  const p = makeTrack('downtown');
  assert.ok(Math.abs(p.deltaS(p.length - 2, 3) - 5) < 1e-9);
  assert.ok(Math.abs(p.deltaS(3, p.length - 2) + 5) < 1e-9);
});

test('reverse layouts run the opposite way over the same ground', () => {
  const f = makeTrack('downtown');
  const r = makeTrack('downtown-r');
  assert.ok(Math.abs(f.length - r.length) < 1);
  const loc = r.locate(f.x[200], f.z[200]);
  assert.ok(loc.dist < 1);
  const dot = f.tx[200] * r.tx[loc.index] + f.tz[200] * r.tz[loc.index];
  assert.ok(dot < -0.95);
});
