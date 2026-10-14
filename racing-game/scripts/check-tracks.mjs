// Validates track layouts: no self-overlap of the road/walls, reports length & tightest radius.
import { TrackPath } from '../src/world/trackPath.js';
import { TRACKS } from '../src/data/tracks.js';
let ok = true;
for (const t of TRACKS) {
  const p = new TrackPath(t.points, { width: t.width, reverse: t.reverse });
  let minD = Infinity, at = null;
  for (let i = 0; i < p.count; i++) for (let j = i + 1; j < p.count; j++) {
    const along = Math.min(j - i, p.count - (j - i)) * p.spacing;
    if (along < 60) continue;
    const d = Math.hypot(p.x[i] - p.x[j], p.z[i] - p.z[j]);
    if (d < minD) { minD = d; at = [i, j]; }
  }
  let maxK = 0; for (let i = 0; i < p.count; i++) maxK = Math.max(maxK, Math.abs(p.curvature[i]));
  const need = t.width + 14;
  const good = minD > need;
  if (!good) ok = false;
  console.log(`${t.id.padEnd(12)} len=${p.length.toFixed(0)}m minSep=${minD.toFixed(1)}m (need>${need}) at ${at} [${p.x[at[0]].toFixed(0)},${p.z[at[0]].toFixed(0)}]  minRadius=${(1/maxK).toFixed(1)}m ${good ? 'OK' : 'OVERLAP'}`);
}
process.exit(ok ? 0 : 1);
