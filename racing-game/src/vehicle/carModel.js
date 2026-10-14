// Procedural stylized car models. Bodies are side profiles extruded across the
// car's width (with bevels), so each car class gets a distinct silhouette from a
// handful of numbers. Draw calls are kept low: paint, glass, trim+lights
// (vertex colors) and one mesh per wheel.

import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { glowTexture } from '../world/textures.js';

// Side profiles: [x along length (-0.5 rear .. 0.5 front), y height (0..1)] normalised.
const PROFILES = {
  coupe: {
    body: [[-0.5, 0.22], [-0.5, 0.62], [-0.44, 0.7], [0.18, 0.7], [0.46, 0.55], [0.5, 0.42], [0.5, 0.22], [0.36, 0.18], [-0.36, 0.18]],
    cabin: [[-0.36, 0.68], [-0.22, 1.0], [0.06, 1.0], [0.26, 0.68]],
    cabinW: 0.78,
  },
  hatch: {
    body: [[-0.5, 0.22], [-0.5, 0.66], [-0.46, 0.7], [0.14, 0.7], [0.44, 0.58], [0.5, 0.45], [0.5, 0.22], [0.34, 0.18], [-0.34, 0.18]],
    cabin: [[-0.48, 0.68], [-0.42, 1.0], [0.04, 1.0], [0.26, 0.68]],
    cabinW: 0.82,
  },
  muscle: {
    body: [[-0.5, 0.24], [-0.5, 0.66], [-0.46, 0.7], [0.1, 0.72], [0.44, 0.66], [0.5, 0.55], [0.5, 0.24], [0.36, 0.2], [-0.36, 0.2]],
    cabin: [[-0.3, 0.7], [-0.14, 0.98], [0.04, 0.98], [0.18, 0.7]],
    cabinW: 0.76,
  },
  wedge: {
    body: [[-0.5, 0.24], [-0.5, 0.66], [-0.4, 0.7], [0.1, 0.66], [0.5, 0.36], [0.5, 0.24], [0.36, 0.18], [-0.36, 0.18]],
    cabin: [[-0.28, 0.66], [-0.1, 1.0], [0.06, 1.0], [0.3, 0.6]],
    cabinW: 0.7,
  },
};

function extrudeProfile(points, length, height, width, bevel) {
  const shape = new THREE.Shape();
  points.forEach(([x, y], i) => {
    const px = x * length, py = y * height;
    if (i === 0) shape.moveTo(px, py);
    else shape.lineTo(px, py);
  });
  shape.closePath();
  const g = new THREE.ExtrudeGeometry(shape, {
    depth: width - bevel * 2, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel * 0.8, bevelSegments: 2, curveSegments: 1,
  });
  g.translate(0, 0, -(width - bevel * 2) / 2);
  // Shape X is the car's length; rotate so length runs along +Z (forward).
  g.rotateY(-Math.PI / 2);
  return g;
}

function colorize(geo, color) {
  const c = new THREE.Color(color);
  const n = geo.attributes.position.count;
  const arr = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) arr.set([c.r, c.g, c.b], i * 3);
  geo.setAttribute('color', new THREE.BufferAttribute(arr, 3));
  if (geo.index) geo = geo.toNonIndexed();
  return geo;
}

function box(w, h, d, x, y, z, color) {
  const g = new THREE.BoxGeometry(w, h, d);
  g.translate(x, y, z);
  return colorize(g, color);
}

function wheelGeometry(radius, width, rim) {
  const parts = [];
  const tire = new THREE.CylinderGeometry(radius, radius, width, 18, 1);
  tire.rotateZ(Math.PI / 2);
  parts.push(colorize(tire, '#141418'));
  const rimR = radius * 0.66;
  const rimColor = rim === 'mesh' ? '#d9e4ff' : rim === 'disc' ? '#9aa3b5' : '#c7ccd6';
  const face = new THREE.CylinderGeometry(rimR, rimR, width + 0.02, 16, 1);
  face.rotateZ(Math.PI / 2);
  parts.push(colorize(face, rim === 'disc' ? '#9aa3b5' : '#2a2d36'));
  if (rim === 'spoke' || rim === 'mesh') {
    const n = rim === 'spoke' ? 5 : 8;
    for (let i = 0; i < n; i++) {
      const sp = new THREE.BoxGeometry(width + 0.04, rimR * 1.9, rim === 'spoke' ? 0.07 : 0.035);
      sp.rotateX((i / n) * Math.PI);
      parts.push(colorize(sp, rimColor));
    }
  }
  const hub = new THREE.CylinderGeometry(rimR * 0.25, rimR * 0.25, width + 0.06, 8);
  hub.rotateZ(Math.PI / 2);
  parts.push(colorize(hub, '#e6e6e6'));
  return mergeGeometries(parts.map((p) => (p.index ? p.toNonIndexed() : p)));
}

