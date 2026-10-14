// Pooled visual effects: tyre skid marks, smoke / sparks particles, nitro flames
// and speed lines. Every system pre-allocates its buffers once; nothing is
// created or garbage-collected while racing.

import * as THREE from 'three';
import { smokeTexture, glowTexture } from '../world/textures.js';

// ---------------------------------------------------------------------------
// Skid marks: a ring buffer of quads laid on the road.
export class SkidMarks {
  constructor(maxQuads = 1600) {
    this.max = maxQuads;
    this.next = 0;
    const pos = new Float32Array(maxQuads * 4 * 3);
    const alpha = new Float32Array(maxQuads * 4);
    const idx = new Uint32Array(maxQuads * 6);
    for (let i = 0; i < maxQuads; i++) {
      const v = i * 4;
      idx.set([v, v + 2, v + 1, v + 1, v + 2, v + 3], i * 6);
    }
    this.geo = new THREE.BufferGeometry();
    this.geo.setAttribute('position', new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
    this.geo.setAttribute('alpha', new THREE.BufferAttribute(alpha, 1).setUsage(THREE.DynamicDrawUsage));
    this.geo.setIndex(new THREE.BufferAttribute(idx, 1));
    this.mat = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -5,
      vertexShader: `attribute float alpha; varying float vA; void main(){ vA = alpha; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
      fragmentShader: `varying float vA; void main(){ gl_FragColor = vec4(0.02,0.02,0.03, vA); }`,
    });
    this.mesh = new THREE.Mesh(this.geo, this.mat);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = 1;
    this.dirty = false;
  }

  // Add a segment from (x0,z0) to (x1,z1) of the given width and strength 0..1.
  add(x0, z0, x1, z1, width, strength) {
    const dx = x1 - x0, dz = z1 - z0;
    const len = Math.hypot(dx, dz);
    if (len < 0.05 || len > 4) return;
    const nx = (-dz / len) * width * 0.5, nz = (dx / len) * width * 0.5;
    const i = this.next;
    this.next = (this.next + 1) % this.max;
    const p = this.geo.attributes.position.array;
    const y = 0.025;
    p.set([x0 - nx, y, z0 - nz, x0 + nx, y, z0 + nz, x1 - nx, y, z1 - nz, x1 + nx, y, z1 + nz], i * 12);
    const a = this.geo.attributes.alpha.array;
    const s = Math.min(0.55, strength * 0.55);
    a.set([s, s, s, s], i * 4);
    this.dirty = true;
  }

  update() {
    if (!this.dirty) return;
    this.geo.attributes.position.needsUpdate = true;
    this.geo.attributes.alpha.needsUpdate = true;
    this.dirty = false;
  }

  clear() {
    this.geo.attributes.alpha.array.fill(0);
    this.geo.attributes.alpha.needsUpdate = true;
  }

  dispose() {
    this.geo.dispose();
    this.mat.dispose();
  }
}

// ---------------------------------------------------------------------------
// Point-sprite particle pool with per-particle size, alpha and color.
export class Particles {
  constructor(max, { additive = false, texture = smokeTexture() } = {}) {
    this.max = max;
    this.pos = new Float32Array(max * 3);
    this.vel = new Float32Array(max * 3);
    this.col = new Float32Array(max * 3);
    this.size = new Float32Array(max);
    this.alpha = new Float32Array(max);
    this.life = new Float32Array(max);
    this.maxLife = new Float32Array(max);
    this.grow = new Float32Array(max);
    this.a0 = new Float32Array(max);
    this.next = 0;
    this.geo = new THREE.BufferGeometry();
    this.geo.setAttribute('position', new THREE.BufferAttribute(this.pos, 3).setUsage(THREE.DynamicDrawUsage));
    this.geo.setAttribute('color', new THREE.BufferAttribute(this.col, 3).setUsage(THREE.DynamicDrawUsage));
    this.geo.setAttribute('size', new THREE.BufferAttribute(this.size, 1).setUsage(THREE.DynamicDrawUsage));
    this.geo.setAttribute('alpha', new THREE.BufferAttribute(this.alpha, 1).setUsage(THREE.DynamicDrawUsage));
    this.mat = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending,
      uniforms: { map: { value: texture }, scale: { value: 400 } },
      vertexShader: `
        attribute float size; attribute float alpha; attribute vec3 color;
        varying float vA; varying vec3 vC; uniform float scale;
        void main(){
          vA = alpha; vC = color;
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          gl_PointSize = size * scale / max(0.1, -mv.z);
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: `
        uniform sampler2D map; varying float vA; varying vec3 vC;
        void main(){ vec4 t = texture2D(map, gl_PointCoord); gl_FragColor = vec4(vC * t.rgb, t.a * vA); if (gl_FragColor.a < 0.004) discard; }`,
    });
    this.points = new THREE.Points(this.geo, this.mat);
    this.points.frustumCulled = false;
    this.points.renderOrder = 3;
    this.active = 0;
  }

