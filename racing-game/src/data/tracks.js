// Track catalogue. Each track is a closed loop of control points (x, z in meters).
// The spline/sampling lives in world/trackPath.js; visual theme in world/scenery.js.
// `reverse` variants reuse the same layout driven the other way (no extra assets).

const DOWNTOWN = [
  [0, -150], [0, 40], [6, 150], [30, 225], [95, 262],
  [200, 262], [258, 225], [272, 145], [240, 88], [165, 66],
  [118, 34], [128, -22], [196, -58], [262, -92], [286, -170],
  [252, -244], [170, -276], [70, -268], [16, -226],
];

const HARBOR = [
  [0, -300], [0, 0], [0, 300], [52, 410], [190, 465],
  [370, 440], [478, 340], [505, 160], [450, 45], [385, -5],
  [395, -125], [505, -215], [540, -335], [500, -430], [420, -450],
  [365, -390], [325, -300], [245, -255], [150, -310], [90, -425],
  [20, -410],
];

export const TRACKS = [
  {
    id: 'downtown',
    name: 'NEON DOWNTOWN',
    subtitle: 'Night city circuit · technical',
    points: DOWNTOWN,
    width: 18,
    laps: 3,
    theme: 'night',
    tunnels: [[0.66, 0.74]],
    unlock: null,
    seed: 1337,
  },
  {
    id: 'harbor',
    name: 'HARBOR HIGHWAY',
    subtitle: 'Dusk coastal run · high speed',
    points: HARBOR,
    width: 20,
    laps: 3,
    theme: 'dusk',
    tunnels: [[0.08, 0.17]],
    unlock: { track: 'downtown', position: 3 },
    seed: 4242,
  },
  {
    id: 'downtown-r',
    name: 'DOWNTOWN REVERSE',
    subtitle: 'Neon Downtown driven backwards',
    points: DOWNTOWN,
    reverse: true,
    width: 18,
    laps: 3,
    theme: 'night',
    tunnels: [[0.66, 0.74]], // same physical tunnel as forward layout
    unlock: { track: 'downtown', position: 1 },
    seed: 1337,
  },
  {
    id: 'harbor-r',
    name: 'HARBOR REVERSE',
    subtitle: 'Harbor Highway driven backwards',
    points: HARBOR,
    reverse: true,
    width: 20,
    laps: 3,
    theme: 'dusk',
    tunnels: [[0.08, 0.17]], // same physical tunnel as forward layout
    unlock: { track: 'harbor', position: 1 },
    seed: 4242,
  },
];

export const MODES = [
  { id: 'race', name: 'STREET RACE', desc: '3 laps against 5 rivals. Finish on the podium to earn big.' },
  { id: 'timetrial', name: 'TIME TRIAL', desc: 'Solo hot laps against your ghost. Beat your best lap.' },
  { id: 'drift', name: 'DRIFT ATTACK', desc: '2 laps, score as many drift points as you can. Walls break combos.' },
];

export function trackById(id) {
  return TRACKS.find((t) => t.id === id) || TRACKS[0];
}
