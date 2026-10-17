// In-race HUD: position, lap, standings, timers, minimap, speedometer, gear,
// nitro gauge, drift combo and transient messages. DOM writes are skipped when
// a value hasn't changed to keep the HUD essentially free.

import { formatTime, KMH, MPH } from '../core/util.js';
import { driftMedalTargets } from '../race/raceManager.js';

const ORD = (n) => (n === 1 ? 'st' : n === 2 ? 'nd' : n === 3 ? 'rd' : 'th');

export class Hud {
  constructor(root) {
    this.root = root;
    root.innerHTML = `
      <div class="fps" id="fps"></div>
      <div class="hud-tl">
        <div class="hud-pos" id="h-pos"></div>
        <div class="hud-lap" id="h-lap"></div>
        <div class="hud-standings" id="h-stand"></div>
      </div>
      <div class="hud-tr">
        <div class="hud-time"><span class="lbl">TIME</span><span id="h-time">0:00.000</span></div>
        <div class="hud-sub" id="h-lapt"></div>
        <div class="hud-sub" id="h-best"></div>
        <canvas id="minimap"></canvas>
      </div>
      <div class="hud-banner" id="h-banner"></div>
      <div class="hud-center" id="h-center"></div>
      <div class="hud-bl">
        <div class="drift-box" id="h-drift"></div>
        <div class="drift-total" id="h-dtotal"></div>
        <div class="ctrl-hint" id="h-hint"><kbd>W</kbd><kbd>S</kbd> gas/brake · <kbd>A</kbd><kbd>D</kbd> steer · <kbd>Space</kbd> drift · <kbd>Shift</kbd> nitro · <kbd>R</kbd> reset · <kbd>C</kbd> camera · <kbd>Esc</kbd> pause</div>
      </div>
      <div class="hud-br">
        <div class="speedo">
          <svg viewBox="0 0 300 160" preserveAspectRatio="xMaxYMax meet">
            <path d="M 20 150 A 130 130 0 0 1 280 150" fill="none" stroke="rgba(255,255,255,0.1)" stroke-width="14" />
            <path id="h-rpm" d="M 20 150 A 130 130 0 0 1 280 150" fill="none" stroke="url(#rg)" stroke-width="14" stroke-dasharray="409" stroke-dashoffset="409" />
            <defs><linearGradient id="rg" x1="0" x2="1"><stop offset="0" stop-color="#00e5ff"/><stop offset="0.75" stop-color="#ff2fd0"/><stop offset="1" stop-color="#ff1744"/></linearGradient></defs>
          </svg>
          <div class="gear" id="h-gear">1</div>
          <div class="speed-num" id="h-speed">0</div>
          <div class="speed-unit" id="h-unit">KM/H</div>
        </div>
        <div class="nitro-wrap"><span class="nitro-lbl">NITRO</span><div class="nitro-bar" id="h-nitro"><i></i></div></div>
      </div>`;
    this.el = {};
    for (const id of ['fps', 'h-pos', 'h-lap', 'h-stand', 'h-time', 'h-lapt', 'h-best', 'h-center', 'h-drift', 'h-dtotal', 'h-rpm', 'h-gear', 'h-speed', 'h-unit', 'h-nitro', 'h-hint', 'h-banner']) this.el[id] = root.querySelector('#' + id);
    this.nitroFill = this.el['h-nitro'].querySelector('i');
    this.minimap = root.querySelector('#minimap');
    this.cache = {};
    this.msgTimer = 0;
    this.centerKind = null;
    this.mapPath = null;
    this.hintTimer = 0;
  }

  set(id, value, prop = 'textContent') {
    const k = id + prop;
    if (this.cache[k] === value) return;
    this.cache[k] = value;
    if (prop === 'textContent' || prop === 'innerHTML') this.el[id][prop] = value;
    else this.el[id].style.setProperty(prop, value);
  }

  show(on) {
    this.root.classList.toggle('active', on);
    if (on) {
      this.cache = {};
      this.el['h-center'].innerHTML = '';
      this.hintTimer = 12;
      this.el['h-hint'].style.opacity = 1;
    }
  }

