// Menu system: title, event setup, garage (car select / customisation /
// upgrades), settings, help, pause and results screens. All screens are fully
// keyboard-navigable (arrows + Enter + Esc), mouse-friendly and gamepad-aware.

import { CARS, PAINTS, GLOWS, RIMS, UPGRADES, carById } from '../data/cars.js';
import { TRACKS, MODES, trackById } from '../data/tracks.js';
import { formatTime } from '../core/util.js';
import { resetSave, DEFAULT_SETTINGS } from '../core/storage.js';
import { Hud } from './hud.js';

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

export class UI {
  constructor(root, game) {
    this.root = root;
    this.game = game;
    this.screens = {};
    this.stack = [];
    this.event = { mode: 'race', trackId: 'downtown' };
    this.garageIndex = Math.max(0, CARS.findIndex((c) => c.id === game.save.selectedCar));
    this.garageTab = 'paint';
    this.garageMode = 'browse'; // 'browse' | 'event'

    for (const id of ['title', 'event', 'garage', 'settings', 'help', 'pause', 'results']) {
      const el = document.createElement('div');
      el.className = 'screen';
      el.id = 'screen-' + id;
      root.appendChild(el);
      this.screens[id] = el;
    }
    const hudEl = document.createElement('div');
    hudEl.id = 'hud';
    root.appendChild(hudEl);
    this.hud = new Hud(hudEl);
    game.hud = this.hud;

    this.bindGame();
    this.bindKeys();
    this.show('title');
  }

  // -------------------------------------------------------------------------
  // Navigation helpers
  show(id, { push = false } = {}) {
    if (!push) this.stack = [];
    for (const [k, el] of Object.entries(this.screens)) el.classList.toggle('active', k === id);
    this.current = id;
    if (push || !this.stack.length || this.stack[this.stack.length - 1] !== id) this.stack.push(id);
    this.render(id);
    this.focusFirst();
  }

  back() {
    const g = this.game;
    this.game.audio.uiBack();
    if (this.current === 'pause') {
      g.setPaused(false);
      return;
    }
    if (this.current === 'title' || this.current === 'results') return;
    this.stack.pop();
    const prev = this.stack.pop() || 'title';
    if (prev === 'pause') {
      this.show('pause', { push: true });
      return;
    }
    this.show(prev, { push: true });
    if (prev === 'title') this.stack = ['title'];
  }

  hideAll() {
    for (const el of Object.values(this.screens)) el.classList.remove('active');
    this.current = null;
  }

  focusables() {
    const el = this.screens[this.current];
    if (!el) return [];
    const modal = el.querySelector('.modal');
    return [...(modal || el).querySelectorAll('button:not(:disabled), input[type=range]')].filter((b) => b.offsetParent !== null);
  }

  focusFirst() {
    const list = this.focusables();
    const pref = list.find((b) => b.dataset.autofocus) || list.find((b) => b.classList.contains('selected')) || list[0];
    if (pref) pref.focus({ preventScroll: false });
  }

  moveFocus(delta) {
    const list = this.focusables();
    if (!list.length) return;
    let i = list.indexOf(document.activeElement);
    i = i < 0 ? 0 : (i + delta + list.length) % list.length;
    list[i].focus();
    list[i].scrollIntoView({ block: 'nearest' });
    this.game.audio.uiMove();
  }

  bindKeys() {
    window.addEventListener('keydown', (e) => {
      this.game.audio.init();
      if (!this.current) return;
      const a = document.activeElement;
      const isRange = a && a.type === 'range';
      if (e.code === 'ArrowDown' || (e.code === 'ArrowRight' && !isRange) || (e.code === 'Tab' && !e.shiftKey)) {
        e.preventDefault();
        this.moveFocus(1);
      } else if (e.code === 'ArrowUp' || (e.code === 'ArrowLeft' && !isRange) || (e.code === 'Tab' && e.shiftKey)) {
        e.preventDefault();
        this.moveFocus(-1);
      } else if (e.code === 'Escape' || e.code === 'Backspace') {
        if (this.current === 'pause' || this.current === 'title' || this.current === 'results') return; // handled elsewhere
        e.preventDefault();
        const modal = this.screens[this.current].querySelector('.modal');
        if (modal) modal.remove();
        else this.back();
      } else if ((e.code === 'Enter' || e.code === 'Space') && a && a.tagName === 'BUTTON') {
        // native click on Enter; Space is reserved for the handbrake in-game
        if (e.code === 'Space') {
          e.preventDefault();
          a.click();
        }
      } else if (this.current === 'garage' && (e.code === 'KeyQ' || e.code === 'KeyE')) {
        this.cycleCar(e.code === 'KeyQ' ? -1 : 1);
      }
    });
    window.addEventListener('pointerdown', () => this.game.audio.init(), { once: false });
    // Gamepad menu navigation
    this.game.on('frameInput', (input) => {
      if (!this.current) return;
      const pa = input.padActions;
      if (pa.has('down') || pa.has('right')) this.moveFocus(1);
      if (pa.has('up') || pa.has('left')) this.moveFocus(-1);
      if (pa.has('confirm') && document.activeElement?.tagName === 'BUTTON') document.activeElement.click();
      if (pa.has('back')) this.back();
      if (pa.has('pause') && this.current === 'pause') {
        pa.delete('pause');
        this.game.setPaused(false);
      }
    });
    this.root.addEventListener('click', (e) => {
      if (e.target.closest('button')) this.game.audio.uiSelect();
    });
  }

