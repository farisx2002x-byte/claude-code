// Game orchestrator: renderer + scene, world loading, the race session (player,
// rivals, race rules, effects, camera, audio, HUD) and the fixed-step main loop.
// Menus live in ui/ui.js and talk to this class through a small public API.

import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

import { TrackPath } from './world/trackPath.js';
import { buildTrackMeshes } from './world/trackMesh.js';
import { buildScenery } from './world/scenery.js';
import { CARS, carById, tunedPhysics } from './data/cars.js';
import { trackById, TRACKS } from './data/tracks.js';
import { createCarState, stepCar, collideCars, placeCar } from './vehicle/carPhysics.js';
import { buildCarModel, syncCarModel } from './vehicle/carModel.js';
import { AIDriver } from './ai/aiDriver.js';
import { RaceManager, computeRewards, driftMedal, CHECKPOINTS } from './race/raceManager.js';
import { CameraRig, OrbitCam, CAMERA_VIEWS } from './fx/cameraRig.js';
import { SkidMarks, Particles, attachFlames, SpeedLines } from './fx/effects.js';
import { glowTexture } from './world/textures.js';
import { Input } from './core/input.js';
import { AudioEngine } from './core/audio.js';
import { loadSettings, saveSettings, loadSave, storeSave, QUALITY_PRESETS } from './core/storage.js';
import { clamp } from './core/util.js';

const FIXED_DT = 1 / 120;
const RIVAL_NAMES = ['VOLT', 'RAZOR', 'NOVA', 'ECHO', 'BLAZE', 'ONYX', 'VIPER', 'KOI', 'JINX', 'HALO'];
const RIVAL_COLORS = ['#ff5252', '#39ff14', '#ffd23f', '#00bfa5', '#7a8cff', '#f5f5f5', '#ff8a1f', '#e040fb'];

// Settings cheap enough to apply on every slider 'input' event.
const LIVE_SETTINGS = new Set(['masterVolume', 'musicVolume', 'sfxVolume', 'fov']);

export class Game {
  constructor(canvas) {
    this.canvas = canvas;
    this.settings = loadSettings();
    this.save = loadSave();
    this.input = new Input();
    this.audio = new AudioEngine();
    this.state = 'menu';
    this.listeners = {};
    this.hud = null; // set by UI
    this.session = null;
    this.world = null;
    this.time = 0;
    this.fps = 60;
    this.frameTimes = [];
    this.stats = { frames: 0, slowFrames: 0 };
    this.debug = { autopilot: false, timeScale: 1 };

    this.initRenderer();
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(64, 16 / 9, 0.3, 2400);
    this.scene.add(this.camera);
    this.rig = new CameraRig(this.camera);
    this.orbit = new OrbitCam(this.camera);
    this.speedLines = new SpeedLines();
    this.camera.add(this.speedLines.mesh);
    this.skids = new SkidMarks();
    this.smoke = new Particles(500, {});
    this.sparks = new Particles(300, { additive: true, texture: glowTexture() });
    this.scene.add(this.skids.mesh, this.smoke.points, this.sparks.points);

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.envMap = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environment = this.envMap;
    pmrem.dispose();

    this.applySettings();
    window.addEventListener('resize', () => this.resize());
    this.resize();
    this.last = performance.now();
    this.acc = 0;
    this.loop = this.loop.bind(this);
    requestAnimationFrame(this.loop);
  }

  on(evt, fn) {
    (this.listeners[evt] ||= []).push(fn);
  }

  emit(evt, data) {
    for (const fn of this.listeners[evt] || []) fn(data);
  }