  prepareMinimap(path) {
    const c = this.minimap;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = c.clientWidth || 180, h = c.clientHeight || 180;
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
    const b = path.bounds();
    const pad = 12 * dpr;
    const sx = (c.width - pad * 2) / (b.maxX - b.minX);
    const sz = (c.height - pad * 2) / (b.maxZ - b.minZ);
    const s = Math.min(sx, sz);
    const ox = pad + (c.width - pad * 2 - (b.maxX - b.minX) * s) / 2;
    const oz = pad + (c.height - pad * 2 - (b.maxZ - b.minZ) * s) / 2;
    // Map x -> canvas x mirrored so the map matches the driver's left/right.
    this.map = { s, ox, oz, b, dpr, path };
    const p2 = new Path2D();
    for (let i = 0; i <= path.count; i += 2) {
      const k = i % path.count;
      const [x, y] = this.mapXY(path.x[k], path.z[k]);
      if (i === 0) p2.moveTo(x, y);
      else p2.lineTo(x, y);
    }
    p2.closePath();
    this.mapPath = p2;
  }

  mapXY(x, z) {
    const m = this.map;
    return [m.ox + (m.b.maxX - x) * m.s, m.oz + (m.b.maxZ - z) * m.s];
  }

  drawMinimap(sess) {
    const c = this.minimap;
    const g = c.getContext('2d');
    const m = this.map;
    if (!m) return;
    g.clearRect(0, 0, c.width, c.height);
    g.lineJoin = 'round';
    g.strokeStyle = 'rgba(0,229,255,0.25)';
    g.lineWidth = 9 * m.dpr;
    g.stroke(this.mapPath);
    g.strokeStyle = 'rgba(230,240,255,0.85)';
    g.lineWidth = 3 * m.dpr;
    g.stroke(this.mapPath);
    // start line
    const p = m.path;
    const [sx, sy] = this.mapXY(p.x[0], p.z[0]);
    g.fillStyle = '#fff';
    g.fillRect(sx - 3 * m.dpr, sy - 3 * m.dpr, 6 * m.dpr, 6 * m.dpr);
    for (const r of sess.race.racers) {
      const [x, y] = this.mapXY(r.car.x, r.car.z);
      g.beginPath();
      g.arc(x, y, (r.isPlayer ? 5.5 : 4) * m.dpr, 0, Math.PI * 2);
      g.fillStyle = r.isPlayer ? '#ff2fd0' : r.color || '#ffd23f';
      g.fill();
      if (r.isPlayer) {
        g.strokeStyle = '#fff';
        g.lineWidth = 2 * m.dpr;
        g.stroke();
      }
    }
    if (sess.ghost && sess.ghost.model.root.visible) {
      const gp = sess.ghost.model.root.position;
      const [x, y] = this.mapXY(gp.x, gp.z);
      g.beginPath();
      g.arc(x, y, 4 * m.dpr, 0, Math.PI * 2);
      g.fillStyle = 'rgba(159,232,255,0.7)';
      g.fill();
    }
  }

  flash(text, kind = '', duration = 1.6) {
    const c = this.el['h-center'];
    if (this.centerKind === 'count' || this.centerKind === 'warn') return;
    c.innerHTML = `<div class="msg ${kind}">${text}</div>`;
    this.centerKind = 'msg';
    this.msgTimer = duration;
  }

  countdown(n) {
    const c = this.el['h-center'];
    c.innerHTML = n > 0 ? `<div class="big-msg">${n}</div>` : '<div class="big-msg go">GO!</div>';
    this.centerKind = n > 0 ? 'count' : 'go';
    this.msgTimer = n > 0 ? 2 : 0.9;
  }

  banner(text, seconds = 3) {
    const b = this.el['h-banner'];
    b.textContent = text;
    b.classList.add('on');
    clearTimeout(this.bannerT);
    this.bannerT = setTimeout(() => b.classList.remove('on'), seconds * 1000);
  }

  persistent(text) {
    // Used for "WRONG WAY": stays until cleared.
    const c = this.el['h-center'];
    if (text) {
      c.innerHTML = `<div class="msg warn">${text}</div>`;
      this.centerKind = 'warn';
      this.msgTimer = 1e9;
    } else if (this.centerKind === 'warn') {
      c.innerHTML = '';
      this.centerKind = null;
    }
  }