  bindGame() {
    const g = this.game;
    g.on('raceStart', (sess) => {
      this.hideAll();
      this.hud.show(true);
      this.hud.prepareMinimap(g.world.path);
      const names = { race: 'STREET RACE', timetrial: 'TIME TRIAL', drift: 'DRIFT ATTACK' };
      this.hud.banner(`${names[sess.mode]} · ${g.world.def.name}`, 3.2);
      this.hud.countdown(3);
    });
    g.on('countdown', (n) => this.hud.countdown(n));
    g.on('checkpoint', (c) => this.hud.flash(`CHECKPOINT ${c.index} · ${formatTime(c.time)}`, 'small', 1.2));
    g.on('lap', (l) => {
      if (l.lap >= l.laps) return;
      const fin = l.lap === l.laps - 1 ? 'FINAL LAP' : `LAP ${l.lap + 1}`;
      this.hud.flash(`${fin} · ${formatTime(l.time)}${l.best ? ' · BEST!' : ''}`, l.best ? 'good' : '', 2);
    });
    g.on('playerFinish', ({ position }) => {
      const s = g.session;
      const txt = s.mode === 'race' ? `FINISHED ${position}${['ST', 'ND', 'RD'][position - 1] || 'TH'}!` : 'FINISHED!';
      this.hud.flash(txt, position === 1 ? 'good' : '', 4);
    });
    g.on('wrongWay', (on) => this.hud.persistent(on ? 'WRONG WAY' : null));
    g.on('drift', ({ points, banked }) => this.hud.driftResult(points, banked));
    g.on('message', ({ text, kind }) => this.hud.flash(text, kind, 1.2));
    g.on('pause', (p) => {
      if (p) this.show('pause');
      else {
        this.hideAll();
        this.stack = [];
      }
    });
    g.on('results', (r) => {
      this.lastResults = r;
      this.hud.show(false);
      this.show('results');
    });
    g.on('menu', () => {
      this.hud.show(false);
      this.show('title');
    });
    // Pause key while paused resumes; while on results, Esc goes to menu.
    window.addEventListener('keydown', (e) => {
      if ((e.code === 'Escape' || e.code === 'KeyP') && this.current === 'pause') {
        g.input.pressed.delete(e.code); // don't let the game re-pause on the same key press
        g.setPaused(false);
      } else if ((e.code === 'Escape' || e.code === 'Backspace') && this.current === 'results' && !e.repeat) {
        e.preventDefault();
        this.screens.results.querySelector('[data-act=menu]')?.click();
      }
    });
  }

  render(id) {
    const fn = this['render_' + id];
    if (fn) fn.call(this, this.screens[id]);
  }

  credits() {
    return `<div class="credits">${this.game.save.credits.toLocaleString('en-US')} CR</div>`;
  }