  emit(x, y, z, vx, vy, vz, size, life, r, g, b, alpha = 1, grow = 1.5) {
    const i = this.next;
    this.next = (this.next + 1) % this.max;
    this.pos.set([x, y, z], i * 3);
    this.vel.set([vx, vy, vz], i * 3);
    this.col.set([r, g, b], i * 3);
    this.size[i] = size;
    this.life[i] = life;
    this.maxLife[i] = life;
    this.grow[i] = grow;
    this.a0[i] = alpha;
    this.alpha[i] = alpha;
  }

  update(dt) {
    let active = 0;
    for (let i = 0; i < this.max; i++) {
      if (this.life[i] <= 0) {
        if (this.alpha[i] !== 0) this.alpha[i] = 0;
        continue;
      }
      active++;
      this.life[i] -= dt;
      const k = i * 3;
      this.pos[k] += this.vel[k] * dt;
      this.pos[k + 1] += this.vel[k + 1] * dt;
      this.pos[k + 2] += this.vel[k + 2] * dt;
      const damp = Math.exp(-2 * dt);
      this.vel[k] *= damp;
      this.vel[k + 2] *= damp;
      this.size[i] += this.grow[i] * dt;
      const t = Math.max(0, this.life[i] / this.maxLife[i]);
      this.alpha[i] = this.a0[i] * t * t;
    }
    this.active = active;
    const a = this.geo.attributes;
    a.position.needsUpdate = a.size.needsUpdate = a.alpha.needsUpdate = a.color.needsUpdate = true;
  }

  clear() {
    this.life.fill(0);
    this.alpha.fill(0);
  }

  dispose() {
    this.geo.dispose();
    this.mat.dispose();
  }
}

// ---------------------------------------------------------------------------
// Nitro exhaust flames attached to a car model.
const flameGeo = (() => {
  const g = new THREE.ConeGeometry(0.16, 1.4, 10, 1, true);
  g.rotateX(-Math.PI / 2); // point backwards (-Z)
  g.translate(0, 0, -0.7);
  return g;
})();

export function attachFlames(model) {
  const outer = new THREE.MeshBasicMaterial({ color: '#4fc3ff', transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false });
  const inner = new THREE.MeshBasicMaterial({ color: '#ffffff', transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false });
  const flames = [];
  for (const p of model.exhausts) {
    const o = new THREE.Mesh(flameGeo, outer);
    const i = new THREE.Mesh(flameGeo, inner);
    i.scale.set(0.5, 0.5, 0.6);
    o.position.copy(p);
    i.position.copy(p);
    o.visible = i.visible = false;
    o.userData.bloom = i.userData.bloom = true;
    model.body.add(o, i);
    flames.push(o, i);
  }
  return {
    update(active, t) {
      for (let k = 0; k < flames.length; k++) {
        const f = flames[k];
        f.visible = active;
        if (active) {
          const s = 0.8 + Math.sin(t * 60 + k * 1.7) * 0.15 + Math.random() * 0.15;
          f.scale.z = (k % 2 ? 0.6 : 1) * s * 1.3;
        }
      }
    },
    dispose() {
      outer.dispose();
      inner.dispose();
    },
  };
}

// ---------------------------------------------------------------------------
// Speed lines streaming past the camera at high speed / nitro.
export class SpeedLines {
  constructor(count = 70) {
    this.count = count;
    const geo = new THREE.BoxGeometry(0.025, 0.025, 7);
    this.mat = new THREE.MeshBasicMaterial({ color: '#cfefff', transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, fog: false });
    this.mesh = new THREE.InstancedMesh(geo, this.mat, count);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = 5;
    this.state = [];
    for (let i = 0; i < count; i++) this.state.push(this.spawn({}, true));
    this.m = new THREE.Matrix4();
  }

  spawn(s, initial) {
    const a = Math.random() * Math.PI * 2;
    const r = 2.6 + Math.random() * 5;
    s.x = Math.cos(a) * r;
    s.y = Math.sin(a) * r * 0.6;
    s.z = initial ? -Math.random() * 60 : -60 - Math.random() * 10;
    return s;
  }

  update(dt, intensity, speed) {
    this.mat.opacity += (intensity * 0.32 - this.mat.opacity) * Math.min(1, dt * 6);
    this.mesh.visible = this.mat.opacity > 0.01;
    if (!this.mesh.visible) return;
    const v = 40 + speed * 2.2;
    for (let i = 0; i < this.count; i++) {
      const s = this.state[i];
      s.z += v * dt;
      if (s.z > 4) this.spawn(s, false);
      this.m.makeTranslation(s.x, s.y, s.z);
      this.mesh.setMatrixAt(i, this.m);
    }
    this.mesh.instanceMatrix.needsUpdate = true;
  }

  dispose() {
    this.mesh.geometry.dispose();
    this.mat.dispose();
  }
}

export { glowTexture };
