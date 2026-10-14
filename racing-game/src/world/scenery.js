// Environment around the track: sky, fog, lights, ground/water, instanced city
// blocks, distant skyline, neon billboards and palm trees.
// Density scales with the quality preset; buildings are split into spatial
// chunks so frustum culling can skip whole blocks that are off-screen.

import * as THREE from 'three';
import { rng } from '../core/util.js';
import { windowTexture, skylineTexture, signTexture, groundTexture, waterTexture } from './textures.js';

export const THEME_SETTINGS = {
  night: {
    skyTop: '#05040f', skyMid: '#1a0f3a', skyHorizon: '#3a1a5c',
    fog: '#1b1238', fogNear: 120, fogFar: 750,
    hemiSky: '#6a7cff', hemiGround: '#20112e', hemiI: 0.95,
    sun: '#9fb4ff', sunI: 0.55, sunDir: [-0.4, 1, 0.3],
    buildingColors: ['#1a1d33', '#20183a', '#151a2b', '#2a1f45', '#13243a'],
    exposure: 1.1,
    envIntensity: 0.35,
  },
  dusk: {
    skyTop: '#1d1b4a', skyMid: '#a3477a', skyHorizon: '#ff9a52',
    fog: '#c9708a', fogNear: 160, fogFar: 1000,
    hemiSky: '#ffc59e', hemiGround: '#5a3d4a', hemiI: 1.35,
    sun: '#ffb070', sunI: 1.25, sunDir: [0.8, 0.45, -0.6],
    buildingColors: ['#5b4a5e', '#6b5560', '#4d4058', '#7a6168', '#5a5470'],
    exposure: 1.0,
    envIntensity: 0.7,
  },
};

const SIGN_WORDS = [
  ['NOVA', 'NOODLE BAR'], ['HYPER', 'ARCADE'], ['VOLT', 'ENERGY'], ['88', 'MOTEL'],
  ['ZENITH', 'TOWER'], ['KAIJU', 'RAMEN'], ['ORBIT', 'RADIO 101'], ['PULSE', 'CLUB'],
  ['DRIFT', 'GARAGE'], ['APEX', 'TYRES'], ['LUNA', 'CINEMA'], ['RUSH', 'NITRO'],
];
const SIGN_COLORS = ['#ff2fd0', '#00e5ff', '#ffb300', '#39ff14', '#7c4dff', '#ff5252'];

