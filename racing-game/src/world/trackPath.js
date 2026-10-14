// Pure geometric description of a closed race track centerline.
// Built from a handful of control points with a centripetal Catmull-Rom spline,
// then re-sampled at an even arc-length spacing. Everything that needs to know
// "where on the track am I" (race progress, AI, wall collisions, resets, minimap)
// goes through this class.

import { wrapAngle } from '../core/util.js';

function catmullRom(p0, p1, p2, p3, t) {
  // Centripetal Catmull-Rom (alpha = 0.5) – avoids cusps and self-intersections.
  const d01 = Math.max(Math.pow(Math.hypot(p1[0] - p0[0], p1[1] - p0[1]), 0.5), 1e-4);
  const d12 = Math.max(Math.pow(Math.hypot(p2[0] - p1[0], p2[1] - p1[1]), 0.5), 1e-4);
  const d23 = Math.max(Math.pow(Math.hypot(p3[0] - p2[0], p3[1] - p2[1]), 0.5), 1e-4);
  const t0 = 0;
  const t1 = t0 + d01;
  const t2 = t1 + d12;
  const t3 = t2 + d23;
  const tt = t1 + (t2 - t1) * t;
  const out = [0, 0];
  for (let k = 0; k < 2; k++) {
    const a1 = ((t1 - tt) / (t1 - t0)) * p0[k] + ((tt - t0) / (t1 - t0)) * p1[k];
    const a2 = ((t2 - tt) / (t2 - t1)) * p1[k] + ((tt - t1) / (t2 - t1)) * p2[k];
    const a3 = ((t3 - tt) / (t3 - t2)) * p2[k] + ((tt - t2) / (t3 - t2)) * p3[k];
    const b1 = ((t2 - tt) / (t2 - t0)) * a1 + ((tt - t0) / (t2 - t0)) * a2;
    const b2 = ((t3 - tt) / (t3 - t1)) * a2 + ((tt - t1) / (t3 - t1)) * a3;
    out[k] = ((t2 - tt) / (t2 - t1)) * b1 + ((tt - t1) / (t2 - t1)) * b2;
  }
  return out;
}

export class TrackPath {
  /**
   * @param {number[][]} points control points [x, z] in meters, in driving order
   * @param {object} opts { width, spacing, reverse }
   */
  constructor(points, opts = {}) {
    this.width = opts.width ?? 18;
    this.halfWidth = this.width / 2;
    const spacing = opts.spacing ?? 2;
    let pts = points.map((p) => [p[0], p[1]]);
    if (opts.reverse) pts = pts.reverse();

    // 1) Dense parametric sampling.
    const dense = [];
    const n = pts.length;
    const sub = 60;
    for (let i = 0; i < n; i++) {
      const p0 = pts[(i - 1 + n) % n];
      const p1 = pts[i];
      const p2 = pts[(i + 1) % n];
      const p3 = pts[(i + 2) % n];
      for (let j = 0; j < sub; j++) dense.push(catmullRom(p0, p1, p2, p3, j / sub));
    }
    // cumulative length of dense polyline (closed)
    const dl = new Float64Array(dense.length + 1);
    for (let i = 0; i < dense.length; i++) {
      const a = dense[i];
      const b = dense[(i + 1) % dense.length];
      dl[i + 1] = dl[i] + Math.hypot(b[0] - a[0], b[1] - a[1]);
    }
    const total = dl[dense.length];

    // 2) Even arc-length resampling.
    const count = Math.max(16, Math.round(total / spacing));
    this.count = count;
    this.length = total;
    this.spacing = total / count;
    this.x = new Float64Array(count);
    this.z = new Float64Array(count);
    let seg = 0;
    for (let i = 0; i < count; i++) {
      const target = i * this.spacing;
      while (dl[seg + 1] < target) seg++;
      const segLen = dl[seg + 1] - dl[seg];
      const t = segLen > 0 ? (target - dl[seg]) / segLen : 0;
      const a = dense[seg];
      const b = dense[(seg + 1) % dense.length];
      this.x[i] = a[0] + (b[0] - a[0]) * t;
      this.z[i] = a[1] + (b[1] - a[1]) * t;
    }

    // 3) Tangents, right-normals, headings, curvature.
    this.tx = new Float64Array(count);
    this.tz = new Float64Array(count);
    this.rx = new Float64Array(count);
    this.rz = new Float64Array(count);
    this.heading = new Float64Array(count);
    this.curvature = new Float64Array(count);
    for (let i = 0; i < count; i++) {
      const prev = (i - 1 + count) % count;
      const next = (i + 1) % count;
      let tx = this.x[next] - this.x[prev];
      let tz = this.z[next] - this.z[prev];
      const l = Math.hypot(tx, tz) || 1;
      tx /= l;
      tz /= l;
      this.tx[i] = tx;
      this.tz[i] = tz;
      // Right-hand side when looking along +tangent (Y up): r = (-tz, tx)
      this.rx[i] = -tz;
      this.rz[i] = tx;
      this.heading[i] = Math.atan2(tx, tz);
    }
    const k = 3;
    for (let i = 0; i < count; i++) {
      const a = this.heading[(i - k + count) % count];
      const b = this.heading[(i + k) % count];
      this.curvature[i] = wrapAngle(b - a) / (2 * k * this.spacing);
    }
  }

