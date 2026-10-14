// Settings + save game. Stored locally (localStorage; in the Windows build this
// lives in the app's user-data folder). No accounts, no network, no telemetry.

import { CARS } from '../data/cars.js';

const SETTINGS_KEY = 'neonrush.settings.v1';
const SAVE_KEY = 'neonrush.save.v1';

export const QUALITY_PRESETS = {
  low: { pixelRatio: 0.75, shadows: false, bloom: false, antialias: false, particles: 0.5, drawDistance: 600 },
  medium: { pixelRatio: 1.0, shadows: false, bloom: false, antialias: true, particles: 1, drawDistance: 900 },
  high: { pixelRatio: 1.5, shadows: true, bloom: true, antialias: true, particles: 1, drawDistance: 1600 },
};

export const DEFAULT_SETTINGS = {
  quality: 'medium',
  renderScale: 1,
  resolution: '1280x720',
  fullscreen: false,
  cameraShake: 1,
  speedEffects: true,
  fov: 64,
  units: 'kmh',
  showFps: false,
  masterVolume: 0.8,
  musicVolume: 0.45,
  sfxVolume: 0.9,
  difficulty: 'normal',
  cameraView: 0,
};

function read(key) {
  try {
    const s = localStorage.getItem(key);
    return s ? JSON.parse(s) : null;
  } catch {
    return null;
  }
}

function write(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function loadSettings() {
  return { ...DEFAULT_SETTINGS, ...(read(SETTINGS_KEY) || {}) };
}

export function saveSettings(s) {
  write(SETTINGS_KEY, s);
}

export function defaultSave() {
  const cars = {};
  for (const c of CARS) cars[c.id] = { paint: c.body.defaultColor, glow: c.body.glow, rim: 'spoke', upgrades: { engine: 0, grip: 0, nitro: 0 } };
  return {
    version: 1,
    credits: 1000,
    owned: CARS.filter((c) => c.price === 0).map((c) => c.id),
    ownedRims: ['spoke'],
    selectedCar: 'vapor',
    cars,
    best: {}, // `${track}:${mode}` -> { lap, total, position, drift }
    ghosts: {}, // track -> { car, lap, frames: [x,z,yaw,...] at 20 Hz }
    stats: { races: 0, wins: 0, podiums: 0, driftTotal: 0, distance: 0 },
  };
}

export function loadSave() {
  const s = read(SAVE_KEY);
  const d = defaultSave();
  if (!s || s.version !== 1) return d;
  // merge to pick up cars added in later versions
  const merged = { ...d, ...s, cars: { ...d.cars, ...s.cars }, stats: { ...d.stats, ...s.stats } };
  for (const id of Object.keys(d.cars)) merged.cars[id] = { ...d.cars[id], ...merged.cars[id], upgrades: { ...d.cars[id].upgrades, ...(merged.cars[id]?.upgrades || {}) } };
  return merged;
}

export function storeSave(save) {
  if (!write(SAVE_KEY, save)) {
    // Quota trouble: ghosts are the only large thing, drop them and retry.
    save.ghosts = {};
    write(SAVE_KEY, save);
  }
}

export function resetSave() {
  const d = defaultSave();
  storeSave(d);
  return d;
}
