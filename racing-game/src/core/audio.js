// Fully synthesized audio (Web Audio API): engine, tyres, nitro, wind, impacts,
// UI sounds and a procedural synthwave soundtrack. No sample files are shipped,
// so every sound is original to the project.

const NOTE = (n) => 440 * Math.pow(2, (n - 69) / 12);

// i - VI - III - VII in A minor, as MIDI note triads.
const PROGRESSION = [
  [57, 60, 64], // Am
  [53, 57, 60], // F
  [48, 52, 55], // C
  [55, 59, 62], // G
];

export class AudioEngine {
  constructor() {
    this.ctx = null;
    this.ready = false;
    this.musicOn = true;
    this.musicMode = 'menu';
    this.volumes = { master: 0.8, music: 0.45, sfx: 0.9 };
  }

  // Must be called from a user gesture in browsers (Electron allows autoplay).
  init() {
    if (this.ctx) {
      if (this.ctx.state === 'suspended') this.ctx.resume();
      return;
    }
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    const ctx = (this.ctx = new AC());
    this.master = ctx.createGain();
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -14;
    comp.ratio.value = 4;
    this.master.connect(comp).connect(ctx.destination);
    this.musicBus = ctx.createGain();
    this.sfxBus = ctx.createGain();
    this.musicBus.connect(this.master);
    this.sfxBus.connect(this.master);
    this.noiseBuf = this.makeNoise(2);
    this.applyVolumes();
    this.buildLoops();
    this.ready = true;
    this.startMusic();
  }

  setVolumes(master, music, sfx) {
    this.volumes = { master, music, sfx };
    this.applyVolumes();
  }

  applyVolumes() {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this.master.gain.setTargetAtTime(this.volumes.master, t, 0.05);
    this.musicBus.gain.setTargetAtTime(this.musicOn ? this.volumes.music * 0.55 : 0, t, 0.1);
    this.sfxBus.gain.setTargetAtTime(this.volumes.sfx, t, 0.05);
  }

  toggleMusic() {
    this.musicOn = !this.musicOn;
    this.applyVolumes();
    return this.musicOn;
  }