  update(sess, game) {
    const dt = 1 / Math.max(10, game.fps);
    const s = game.settings;
    const race = sess.race;
    const pr = sess.playerRacer;
    const car = sess.player;

    this.el['fps'].classList.toggle('on', !!s.showFps);
    if (s.showFps && (game.stats.frames & 15) === 0) {
      const d = game.getDebugInfo();
      this.el['fps'].textContent = `${d.fps.toFixed(0)} FPS · ${d.drawCalls} draws · ${(d.triangles / 1000).toFixed(0)}k tris`;
    }

    // Position / lap
    if (sess.mode === 'race') this.set('h-pos', `${pr.position}<sup>${ORD(pr.position)}</sup><span class="of"> / ${race.racers.length}</span>`, 'innerHTML');
    else this.set('h-pos', sess.mode === 'drift' ? 'DRIFT' : 'SOLO', 'innerHTML');
    const lapShown = Math.min(race.laps, pr.lap + 1);
    this.set('h-lap', `<span>LAP</span> ${lapShown}/${race.laps}`, 'innerHTML');

    // Standings (race only), refreshed a few times per second.
    if (sess.mode === 'race' && (game.stats.frames % 10 === 0)) {
      const order = race.order || race.racers;
      const lead = order[0];
      const html = order.map((r) => {
        const gap = r === lead ? '' : r.finished ? 'FIN' : `+${((lead.dist - r.dist) / Math.max(20, Math.hypot(r.car.vx, r.car.vz) || 20)).toFixed(1)}s`;
        return `<div class="${r.isPlayer ? 'me' : ''}"><b>${r.position}</b>${r.name}<span class="gap">${gap}</span></div>`;
      }).join('');
      this.set('h-stand', html, 'innerHTML');
    } else if (sess.mode !== 'race') this.set('h-stand', '', 'innerHTML');

    // Timers
    const t = race.state === 'countdown' ? 0 : pr.finished ? pr.finishTime : race.time;
    this.set('h-time', formatTime(t));
    const lapT = race.state === 'countdown' ? 0 : pr.finished ? pr.lapTimes[pr.lapTimes.length - 1] : race.time - pr.lapStart;
    this.set('h-lapt', `LAP ${formatTime(lapT)}`);
    let best = isFinite(pr.bestLap) ? formatTime(pr.bestLap) : '--:--.---';
    if (sess.ghost) best += ` · GHOST ${formatTime(sess.ghost.data.lap)}`;
    this.set('h-best', `BEST ${best}`);

    // Speed / gear / rpm
    const speed = Math.abs(car.speed) * (s.units === 'mph' ? MPH : KMH);
    this.set('h-speed', String(Math.round(speed)));
    this.set('h-unit', s.units === 'mph' ? 'MPH' : 'KM/H');
    this.set('h-gear', car.speed < -0.5 ? 'R' : String(car.gear));
    this.set('h-rpm', String(Math.round(409 * (1 - Math.min(1, car.rpm)))), 'stroke-dashoffset');

    // Nitro
    const nf = car.nitro / car.p.nitroCap;
    this.nitroFill.style.width = `${(nf * 100).toFixed(1)}%`;
    this.el['h-nitro'].classList.toggle('active', car.nitroActive);
    this.el['h-nitro'].classList.toggle('full', nf > 0.99);

    // Drift
    if (car.drifting && car.driftCombo > 20) this.set('h-drift', `<small>DRIFT</small>${Math.round(car.driftCombo).toLocaleString('en-US')}`, 'innerHTML');
    else if (!this.driftFlash) this.set('h-drift', '', 'innerHTML');
    if (this.driftFlash) {
      this.driftFlash -= dt;
      if (this.driftFlash <= 0) this.driftFlash = 0;
    }
    if (sess.mode === 'drift') {
      const next = driftMedalTargets(race.track.length).find(([, v]) => sess.driftScore < v);
      this.set('h-dtotal', `DRIFT SCORE ${sess.driftScore.toLocaleString('en-US')}${next ? ` · ${next[0]} AT ${next[1].toLocaleString('en-US')}` : ' · GOLD!'}`);
    } else if (sess.driftScore > 0) this.set('h-dtotal', `DRIFT SCORE ${sess.driftScore.toLocaleString('en-US')}`);
    else this.set('h-dtotal', '');

    // Messages fade
    if (this.msgTimer > 0) {
      this.msgTimer -= dt;
      if (this.msgTimer <= 0 && this.centerKind !== 'warn') {
        this.el['h-center'].innerHTML = '';
        this.centerKind = null;
      }
    }
    if (pr.stuckTimer > 3 && race.state === 'running' && !pr.finished && this.centerKind == null) this.flash('PRESS R TO RESET', 'small', 1);
    if (this.hintTimer > 0) {
      this.hintTimer -= dt;
      if (this.hintTimer <= 0) this.el['h-hint'].style.opacity = 0.0;
    }

    this.drawMinimap(sess);
  }

  driftResult(points, banked) {
    this.set('h-drift', banked ? `<small>DRIFT BANKED</small>+${points.toLocaleString('en-US')}` : `<small>COMBO LOST</small><s>${points.toLocaleString('en-US')}</s>`, 'innerHTML');
    this.driftFlash = 1.4;
  }
}
