// Entry point: create the game + UI once the page is ready.
import { Game } from './game.js';
import { UI } from './ui/ui.js';

function boot() {
  const canvas = document.getElementById('game');
  let game;
  try {
    game = new Game(canvas);
  } catch (err) {
    document.querySelector('#boot .boot-msg').textContent = 'Could not start WebGL. Please update your graphics drivers. (' + err.message + ')';
    throw err;
  }
  const ui = new UI(document.getElementById('ui'), game);
  game.showroom('downtown');
  window.__neonRush = { game, ui }; // handy for debugging and automated tests
  requestAnimationFrame(() => document.getElementById('boot').classList.add('hidden'));
  game.applyWindowMode();
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();
