import { TrackPath } from '../../src/world/trackPath.js';
import { TRACKS } from '../../src/data/tracks.js';
import { CARS, tunedPhysics } from '../../src/data/cars.js';
import { createCarState, placeCar } from '../../src/vehicle/carPhysics.js';

export const DT = 1 / 120;

export function makeTrack(id = 'downtown') {
  const t = TRACKS.find((x) => x.id === id);
  return new TrackPath(t.points, { width: t.width, reverse: t.reverse });
}

export function makeCar(id = 'vapor', upgrades) {
  const def = CARS.find((c) => c.id === id);
  const p = tunedPhysics(def, upgrades);
  p.wheelR = def.body.wheelR;
  return createCarState(p);
}

// A long straight "track" so physics can be tested without corners.
export function straightTrack(width = 60) {
  const pts = [];
  for (let z = -5000; z <= 5000; z += 1000) pts.push([0, z]);
  pts.push([300, 5400]);
  for (let z = 5000; z >= -5000; z -= 1000) pts.push([600, z]);
  pts.push([300, -5400]);
  return new TrackPath(pts, { width });
}

export function carOnStraight(id = 'vapor') {
  const c = makeCar(id);
  placeCar(c, 0, -4000, 0); // straight runs from z=-4000 to z=4000
  return c;
}