  // -------------------------------------------------------------------------
  render_title(el) {
    const native = !!window.neonRushNative;
    el.className = 'screen menu-screen active';
    el.innerHTML = `
      <div class="topbar">${this.credits()}</div>
      <div class="logo"><span class="l1">NEON</span><span class="l2">RUSH</span></div>
      <div class="btn-col">
        <button class="primary" data-act="race">Race<span class="btn-sub">Street race · Time trial · Drift attack</span></button>
        <button data-act="garage">Garage<span class="btn-sub">Cars, paint & upgrades</span></button>
        <button data-act="settings">Settings</button>
        <button data-act="help">How to play</button>
        ${native ? '<button data-act="quit">Quit</button>' : ''}
      </div>
      <div class="hint">↑ ↓ NAVIGATE · ENTER SELECT · ESC BACK</div>`;
    el.querySelector('[data-act=race]').onclick = () => this.show('event', { push: true });
    el.querySelector('[data-act=garage]').onclick = () => {
      this.garageMode = 'browse';
      this.show('garage', { push: true });
    };
    el.querySelector('[data-act=settings]').onclick = () => this.show('settings', { push: true });
    el.querySelector('[data-act=help]').onclick = () => this.show('help', { push: true });
    const q = el.querySelector('[data-act=quit]');
    if (q) q.onclick = () => window.neonRushNative.quit();
  }

  trackUnlocked(t) {
    if (!t.unlock) return true;
    const best = this.game.save.best[`${t.unlock.track}:race`];
    return !!best && best.position <= t.unlock.position;
  }

  render_event(el) {
    const ev = this.event;
    const save = this.game.save;
    el.className = 'screen menu-screen full active';
    const modes = MODES.map((m) => `<button class="card ${ev.mode === m.id ? 'selected' : ''}" data-mode="${m.id}"><div class="c-title">${m.name}</div><div class="c-sub">${m.desc}</div></button>`).join('');
    const tracks = TRACKS.map((t) => {
      const open = this.trackUnlocked(t);
      const best = save.best[`${t.id}:${ev.mode}`];
      let meta = '';
      if (!open) meta = `Unlock: finish ${t.unlock.position === 1 ? '1st' : `top ${t.unlock.position}`} on ${trackById(t.unlock.track).name}`;
      else if (best) {
        meta = ev.mode === 'drift' ? `Best drift ${(best.drift || 0).toLocaleString('en-US')}` : `Best lap ${formatTime(best.lap)}${best.position ? ` · Best P${best.position}` : ''}`;
      } else meta = 'No record yet';
      return `<button class="card ${ev.trackId === t.id ? 'selected' : ''} ${open ? '' : 'locked'}" data-track="${t.id}" ${open ? '' : 'data-locked="1"'}><div class="c-title">${t.name}</div><div class="c-sub">${t.subtitle}</div><div class="c-meta">${meta}</div></button>`;
    }).join('');
    const diff = this.game.settings.difficulty;
    el.innerHTML = `
      <div class="topbar">${this.credits()}</div>
      <div class="menu-title"><small>EVENT SETUP</small>CHOOSE YOUR RACE</div>
      <div class="event-wrap">
        <div class="section-label">Mode</div>
        <div class="cards">${modes}</div>
        <div class="section-label">Track</div>
        <div class="cards">${tracks}</div>
        <div class="section-label">Rival difficulty</div>
        <div class="seg">${['easy', 'normal', 'hard'].map((d) => `<button data-diff="${d}" class="${diff === d ? 'on' : ''}">${d}</button>`).join('')}</div>
        <div class="row" style="margin-top:1.4em">
          <button class="ghost" data-act="back">Back</button>
          <button class="primary" data-act="next" data-autofocus="1">Choose car →</button>
        </div>
      </div>`;
    el.querySelectorAll('[data-mode]').forEach((b) => (b.onclick = () => {
      ev.mode = b.dataset.mode;
      this.render('event');
      el.querySelector(`[data-mode=${ev.mode}]`).focus();
    }));
    el.querySelectorAll('[data-track]').forEach((b) => (b.onclick = () => {
      if (b.dataset.locked) {
        this.toast(el, 'Track locked — see the requirement on the card.');
        return;
      }
      ev.trackId = b.dataset.track;
      this.render('event');
      el.querySelector(`[data-track=${ev.trackId}]`).focus();
      this.game.showroom(ev.trackId);
    }));
    el.querySelectorAll('[data-diff]').forEach((b) => (b.onclick = () => {
      this.game.updateSettings({ difficulty: b.dataset.diff });
      this.render('event');
      el.querySelector(`[data-diff=${b.dataset.diff}]`).focus();
    }));
    el.querySelector('[data-act=back]').onclick = () => this.back();
    el.querySelector('[data-act=next]').onclick = () => {
      this.garageMode = 'event';
      this.show('garage', { push: true });
    };
  }

