// Procedurally painted canvas textures. Everything visual in the game is generated
// at runtime: no external image assets, no licensing questions, tiny download.

import * as THREE from 'three';
import { rng } from '../core/util.js';

function canvas(w, h) {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  return [c, c.getContext('2d')];
}

function toTexture(c, { repeat = false, srgb = true, aniso = 4 } = {}) {
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  if (repeat) t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = aniso;
  t.needsUpdate = true;
  return t;
}

const cache = new Map();
function cached(key, fn) {
  if (!cache.has(key)) cache.set(key, fn());
  return cache.get(key);
}

// Asphalt with lane markings. u = across road (0..1), v = along road (repeats).
export function roadTexture(lanes = 4, theme = 'night') {
  return cached(`road${lanes}${theme}`, () => {
    const [c, g] = canvas(512, 512);
    const base = theme === 'night' ? [34, 36, 46] : [58, 56, 60];
    g.fillStyle = `rgb(${base.join(',')})`;
    g.fillRect(0, 0, 512, 512);
    const r = rng(9);
    for (let i = 0; i < 9000; i++) {
      const v = (r() - 0.5) * 22;
      g.fillStyle = `rgba(${base[0] + v},${base[1] + v},${base[2] + v + 2},0.6)`;
      g.fillRect(r() * 512, r() * 512, 2, 2);
    }
    // subtle tyre-worn racing line
    const grd = g.createLinearGradient(0, 0, 512, 0);
    grd.addColorStop(0.3, 'rgba(0,0,0,0)');
    grd.addColorStop(0.5, 'rgba(0,0,0,0.12)');
    grd.addColorStop(0.7, 'rgba(0,0,0,0)');
    g.fillStyle = grd;
    g.fillRect(0, 0, 512, 512);
    // edge lines
    g.fillStyle = theme === 'night' ? '#e8e8f0' : '#f2efe6';
    g.fillRect(14, 0, 10, 512);
    g.fillRect(512 - 24, 0, 10, 512);
    // dashed lane dividers
    g.fillStyle = theme === 'night' ? 'rgba(230,230,240,0.85)' : 'rgba(255,214,90,0.9)';
    for (let l = 1; l < lanes; l++) {
      const x = (512 * l) / lanes;
      for (let y = 0; y < 512; y += 128) g.fillRect(x - 4, y + 20, 8, 70);
    }
    return toTexture(c, { repeat: true, aniso: 8 });
  });
}

export function kerbTexture() {
  return cached('kerb', () => {
    const [c, g] = canvas(64, 128);
    for (let i = 0; i < 4; i++) {
      g.fillStyle = i % 2 ? '#f4f4f4' : '#e0223a';
      g.fillRect(0, i * 32, 64, 32);
    }
    return toTexture(c, { repeat: true });
  });
}

export function checkerTexture() {
  return cached('checker', () => {
    const [c, g] = canvas(256, 64);
    const n = 16;
    for (let x = 0; x < n; x++)
      for (let y = 0; y < 4; y++) {
        g.fillStyle = (x + y) % 2 ? '#111' : '#f5f5f5';
        g.fillRect((x * 256) / n, y * 16, 256 / n, 16);
      }
    return toTexture(c);
  });
}

// Radial soft glow used for light pools, underglow, particles.
export function glowTexture() {
  return cached('glow', () => {
    const [c, g] = canvas(128, 128);
    const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grd.addColorStop(0, 'rgba(255,255,255,1)');
    grd.addColorStop(0.35, 'rgba(255,255,255,0.45)');
    grd.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grd;
    g.fillRect(0, 0, 128, 128);
    return toTexture(c, { srgb: false });
  });
}

export function smokeTexture() {
  return cached('smoke', () => {
    const [c, g] = canvas(128, 128);
    const r = rng(3);
    for (let i = 0; i < 18; i++) {
      const x = 40 + r() * 48, y = 40 + r() * 48, rad = 18 + r() * 30;
      const grd = g.createRadialGradient(x, y, 0, x, y, rad);
      grd.addColorStop(0, 'rgba(255,255,255,0.22)');
      grd.addColorStop(1, 'rgba(255,255,255,0)');
      g.fillStyle = grd;
      g.fillRect(0, 0, 128, 128);
    }
    return toTexture(c, { srgb: false });
  });
}

// Building facade: grid of windows. Bottom-left 8x8 px block is solid dark (used for roofs).
export function windowTexture(theme) {
  return cached(`win${theme}`, () => {
    const [c, g] = canvas(256, 256);
    g.fillStyle = '#000';
    g.fillRect(0, 0, 256, 256);
    const r = rng(theme === 'night' ? 21 : 22);
    const cols = 8, rows = 16;
    const palette = theme === 'night'
      ? ['#ffd59a', '#9fe8ff', '#ffffff', '#ff9ad5', '#ffe9b0']
      : ['#ffcf8a', '#ffe6bf', '#fff1d6'];
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < cols; x++) {
        const lit = r() < (theme === 'night' ? 0.42 : 0.22);
        const px = x * 32 + 6, py = y * 16 + 4;
        if (lit) {
          g.fillStyle = palette[Math.floor(r() * palette.length)];
          g.globalAlpha = 0.55 + r() * 0.45;
        } else {
          g.fillStyle = '#1b2233';
          g.globalAlpha = 1;
        }
        g.fillRect(px, py, 20, 9);
      }
    }
    g.globalAlpha = 1;
    g.fillStyle = '#000';
    g.fillRect(0, 248, 8, 8);
    return toTexture(c, { repeat: true });
  });
}