export function buildScenery(path, def, quality) {
  const T = THEME_SETTINGS[def.theme] || THEME_SETTINGS.night;
  const group = new THREE.Group();
  group.name = 'scenery';
  const disposables = [];
  const keep = (o) => (disposables.push(o), o);
  const r = rng(def.seed || 1);
  const b = path.bounds();
  const cx = (b.minX + b.maxX) / 2, cz = (b.minZ + b.maxZ) / 2;
  const span = Math.max(b.maxX - b.minX, b.maxZ - b.minZ);
  const density = quality === 'low' ? 0.45 : quality === 'medium' ? 0.75 : 1;

  // --- Sky dome (vertex-colored gradient, unlit) ---------------------------
  const skyGeo = keep(new THREE.SphereGeometry(1800, 24, 16));
  const top = new THREE.Color(T.skyTop), mid = new THREE.Color(T.skyMid), hor = new THREE.Color(T.skyHorizon);
  const cols = [];
  const pa = skyGeo.attributes.position;
  const c = new THREE.Color();
  for (let i = 0; i < pa.count; i++) {
    const y = pa.getY(i) / 1800;
    if (y > 0.25) c.copy(mid).lerp(top, Math.min(1, (y - 0.25) / 0.6));
    else if (y > 0) c.copy(hor).lerp(mid, y / 0.25);
    else c.copy(hor).multiplyScalar(0.6);
    cols.push(c.r, c.g, c.b);
  }
  skyGeo.setAttribute('color', new THREE.Float32BufferAttribute(cols, 3));
  const sky = new THREE.Mesh(skyGeo, keep(new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide, fog: false, depthWrite: false })));
  sky.renderOrder = -10;
  sky.frustumCulled = false;
  group.add(sky);

  // Stars (night) or a low sun disc (dusk).
  if (def.theme === 'night') {
    const starPos = [];
    for (let i = 0; i < 700; i++) {
      const th = r() * Math.PI * 2, ph = 0.12 + r() * 1.2;
      starPos.push(Math.cos(th) * Math.cos(ph) * 1700, Math.sin(ph) * 1700, Math.sin(th) * Math.cos(ph) * 1700);
    }
    const sg = keep(new THREE.BufferGeometry());
    sg.setAttribute('position', new THREE.Float32BufferAttribute(starPos, 3));
    const stars = new THREE.Points(sg, keep(new THREE.PointsMaterial({ color: 0xffffff, size: 2.2, sizeAttenuation: false, fog: false, transparent: true, opacity: 0.8 })));
    stars.frustumCulled = false;
    group.add(stars);
  } else {
    const sun = new THREE.Mesh(keep(new THREE.CircleGeometry(120, 32)), keep(new THREE.MeshBasicMaterial({ color: '#ffd08a', fog: false, transparent: true, opacity: 0.95 })));
    const d = new THREE.Vector3(...T.sunDir).normalize();
    sun.position.set(d.x * 1600, 160, d.z * 1600);
    sun.lookAt(0, 0, 0);
    group.add(sun);
  }

  // Distant skyline ring.
  const ringGeo = keep(new THREE.CylinderGeometry(1500, 1500, 260, 48, 1, true));
  const skyTex = skylineTexture(def.theme);
  skyTex.repeat.set(3, 1);
  const ring = new THREE.Mesh(ringGeo, keep(new THREE.MeshBasicMaterial({ map: skyTex, transparent: true, side: THREE.BackSide, fog: false, depthWrite: false })));
  ring.position.set(cx, 110, cz);
  ring.renderOrder = -9;
  ring.frustumCulled = false;
  group.add(ring);

  // --- Lights -------------------------------------------------------------------
  const hemi = new THREE.HemisphereLight(T.hemiSky, T.hemiGround, T.hemiI);
  const sun = new THREE.DirectionalLight(T.sun, T.sunI);
  sun.position.set(...T.sunDir).multiplyScalar(100);
  group.add(hemi, sun, sun.target);

  // --- Ground / water -------------------------------------------------------------
  const harbor = def.theme === 'dusk';
  const gTex = groundTexture(def.theme);
  const groundSize = harbor ? span + 260 : 4000;
  gTex.repeat.set(groundSize / 24, groundSize / 24);
  const ground = new THREE.Mesh(keep(new THREE.PlaneGeometry(groundSize, groundSize)), keep(new THREE.MeshLambertMaterial({ map: gTex })));
  ground.rotation.x = -Math.PI / 2;
  ground.position.set(cx, -0.05, cz);
  ground.receiveShadow = true;
  group.add(ground);
  let water = null;
  if (harbor) {
    const wTex = waterTexture();
    wTex.repeat.set(120, 120);
    water = new THREE.Mesh(keep(new THREE.PlaneGeometry(5000, 5000)), keep(new THREE.MeshLambertMaterial({ map: wTex, emissive: '#2a1a40', emissiveIntensity: 0.6 })));
    water.rotation.x = -Math.PI / 2;
    water.position.set(cx, -1.2, cz);
    group.add(water);
  }

  // --- Buildings (chunked instancing) ------------------------------------------
  const winTex = windowTexture(def.theme);
  const bMat = keep(new THREE.MeshLambertMaterial({
    map: winTex, emissiveMap: winTex, emissive: new THREE.Color(def.theme === 'night' ? '#ffffff' : '#a08070'),
    emissiveIntensity: def.theme === 'night' ? 1.0 : 0.8,
  }));
  // A few prototype boxes whose UVs tile the window texture at a sane scale.
  const protos = [
    [16, 30, 16], [22, 55, 18], [14, 80, 14], [26, 22, 26], [18, 120, 18],
  ].map(([w, h, d]) => {
    const g = new THREE.BoxGeometry(w, h, d);
    g.translate(0, h / 2, 0);
    const uv = g.attributes.uv;
    const nrm = g.attributes.normal;
    for (let i = 0; i < uv.count; i++) {
      const ny = nrm.getY(i);
      if (Math.abs(ny) > 0.5) {
        uv.setXY(i, 0.005, 0.005); // roofs/bottoms: dark corner of the texture
      } else {
        const faceW = Math.abs(nrm.getX(i)) > 0.5 ? d : w;
        uv.setXY(i, uv.getX(i) * (faceW / 32), uv.getY(i) * (h / 64));
      }
    }
    return keep(g);
  });

  const placements = []; // [proto, x, z, rotY, sy, color]
  const margin = path.halfWidth + 22;
  const step = harbor ? 42 : 34;
  const ext = harbor ? 160 : 420;
  const near = (x, z) => path.locate(x, z).dist;
  const shoreline = harbor ? 120 : Infinity;
  for (let x = b.minX - ext; x <= b.maxX + ext; x += step) {
    for (let z = b.minZ - ext; z <= b.maxZ + ext; z += step) {
      if (r() > density) continue;
      const jx = x + (r() - 0.5) * step * 0.4, jz = z + (r() - 0.5) * step * 0.4;
      const d = near(jx, jz);
      if (d < margin) continue;
      if (d > shoreline) continue;
      if (harbor && r() < 0.35) continue;
      const proto = Math.floor(r() * protos.length);
      // taller towers further away from the road, low blocks close by
      let sy = 0.6 + r() * 0.8;
      if (d < margin + 25) sy *= 0.55;
      if (harbor) sy *= 0.6;
      const col = T.buildingColors[Math.floor(r() * T.buildingColors.length)];
      placements.push([proto, jx, jz, Math.floor(r() * 4) * (Math.PI / 2), sy, col]);
    }
  }
  // Group placements into spatial chunks per prototype.
  const chunkSize = 380;
  const chunks = new Map();
  for (const p of placements) {
    const key = `${p[0]}_${Math.floor(p[1] / chunkSize)}_${Math.floor(p[2] / chunkSize)}`;
    if (!chunks.has(key)) chunks.set(key, []);
    chunks.get(key).push(p);
  }
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), v = new THREE.Vector3();
  const up = new THREE.Vector3(0, 1, 0);
  const col = new THREE.Color();
  for (const list of chunks.values()) {
    const im = new THREE.InstancedMesh(protos[list[0][0]], bMat, list.length);
    list.forEach((p, i) => {
      q.setFromAxisAngle(up, p[3]);
      s.set(1, p[4], 1);
      v.set(p[1], 0, p[2]);
      m.compose(v, q, s);
      im.setMatrixAt(i, m);
      im.setColorAt(i, col.set(p[5]));
    });
    im.computeBoundingSphere();
    group.add(im);
  }

  // --- Neon billboards beside the road --------------------------------------------
  const signs = [];
  const signCount = Math.round((path.length / 140) * (quality === 'low' ? 0.6 : 1));
  const postGeo = keep(new THREE.BoxGeometry(0.5, 7, 0.5));
  const postMat = keep(new THREE.MeshLambertMaterial({ color: 0x1b1c26 }));
  const panelGeo = keep(new THREE.BoxGeometry(12, 4.5, 0.3));
  const backMat = keep(new THREE.MeshLambertMaterial({ color: 0x14151f }));
  for (let k = 0; k < signCount; k++) {
    const sPos = ((k + 0.5) / signCount) * path.length;
    const f = path.frameAt(sPos);
    const side = k % 2 ? 1 : -1;
    const lat = side * (path.halfWidth + 9 + r() * 6);
    const px = f.x + f.rx * lat, pz = f.z + f.rz * lat;
    if (path.locate(px, pz).dist < path.halfWidth + 6) continue;
    const [word, sub] = SIGN_WORDS[Math.floor(r() * SIGN_WORDS.length)];
    const color = SIGN_COLORS[Math.floor(r() * SIGN_COLORS.length)];
    const mat = keep(new THREE.MeshBasicMaterial({ map: signTexture(word, color, sub) }));
    const g = new THREE.Group();
    g.position.set(px, 0, pz);
    // face the oncoming traffic, angled towards the road
    g.rotation.y = f.heading + Math.PI + side * 0.5;
    const post = new THREE.Mesh(postGeo, postMat);
    post.position.y = 3.5;
    // Box faces: +x, -x, +y, -y, +z (front), -z (back)
    const panel = new THREE.Mesh(panelGeo, [backMat, backMat, backMat, backMat, mat, backMat]);
    panel.position.y = 8.5;
    panel.userData.bloom = true;
    g.add(post, panel);
    group.add(g);
    signs.push({ mat, phase: r() * 10 });
  }

  // --- Palm trees (harbor) ------------------------------------------------------
  if (harbor) {
    const n = Math.round((path.length / 22) * density);
    const trunkGeo = keep(new THREE.CylinderGeometry(0.25, 0.4, 9, 6));
    trunkGeo.translate(0, 4.5, 0);
    const leafGeo = keep(new THREE.ConeGeometry(3.6, 2.2, 7));
    leafGeo.translate(0, 9.2, 0);
    const trunks = new THREE.InstancedMesh(trunkGeo, keep(new THREE.MeshLambertMaterial({ color: '#4a3226' })), n);
    const leaves = new THREE.InstancedMesh(leafGeo, keep(new THREE.MeshLambertMaterial({ color: '#2d5a3c' })), n);
    let placed = 0;
    for (let k = 0; k < n; k++) {
      const f = path.frameAt((k / n) * path.length + r() * 8);
      const side = r() < 0.5 ? -1 : 1;
      const lat = side * (path.halfWidth + 5 + r() * 5);
      const px = f.x + f.rx * lat, pz = f.z + f.rz * lat;
      if (path.locate(px, pz).dist < path.halfWidth + 4) continue;
      const sc = 0.8 + r() * 0.5;
      q.setFromAxisAngle(up, r() * 6.28);
      m.compose(v.set(px, 0, pz), q, s.set(sc, sc, sc));
      trunks.setMatrixAt(placed, m);
      leaves.setMatrixAt(placed, m);
      placed++;
    }
    trunks.count = leaves.count = placed;
    trunks.computeBoundingSphere();
    leaves.computeBoundingSphere();
    group.add(trunks, leaves);
  }

  let t = 0;
  return {
    group,
    sunLight: sun,
    theme: T,
    update(dt) {
      t += dt;
      // occasional neon flicker
      for (const sg of signs) {
        const f = Math.sin(t * 13 + sg.phase * 7) > 0.985 ? 0.35 : 1;
        sg.mat.color.setScalar(f);
      }
      if (water) water.material.map.offset.x = (t * 0.004) % 1;
    },
    dispose() {
      for (const d of disposables) d.dispose?.();
    },
  };
}