  toast(el, text) {
    const t = document.createElement('div');
    t.className = 'modal';
    t.innerHTML = `<div class="panel"><div style="margin-bottom:1em">${esc(text)}</div><button data-autofocus="1">OK</button></div>`;
    t.querySelector('button').onclick = () => {
      t.remove();
      this.focusFirst();
    };
    el.appendChild(t);
    t.querySelector('button').focus();
  }

  confirm(el, text, onYes) {
    const t = document.createElement('div');
    t.className = 'modal';
    t.innerHTML = `<div class="panel"><div style="margin-bottom:1em">${esc(text)}</div><div class="row"><button data-no="1" data-autofocus="1">Cancel</button><button class="primary" data-yes="1">Confirm</button></div></div>`;
    t.querySelector('[data-no]').onclick = () => {
      t.remove();
      this.focusFirst();
    };
    t.querySelector('[data-yes]').onclick = () => {
      t.remove();
      onYes();
    };
    el.appendChild(t);
    t.querySelector('[data-no]').focus();
  }

  // -------------------------------------------------------------------------
  cycleCar(d) {
    this.garageIndex = (this.garageIndex + d + CARS.length) % CARS.length;
    const car = CARS[this.garageIndex];
    this.game.refreshShowroomCar(car.id);
    this.render('garage');
    this.screens.garage.querySelector(d < 0 ? '[data-act=prev]' : '[data-act=next]')?.focus();
  }

