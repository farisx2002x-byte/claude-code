// Small math helpers shared by gameplay code. Pure functions, no Three.js dependency,
// so physics / AI / race logic can be unit-tested in Node.

export const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
export const lerp = (a, b, t) => a + (b - a) * t;
export const sign = (v) => (v > 0 ? 1 : v < 0 ? -1 : 0);

// Frame-rate independent exponential approach: move `cur` towards `target`
// with the given rate (1/s).
export const damp = (cur, target, rate, dt) => lerp(cur, target, 1 - Math.exp(-rate * dt));

// Move `cur` towards `target` by at most `maxDelta`.
export const approach = (cur, target, maxDelta) => {
  if (cur < target) return Math.min(cur + maxDelta, target);
  return Math.max(cur - maxDelta, target);
};

// Wrap angle into [-PI, PI].
export const wrapAngle = (a) => {
  while (a > Math.PI) a -= Math.PI * 2;
  while (a < -Math.PI) a += Math.PI * 2;
  return a;
};

export const smoothstep = (e0, e1, x) => {
  const t = clamp((x - e0) / (e1 - e0), 0, 1);
  return t * t * (3 - 2 * t);
};

// Deterministic PRNG (mulberry32) so scenery and AI personalities are stable per track.
export function rng(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function formatTime(seconds) {
  if (!isFinite(seconds) || seconds < 0) return '--:--.---';
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${m}:${s.toFixed(3).padStart(6, '0')}`;
}

export const KMH = 3.6;
export const MPH = 2.23694;
