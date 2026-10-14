// Car catalogue. All cars, names and designs are original to this project.
// `physics` values feed CarPhysics directly; `rating` is the 1-10 UI summary.
// Adding a car = adding an entry here (the model is generated from `body`).

export const CARS = [
  {
    id: 'vapor',
    name: 'VAPOR GT',
    class: 'Street Coupe',
    blurb: 'Balanced all-rounder. Forgiving grip, easy drifts.',
    price: 0,
    rating: { speed: 6, accel: 6, handling: 7, drift: 7, nitro: 6 },
    physics: {
      topSpeed: 64, // m/s (~230 km/h)
      accel: 11.5,
      brake: 32,
      maxTurn: 2.35, // rad/s at low speed
      grip: 9.5,
      driftGrip: 1.7,
      driftSteer: 1.35,
      mass: 1.0,
      nitroCap: 100,
      nitroAccel: 11,
      nitroTop: 1.22,
      nitroCharge: 26, // per second while drifting
    },
    body: {
      length: 4.4, width: 1.95, height: 1.18,
      profile: 'coupe', spoiler: 'lip', wheelR: 0.36,
      defaultColor: '#19c6ff', glow: '#00e5ff',
    },
  },
  {
    id: 'kite',
    name: 'KITE R',
    class: 'Hot Hatch',
    blurb: 'Light and twitchy. Turns on a dime and loves to slide.',
    price: 0,
    rating: { speed: 5, accel: 7, handling: 9, drift: 9, nitro: 5 },
    physics: {
      topSpeed: 59,
      accel: 12.5,
      brake: 34,
      maxTurn: 2.7,
      grip: 11,
      driftGrip: 1.9,
      driftSteer: 1.45,
      mass: 0.85,
      nitroCap: 90,
      nitroAccel: 10,
      nitroTop: 1.2,
      nitroCharge: 32,
    },
    body: {
      length: 4.0, width: 1.85, height: 1.3,
      profile: 'hatch', spoiler: 'roof', wheelR: 0.34,
      defaultColor: '#ff3d8b', glow: '#ff2fd0',
    },
  },
  {
    id: 'bulwark',
    name: 'BULWARK V8',
    class: 'Muscle',
    blurb: 'Brutal straight-line pace and a huge nitro tank. Heavy in corners.',
    price: 8000,
    rating: { speed: 8, accel: 7, handling: 5, drift: 6, nitro: 9 },
    physics: {
      topSpeed: 69,
      accel: 12.4,
      brake: 30,
      maxTurn: 2.1,
      grip: 8,
      driftGrip: 1.5,
      driftSteer: 1.3,
      mass: 1.3,
      nitroCap: 130,
      nitroAccel: 12.5,
      nitroTop: 1.24,
      nitroCharge: 24,
    },
    body: {
      length: 4.7, width: 2.05, height: 1.25,
      profile: 'muscle', spoiler: 'duck', wheelR: 0.39,
      defaultColor: '#ff8a1f', glow: '#ffb300',
    },
  },
  {
    id: 'phantom',
    name: 'PHANTOM X',
    class: 'Hypercar',
    blurb: 'Top of the food chain. Fast everywhere, demands a light touch.',
    price: 20000,
    rating: { speed: 10, accel: 9, handling: 8, drift: 7, nitro: 8 },
    physics: {
      topSpeed: 75,
      accel: 14,
      brake: 36,
      maxTurn: 2.4,
      grip: 10.5,
      driftGrip: 1.7,
      driftSteer: 1.35,
      mass: 1.05,
      nitroCap: 110,
      nitroAccel: 12,
      nitroTop: 1.22,
      nitroCharge: 26,
    },
    body: {
      length: 4.6, width: 2.0, height: 1.05,
      profile: 'wedge', spoiler: 'wing', wheelR: 0.37,
      defaultColor: '#a46bff', glow: '#7c4dff',
    },
  },
];

export const PAINTS = [
  '#19c6ff', '#ff3d8b', '#ff8a1f', '#a46bff', '#2ee59d', '#f5f5f5',
  '#ffd23f', '#e53935', '#1a1a2e', '#00bfa5', '#7a8cff', '#c0c7d0',
];

export const GLOWS = ['#00e5ff', '#ff2fd0', '#ffb300', '#7c4dff', '#39ff14', '#ffffff', 'off'];

export const RIMS = [
  { id: 'spoke', name: 'Five Spoke', price: 0 },
  { id: 'disc', name: 'Aero Disc', price: 600 },
  { id: 'mesh', name: 'Neon Mesh', price: 1200 },
];

// Performance upgrades: level 0..3. Effects are multiplicative on base physics.
export const UPGRADES = {
  engine: { name: 'Engine', desc: 'Top speed & acceleration', cost: [1500, 3000, 5500] },
  grip: { name: 'Tyres & Suspension', desc: 'Grip & steering response', cost: [1200, 2500, 4500] },
  nitro: { name: 'Nitro System', desc: 'Tank size & recharge', cost: [1000, 2200, 4000] },
};

export function carById(id) {
  return CARS.find((c) => c.id === id) || CARS[0];
}

// Physics parameters for a car with the player's upgrade levels applied.
export function tunedPhysics(car, upgrades = {}) {
  const p = { ...car.physics };
  const e = upgrades.engine || 0;
  const g = upgrades.grip || 0;
  const n = upgrades.nitro || 0;
  p.topSpeed *= 1 + 0.035 * e;
  p.accel *= 1 + 0.06 * e;
  p.grip *= 1 + 0.06 * g;
  p.maxTurn *= 1 + 0.035 * g;
  p.nitroCap *= 1 + 0.15 * n;
  p.nitroCharge *= 1 + 0.1 * n;
  return p;
}