  makeNoise(seconds) {
    const ctx = this.ctx;
    const buf = ctx.createBuffer(1, ctx.sampleRate * seconds, ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    return buf;
  }

  noiseSource() {
    const s = this.ctx.createBufferSource();
    s.buffer = this.noiseBuf;
    s.loop = true;
    return s;
  }

  // Continuous voices: engine, rival engine, skid, nitro, wind.
  buildLoops() {
    const ctx = this.ctx;
    const mk = (type, f) => {
      const o = ctx.createOscillator();
      o.type = type;
      o.frequency.value = f;
      return o;
    };
    // Player engine: saw + square sub, through a lowpass whose cutoff follows load.
    const eng = (this.engine = {});
    eng.o1 = mk('sawtooth', 60);
    eng.o2 = mk('square', 30);
    eng.o3 = mk('sawtooth', 90);
    eng.filter = ctx.createBiquadFilter();
    eng.filter.type = 'lowpass';
    eng.filter.Q.value = 3;
    eng.gain = ctx.createGain();
    eng.gain.gain.value = 0;
    const g2 = ctx.createGain();
    g2.gain.value = 0.55;
    const g3 = ctx.createGain();
    g3.gain.value = 0.25;
    eng.o1.connect(eng.filter);
    eng.o2.connect(g2).connect(eng.filter);
    eng.o3.connect(g3).connect(eng.filter);
    eng.filter.connect(eng.gain).connect(this.sfxBus);
    eng.o1.start();
    eng.o2.start();
    eng.o3.start();

    // Nearest rival engine (one shared voice keeps CPU cost flat).
    const riv = (this.rival = {});
    riv.o = mk('sawtooth', 70);
    riv.filter = ctx.createBiquadFilter();
    riv.filter.type = 'lowpass';
    riv.filter.frequency.value = 700;
    riv.gain = ctx.createGain();
    riv.gain.gain.value = 0;
    riv.o.connect(riv.filter).connect(riv.gain).connect(this.sfxBus);
    riv.o.start();

    const noiseVoice = (type, freq, q) => {
      const src = this.noiseSource();
      const f = ctx.createBiquadFilter();
      f.type = type;
      f.frequency.value = freq;
      f.Q.value = q;
      const g = ctx.createGain();
      g.gain.value = 0;
      src.connect(f).connect(g).connect(this.sfxBus);
      src.start();
      return { src, f, g };
    };
    this.skid = noiseVoice('bandpass', 1100, 1.6);
    this.nitroV = noiseVoice('highpass', 1400, 0.7);
    this.wind = noiseVoice('lowpass', 500, 0.5);
    this.scrape = noiseVoice('bandpass', 2600, 2);
  }

  /** Called every frame while racing with the player's car state. */
  updateCar(car, opts = {}) {
    if (!this.ready) return;
    const t = this.ctx.currentTime;
    const e = this.engine;
    const rpm = car.rpm;
    const thr = car.input.throttle;
    const base = 38 + rpm * 170 + (car.nitroActive ? 12 : 0);
    e.o1.frequency.setTargetAtTime(base, t, 0.03);
    e.o2.frequency.setTargetAtTime(base * 0.5, t, 0.03);
    e.o3.frequency.setTargetAtTime(base * 1.5 + 3, t, 0.03);
    e.filter.frequency.setTargetAtTime(300 + rpm * 1600 + thr * 900, t, 0.05);
    const active = opts.active !== false;
    e.gain.gain.setTargetAtTime(active ? 0.12 + thr * 0.1 + rpm * 0.05 : 0, t, 0.08);

    const speed = Math.hypot(car.vx, car.vz);
    const slip = Math.abs(car.slip);
    const skid = active && speed > 6 ? Math.min(1, Math.max(0, (slip - 0.12) * 2.2) + (car.input.brake && speed > 15 ? 0.25 : 0)) : 0;
    this.skid.g.gain.setTargetAtTime(skid * 0.28, t, 0.05);
    this.skid.f.frequency.setTargetAtTime(800 + speed * 12, t, 0.1);
    this.nitroV.g.gain.setTargetAtTime(active && car.nitroActive ? 0.16 : 0, t, 0.06);
    this.wind.g.gain.setTargetAtTime(active ? Math.min(0.2, (speed / 70) * 0.2) : 0, t, 0.2);
    this.wind.f.frequency.setTargetAtTime(300 + speed * 8, t, 0.2);
    this.scrape.g.gain.setTargetAtTime(active && car.wallContact && speed > 5 ? 0.18 : 0, t, 0.04);

    // Rival engine
    const rd = opts.rivalDist ?? Infinity;
    const rv = active && rd < 60 ? (1 - rd / 60) * 0.09 : 0;
    this.rival.gain.gain.setTargetAtTime(rv, t, 0.1);
    this.rival.o.frequency.setTargetAtTime(45 + (opts.rivalRpm ?? 0.5) * 150, t, 0.05);
  }

  silenceCar() {
    if (!this.ready) return;
    const t = this.ctx.currentTime;
    for (const g of [this.engine.gain, this.skid.g, this.nitroV.g, this.wind.g, this.scrape.g, this.rival.gain]) g.gain.setTargetAtTime(0, t, 0.08);
  }

  // ----- One-shots -------------------------------------------------------------
  tone(freq, dur, { type = 'sine', vol = 0.2, attack = 0.005, bus = this.sfxBus, when = 0, slideTo = null } = {}) {
    if (!this.ready) return;
    const ctx = this.ctx;
    const t = ctx.currentTime + when;
    const o = ctx.createOscillator();
    o.type = type;
    o.frequency.setValueAtTime(freq, t);
    if (slideTo) o.frequency.exponentialRampToValueAtTime(slideTo, t + dur);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(vol, t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(bus);
    o.start(t);
    o.stop(t + dur + 0.05);
  }

  noiseBurst(dur, { type = 'lowpass', freq = 800, vol = 0.3, when = 0, sweepTo = null, bus = this.sfxBus } = {}) {
    if (!this.ready) return;
    const ctx = this.ctx;
    const t = ctx.currentTime + when;
    const s = ctx.createBufferSource();
    s.buffer = this.noiseBuf;
    const f = ctx.createBiquadFilter();
    f.type = type;
    f.frequency.setValueAtTime(freq, t);
    if (sweepTo) f.frequency.exponentialRampToValueAtTime(sweepTo, t + dur);
    const g = ctx.createGain();
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    s.connect(f).connect(g).connect(bus);
    s.start(t, Math.random());
    s.stop(t + dur + 0.05);
  }

  impact(strength) {
    const v = Math.min(1, strength / 18);
    this.noiseBurst(0.25 + v * 0.2, { freq: 500 + v * 900, vol: 0.15 + v * 0.35 });
    this.tone(70, 0.25, { vol: 0.2 + v * 0.3, slideTo: 40 });
  }

  nitroStart() {
    this.noiseBurst(0.6, { type: 'bandpass', freq: 300, sweepTo: 3000, vol: 0.35 });
    this.tone(110, 0.4, { type: 'sawtooth', vol: 0.08, slideTo: 220 });
  }

  gearShift() {
    this.noiseBurst(0.06, { type: 'bandpass', freq: 1800, vol: 0.06 });
  }

  countBeep(final) {
    this.tone(final ? 880 : 440, final ? 0.6 : 0.25, { type: 'square', vol: 0.12 });
  }

  checkpoint() {
    this.tone(1046, 0.12, { type: 'triangle', vol: 0.12 });
    this.tone(1568, 0.2, { type: 'triangle', vol: 0.1, when: 0.07 });
  }

  driftBank(points) {
    const n = points > 3000 ? 3 : points > 1000 ? 2 : 1;
    [784, 988, 1175].slice(0, n).forEach((f, i) => this.tone(f, 0.18, { type: 'triangle', vol: 0.1, when: i * 0.06 }));
  }

  driftFail() {
    this.tone(300, 0.3, { type: 'sawtooth', vol: 0.06, slideTo: 120 });
  }

  lap() {
    [659, 784, 1046].forEach((f, i) => this.tone(f, 0.25, { type: 'triangle', vol: 0.12, when: i * 0.09 }));
  }

  finish(win) {
    const notes = win ? [523, 659, 784, 1046, 1318] : [523, 587, 659, 523];
    notes.forEach((f, i) => this.tone(f, 0.35, { type: 'square', vol: 0.08, when: i * 0.12 }));
  }

  uiMove() {
    this.tone(1200, 0.05, { type: 'sine', vol: 0.05 });
  }

  uiSelect() {
    this.tone(880, 0.08, { type: 'triangle', vol: 0.09 });
    this.tone(1320, 0.1, { type: 'triangle', vol: 0.07, when: 0.05 });
  }

  uiBack() {
    this.tone(500, 0.08, { type: 'triangle', vol: 0.08, slideTo: 350 });
  }

  // ----- Procedural music ------------------------------------------------------------
  setMusicMode(mode) {
    this.musicMode = mode; // 'menu' | 'race' | 'results'
  }

  startMusic() {
    if (this.musicTimer) return;
    this.bpm = 104;
    this.step = 0;
    this.nextTime = this.ctx.currentTime + 0.1;
    this.musicTimer = setInterval(() => this.scheduleMusic(), 50);
  }

  scheduleMusic() {
    const ctx = this.ctx;
    if (!ctx || ctx.state !== 'running') return;
    const sixteenth = 60 / this.bpm / 4;
    while (this.nextTime < ctx.currentTime + 0.25) {
      this.playStep(this.step, this.nextTime - ctx.currentTime);
      this.nextTime += sixteenth;
      this.step = (this.step + 1) % 256;
    }
  }

  playStep(step, when) {
    const bus = this.musicBus;
    const race = this.musicMode === 'race';
    const bar = Math.floor(step / 16) % 4;
    const s = step % 16;
    const chord = PROGRESSION[bar];
    const sixteenth = 60 / this.bpm / 4;
    // Arpeggio
    const arpNote = chord[[0, 1, 2, 1][s % 4]] + 12 + (s >= 8 && race ? 12 : 0);
    if (race || s % 2 === 0) this.tone(NOTE(arpNote), sixteenth * 1.6, { type: 'sawtooth', vol: 0.035, bus, when });
    // Bass on eighths
    if (s % 2 === 0) this.tone(NOTE(chord[0] - 24), sixteenth * 1.8, { type: race ? 'sawtooth' : 'triangle', vol: race ? 0.09 : 0.07, bus, when });
    // Pad at the start of each bar
    if (s === 0) for (const n of chord) this.tone(NOTE(n), sixteenth * 15, { type: 'triangle', vol: 0.03, attack: 0.3, bus, when });
    if (!race) return;
    // Drums
    if (s % 8 === 0) this.tone(120, 0.18, { vol: 0.32, bus, when, slideTo: 40 });
    if (s % 8 === 4) this.noiseBurst(0.16, { type: 'bandpass', freq: 1800, vol: 0.14, bus, when });
    if (s % 2 === 1) this.noiseBurst(0.04, { type: 'highpass', freq: 7000, vol: 0.05, bus, when });
  }
}