  idx(i) {
    const c = this.count;
    return ((i % c) + c) % c;
  }

  // Signed shortest distance along the track from s0 to s1.
  deltaS(s0, s1) {
    let d = s1 - s0;
    const L = this.length;
    if (d > L / 2) d -= L;
    if (d < -L / 2) d += L;
    return d;
  }

  wrapS(s) {
    const L = this.length;
    return ((s % L) + L) % L;
  }

  /**
   * Find the closest sample to (x, z). When `hint` is a valid index only a window
   * around it is searched (fast, and robust where the track passes near itself).
   * Returns a reused result object: { index, s, lateral, dist }.
   */
  locate(x, z, hint = -1, window = 24, out = { index: 0, s: 0, lateral: 0, dist: 0 }) {
    let best = -1;
    let bestD = Infinity;
    if (hint >= 0) {
      for (let o = -window; o <= window; o++) {
        const i = this.idx(hint + o);
        const dx = x - this.x[i];
        const dz = z - this.z[i];
        const d = dx * dx + dz * dz;
        if (d < bestD) {
          bestD = d;
          best = i;
        }
      }
    } else {
      for (let i = 0; i < this.count; i++) {
        const dx = x - this.x[i];
        const dz = z - this.z[i];
        const d = dx * dx + dz * dz;
        if (d < bestD) {
          bestD = d;
          best = i;
        }
      }
    }
    const i = best;
    const dx = x - this.x[i];
    const dz = z - this.z[i];
    const along = dx * this.tx[i] + dz * this.tz[i];
    out.index = i;
    out.s = this.wrapS(i * this.spacing + along);
    out.lateral = dx * this.rx[i] + dz * this.rz[i];
    out.dist = Math.sqrt(bestD);
    return out;
  }

  // Interpolated frame at arc length s. Returns { x, z, tx, tz, rx, rz, heading }.
  frameAt(s, out = {}) {
    const f = this.wrapS(s) / this.spacing;
    const i0 = Math.floor(f) % this.count;
    const i1 = (i0 + 1) % this.count;
    const t = f - Math.floor(f);
    out.x = this.x[i0] + (this.x[i1] - this.x[i0]) * t;
    out.z = this.z[i0] + (this.z[i1] - this.z[i0]) * t;
    let tx = this.tx[i0] + (this.tx[i1] - this.tx[i0]) * t;
    let tz = this.tz[i0] + (this.tz[i1] - this.tz[i0]) * t;
    const l = Math.hypot(tx, tz) || 1;
    tx /= l;
    tz /= l;
    out.tx = tx;
    out.tz = tz;
    out.rx = -tz;
    out.rz = tx;
    out.heading = Math.atan2(tx, tz);
    return out;
  }

  // Max |curvature| between s and s + dist.
  maxCurvatureAhead(s, dist) {
    const start = Math.floor(this.wrapS(s) / this.spacing);
    const steps = Math.ceil(dist / this.spacing);
    let m = 0;
    for (let o = 0; o <= steps; o++) {
      const c = Math.abs(this.curvature[this.idx(start + o)]);
      if (c > m) m = c;
    }
    return m;
  }

  bounds() {
    let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
    for (let i = 0; i < this.count; i++) {
      minX = Math.min(minX, this.x[i]);
      maxX = Math.max(maxX, this.x[i]);
      minZ = Math.min(minZ, this.z[i]);
      maxZ = Math.max(maxZ, this.z[i]);
    }
    return { minX, maxX, minZ, maxZ };
  }
}