  // ---------------------------------------------------------------------------
  // Rendering setup / settings
  initRenderer() {
    const preset = QUALITY_PRESETS[this.settings.quality] || QUALITY_PRESETS.medium;
    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: preset.antialias, powerPreference: 'high-performance' });
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.antialiasAtStart = preset.antialias;
  }

  applySettings() {
    const s = this.settings;
    const preset = QUALITY_PRESETS[s.quality] || QUALITY_PRESETS.medium;
    this.preset = preset;
    const dpr = Math.min(window.devicePixelRatio || 1, preset.pixelRatio);
    this.renderer.setPixelRatio(dpr * s.renderScale);
    this.renderer.shadowMap.enabled = preset.shadows;
    this.rig.shakeScale = s.cameraShake;
    this.rig.speedFx = s.speedEffects;
    this.rig.baseFov = s.fov;
    this.rig.view = s.cameraView || 0;
    this.camera.far = preset.drawDistance + 900;
    this.camera.updateProjectionMatrix();
    if (this.scene.fog && this.world) this.applyFog();
    this.audio.setVolumes(s.masterVolume, s.musicVolume, s.sfxVolume);
    this.setupComposer();
    if (this.world) {
      const sun = this.world.scenery.sunLight;
      sun.castShadow = preset.shadows;
      this.world.trackMeshes.group.traverse((o) => {
        if (o.isMesh) o.material.needsUpdate = true;
      });
    }
    this.resize();
  }

  setupComposer() {
    if (this.composer) {
      this.composer.dispose();
      this.composer = null;
    }
    if (!this.preset.bloom) return;
    const size = this.renderer.getDrawingBufferSize(new THREE.Vector2());
    const rt = new THREE.WebGLRenderTarget(size.x, size.y, { type: THREE.HalfFloatType, samples: 4 });
    this.composer = new EffectComposer(this.renderer, rt);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(size.x / 2, size.y / 2), 0.55, 0.45, 0.82);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());
  }

  updateSettings(patch, { live = false } = {}) {
    Object.assign(this.settings, patch);
    // Sliders (volumes, FOV) update live while dragging; the full apply rebuilds
    // render targets and recompiles materials, so it only runs once on release.
    if (live && Object.keys(patch).every((k) => LIVE_SETTINGS.has(k))) {
      const s = this.settings;
      this.audio.setVolumes(s.masterVolume, s.musicVolume, s.sfxVolume);
      this.rig.baseFov = s.fov;
      return;
    }
    saveSettings(this.settings);
    this.applySettings();
    if (patch.resolution !== undefined || patch.fullscreen !== undefined) this.applyWindowMode();
  }

  applyWindowMode() {
    const s = this.settings;
    if (window.neonRushNative) {
      const [w, h] = s.resolution.split('x').map(Number);
      window.neonRushNative.setWindowMode({ width: w, height: h, fullscreen: s.fullscreen });
    } else if (s.fullscreen && !document.fullscreenElement) {
      document.documentElement.requestFullscreen?.().catch(() => {});
    } else if (!s.fullscreen && document.fullscreenElement) {
      document.exitFullscreen?.().catch(() => {});
    }
  }

  resize() {
    const w = window.innerWidth, h = window.innerHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    if (this.composer) {
      this.composer.setPixelRatio(this.renderer.getPixelRatio());
      this.composer.setSize(w, h);
    }
    const scale = (h * this.renderer.getPixelRatio()) / 2;
    this.smoke.mat.uniforms.scale.value = scale;
    this.sparks.mat.uniforms.scale.value = scale;
  }

  applyFog() {
    const T = this.world.scenery.theme;
    const far = Math.min(T.fogFar, this.preset.drawDistance);
    this.scene.fog = new THREE.Fog(T.fog, Math.min(T.fogNear, far * 0.4), far);
    this.renderer.toneMappingExposure = T.exposure;
    this.scene.environmentIntensity = T.envIntensity ?? 0.5;
  }

  // ---------------------------------------------------------------------------
  // World
  loadTrack(trackId) {
    const def = trackById(trackId);
    if (this.world && this.world.def.id === def.id && this.world.quality === this.settings.quality) return this.world;
    this.unloadTrack();
    const path = new TrackPath(def.points, { width: def.width, reverse: def.reverse });
    const trackMeshes = buildTrackMeshes(path, def, this.settings.quality);
    const scenery = buildScenery(path, def, this.settings.quality);
    this.scene.add(trackMeshes.group, scenery.group);
    const sun = scenery.sunLight;
    sun.castShadow = this.preset.shadows;
    sun.shadow.mapSize.set(1024, 1024);
    const sc = sun.shadow.camera;
    sc.left = sc.bottom = -40;
    sc.right = sc.top = 40;
    sc.near = 1;
    sc.far = 300;
    sun.shadow.bias = -0.0008;
    this.world = { def, path, trackMeshes, scenery, quality: this.settings.quality };
    this.applyFog();
    this.skids.clear();
    this.smoke.clear();
    this.sparks.clear();
    return this.world;
  }

  unloadTrack() {
    if (!this.world) return;
    this.scene.remove(this.world.trackMeshes.group, this.world.scenery.group);
    this.world.trackMeshes.dispose();
    this.world.scenery.dispose();
    this.world = null;
  }

  // ---------------------------------------------------------------------------
  // Showroom (menu / garage background): the selected car parked on the grid.
  showroom(trackId = 'downtown') {
    this.endSession();
    this.loadTrack(trackId);
    this.state = 'menu';
    this.audio.setMusicMode('menu');
    this.audio.silenceCar();
    this.refreshShowroomCar();
  }

  persist() {
    storeSave(this.save);
  }

  refreshShowroomCar(carId = this.save.selectedCar) {
    this.showroomCarId = carId;
    if (this.showroomModel) {
      this.scene.remove(this.showroomModel.root);
      this.showroomModel.dispose();
    }
    const def = carById(carId);
    const cfg = this.save.cars[def.id];
    const m = buildCarModel(def, { quality: this.settings.quality, paint: cfg.paint, glow: cfg.glow, rim: cfg.rim });
    const f = this.world.path.frameAt(this.world.path.length - 30);
    m.root.position.set(f.x, 0, f.z);
    m.root.rotation.y = f.heading;
    this.scene.add(m.root);
    this.showroomModel = m;
    this.showroomTarget = new THREE.Vector3(f.x, 0, f.z);
  }

  // ---------------------------------------------------------------------------
  // Race session
  startEvent(cfg) {
    this.endSession();
    this.lastEvent = { ...cfg };
    const world = this.loadTrack(cfg.trackId);
    const def = world.def;
    const path = world.path;
    const mode = cfg.mode || 'race';
    const laps = mode === 'drift' ? 2 : def.laps;
    const race = new RaceManager(path, { laps, mode });
    const playerDef = carById(cfg.carId || this.save.selectedCar);
    const pcfg = this.save.cars[playerDef.id];
    const difficulty = this.settings.difficulty;

    const entrants = [];
    const rivalCount = mode === 'race' ? 5 : 0;
    // Rivals drive a mix of every car class. Rivals in a faster car than the
    // player's get a pace handicap (and slower cars a small bonus) so the field
    // stays fair whatever the player drives.
    const playerTier = CARS.indexOf(playerDef);
    const upg = this.save.cars[playerDef.id].upgrades;
    for (let i = 0; i < rivalCount; i++) {
      const tier = (playerTier + 1 + i) % CARS.length;
      const rdef = CARS[tier];
      const paceScale = Math.min(1.05, 1 - 0.035 * (tier - playerTier));
      // Rivals get roughly matching upgrades so upgrading doesn't trivialise races.
      const rUpg = { engine: Math.max(0, upg.engine - (i % 2)), grip: Math.max(0, upg.grip - 1), nitro: upg.nitro };
      entrants.push({ def: rdef, upgrades: rUpg, paceScale, paint: RIVAL_COLORS[i % RIVAL_COLORS.length], glow: rdef.body.glow, name: RIVAL_NAMES[(i + def.seed) % RIVAL_NAMES.length], ai: true });
    }
    // Player starts at the back-middle of the grid in races.
    const playerEntry = { def: playerDef, upgrades: pcfg.upgrades, paint: pcfg.paint, glow: pcfg.glow, rim: pcfg.rim, name: 'YOU', ai: false };
    entrants.splice(Math.min(entrants.length, 4), 0, playerEntry);

    const sess = (this.session = {
      cfg: { ...cfg, mode, laps },
      race,
      mode,
      cars: [],
      models: [],
      flames: [],
      ais: [],
      player: null,
      playerModel: null,
      emitters: [],
      driftScore: 0,
      wallHitsPlayer: 0,
      messages: [],
      resultsShown: false,
      ghost: null,
      ghostRec: [],
      ghostRecTimer: 0,
      tSinceGo: 0,
      finishCam: 0,
      playerAI: null,
    });

    entrants.forEach((e, i) => {
      const p = tunedPhysics(e.def, e.upgrades);
      p.wheelR = e.def.body.wheelR;
      const car = createCarState(p);
      const model = buildCarModel(e.def, { quality: this.settings.quality, paint: e.paint, glow: e.glow, rim: e.rim || 'spoke' });
      this.scene.add(model.root);
      const flames = attachFlames(model);
      const racer = race.addRacer(car, { name: e.name, isPlayer: !e.ai, id: i });
      racer.carName = e.def.name;
      racer.color = e.paint;
      sess.cars.push(car);
      sess.models.push(model);
      sess.flames.push(flames);
      sess.emitters.push({ lx: null, lz: null, rx: null, rz: null });
      if (e.ai) {
        sess.ais.push(new AIDriver(car, path, { difficulty, seed: def.seed + i * 31, paceScale: e.paceScale ?? 1 }));
      } else {
        sess.ais.push(null);
        sess.player = car;
        sess.playerRacer = racer;
        sess.playerModel = model;
        sess.playerIndex = i;
      }
    });
    race.setupGrid();

    // Time trial ghost
    if (mode === 'timetrial') {
      const g = this.save.ghosts[def.id];
      if (g && g.frames?.length) {
        const gdef = carById(g.car);
        const gm = buildCarModel(gdef, { quality: 'low', paint: '#9fe8ff', glow: 'off' });
        gm.setOpacity(0.3);
        this.scene.add(gm.root);
        sess.ghost = { data: g, model: gm };
      }
    }

    // Prime render interpolation & camera.
    for (let i = 0; i < sess.cars.length; i++) syncCarModel(sess.models[i], sess.cars[i], 1);
    this.rig.snap(sess.player);
    this.skids.clear();
    this.smoke.clear();
    this.sparks.clear();
    if (this.showroomModel) this.showroomModel.root.visible = false;
    for (const gate of world.trackMeshes.gates) gate.visible = true;

    this.state = 'race';
    this.paused = false;
    this.audio.setMusicMode('race');
    this.emit('raceStart', sess);
  }

  restart() {
    if (this.lastEvent) this.startEvent(this.lastEvent);
  }

  endSession() {
    const sess = this.session;
    if (!sess) return;
    for (const m of sess.models) {
      this.scene.remove(m.root);
      m.dispose();
    }
    for (const f of sess.flames) f.dispose();
    if (sess.ghost) {
      this.scene.remove(sess.ghost.model.root);
      sess.ghost.model.dispose();
    }
    this.session = null;
    this.speedLines.mesh.visible = false;
    if (this.showroomModel) this.showroomModel.root.visible = true;
    this.audio.silenceCar();
  }

  setPaused(p) {
    if (this.state !== 'race' || !this.session) return;
    if (this.session.resultsShown) return;
    this.paused = p;
    if (p) this.audio.silenceCar();
    this.emit('pause', p);
  }

  quitToMenu() {
    this.paused = false;
    const tid = this.world?.def.id || 'downtown';
    this.showroom(tid);
    this.emit('menu');
  }

  resetPlayer() {
    const s = this.session;
    if (!s || s.race.state === 'countdown' || s.playerRacer.finished) return;
    s.race.resetRacer(s.playerRacer);
    this.rig.snap(s.player);
    this.audio.tone(330, 0.15, { type: 'triangle', vol: 0.1 });
  }

  // ---------------------------------------------------------------------------
  // Main loop
  loop(now) {
    requestAnimationFrame(this.loop);
    let dt = (now - this.last) / 1000;
    this.last = now;
    if (!(dt > 0)) dt = 1 / 60;
    this.trackFps(dt);
    dt = Math.min(dt, 0.1);
    this.time += dt;
    this.input.pollGamepad();
    this.emit('frameInput', this.input);

    if (this.state === 'race' && this.session) this.updateRace(dt);
    else this.updateMenu(dt);

    this.render();
    this.input.endFrame();
  }

  trackFps(dt) {
    this.frameTimes.push(dt);
    if (this.frameTimes.length > 60) this.frameTimes.shift();
    const avg = this.frameTimes.reduce((a, b) => a + b, 0) / this.frameTimes.length;
    this.fps = 1 / avg;
    this.stats.frames++;
    if (dt > 1 / 25) this.stats.slowFrames++;
  }

  updateMenu(dt) {
    if (this.world) this.world.scenery.update(dt);
    if (this.showroomModel) {
      this.orbit.update(dt, this.showroomTarget, { radius: 8.5, height: 2.6, speed: 0.18, lookY: 0.7 });
    }
    this.speedLines.update(dt, 0, 0);
    this.smoke.update(dt);
    this.sparks.update(dt);
  }

  updateRace(dt) {
    const s = this.session;
    const inp = this.input;
    if (inp.wasPressed('pause') && !this.paused && !s.resultsShown) this.setPaused(true);
    if (this.paused || s.resultsShown) {
      if (s.resultsShown) this.updateFinishedView(dt);
      return;
    }
    if (inp.wasPressed('reset')) this.resetPlayer();
    if (inp.wasPressed('camera')) {
      this.rig.view = (this.rig.view + 1) % CAMERA_VIEWS.length;
      this.settings.cameraView = this.rig.view;
      saveSettings(this.settings);
      this.emit('message', { text: `CAMERA: ${CAMERA_VIEWS[this.rig.view].name.toUpperCase()}`, kind: 'small' });
    }
    if (inp.wasPressed('music')) {
      const on = this.audio.toggleMusic();
      this.emit('message', { text: on ? 'MUSIC ON' : 'MUSIC OFF', kind: 'small' });
    }

    // Fixed-step simulation.
    this.acc += dt * this.debug.timeScale;
    let steps = 0;
    while (this.acc >= FIXED_DT && steps < 24) {
      this.fixedUpdate(FIXED_DT);
      this.acc -= FIXED_DT;
      steps++;
    }
    if (steps >= 24) this.acc = 0;
    const alpha = this.acc / FIXED_DT;

    for (let i = 0; i < s.cars.length; i++) {
      syncCarModel(s.models[i], s.cars[i], alpha);
      s.flames[i].update(s.cars[i].nitroActive, this.time);
    }
    this.updateEffects(dt);
    this.updateGhost();
    this.world.scenery.update(dt);

    const pc = s.player;
    if (s.race.state === 'finished' && s.race.postFinishTimer > 1.5) {
      this.orbit.angle = this.orbit.angle || 0;
      this.orbit.update(dt, s.playerModel.root.position, { radius: 9, height: 3, speed: 0.35, lookY: 0.8 });
    } else {
      this.rig.update(dt, pc, s.playerModel);
    }
    const speedFrac = Math.hypot(pc.vx, pc.vz) / pc.p.topSpeed;
    const lines = this.settings.speedEffects ? clamp((speedFrac - 0.72) * 3, 0, 1) * 0.6 + (pc.nitroActive ? 0.6 : 0) : 0;
    this.speedLines.update(dt, s.race.state === 'running' ? lines : 0, Math.hypot(pc.vx, pc.vz));

    // Rival engine audio: nearest AI car.
    let rd = Infinity, rrpm = 0.5;
    for (const c of s.cars) {
      if (c === pc) continue;
      const d = Math.hypot(c.x - pc.x, c.z - pc.z);
      if (d < rd) {
        rd = d;
        rrpm = c.rpm;
      }
    }
    this.audio.updateCar(pc, { rivalDist: rd, rivalRpm: rrpm, active: true });

    // Highlight next checkpoint gate.
    const pr = s.playerRacer;
    for (const g of this.world.trackMeshes.gates) {
      const next = g.userData.index === pr.nextCheckpoint && !pr.finished;
      g.userData.mat.opacity = next ? 0.85 + Math.sin(this.time * 8) * 0.1 : 0.22;
    }

    // Shadow camera follows the player.
    const sun = this.world.scenery.sunLight;
    if (sun.castShadow) {
      const dir = this.world.scenery.sunDir;
      sun.target.position.set(pc.x, 0, pc.z);
      sun.position.set(pc.x + dir.x * 100, dir.y * 100, pc.z + dir.z * 100);
    }

    if (this.hud) this.hud.update(s, this);

    // Results timing.
    if (!s.resultsShown) {
      const done = s.race.state === 'finished';
      const wait = s.mode === 'race' ? 4.5 : 3;
      if (done && s.race.postFinishTimer > wait) this.finishEvent();
    }
  }

  fixedUpdate(dt) {
    const s = this.session;
    const race = s.race;
    const path = this.world.path;
    const pc = s.player;
    const drive = this.input.driving();

    if (race.state === 'countdown') {
      // Engines rev but cars are held on the line.
      for (const c of s.cars) {
        c.prevX = c.x; c.prevZ = c.z; c.prevYaw = c.yaw;
        c.rpm += ((c === pc ? (drive.throttle ? 0.85 : 0.2) : 0.3 + Math.random() * 0.3) - c.rpm) * 0.08;
        c.input.throttle = c === pc ? drive.throttle : 0;
      }
      race.update(dt);
      this.handleRaceEvents();
      return;
    }

    // Player input (or autopilot after the finish / in tests).
    if (pc && (s.playerRacer.finished || this.debug.autopilot)) {
      if (!s.playerAI) s.playerAI = new AIDriver(pc, path, { difficulty: 'normal', seed: 99, paceScale: s.playerRacer.finished ? 0.8 : 1 });
      s.playerAI.update(dt, s.cars, 0);
    } else if (pc) {
      Object.assign(pc.input, drive);
    }

    const gapRef = s.playerRacer.dist;
    for (let i = 0; i < s.cars.length; i++) {
      const ai = s.ais[i];
      if (ai) ai.update(dt, s.cars, race.racers[i].dist - gapRef);
    }
    for (const c of s.cars) stepCar(c, dt, path);
    collideCars(s.cars);
    race.update(dt);

    // AI auto-recovery; player gets a hint (and an automatic reset if truly stuck).
    for (const r of race.racers) {
      if (r.finished && !r.isPlayer) continue;
      if (!r.isPlayer && r.stuckTimer > 3) race.resetRacer(r);
      if (r.isPlayer && r.stuckTimer > 8 && !r.finished) {
        race.resetRacer(r);
        this.rig.snap(r.car);
      }
    }

    // Ghost recording (time trial).
    if (s.mode === 'timetrial' && race.state === 'running') {
      s.ghostRecTimer += dt;
      if (s.ghostRecTimer >= 0.05) {
        s.ghostRecTimer -= 0.05;
        s.ghostRec.push(+pc.x.toFixed(2), +pc.z.toFixed(2), +pc.yaw.toFixed(3));
      }
    }

    this.handleCarEvents();
    this.handleRaceEvents();
  }

  handleCarEvents() {
    const s = this.session;
    const pc = s.player;
    for (let i = 0; i < s.cars.length; i++) {
      const c = s.cars[i];
      const isP = c === pc;
      for (const e of c.events) {
        if (e.type === 'wall' || e.type === 'car') {
          const near = Math.hypot(c.x - pc.x, c.z - pc.z) < 30;
          if (isP) {
            this.rig.addShake(Math.min(1, e.value / 14));
            this.audio.impact(e.value);
            if (e.type === 'wall' && e.value > 4) s.wallHitsPlayer++;
          } else if (near && e.value > 5) {
            this.audio.impact(e.value * 0.5);
          }
          if (near) this.burstSparks(c, Math.min(30, e.value * 2));
        } else if (isP) {
          if (e.type === 'nitroStart') this.audio.nitroStart();
          else if (e.type === 'gear') this.audio.gearShift();
          else if (e.type === 'driftEnd') {
            s.driftScore += e.value;
            s.playerRacer.driftScore = s.driftScore;
            this.audio.driftBank(e.value);
            this.emit('drift', { points: e.value, banked: true });
          } else if (e.type === 'driftFail') {
            this.audio.driftFail();
            this.emit('drift', { points: e.value, banked: false });
          }
        }
      }
      c.events.length = 0;
    }
  }

  handleRaceEvents() {
    const s = this.session;
    const race = s.race;
    for (const e of race.events) {
      if (e.type === 'count') {
        this.audio.countBeep(false);
        this.emit('countdown', e.value);
      } else if (e.type === 'go') {
        this.audio.countBeep(true);
        this.emit('countdown', 0);
      } else if (e.racer && e.racer.isPlayer) {
        if (e.type === 'checkpoint') {
          this.audio.checkpoint();
          this.emit('checkpoint', { index: e.index, time: e.time });
        } else if (e.type === 'lap') {
          this.onPlayerLap(e);
        } else if (e.type === 'finish') {
          this.audio.finish(e.position === 1 || s.mode !== 'race');
          this.emit('playerFinish', { position: e.position });
        } else if (e.type === 'wrongWay') {
          this.emit('wrongWay', e.value);
        }
      }
    }
  }

  onPlayerLap(e) {
    const s = this.session;
    const race = s.race;
    const r = s.playerRacer;
    this.audio.lap();
    this.emit('lap', { lap: r.lap, laps: race.laps, time: e.value, best: e.best });
    if (s.mode === 'timetrial') {
      // Store ghost for the best lap on this track.
      const key = this.world.def.id;
      const prev = this.save.ghosts[key];
      const frames = s.ghostRec;
      if (r.lap > 1 && (!prev || e.value < prev.lap) && frames.length > 30) {
        this.save.ghosts[key] = { car: carById(this.lastEvent.carId || this.save.selectedCar).id, lap: e.value, frames };
        storeSave(this.save);
      }
      s.ghostRec = [];
      s.ghostRecTimer = 0;
    }
  }

  updateGhost() {
    const s = this.session;
    if (!s.ghost) return;
    const g = s.ghost;
    const t = s.race.state === 'running' ? s.race.time - s.playerRacer.lapStart : 0;
    const f = g.data.frames;
    const n = f.length / 3;
    const k = t / 0.05;
    const i0 = Math.min(n - 1, Math.floor(k)), i1 = Math.min(n - 1, i0 + 1);
    const a = k - Math.floor(k);
    const x = f[i0 * 3] + (f[i1 * 3] - f[i0 * 3]) * a;
    const z = f[i0 * 3 + 1] + (f[i1 * 3 + 1] - f[i0 * 3 + 1]) * a;
    let dy = f[i1 * 3 + 2] - f[i0 * 3 + 2];
    dy = Math.atan2(Math.sin(dy), Math.cos(dy));
    g.model.root.position.set(x, 0, z);
    g.model.root.rotation.y = f[i0 * 3 + 2] + dy * a;
    g.model.root.visible = s.race.state === 'running' && !s.playerRacer.finished;
  }

  burstSparks(car, n) {
    const scale = this.preset.particles;
    const count = Math.round(n * scale);
    for (let k = 0; k < count; k++) {
      this.sparks.emit(car.x + (Math.random() - 0.5) * 2, 0.5, car.z + (Math.random() - 0.5) * 2,
        (Math.random() - 0.5) * 10 + car.vx * 0.3, 2 + Math.random() * 4, (Math.random() - 0.5) * 10 + car.vz * 0.3,
        0.35, 0.3 + Math.random() * 0.3, 1, 0.75, 0.3, 1, -0.3);
    }
  }

  updateEffects(dt) {
    const s = this.session;
    const pc = s.player;
    const partScale = this.preset.particles;
    for (let i = 0; i < s.cars.length; i++) {
      const c = s.cars[i];
      const em = s.emitters[i];
      const fx = Math.sin(c.yaw), fz = Math.cos(c.yaw);
      const rx = -fz, rz = fx;
      const halfW = 0.82, back = -1.45;
      const lx = c.x + fx * back - rx * halfW, lz = c.z + fz * back - rz * halfW;
      const rrx = c.x + fx * back + rx * halfW, rrz = c.z + fz * back + rz * halfW;
      const speed = Math.hypot(c.vx, c.vz);
      const slip = Math.abs(c.slip);
      const braking = c.input.brake > 0 && c.speed > 12;
      const marking = speed > 5 && (slip > 0.16 || braking || c.drifting);
      const dist = Math.hypot(c.x - pc.x, c.z - pc.z);
      if (marking) {
        const strength = Math.min(1, slip * 2 + (braking ? 0.6 : 0));
        if (em.lx !== null) {
          this.skids.add(em.lx, em.lz, lx, lz, 0.28, strength);
          this.skids.add(em.rx, em.rz, rrx, rrz, 0.28, strength);
        }
        em.lx = lx; em.lz = lz; em.rx = rrx; em.rz = rrz;
        // Smoke (only near the camera to save fill-rate).
        if (dist < 90 && slip > 0.2 && Math.random() < 0.75 * partScale) {
          const shade = 0.75 + Math.random() * 0.2;
          for (const [px, pz] of [[lx, lz], [rrx, rrz]]) {
            this.smoke.emit(px, 0.35, pz, c.vx * 0.15 + (Math.random() - 0.5) * 1.5, 0.6 + Math.random(), c.vz * 0.15 + (Math.random() - 0.5) * 1.5,
              1.2, 0.9 + Math.random() * 0.6, shade, shade, shade + 0.05, 0.38, 3.6);
          }
        }
      } else {
        em.lx = null;
      }
      // Nitro trail sparks
      if (c.nitroActive && dist < 80 && Math.random() < 0.8 * partScale) {
        this.sparks.emit(c.x - fx * 2.5, 0.45, c.z - fz * 2.5, -fx * 6 + (Math.random() - 0.5), Math.random(), -fz * 6 + (Math.random() - 0.5),
          0.7, 0.25, 0.3, 0.75, 1, 0.8, 1.2);
      }
      if (c.wallContact && speed > 8 && dist < 60 && Math.random() < 0.6) this.burstSparks(c, 2);
    }
    this.skids.update();
    this.smoke.update(dt);
    this.sparks.update(dt);
  }

  updateFinishedView(dt) {
    const s = this.session;
    // Keep the world ticking slowly behind the results screen.
    this.orbit.update(dt, s.playerModel.root.position, { radius: 9, height: 3, speed: 0.25, lookY: 0.8 });
    this.world.scenery.update(dt);
    this.smoke.update(dt);
    this.sparks.update(dt);
    this.speedLines.update(dt, 0, 0);
  }

  finishEvent() {
    const s = this.session;
    s.resultsShown = true;
    this.audio.silenceCar();
    this.audio.setMusicMode('results');
    const race = s.race;
    const def = this.world.def;
    const pr = s.playerRacer;
    const results = race.results();
    const position = results.findIndex((x) => x.racer === pr) + 1;
    const key = `${def.id}:${s.mode}`;
    const prev = this.save.best[key] || {};
    const prevBestLap = prev.lap ?? Infinity;
    const rewards = computeRewards({
      mode: s.mode,
      position,
      racers: results.length,
      driftScore: s.driftScore,
      bestLap: pr.bestLap,
      prevBestLap,
      cleanRace: s.wallHitsPlayer === 0,
      difficulty: this.settings.difficulty,
    });
    // Persist progress.
    const best = { ...prev };
    if (pr.bestLap < (best.lap ?? Infinity)) best.lap = pr.bestLap;
    if (pr.finishTime < (best.total ?? Infinity)) best.total = pr.finishTime;
    if (s.mode === 'race' && position < (best.position ?? Infinity)) best.position = position;
    if (s.driftScore > (best.drift ?? 0)) best.drift = s.driftScore;
    this.save.best[key] = best;
    this.save.credits += rewards.total;
    const st = this.save.stats;
    st.races++;
    if (s.mode === 'race' && position === 1) st.wins++;
    if (s.mode === 'race' && position <= 3) st.podiums++;
    st.driftTotal += s.driftScore;
    storeSave(this.save);

    const medal = s.mode === 'drift' ? driftMedal(s.driftScore, this.world.path.length) : null;
    this.emit('results', {
      mode: s.mode,
      track: def,
      position,
      results: results.map((x) => ({
        name: x.racer.name,
        car: x.racer.carName,
        time: x.time,
        estimated: x.estimated,
        bestLap: x.racer.bestLap,
        isPlayer: x.racer.isPlayer,
      })),
      player: { bestLap: pr.bestLap, total: pr.finishTime, lapTimes: pr.lapTimes, drift: s.driftScore, wallHits: s.wallHitsPlayer },
      prevBest: prev,
      rewards,
      credits: this.save.credits,
      medal,
      newUnlocks: this.newlyUnlocked(def.id, position, s.mode, prev.position),
    });
  }

  newlyUnlocked(trackId, position, mode, prevPos) {
    if (mode !== 'race') return [];
    return TRACKS.filter((t) => t.unlock && t.unlock.track === trackId && position <= t.unlock.position && !(prevPos <= t.unlock.position)).map((t) => t.name);
  }

  render() {
    // Accumulate stats over all post-processing passes (for the FPS overlay / tests).
    this.renderer.info.autoReset = false;
    this.renderer.info.reset();
    if (this.composer) this.composer.render();
    else this.renderer.render(this.scene, this.camera);
  }

  // Test hook: advance the race simulation by `seconds` without rendering.
  fastForward(seconds) {
    if (!this.session) return;
    const steps = Math.round(seconds / FIXED_DT);
    for (let i = 0; i < steps && !this.session.resultsShown; i++) this.fixedUpdate(FIXED_DT);
    this.rig.snap(this.session.player);
  }

  // Introspection used by automated tests and the FPS overlay.
  getDebugInfo() {
    const info = this.renderer.info;
    return {
      state: this.state,
      fps: this.fps,
      drawCalls: info.render.calls,
      triangles: info.render.triangles,
      geometries: info.memory.geometries,
      textures: info.memory.textures,
      slowFrames: this.stats.slowFrames,
      frames: this.stats.frames,
    };
  }
}

export { placeCar, CHECKPOINTS };
