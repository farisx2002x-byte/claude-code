// Third-person chase camera. Follows the car with critically-damped smoothing,
// swings out during drifts (looks along the velocity, not the nose), widens the
// FOV with speed / nitro and adds a small, settings-scaled shake on impacts.

import { damp, clamp, lerp } from '../core/util.js';

export const CAMERA_VIEWS = [
  { name: 'Chase', dist: 7.2, height: 2.6, look: 1.2 },
  { name: 'Far', dist: 10.5, height: 3.8, look: 1.4 },
  { name: 'Hood', dist: -0.6, height: 1.35, look: 1.2, hood: true },
];

export class CameraRig {
  constructor(camera) {
    this.camera = camera;
    this.view = 0;
    this.x = 0;
    this.y = 5;
    this.z = 0;
    this.yaw = 0;
    this.shake = 0;
    this.fov = 64;
    this.baseFov = 64;
    this.shakeScale = 1;
    this.speedFx = true;
    this.t = 0;
  }

  snap(car) {
    const v = CAMERA_VIEWS[this.view];
    this.yaw = car.yaw;
    this.x = car.x - Math.sin(car.yaw) * v.dist;
    this.z = car.z - Math.cos(car.yaw) * v.dist;
    this.y = v.height;
    this.shake = 0;
  }

  addShake(amount) {
    this.shake = Math.min(1.2, this.shake + amount);
  }

  update(dt, car, model, opts = {}) {
    this.t += dt;
    const v = CAMERA_VIEWS[this.view];
    const pos = model.root.position;
    const speed = Math.hypot(car.vx, car.vz);
    const top = car.p.topSpeed;
    const sf = clamp(speed / top, 0, 1.3);

    // Aim direction: blend between heading and travel direction while sliding.
    const travel = speed > 4 ? Math.atan2(car.vx, car.vz) : car.yaw;
    let d = travel - car.yaw;
    d = Math.atan2(Math.sin(d), Math.cos(d));
    const blend = v.hood ? 0.1 : clamp(Math.abs(car.slip) * 1.2, 0, 0.55);
    const reversing = car.speed < -2;
    const targetYaw = car.yaw + d * blend + (reversing && !v.hood ? 0 : 0);
    let dy = targetYaw - this.yaw;
    dy = Math.atan2(Math.sin(dy), Math.cos(dy));
    this.yaw += dy * (1 - Math.exp(-(v.hood ? 30 : 6.5) * dt));

    const dist = v.dist + (v.hood ? 0 : sf * 1.6 + (car.nitroActive ? 0.8 : 0));
    const tx = pos.x - Math.sin(this.yaw) * dist;
    const tz = pos.z - Math.cos(this.yaw) * dist;
    const ty = v.height + (v.hood ? 0 : sf * 0.3);
    const follow = v.hood ? 60 : 12;
    this.x = damp(this.x, tx, follow, dt);
    this.z = damp(this.z, tz, follow, dt);
    this.y = damp(this.y, ty, 8, dt);
    if (v.hood) {
      this.x = tx;
      this.z = tz;
    }

    // Shake (impacts + subtle rumble under nitro).
    this.shake = Math.max(0, this.shake - dt * 2.5);
    const rumble = car.nitroActive && this.speedFx ? 0.06 : 0;
    const sh = (this.shake * 0.35 + rumble * sf) * this.shakeScale;
    const sx = (Math.sin(this.t * 41) + Math.sin(this.t * 23.7)) * 0.5 * sh;
    const sy = (Math.sin(this.t * 37.3) + Math.sin(this.t * 19.1)) * 0.5 * sh;

    const cam = this.camera;
    cam.position.set(this.x + sx, this.y + sy, this.z);
    const lookAhead = v.hood ? 20 : 4 + sf * 3;
    cam.lookAt(pos.x + Math.sin(this.yaw) * lookAhead, v.look, pos.z + Math.cos(this.yaw) * lookAhead);

    // FOV kick with speed / nitro.
    const fx = this.speedFx ? 1 : 0;
    const target = this.baseFov + fx * (sf * 12 + (car.nitroActive ? 8 : 0));
    this.fov = damp(this.fov, target, 3.5, dt);
    if (Math.abs(cam.fov - this.fov) > 0.01) {
      cam.fov = this.fov;
      cam.updateProjectionMatrix();
    }
    void opts;
    void lerp;
  }
}

/** Slow orbit around a point, used behind menus / garage / after the finish. */
export class OrbitCam {
  constructor(camera) {
    this.camera = camera;
    this.angle = 0;
  }

  update(dt, target, { radius = 9, height = 3, speed = 0.15, lookY = 0.8 } = {}) {
    this.angle += dt * speed;
    const c = this.camera;
    c.position.set(target.x + Math.sin(this.angle) * radius, height, target.z + Math.cos(this.angle) * radius);
    c.lookAt(target.x, lookY, target.z);
    if (c.fov !== 50) {
      c.fov = 50;
      c.updateProjectionMatrix();
    }
  }
}