  render_garage(el) {
    const g = this.game;
    const save = g.save;
    const car = CARS[this.garageIndex];
    const cfg = save.cars[car.id];
    const owned = save.owned.includes(car.id);
    if (!g.showroomModel || g.showroomCarId !== car.id) {
      g.refreshShowroomCar(car.id);
      g.showroomCarId = car.id;
    }
    el.className = 'screen garage active';
    const statRows = Object.entries(car.rating).map(([k, v]) => {
      const bonus = k === 'speed' || k === 'accel' ? cfg.upgrades.engine * 0.5 : k === 'handling' ? cfg.upgrades.grip * 0.5 : k === 'nitro' ? cfg.upgrades.nitro * 0.6 : 0;
      return `<div class="stat"><span>${k.toUpperCase()}</span><div class="bar"><i class="up" style="width:${Math.min(100, (v + bonus) * 10)}%"></i><i style="width:${v * 10}%"></i></div><span>${(v + bonus).toFixed(bonus % 1 ? 1 : 0)}</span></div>`;
    }).join('');

    let tab = '';
    if (this.garageTab === 'paint') {
      tab = `<div class="section-label">Body paint</div><div class="swatches">${PAINTS.map((p) => `<button class="swatch ${cfg.paint === p ? 'on' : ''}" data-paint="${p}" style="background:${p}" aria-label="paint ${p}"></button>`).join('')}</div>`;
    } else if (this.garageTab === 'glow') {
      tab = `<div class="section-label">Underglow</div><div class="swatches">${GLOWS.map((p) => `<button class="swatch ${p === 'off' ? 'off' : ''} ${cfg.glow === p ? 'on' : ''}" data-glow="${p}" style="background:${p === 'off' ? '' : p}" aria-label="glow ${p}"></button>`).join('')}</div>`;
    } else if (this.garageTab === 'rims') {
      tab = `<div class="section-label">Wheels</div>${RIMS.map((r) => {
        const has = save.ownedRims.includes(r.id);
        return `<button class="${cfg.rim === r.id ? 'selected' : ''}" data-rim="${r.id}" style="width:100%;margin-bottom:0.4em">${r.name} ${has ? (cfg.rim === r.id ? '· FITTED' : '') : `<span class="price">· ${r.price.toLocaleString('en-US')} CR</span>`}</button>`;
      }).join('')}`;
    } else {
      tab = `<div class="section-label">Performance</div>${Object.entries(UPGRADES).map(([k, u]) => {
        const lvl = cfg.upgrades[k];
        const cost = u.cost[lvl];
        return `<div class="upg"><div><div class="name">${u.name}</div><div class="desc">${u.desc}</div><div class="pips">${[0, 1, 2].map((i) => `<i class="${i < lvl ? 'on' : ''}"></i>`).join('')}</div></div>
          <button class="small" data-upg="${k}" ${cost === undefined || !owned ? 'disabled' : ''}>${cost === undefined ? 'MAX' : `${cost.toLocaleString('en-US')} CR`}</button></div>`;
      }).join('')}${owned ? '' : '<div class="desc" style="color:var(--muted);font-size:0.65em">Buy the car to upgrade it.</div>'}`;
    }

    const eventMode = this.garageMode === 'event';
    const ev = this.event;
    const action = owned
      ? eventMode
        ? `<button class="primary" data-act="start" data-autofocus="1">Start race →<span class="btn-sub">${trackById(ev.trackId).name} · ${MODES.find((m) => m.id === ev.mode).name}</span></button>`
        : `<button class="primary" data-act="select" ${save.selectedCar === car.id ? 'disabled' : ''}>${save.selectedCar === car.id ? 'Selected' : 'Select car'}</button>`
      : `<button class="primary" data-act="buy" ${save.credits < car.price ? 'disabled' : ''}>Buy · ${car.price.toLocaleString('en-US')} CR</button>`;

    el.innerHTML = `
      <div class="left">
        <div class="menu-title" style="font-size:1.1em"><small>${eventMode ? 'CHOOSE YOUR CAR' : 'GARAGE'}</small></div>
        <div class="car-name">${car.name}</div>
        <div class="car-class">${car.class}${owned ? '' : ' · LOCKED'}</div>
        <div class="car-blurb">${car.blurb}</div>
        ${statRows}
        <div class="car-nav">
          <button class="small" data-act="prev">‹ Prev</button>
          <span class="idx">${this.garageIndex + 1} / ${CARS.length}</span>
          <button class="small" data-act="next">Next ›</button>
        </div>
        <div class="spacer"></div>
        <div class="btn-col" style="width:100%">
          ${action}
          <button class="ghost" data-act="back">Back</button>
        </div>
      </div>
      <div class="right">
        <div class="topbar" style="position:static;justify-content:flex-end">${this.credits()}</div>
        <div class="panel" style="margin-top:1em">
          <div class="tabbar">${['paint', 'glow', 'rims', 'upgrades'].map((t) => `<button data-tab="${t}" class="${this.garageTab === t ? 'on' : ''}">${t}</button>`).join('')}</div>
          ${tab}
        </div>
        <div class="hint" style="position:static;margin-top:1em">Q / E switch car</div>
      </div>`;

    const keepFocus = (sel) => {
      this.render('garage');
      el.querySelector(sel)?.focus();
    };
    el.querySelector('[data-act=prev]').onclick = () => this.cycleCar(-1);
    el.querySelector('[data-act=next]').onclick = () => this.cycleCar(1);
    el.querySelector('[data-act=back]').onclick = () => {
      g.refreshShowroomCar(save.selectedCar);
      g.showroomCarId = save.selectedCar;
      this.garageIndex = Math.max(0, CARS.findIndex((c) => c.id === save.selectedCar));
      this.back();
    };
    el.querySelectorAll('[data-tab]').forEach((b) => (b.onclick = () => {
      this.garageTab = b.dataset.tab;
      keepFocus(`[data-tab=${b.dataset.tab}]`);
    }));
    el.querySelectorAll('[data-paint]').forEach((b) => (b.onclick = () => {
      cfg.paint = b.dataset.paint;
      g.showroomModel?.setPaint(cfg.paint);
      g.persist();
      keepFocus(`[data-paint="${cfg.paint}"]`);
    }));
    el.querySelectorAll('[data-glow]').forEach((b) => (b.onclick = () => {
      cfg.glow = b.dataset.glow;
      g.showroomModel?.setGlow(cfg.glow);
      g.persist();
      keepFocus(`[data-glow="${cfg.glow}"]`);
    }));
    el.querySelectorAll('[data-rim]').forEach((b) => (b.onclick = () => {
      const r = RIMS.find((x) => x.id === b.dataset.rim);
      if (!save.ownedRims.includes(r.id)) {
        if (save.credits < r.price) return this.toast(el, `Not enough credits (${r.price} CR needed).`);
        this.confirm(el, `Buy ${r.name} wheels for ${r.price} CR? (usable on every car)`, () => {
          save.credits -= r.price;
          save.ownedRims.push(r.id);
          cfg.rim = r.id;
          g.persist();
          g.refreshShowroomCar(car.id);
          keepFocus(`[data-rim=${r.id}]`);
        });
        return;
      }
      cfg.rim = r.id;
      g.persist();
      g.refreshShowroomCar(car.id);
      keepFocus(`[data-rim=${r.id}]`);
    }));
    el.querySelectorAll('[data-upg]').forEach((b) => (b.onclick = () => {
      const k = b.dataset.upg;
      const lvl = cfg.upgrades[k];
      const cost = UPGRADES[k].cost[lvl];
      if (cost === undefined) return;
      if (save.credits < cost) return this.toast(el, `Not enough credits — ${cost.toLocaleString('en-US')} CR needed. Win races and drift to earn more.`);
      save.credits -= cost;
      cfg.upgrades[k]++;
      g.persist();
      keepFocus(`[data-upg=${k}]`);
    }));
    const buy = el.querySelector('[data-act=buy]');
    if (buy) buy.onclick = () => this.confirm(el, `Buy ${car.name} for ${car.price.toLocaleString('en-US')} CR?`, () => {
      save.credits -= car.price;
      save.owned.push(car.id);
      save.selectedCar = car.id;
      g.persist();
      keepFocus('[data-act=select], [data-act=start]');
    });
    const sel = el.querySelector('[data-act=select]');
    if (sel) sel.onclick = () => {
      save.selectedCar = car.id;
      g.persist();
      keepFocus('[data-act=next]');
    };
    const start = el.querySelector('[data-act=start]');
    if (start) start.onclick = () => {
      save.selectedCar = car.id;
      g.persist();
      this.startRace();
    };
  }