const sharedMats = {};
function mats(quality) {
  const key = quality === 'low' ? 'low' : 'std';
  if (!sharedMats[key]) {
    const VC = quality === 'low' ? THREE.MeshLambertMaterial : THREE.MeshStandardMaterial;
    sharedMats[key] = {
      glass: quality === 'low'
        ? new THREE.MeshLambertMaterial({ color: '#0b1020', emissive: '#0a1430' })
        : new THREE.MeshStandardMaterial({ color: '#0a0e1c', metalness: 0.9, roughness: 0.08, envMapIntensity: 1.4 }),
      trim: quality === 'low'
        ? new THREE.MeshLambertMaterial({ vertexColors: true })
        : new VC({ vertexColors: true, metalness: 0.3, roughness: 0.6 }),
      lights: new THREE.MeshBasicMaterial({ vertexColors: true }),
      wheel: new THREE.MeshLambertMaterial({ vertexColors: true }),
    };
  }
  return sharedMats[key];
}

/**
 * Build a car. Returns { root, body, wheels[], exhausts[], glow, setPaint, setGlow, dispose }.
 * `root` is positioned/rotated by the game; `body` carries roll/pitch.
 */
export function buildCarModel(def, opts = {}) {
  const quality = opts.quality || 'medium';
  const B = def.body;
  const prof = PROFILES[B.profile] || PROFILES.coupe;
  const L = B.length, W = B.width, H = B.height;
  const M = mats(quality);
  const root = new THREE.Group();
  const body = new THREE.Group();
  root.add(body);

  const paint = quality === 'low'
    ? new THREE.MeshLambertMaterial({ color: opts.paint || B.defaultColor })
    : new THREE.MeshStandardMaterial({ color: opts.paint || B.defaultColor, metalness: 0.55, roughness: 0.32, envMapIntensity: 1.2 });

  // Main body shell + cabin.
  const shell = extrudeProfile(prof.body, L, H, W, 0.08);
  const shellMesh = new THREE.Mesh(shell, paint);
  shellMesh.castShadow = true;
  body.add(shellMesh);
  const cabin = extrudeProfile(prof.cabin, L, H, W * prof.cabinW, 0.06);
  const cabinMesh = new THREE.Mesh(cabin, M.glass);
  body.add(cabinMesh);
  // Roof panel in paint color on top of the glass cabin.
  const roofTopY = H * 1.0;
  const roofZ0 = prof.cabin[1][0] * L, roofZ1 = prof.cabin[2][0] * L;
  const roof = new THREE.Mesh(new THREE.BoxGeometry(W * prof.cabinW * 0.92, 0.05, Math.abs(roofZ1 - roofZ0) * 0.95), paint);
  roof.position.set(0, roofTopY + 0.035, (roofZ0 + roofZ1) / 2);
  body.add(roof);

  // Trim (bumpers, skirts, grille, spoiler) – merged, vertex colored.
  const trimParts = [];
  const dark = '#15161c';
  trimParts.push(box(W * 0.98, 0.16, 0.25, 0, H * 0.24, L * 0.5 + 0.03, dark)); // front splitter
  trimParts.push(box(W * 0.98, 0.2, 0.22, 0, H * 0.26, -L * 0.5 - 0.02, dark)); // rear diffuser
  trimParts.push(box(0.08, 0.14, L * 0.62, W * 0.5 + 0.01, H * 0.24, 0, dark)); // skirts
  trimParts.push(box(0.08, 0.14, L * 0.62, -W * 0.5 - 0.01, H * 0.24, 0, dark));
  trimParts.push(box(W * 0.5, H * 0.12, 0.05, 0, H * 0.36, L * 0.5 + 0.005, '#0b0b10')); // grille
  if (B.spoiler === 'wing') {
    trimParts.push(box(W * 0.95, 0.06, 0.38, 0, H * 0.98, -L * 0.45, dark));
    trimParts.push(box(0.06, H * 0.3, 0.2, W * 0.32, H * 0.82, -L * 0.45, dark));
    trimParts.push(box(0.06, H * 0.3, 0.2, -W * 0.32, H * 0.82, -L * 0.45, dark));
  } else if (B.spoiler === 'duck') {
    trimParts.push(box(W * 0.9, 0.08, 0.3, 0, H * 0.72, -L * 0.47, dark));
  } else if (B.spoiler === 'roof') {
    trimParts.push(box(W * 0.72, 0.06, 0.3, 0, H * 1.02, prof.cabin[0][0] * L + 0.05, dark));
  } else {
    trimParts.push(box(W * 0.85, 0.05, 0.12, 0, H * 0.72, -L * 0.49, dark));
  }
  const trim = new THREE.Mesh(mergeGeometries(trimParts), M.trim);
  body.add(trim);

  // Lights (emissive, vertex colored): headlights, taillight bar.
  const lightParts = [];
  const frontY = H * 0.5;
  lightParts.push(box(W * 0.26, 0.09, 0.06, W * 0.3, frontY, L * 0.5 - 0.0, '#f4fbff'));
  lightParts.push(box(W * 0.26, 0.09, 0.06, -W * 0.3, frontY, L * 0.5 - 0.0, '#f4fbff'));
  lightParts.push(box(W * 0.9, 0.08, 0.05, 0, H * 0.6, -L * 0.5 - 0.02, '#ff1638'));
  const lights = new THREE.Mesh(mergeGeometries(lightParts), M.lights);
  lights.userData.bloom = true;
  body.add(lights);

  // Wheels.
  const wr = B.wheelR;
  const wGeo = wheelGeometry(wr, 0.28, opts.rim || 'spoke');
  const wheels = [];
  const wx = W * 0.5 - 0.12, wzF = L * 0.32, wzR = -L * 0.33;
  for (const [x, z, front] of [[wx, wzF, true], [-wx, wzF, true], [wx, wzR, false], [-wx, wzR, false]]) {
    const pivot = new THREE.Group();
    pivot.position.set(x, wr, z);
    const wm = new THREE.Mesh(wGeo, M.wheel);
    pivot.add(wm);
    root.add(pivot);
    wheels.push({ pivot, mesh: wm, front });
  }

  // Underglow.
  const glowMat = new THREE.MeshBasicMaterial({
    map: glowTexture(), color: opts.glow || B.glow, transparent: true, opacity: 0.85,
    blending: THREE.AdditiveBlending, depthWrite: false,
  });
  const glow = new THREE.Mesh(new THREE.PlaneGeometry(W * 2.1, L * 1.5), glowMat);
  glow.rotation.x = -Math.PI / 2;
  glow.position.y = 0.04;
  glow.renderOrder = 2;
  root.add(glow);
  glow.visible = (opts.glow || B.glow) !== 'off';

  // Exhaust anchor points (for nitro flames).
  const exhausts = [new THREE.Vector3(W * 0.25, H * 0.3, -L * 0.5 - 0.1), new THREE.Vector3(-W * 0.25, H * 0.3, -L * 0.5 - 0.1)];

  body.position.y = 0.05;
  root.traverse((o) => {
    if (o.isMesh && o !== glow) o.castShadow = true;
  });

  return {
    root,
    body,
    wheels,
    exhausts,
    glow,
    paint,
    setPaint(color) {
      paint.color.set(color);
    },
    setGlow(color) {
      glow.visible = color !== 'off';
      if (color !== 'off') glowMat.color.set(color);
    },
    setOpacity(o) {
      root.traverse((m) => {
        if (m.isMesh && m !== glow) {
          m.material = m.material.clone();
          m.material.transparent = true;
          m.material.opacity = o;
          m.material.depthWrite = false;
          m.castShadow = false;
        }
      });
    },
    dispose() {
      shell.dispose();
      cabin.dispose();
      roof.geometry.dispose();
      trim.geometry.dispose();
      lights.geometry.dispose();
      wGeo.dispose();
      glow.geometry.dispose();
      glowMat.dispose();
      paint.dispose();
    },
  };
}

/** Sync a model with a simulated car (with render interpolation alpha). */
export function syncCarModel(model, car, alpha) {
  const x = car.prevX + (car.x - car.prevX) * alpha;
  const z = car.prevZ + (car.z - car.prevZ) * alpha;
  let dy = car.yaw - car.prevYaw;
  dy = Math.atan2(Math.sin(dy), Math.cos(dy));
  const yaw = car.prevYaw + dy * alpha;
  model.root.position.set(x, 0, z);
  model.root.rotation.y = yaw;
  model.body.rotation.z = -car.roll;
  model.body.rotation.x = car.pitch;
  const steerAngle = car.steer * 0.42;
  for (const w of model.wheels) {
    w.mesh.rotation.x = car.wheelSpin;
    if (w.front) w.pivot.rotation.y = -steerAngle;
  }
}