// Panoramic distant skyline silhouette (transparent background).
export function skylineTexture(theme) {
  return cached(`sky${theme}`, () => {
    const [c, g] = canvas(2048, 256);
    const r = rng(77);
    const night = theme === 'night';
    let x = 0;
    while (x < 2048) {
      const w = 20 + r() * 60;
      const h = 40 + r() * 180 * (r() < 0.15 ? 1.2 : 0.7);
      g.fillStyle = night ? `rgb(${12 + r() * 14},${14 + r() * 14},${34 + r() * 20})` : `rgb(${70 + r() * 20},${50 + r() * 15},${80 + r() * 20})`;
      g.fillRect(x, 256 - h, w, h);
      // windows
      for (let wy = 256 - h + 6; wy < 250; wy += 8)
        for (let wx = x + 3; wx < x + w - 4; wx += 6)
          if (r() < (night ? 0.18 : 0.06)) {
            g.fillStyle = night ? (r() < 0.5 ? '#ffcf7a' : '#7fe0ff') : '#ffd9a0';
            g.fillRect(wx, wy, 2, 3);
          }
      if (night && r() < 0.08) {
        g.fillStyle = r() < 0.5 ? '#ff2fd0' : '#00e5ff';
        g.fillRect(x + 2, 256 - h - 3, w - 4, 3);
      }
      x += w + r() * 6;
    }
    const t = toTexture(c, { repeat: true });
    t.wrapT = THREE.ClampToEdgeWrapping;
    return t;
  });
}

// Neon sign with invented names (no real brands).
export function signTexture(text, color, sub = '') {
  return cached(`sign${text}${color}${sub}`, () => {
    const [c, g] = canvas(512, 192);
    g.fillStyle = 'rgba(6,6,16,0.92)';
    g.fillRect(0, 0, 512, 192);
    g.strokeStyle = color;
    g.lineWidth = 8;
    g.shadowColor = color;
    g.shadowBlur = 24;
    g.strokeRect(12, 12, 488, 168);
    g.font = 'italic 900 92px "Segoe UI", Arial, sans-serif';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillStyle = '#fff';
    g.fillText(text, 256, sub ? 82 : 98);
    g.shadowBlur = 0;
    g.fillStyle = color;
    g.globalAlpha = 0.25;
    g.fillText(text, 256, sub ? 82 : 98);
    g.globalAlpha = 1;
    if (sub) {
      g.font = '600 30px "Segoe UI", Arial, sans-serif';
      g.fillStyle = color;
      g.fillText(sub, 256, 150);
    }
    return toTexture(c);
  });
}

export function groundTexture(theme) {
  return cached(`ground${theme}`, () => {
    const [c, g] = canvas(256, 256);
    const night = theme === 'night';
    g.fillStyle = night ? '#121424' : '#3a3438';
    g.fillRect(0, 0, 256, 256);
    const r = rng(5);
    for (let i = 0; i < 2500; i++) {
      const v = r() * 18;
      g.fillStyle = night ? `rgba(${30 + v},${32 + v},${55 + v},0.35)` : `rgba(${80 + v},${70 + v},${70 + v},0.35)`;
      g.fillRect(r() * 256, r() * 256, 3, 3);
    }
    g.strokeStyle = night ? 'rgba(80,90,170,0.35)' : 'rgba(120,100,100,0.3)';
    g.lineWidth = 2;
    g.strokeRect(0, 0, 256, 256);
    return toTexture(c, { repeat: true });
  });
}

export function tunnelTexture() {
  return cached('tunnel', () => {
    const [c, g] = canvas(128, 128);
    g.fillStyle = '#2a2d3a';
    g.fillRect(0, 0, 128, 128);
    g.fillStyle = '#343848';
    for (let y = 0; y < 128; y += 32) g.fillRect(0, y, 128, 28);
    g.fillStyle = '#ffb347';
    g.fillRect(0, 100, 128, 6);
    return toTexture(c, { repeat: true });
  });
}

export function waterTexture() {
  return cached('water', () => {
    const [c, g] = canvas(256, 256);
    g.fillStyle = '#1c2a4a';
    g.fillRect(0, 0, 256, 256);
    const r = rng(11);
    for (let i = 0; i < 400; i++) {
      g.fillStyle = `rgba(255,${150 + r() * 80},${120 + r() * 60},${0.08 + r() * 0.2})`;
      g.fillRect(r() * 256, r() * 256, 6 + r() * 20, 1.5);
    }
    return toTexture(c, { repeat: true });
  });
}

// Wide gantry banner (aspect ~18:1).
export function bannerTexture(text, color) {
  return cached(`banner${text}${color}`, () => {
    const [c, g] = canvas(1024, 64);
    g.fillStyle = '#07060f';
    g.fillRect(0, 0, 1024, 64);
    g.fillStyle = color;
    g.fillRect(0, 0, 1024, 5);
    g.fillRect(0, 59, 1024, 5);
    g.font = 'italic 900 40px "Segoe UI", Arial, sans-serif';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.shadowColor = color;
    g.shadowBlur = 14;
    g.fillStyle = '#ffffff';
    g.fillText(text, 512, 34);
    // checker ends
    for (let x = 0; x < 6; x++) for (let y = 0; y < 3; y++) {
      g.fillStyle = (x + y) % 2 ? '#111' : '#eee';
      g.fillRect(8 + x * 14, 11 + y * 14, 14, 14);
      g.fillRect(1024 - 92 + x * 14, 11 + y * 14, 14, 14);
    }
    return toTexture(c);
  });
}