  startRace() {
    const ev = this.event;
    this.hideAll();
    this.stack = [];
    this.game.startEvent({ mode: ev.mode, trackId: ev.trackId, carId: this.game.save.selectedCar });
  }

  // -------------------------------------------------------------------------
  render_settings(el) {
    const s = this.game.settings;
    const native = !!window.neonRushNative;
    el.className = 'screen menu-screen full active';
    const seg = (key, opts) => `<div class="seg">${opts.map(([v, label]) => `<button data-set="${key}" data-val="${v}" class="${String(s[key]) === String(v) ? 'on' : ''}">${label}</button>`).join('')}</div>`;
    const range = (key, min, max, step) => `<input type="range" data-range="${key}" min="${min}" max="${max}" step="${step}" value="${s[key]}" />`;
    const toggle = (key) => `<button class="toggle ${s[key] ? 'on' : ''}" data-toggle="${key}">${s[key] ? 'ON' : 'OFF'}</button>`;
    el.innerHTML = `
      <div class="menu-title"><small>OPTIONS</small>SETTINGS</div>
      <div class="settings-grid">
        <div>
          <div class="section-label">Graphics</div>
          <div class="setting"><label>Quality preset</label>${seg('quality', [['low', 'Low'], ['medium', 'Medium'], ['high', 'High']])}
            <div class="note">Low: no AA/glow, fewer props · High: shadows + bloom. Anti-aliasing changes apply after restart.</div></div>
          <div class="setting"><label>Render scale</label>${seg('renderScale', [[0.6, '60%'], [0.75, '75%'], [0.9, '90%'], [1, '100%']])}</div>
          <div class="setting"><label>Show FPS</label>${toggle('showFps')}</div>
          ${native ? `<div class="section-label">Display</div>
          <div class="setting"><label>Window size</label>${seg('resolution', [['1280x720', '720p'], ['1600x900', '900p'], ['1920x1080', '1080p']])}</div>
          <div class="setting"><label>Fullscreen</label>${toggle('fullscreen')}</div>` : `<div class="section-label">Display</div><div class="setting"><label>Fullscreen</label>${toggle('fullscreen')}</div>`}
          <div class="section-label">Camera</div>
          <div class="setting"><label>Camera shake</label>${seg('cameraShake', [[0, 'Off'], [0.5, 'Low'], [1, 'Full']])}</div>
          <div class="setting"><label>Speed effects</label>${toggle('speedEffects')}<div class="note">FOV kick and speed lines</div></div>
          <div class="setting"><label>Field of view</label>${range('fov', 55, 80, 1)}</div>
        </div>
        <div>
          <div class="section-label">Audio</div>
          <div class="setting"><label>Master volume</label>${range('masterVolume', 0, 1, 0.05)}</div>
          <div class="setting"><label>Music volume</label>${range('musicVolume', 0, 1, 0.05)}</div>
          <div class="setting"><label>Effects volume</label>${range('sfxVolume', 0, 1, 0.05)}</div>
          <div class="section-label">Gameplay</div>
          <div class="setting"><label>Difficulty</label>${seg('difficulty', [['easy', 'Easy'], ['normal', 'Normal'], ['hard', 'Hard']])}</div>
          <div class="setting"><label>Speed units</label>${seg('units', [['kmh', 'km/h'], ['mph', 'mph']])}</div>
          <div class="section-label">Data</div>
          <div class="row"><button class="small ghost" data-act="defaults">Restore defaults</button><button class="small ghost" data-act="reset">Reset progress</button></div>
        </div>
      </div>
      <div class="row" style="margin-top:1.2em"><button class="ghost" data-act="back" data-autofocus="1">Back</button></div>`;
    const keep = (sel) => {
      this.render('settings');
      el.querySelector(sel)?.focus();
    };
    el.querySelectorAll('[data-set]').forEach((b) => (b.onclick = () => {
      const key = b.dataset.set;
      let v = b.dataset.val;
      if (typeof DEFAULT_SETTINGS[key] === 'number') v = Number(v);
      this.game.updateSettings({ [key]: v });
      if (key === 'quality' && this.game.world) {
        // rebuild scenery density for the new preset
        const id = this.game.world.def.id;
        if (!this.game.session) this.game.showroom(id);
      }
      keep(`[data-set=${key}][data-val="${b.dataset.val}"]`);
    }));
    el.querySelectorAll('[data-toggle]').forEach((b) => (b.onclick = () => {
      const key = b.dataset.toggle;
      this.game.updateSettings({ [key]: !s[key] });
      keep(`[data-toggle=${key}]`);
    }));
    el.querySelectorAll('[data-range]').forEach((r) => {
      r.oninput = () => this.game.updateSettings({ [r.dataset.range]: Number(r.value) }, { live: true });
      r.onchange = () => this.game.updateSettings({ [r.dataset.range]: Number(r.value) });
    });
    el.querySelector('[data-act=back]').onclick = () => this.back();
    el.querySelector('[data-act=defaults]').onclick = () => {
      this.game.updateSettings({ ...DEFAULT_SETTINGS });
      keep('[data-act=defaults]');
    };
    el.querySelector('[data-act=reset]').onclick = () => this.confirm(el, 'Erase all credits, cars, upgrades and records?', () => {
      this.game.save = resetSave();
      this.garageIndex = 0;
      if (!this.game.session) this.game.refreshShowroomCar();
      keep('[data-act=reset]');
    });
  }

