// Builds the drivable track visuals from a TrackPath: road surface, barriers with
// neon strips, kerbs on tight corners, start/finish gantry, checkpoint gates,
// tunnels and street lamps with fake light pools (no dynamic lights needed).

import * as THREE from 'three';
import { roadTexture, kerbTexture, checkerTexture, glowTexture, tunnelTexture, bannerTexture } from './textures.js';
import { TrackPath } from './trackPath.js';
import { CHECKPOINTS } from '../race/raceManager.js';

const THEMES = {
  night: { wallA: '#00e5ff', wallB: '#ff2fd0', wall: '#1d2030', lamp: '#ffc477', gate: '#00e5ff' },
  dusk: { wallA: '#ff9f43', wallB: '#ffe3a3', wall: '#3b3340', lamp: '#ffd59a', gate: '#ff9f43' },
};

/**
 * Generic strip along the track between sample indices [i0, i1] (inclusive, may wrap).
 * latFn(i) -> [latA, latB]; yFn(i) -> [yA, yB]. Closed when i0 === i1 === null.
 */
function strip(path, latFn, yFn, { i0 = null, i1 = null, vScale = 10, uSpan = 1 } = {}) {
  const n = path.count;
  const idx = [];
  if (i0 === null) {
    for (let i = 0; i <= n; i++) idx.push(i % n);
  } else {
    let i = i0;
    idx.push(i);
    while (i !== i1) {
      i = (i + 1) % n;
      idx.push(i);
    }
  }
  const closed = i0 === null;
  const reps = closed ? Math.max(1, Math.round(path.length / vScale)) : 0;
  const vs = closed ? path.length / reps : vScale;
  const pos = new Float32Array(idx.length * 2 * 3);
  const uv = new Float32Array(idx.length * 2 * 2);
  const indices = [];
  let along = 0;
  for (let k = 0; k < idx.length; k++) {
    const i = idx[k];
    if (k > 0) along += path.spacing;
    const [la, lb] = latFn(i);
    const [ya, yb] = yFn(i);
    pos.set([path.x[i] + path.rx[i] * la, ya, path.z[i] + path.rz[i] * la], k * 6);
    pos.set([path.x[i] + path.rx[i] * lb, yb, path.z[i] + path.rz[i] * lb], k * 6 + 3);
    const v = along / vs;
    uv.set([0, v, uSpan, v], k * 4);
    if (k < idx.length - 1) {
      const a = k * 2, b = a + 1, c = a + 2, d = a + 3;
      indices.push(a, b, c, b, d, c);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  g.setIndex(indices);
  g.computeVertexNormals();
  return g;
}

// Tunnel ranges are authored as fractions of the forward layout. For reverse
// tracks they're mapped through world positions so the tunnel stays put.
export function tunnelIndexRanges(def, path) {
  const out = [];
  if (!def.tunnels) return out;
  const fwd = def.reverse ? new TrackPath(def.points, { width: def.width }) : path;
  for (const [a, b] of def.tunnels) {
    const ia = Math.floor(a * fwd.count), ib = Math.floor(b * fwd.count);
    if (!def.reverse) out.push([ia, ib]);
    else {
      const la = path.locate(fwd.x[ia], fwd.z[ia]).index;
      const lb = path.locate(fwd.x[ib], fwd.z[ib]).index;
      out.push([lb, la]);
    }
  }
  return out;
}

function inRanges(i, ranges, n) {
  for (const [a, b] of ranges) {
    if (a <= b ? i >= a && i <= b : i >= a || i <= b) return true;
  }
  void n;
  return false;
}

export function buildTrackMeshes(path, def, quality) {
  const theme = THEMES[def.theme] || THEMES.night;
  const group = new THREE.Group();
  group.name = 'track';
  const hw = path.halfWidth;
  const n = path.count;
  const disposables = [];
  const track = (o) => (disposables.push(o), o);

  // Road
  const roadMat = track(new THREE.MeshLambertMaterial({ map: roadTexture(def.width >= 20 ? 4 : 4, def.theme) }));
  const road = new THREE.Mesh(track(strip(path, () => [-hw - 0.8, hw + 0.8], () => [0, 0], { vScale: 14 })), roadMat);
  road.receiveShadow = true;
  group.add(road);

  // Shoulders (slightly darker border beyond the walls so the road edge reads clearly)
  const shoulderMat = track(new THREE.MeshLambertMaterial({ color: def.theme === 'night' ? 0x0c0d18 : 0x2c2629 }));
  group.add(new THREE.Mesh(track(strip(path, () => [hw + 0.8, hw + 5], () => [-0.01, -0.01], { vScale: 20 })), shoulderMat));
  group.add(new THREE.Mesh(track(strip(path, () => [-hw - 5, -hw - 0.8], () => [-0.01, -0.01], { vScale: 20 })), shoulderMat));

  // Barriers: solid low wall + glowing neon strip on top.
  const tunnels = tunnelIndexRanges(def, path);
  const wallMat = track(new THREE.MeshLambertMaterial({ color: theme.wall }));
  const wl = hw + 0.4;
  for (const side of [-1, 1]) {
    const lat = side * wl;
    const geo = track(strip(path, () => (side < 0 ? [lat, lat] : [lat, lat]), () => [0, 1.15], { vScale: 6 }));
    const w = new THREE.Mesh(geo, wallMat);
    group.add(w);
    // inner face needs correct facing: material double sided is simplest for thin walls
    wallMat.side = THREE.DoubleSide;
    const neon = new THREE.Mesh(
      track(strip(path, () => [lat - side * 0.05, lat - side * 0.05], () => [1.0, 1.22], { vScale: 6 })),
      track(new THREE.MeshBasicMaterial({ color: side < 0 ? theme.wallA : theme.wallB, side: THREE.DoubleSide }))
    );
    neon.userData.bloom = true;
    group.add(neon);
  }

  // Kerbs on the inside of tight corners.
  const kerbMat = track(new THREE.MeshLambertMaterial({ map: kerbTexture(), polygonOffset: true, polygonOffsetFactor: -2 }));
  let i = 0;
  const kerbK = 1 / 70;
  const visited = new Uint8Array(n);
  while (i < n) {
    if (Math.abs(path.curvature[i]) > kerbK && !visited[i]) {
      let a = i;
      while (Math.abs(path.curvature[path.idx(a - 1)]) > kerbK && !visited[path.idx(a - 1)] && a > i - n) a--;
      let b = i;
      while (Math.abs(path.curvature[path.idx(b + 1)]) > kerbK && b < i + n) b++;
      for (let k = a; k <= b; k++) visited[path.idx(k)] = 1;
      const sgn = path.curvature[i] > 0 ? -1 : 1; // inside of the corner
      const ia = path.idx(a - 3), ib = path.idx(b + 3);
      const g = strip(path, () => (sgn > 0 ? [hw - 1.3, hw + 0.2] : [-hw - 0.2, -hw + 1.3]), () => [0.015, 0.015], { i0: ia, i1: ib, vScale: 4 });
      group.add(new THREE.Mesh(track(g), kerbMat));
      i = b + 1;
    } else i++;
  }

  // Tunnels: tall walls, roof, and rows of ceiling lights.
  if (tunnels.length) {
    const tMat = track(new THREE.MeshLambertMaterial({ map: tunnelTexture(), side: THREE.DoubleSide }));
    const roofMat = track(new THREE.MeshLambertMaterial({ color: 0x1a1c26, side: THREE.DoubleSide }));
    const lightGeo = track(new THREE.BoxGeometry(hw * 1.1, 0.12, 1.4));
    const lightMat = track(new THREE.MeshBasicMaterial({ color: '#ffe0a8' }));
    for (const [a, b] of tunnels) {
      for (const side of [-1, 1]) {
        const lat = side * (hw + 0.5);
        group.add(new THREE.Mesh(track(strip(path, () => [lat, lat], () => [0, 7.5], { i0: a, i1: b, vScale: 8 })), tMat));
      }
      group.add(new THREE.Mesh(track(strip(path, () => [-hw - 0.5, hw + 0.5], () => [7.5, 7.5], { i0: a, i1: b })), roofMat));
      // outer shell so the tunnel looks solid from outside
      group.add(new THREE.Mesh(track(strip(path, () => [-hw - 3, hw + 3], () => [8.6, 8.6], { i0: a, i1: b })), roofMat));
      // Portals at both ends so the tunnel reads clearly from a distance.
      const portalMat = track(new THREE.MeshLambertMaterial({ color: 0x2a2c38 }));
      const portalGlow = track(new THREE.MeshBasicMaterial({ color: theme.wallA }));
      const pillarG = track(new THREE.BoxGeometry(1.6, 9.2, 1.6));
      const beamG = track(new THREE.BoxGeometry(hw * 2 + 4.6, 1.6, 1.6));
      const stripG = track(new THREE.BoxGeometry(hw * 2 + 4.6, 0.25, 1.7));
      for (const idx of [a, b]) {
        const f = path.frameAt(idx * path.spacing);
        const portal = new THREE.Group();
        portal.position.set(f.x, 0, f.z);
        portal.rotation.y = f.heading;
        for (const sx of [-1, 1]) {
          const p = new THREE.Mesh(pillarG, portalMat);
          p.position.set(sx * (hw + 1.5), 4.6, 0);
          portal.add(p);
        }
        const beam = new THREE.Mesh(beamG, portalMat);
        beam.position.y = 8.4;
        const strip = new THREE.Mesh(stripG, portalGlow);
        strip.position.y = 7.55;
        strip.userData.bloom = true;
        portal.add(beam, strip);
        group.add(portal);
      }
      const count = Math.ceil((((b - a + n) % n) * path.spacing) / 9);
      const lights = new THREE.InstancedMesh(lightGeo, lightMat, count);
      const m = new THREE.Matrix4();
      const q = new THREE.Quaternion();
      for (let k = 0; k < count; k++) {
        const s = path.wrapS((a + (k * 9) / path.spacing) * path.spacing);
        const f = path.frameAt(s);
        q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), f.heading);
        m.compose(new THREE.Vector3(f.x, 7.35, f.z), q, new THREE.Vector3(1, 1, 1));
        lights.setMatrixAt(k, m);
      }
      lights.userData.bloom = true;
      group.add(lights);
    }
  }

  // Start / finish gantry.
  const f0 = path.frameAt(0);
  const gantry = new THREE.Group();
  gantry.position.set(f0.x, 0, f0.z);
  gantry.rotation.y = f0.heading;
  const lineMat = track(new THREE.MeshLambertMaterial({ map: checkerTexture(), polygonOffset: true, polygonOffsetFactor: -3 }));
  const line = new THREE.Mesh(track(new THREE.PlaneGeometry(hw * 2, 3)), lineMat);
  line.rotation.x = -Math.PI / 2;
  line.position.y = 0.02;
  gantry.add(line);
  const pillarGeo = track(new THREE.BoxGeometry(1, 9, 1));
  const pillarMat = track(new THREE.MeshLambertMaterial({ color: 0x22232e }));
  for (const sx of [-1, 1]) {
    const pl = new THREE.Mesh(pillarGeo, pillarMat);
    pl.position.set(sx * (hw + 1.5), 4.5, 0);
    gantry.add(pl);
  }
  const banner = new THREE.Mesh(
    track(new THREE.BoxGeometry(hw * 2 + 4, 2.2, 0.6)),
    [pillarMat, pillarMat, pillarMat, pillarMat,
      track(new THREE.MeshBasicMaterial({ map: bannerTexture('START  ·  FINISH', theme.gate) })),
      track(new THREE.MeshBasicMaterial({ map: bannerTexture('START  ·  FINISH', theme.gate) }))]
  );
  banner.position.y = 8.5;
  banner.userData.bloom = true;
  gantry.add(banner);
  group.add(gantry);

  // Checkpoint gates (light arches). Kept as separate materials so the next one can glow.
  const gates = [];
  const gateBeamGeo = track(new THREE.BoxGeometry(hw * 2 + 3, 0.18, 0.18));
  const gatePostGeo = track(new THREE.BoxGeometry(0.22, 7.5, 0.22));
  for (let c = 1; c < CHECKPOINTS; c++) {
    const s = (c / CHECKPOINTS) * path.length;
    const f = path.frameAt(s);
    const gg = new THREE.Group();
    gg.position.set(f.x, 0, f.z);
    gg.rotation.y = f.heading;
    const mat = track(new THREE.MeshBasicMaterial({ color: theme.gate, transparent: true, opacity: 0.35 }));
    const beam = new THREE.Mesh(gateBeamGeo, mat);
    beam.position.y = 7.5;
    gg.add(beam);
    for (const sx of [-1, 1]) {
      const post = new THREE.Mesh(gatePostGeo, mat);
      post.position.set(sx * (hw + 1.3), 3.75, 0);
      gg.add(post);
    }
    gg.userData = { mat, index: c };
    gates.push(gg);
    group.add(gg);
  }

  // Street lamps every ~34 m alternating sides, with additive light pools on the road.
  const spacing = 34;
  const lampCount = Math.floor(path.length / spacing);
  const poleGeo = track(new THREE.CylinderGeometry(0.12, 0.16, 8, 6));
  const headGeo = track(new THREE.BoxGeometry(2.2, 0.25, 0.6));
  const poles = new THREE.InstancedMesh(poleGeo, pillarMat, lampCount);
  const heads = new THREE.InstancedMesh(headGeo, track(new THREE.MeshBasicMaterial({ color: theme.lamp })), lampCount);
  heads.userData.bloom = true;
  const poolGeo = track(new THREE.PlaneGeometry(13, 13));
  poolGeo.rotateX(-Math.PI / 2);
  const poolMat = track(new THREE.MeshBasicMaterial({
    map: glowTexture(), color: theme.lamp, transparent: true, opacity: def.theme === 'night' ? 0.32 : 0.16,
    blending: THREE.AdditiveBlending, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -4,
  }));
  const pools = new THREE.InstancedMesh(poolGeo, poolMat, lampCount);
  const m = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  const one = new THREE.Vector3(1, 1, 1);
  let li = 0;
  for (let k = 0; k < lampCount; k++) {
    const s = k * spacing + 10;
    const f = path.frameAt(s);
    const idx = Math.floor(path.wrapS(s) / path.spacing);
    if (inRanges(idx, tunnels, n)) {
      m.makeScale(0, 0, 0);
      poles.setMatrixAt(li, m);
      heads.setMatrixAt(li, m);
      pools.setMatrixAt(li, m);
      li++;
      continue;
    }
    const side = k % 2 ? 1 : -1;
    const lat = side * (hw + 2.2);
    const px = f.x + f.rx * lat, pz = f.z + f.rz * lat;
    q.setFromAxisAngle(up, f.heading);
    m.compose(new THREE.Vector3(px, 4, pz), q, one);
    poles.setMatrixAt(li, m);
    const hx = f.x + f.rx * (lat - side * 1.1), hz = f.z + f.rz * (lat - side * 1.1);
    m.compose(new THREE.Vector3(hx, 8, hz), q, one);
    heads.setMatrixAt(li, m);
    const lx = f.x + f.rx * (lat - side * 4.5), lz = f.z + f.rz * (lat - side * 4.5);
    m.compose(new THREE.Vector3(lx, 0.03, lz), q, one);
    pools.setMatrixAt(li, m);
    li++;
  }
  group.add(poles, heads);
  if (quality !== 'low') group.add(pools);

  return {
    group,
    gates,
    tunnels,
    dispose() {
      for (const d of disposables) d.dispose?.();
    },
  };
}
