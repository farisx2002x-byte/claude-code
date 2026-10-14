// Keyboard (primary) + optional gamepad input. Produces analog-style values for
// driving and edge-triggered "actions" for menus / pause / reset.

export const KEYMAP = {
  throttle: ['KeyW', 'ArrowUp'],
  brake: ['KeyS', 'ArrowDown'],
  left: ['KeyA', 'ArrowLeft'],
  right: ['KeyD', 'ArrowRight'],
  handbrake: ['Space'],
  nitro: ['ShiftLeft', 'ShiftRight', 'KeyN'],
  reset: ['KeyR'],
  camera: ['KeyC'],
  pause: ['Escape', 'KeyP'],
  music: ['KeyM'],
};

export class Input {
  constructor() {
    this.down = new Set();
    this.pressed = new Set(); // codes pressed since last poll
    this.gamepad = null;
    this.padPrev = [];
    this.padActions = new Set();
    this.enabled = true;
    window.addEventListener('keydown', (e) => {
      if (['Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Tab'].includes(e.code) && !(e.target instanceof HTMLInputElement)) e.preventDefault();
      if (!e.repeat) this.pressed.add(e.code);
      this.down.add(e.code);
    });
    window.addEventListener('keyup', (e) => this.down.delete(e.code));
    window.addEventListener('blur', () => this.down.clear());
  }

  any(action) {
    return KEYMAP[action].some((k) => this.down.has(k));
  }

  wasPressed(action) {
    return KEYMAP[action].some((k) => this.pressed.has(k)) || this.padActions.has(action);
  }

  pollGamepad() {
    this.padActions.clear();
    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    this.gamepad = null;
    for (const p of pads) if (p && p.connected && p.mapping === 'standard') { this.gamepad = p; break; }
    if (!this.gamepad) return;
    const b = this.gamepad.buttons.map((x) => x.pressed);
    const edge = (i) => b[i] && !this.padPrev[i];
    if (edge(9)) this.padActions.add('pause');
    if (edge(3)) this.padActions.add('reset');
    if (edge(8)) this.padActions.add('camera');
    // menu navigation
    if (edge(12)) this.padActions.add('up');
    if (edge(13)) this.padActions.add('down');
    if (edge(14)) this.padActions.add('left');
    if (edge(15)) this.padActions.add('right');
    if (edge(0)) this.padActions.add('confirm');
    if (edge(1)) this.padActions.add('back');
    this.padPrev = b;
  }

  /** Driving controls merged from keyboard + gamepad. */
  driving() {
    let throttle = this.any('throttle') ? 1 : 0;
    let brake = this.any('brake') ? 1 : 0;
    let steer = (this.any('right') ? 1 : 0) - (this.any('left') ? 1 : 0);
    let handbrake = this.any('handbrake');
    let nitro = this.any('nitro');
    const gp = this.gamepad;
    if (gp) {
      const ax = gp.axes[0] || 0;
      if (Math.abs(ax) > 0.12) steer = Math.sign(ax) * Math.min(1, (Math.abs(ax) - 0.12) / 0.8);
      throttle = Math.max(throttle, gp.buttons[7]?.value || 0);
      brake = Math.max(brake, gp.buttons[6]?.value || 0);
      handbrake = handbrake || gp.buttons[1]?.pressed || gp.buttons[5]?.pressed;
      nitro = nitro || gp.buttons[0]?.pressed || gp.buttons[2]?.pressed;
    }
    return { throttle, brake, steer, handbrake: !!handbrake, nitro: !!nitro };
  }

  endFrame() {
    this.pressed.clear();
  }
}