  render_help(el) {
    el.className = 'screen menu-screen full active';
    el.innerHTML = `
      <div class="menu-title"><small>HOW TO PLAY</small>CONTROLS</div>
      <div class="keys">
        <div><kbd>W</kbd> / <kbd>↑</kbd></div><div>Accelerate</div>
        <div><kbd>S</kbd> / <kbd>↓</kbd></div><div>Brake · hold to reverse</div>
        <div><kbd>A</kbd><kbd>D</kbd> / <kbd>←</kbd><kbd>→</kbd></div><div>Steer</div>
        <div><kbd>Space</kbd></div><div>Handbrake / drift — tap while turning to kick the tail out</div>
        <div><kbd>Shift</kbd> / <kbd>N</kbd></div><div>Nitro boost</div>
        <div><kbd>R</kbd></div><div>Reset car to the track</div>
        <div><kbd>C</kbd></div><div>Change camera (chase / far / hood)</div>
        <div><kbd>M</kbd></div><div>Music on / off</div>
        <div><kbd>Esc</kbd> / <kbd>P</kbd></div><div>Pause</div>
        <div>Gamepad</div><div>RT gas · LT brake · stick steer · B/RB drift · A/X nitro · Y reset · Back camera · Start pause</div>
      </div>
      <div class="tips">
        <b>Drifting</b> is the heart of Neon Rush: turn into a corner and tap or hold <kbd>Space</kbd>. Keep steering to hold the slide, counter-steer to straighten out.
        Long, fast, wide drifts bank <b>drift points</b> and refill your <b>nitro</b> quickly — hitting a wall loses the combo.<br/>
        Pass through every <b>checkpoint gate</b>; the next one glows. Finish on the podium to unlock new tracks, earn credits to buy cars, wheels and upgrades.
      </div>
      <div class="row" style="margin-top:1.2em"><button class="ghost" data-act="back" data-autofocus="1">Back</button></div>`;
    el.querySelector('[data-act=back]').onclick = () => this.back();
  }

  render_pause(el) {
    el.className = 'screen menu-screen active';
    const g = this.game;
    const s = g.session;
    el.innerHTML = `
      <div class="menu-title"><small>${esc(g.world?.def.name || '')}</small>PAUSED</div>
      <div class="btn-col">
        <button class="primary" data-act="resume" data-autofocus="1">Resume</button>
        <button data-act="restart">Restart</button>
        <button data-act="settings">Settings</button>
        <button data-act="help">Controls</button>
        <button data-act="quit">Quit to menu</button>
      </div>
      <div class="hint">LAP ${Math.min(s?.race.laps || 0, (s?.playerRacer.lap || 0) + 1)}/${s?.race.laps || 0} · ESC TO RESUME</div>`;
    el.querySelector('[data-act=resume]').onclick = () => g.setPaused(false);
    el.querySelector('[data-act=restart]').onclick = () => {
      this.hideAll();
      g.restart();
    };
    el.querySelector('[data-act=settings]').onclick = () => this.show('settings', { push: true });
    el.querySelector('[data-act=help]').onclick = () => this.show('help', { push: true });
    el.querySelector('[data-act=quit]').onclick = () => this.confirm(el, 'Quit this race? Progress in this event will be lost.', () => g.quitToMenu());
  }

  render_results(el) {
    const r = this.lastResults;
    if (!r) return;
    el.className = 'screen menu-screen active';
    let title;
    if (r.mode === 'race') title = r.position === 1 ? 'YOU WIN!' : `${r.position}${['ST', 'ND', 'RD'][r.position - 1] || 'TH'} PLACE`;
    else if (r.mode === 'drift') title = r.medal ? `${r.medal} DRIFT!` : 'DRIFT ATTACK DONE';
    else title = 'TIME TRIAL DONE';
    const rows = r.results.map((x, i) => `<tr class="${x.isPlayer ? 'me' : ''}"><td>${i + 1}</td><td>${esc(x.name)}</td><td>${esc(x.car)}</td><td>${formatTime(x.time)}${x.estimated ? ' *' : ''}</td><td>${formatTime(x.bestLap)}</td></tr>`).join('');
    const prevLap = r.prevBest.lap;
    const badges = [];
    if (isFinite(r.player.bestLap) && (!prevLap || r.player.bestLap < prevLap)) badges.push('<span class="badge gold">NEW BEST LAP</span>');
    if (r.mode === 'drift' && r.player.drift > (r.prevBest.drift || 0)) badges.push('<span class="badge gold">NEW DRIFT RECORD</span>');
    for (const u of r.newUnlocks) badges.push(`<span class="badge">UNLOCKED: ${esc(u)}</span>`);
    if (r.mode === 'race' && r.player.wallHits === 0) badges.push('<span class="badge">CLEAN RACE</span>');
    el.innerHTML = `
      <div class="topbar">${this.credits()}</div>
      <div class="menu-title"><small>${esc(r.track.name)} · RESULTS</small></div>
      <div class="results-title ${r.position === 1 || r.medal === 'GOLD' ? 'win' : ''}">${title}</div>
      <div>${badges.join('')}</div>
      <table class="res"><tr><th>POS</th><th>DRIVER</th><th>CAR</th><th>TIME</th><th>BEST LAP</th></tr>${rows}</table>
      ${r.results.some((x) => x.estimated) ? '<div style="font-size:0.6em;color:var(--muted);margin-top:0.3em">* estimated — still racing when you finished</div>' : ''}
      ${r.mode === 'drift' ? `<div style="margin-top:0.6em;font-weight:800">DRIFT SCORE: ${r.player.drift.toLocaleString('en-US')}</div>` : ''}
      <div class="rewards">${r.rewards.items.map((i) => `<div><span>${esc(i.label)}</span><span class="price">+${i.value.toLocaleString('en-US')}</span></div>`).join('')}
        <div class="total"><span>TOTAL EARNED</span><span>+${r.rewards.total.toLocaleString('en-US')} CR</span></div></div>
      <div class="row" style="margin-top:1.2em">
        <button class="primary" data-act="again" data-autofocus="1">Race again</button>
        <button data-act="garage">Garage</button>
        <button data-act="event">Change event</button>
        <button class="ghost" data-act="menu">Main menu</button>
      </div>`;
    el.querySelector('[data-act=again]').onclick = () => {
      this.hideAll();
      this.game.restart();
    };
    el.querySelector('[data-act=garage]').onclick = () => {
      this.game.quitToMenu();
      this.garageMode = 'event';
      this.show('event');
      this.show('garage', { push: true });
    };
    el.querySelector('[data-act=event]').onclick = () => {
      this.game.quitToMenu();
      this.show('event', { push: true });
    };
    el.querySelector('[data-act=menu]').onclick = () => this.game.quitToMenu();
  }
}

export { carById };
