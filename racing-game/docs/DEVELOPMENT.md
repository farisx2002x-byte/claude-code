# Neon Rush: development notes and test report

## 1. Creative brief

*Neon Rush* is a night-time street-racing arcade game: synthwave colours, neon barriers, wet-looking asphalt, glowing underbodies. A race lasts about 2–3 minutes. The core verbs are **brake, drift, boost**: drifting fills the nitro tank, and nitro wins straights. One race always ends with a reward and a reason to go again: a better lap, a podium that unlocks a track, credits for an upgrade, or beating your own ghost.

Pillars, in priority order: fun to drive, smooth performance, readable racing, then visual flair.

## 2. Engine choice: Three.js + Electron

| Option | Why not / why |
|---|---|
| Unreal | Excellent visuals, but heavy runtime and high GPU requirements. Hard to keep "mid-range PC at 60 FPS" and a small download. Overkill for a stylized arcade racer. |
| Unity / Godot | Both good fits in principle. Neither editor/export pipeline was available in this build environment, so the result couldn't be compiled or tested here. |
| **Three.js (WebGL 2) + Electron** ✔ | Lightweight renderer with full control over draw calls. Custom arcade physics (no rigid-body solver) gives predictable, stable handling. The same build runs in a browser, so it can be **tested automatically end to end** (headless Chromium). Electron packages it as a standard Windows x64 `.exe` from any OS. |

The trade-off is that the Electron runtime adds about 150 MB to the download, mostly Chromium. That's acceptable for a PC game and it buys reliable WebGL on Windows through ANGLE/Direct3D 11.

## 3. Architecture

```
src/
  main.js              entry: creates Game + UI
  game.js              orchestrator: renderer, world loading, race session, fixed-step loop
  core/   util.js      math helpers, deterministic RNG, time formatting
          input.js     keyboard + standard gamepad, edge-triggered actions
          audio.js     Web Audio synth: engine/gearbox, tyres, nitro, wind, impacts, UI, music sequencer
          storage.js   settings + save game (localStorage), quality presets
  data/   cars.js      car catalogue (physics + body params), paints, rims, upgrades
          tracks.js    track control points, themes, unlock rules, modes
  world/  trackPath.js closed Catmull-Rom centreline, arc-length samples, locate()/frameAt()
          trackMesh.js road, barriers, kerbs, tunnels, gantry, checkpoint gates, lamps
          scenery.js   sky, lights, ground/water, chunked instanced buildings, billboards, palms
          textures.js  all canvas-generated textures
  vehicle/carPhysics.js arcade vehicle model, wall + car collisions
          carModel.js  procedural car meshes (extruded profiles), wheels, underglow
  ai/     aiDriver.js  speed-profile planner + steering/overtaking/nitro logic
  race/   raceManager.js countdown, progress, checkpoints, laps, positions, resets, rewards
  fx/     cameraRig.js chase / far / hood cameras, FOV kick, shake; orbit camera
          effects.js   skid marks, smoke/sparks particles, nitro flames, speed lines
  ui/     ui.js        menus (title, event, garage, settings, help, pause, results)
          hud.js       in-race HUD + minimap
electron/              main process (window, IPC for window mode/quit) + preload bridge
scripts/               build, packaging, icon, track validation, race simulation, perf probe
test/unit              Node tests (no browser): physics, tracks, AI races, race rules, keyboard driving
test/e2e               Playwright: full UI/game flow in Chromium; packaged-Electron smoke test
```

The gameplay code (track path, physics, AI, race rules) is **pure JavaScript with no rendering dependency**, which is why entire races can be simulated and asserted in unit tests.

### Physics model (`vehicle/carPhysics.js`)
Every 1/120 s (fixed step, with render interpolation):
1. Steering slews toward the input (fast return to centre). Target yaw rate is speed-sensitive. While drifting, the car may rotate more freely.
2. Velocity is split into forward and lateral parts relative to the heading. Lateral velocity decays by *grip*: high when gripping, low when drifting.
3. Engine power curve (reaches each car's rated top speed), brakes and reverse, engine braking, nitro (extra acceleration and +20–24 % top speed).
4. Barriers: the car is projected back inside, the into-wall velocity is removed, speed loss scales with impact angle, and the nose is swung along the barrier. Hard crashes therefore never leave the car stuck. Car-vs-car contact uses two circles per car with mass-weighted impulses.

The drift is a state machine: handbrake + steer above 13 m/s starts it with a small tail kick. Holding steer into the corner sustains it. Straightening or counter-steering recovers grip over about 0.3 s. An anti-spin assist caps the slip angle near 50°. Drifting scores `|slip| × speed` points and charges nitro. A big slide also scrubs speed, so it's a cornering tool, not a free boost.

### AI (`ai/aiDriver.js`)
- Per car, a speed profile is precomputed from the track curvature and that car's real steering authority. A backward pass then adds braking zones.
- At runtime the AI steers toward a look-ahead point offset to the inside of upcoming corners. It picks an overtaking side when a car blocks its lane, uses nitro on long straights, slows down when off-line after a hit, and is reset after 3 s stuck.
- Difficulty scales pace (Easy 84 %, Normal 93 %, Hard 99.5 % of the computed limit) plus steering noise. Rivals in faster cars get a pace handicap. Catch-up is capped at ±4 %.

### Rendering and performance techniques
- Unlit/Lambert materials for the world. Standard (PBR) only on car bodies, with a tiny PMREM environment.
- Buildings: 5 prototype boxes × spatial chunks of `InstancedMesh`, so frustum culling skips whole blocks. Lamps, palms and tunnel lights are instanced too.
- Fake lighting instead of real lights: emissive windows, additive light pools under lamps, glow sprites for underglow. Only 2 real lights (hemisphere + directional).
- Shadows only on High: one 1024² map following the player, cars only. Bloom only on High.
- Draw distance and fog per preset; scenery density per preset; render scale 60–100 %.
- Pooled particles/skid marks (no allocations while racing); smoke only near the camera.
- Physics, AI and race logic cost about 0.2–0.3 ms per frame (see §5).

## 4. Extending the game

- **New car:** add an entry to `src/data/cars.js` (physics numbers + body profile). The model, garage card, stats and AI all pick it up.
- **New track:** add control points to `src/data/tracks.js` and run `npm run check:tracks` (validates loop spacing and that no two sections overlap). Run `node scripts/sim-race.mjs <id>` to check AI lap times, and add an unlock rule if wanted.
- **New mode:** `RaceManager` handles laps/checkpoints/progress. Add a mode entry in `tracks.js`, set its rules in `Game.startEvent` and rewards in `computeRewards`.
- **More customisation:** `save.cars[id]` already stores paint/glow/rim/upgrades. Add a field and a garage tab.

## 5. Test report (what was actually run)

Environment: Linux container, Node 22, Chromium 141 headless with **software WebGL (SwiftShader)**, Electron 44 (Linux build under Xvfb). **No physical GPU and no Windows machine were available.**

### Automated tests: all passing

| Suite | Command | Result |
|---|---|---|
| Unit: tracks | `npm run test:unit` | 4 tests: loops valid, even sampling, no overlapping sections, locate/wrap/reverse correct |
| Unit: physics | | 9 tests: 0–100 km/h in 2.1–2.7 s per car, top speed reached and respected, braking 200→0 under 2.6 s, reverse, steering direction, drift entry/hold/recovery without spin, nitro boost/drain/lock-out, wall deflection keeps the car on track, hard 55° crash leaves the car aligned and able to drive on, car-car separation |
| Unit: races | | 11 tests: a full 6-car AI race completes on **all 4 tracks** (every car finishes 3 laps, ≤ 2 AI resets), difficulty ordering, checkpoint order, wrong-way detection, reset placement, reward scaling, countdown beeps 3-2-1-GO, same-step finishers keep their crossing order |
| Unit: keyboard driving | | 4 tests: a driver limited to on/off keys laps within 1–2 % of analog input with **0 wall hits** (Downtown: Vapor, Kite; Harbor: Bulwark, Phantom) |
| E2E: browser | `npm run test:e2e` | 24 checks; see `test/e2e/run-e2e.mjs` and the list below |
| E2E: packaged app | `npm run test:electron` | Packaged Electron app boots, native bridge present, race starts, window-mode IPC resizes to 1600×900, no errors |
| Windows packaging | `npm run package:win` | Produces `NeonRush.exe` (PE32+ x86-64 GUI) with icon + version info, and the zip |
| **Windows (GitHub Actions `windows-latest`)** | workflow `racing-game.yml` | Unit tests pass on Windows. `NeonRush.exe` is packaged on Windows, **launched there**, boots to the title screen, the native bridge works, a race starts, no errors (run #1, 14 Oct 2026). The build is uploaded as the `NeonRush-win32-x64` artifact |

E2E checks cover: boot without errors; arrow/Enter/Esc navigation; settings persistence; locked-track handling; garage→race with 6 cars; cars held during the countdown; throttle; nitro; drift; `R` reset; pause freezes the simulation and resumes; **complete street race → results with 6 rows, 3 laps, credits earned**; "Race again"; quit with confirmation; time trial saving a best lap + ghost and loading the ghost next time; drift attack (2 laps) to results; podium unlocks Harbor Highway; buying a car, painting it, buying an upgrade (exact credit maths); disabled buy button without credits; Low/Medium/High presets rendering both tracks without errors; 1080p layout; Esc on the results screen returns to the main menu. Screenshots are written to `test/e2e/out/`.

### Performance measurements (`npm run perf`, `docs/test-results/perf-report.json`)

| Preset / track | Logic avg / p95 (ms per frame) | Draw calls | Triangles | JS heap |
|---|---|---|---|---|
| Low, Downtown | 0.20 / 0.40 | 135 | 28 k | 14 MB |
| Low, Harbor | 0.23 / 0.50 | 144 | 38 k | 11 MB |
| Medium, Downtown | 0.27 / 0.60 | 157 | 32 k | 13 MB |
| Medium, Harbor | 0.33 / 0.80 | 179 | 40 k | 12 MB |
| High, Downtown | 0.16 / 0.50 | 227 (incl. bloom + shadow passes) | 41 k | 13 MB |
| High, Harbor | 0.25 / 0.60 | 252 | 49 k | 12 MB |

"Logic" is everything except GPU rendering: 6 cars at 120 Hz physics, AI, race rules, effects, camera, HUD and audio scheduling. It uses well under 1 ms of the 16.7 ms budget for 60 FPS. Scene complexity is small by modern standards: under 50k triangles, about 250 draw calls at most, and about 12 MB of game heap.

**Not measured: real frame rates.** The only renderer available here was a CPU software rasterizer (1–3 FPS, meaningless for GPU performance). The 60 FPS target on mid-range PCs and 30 FPS on weak ones are **design targets that still need to be measured on real Windows hardware**. The in-game FPS counter (Settings → Show FPS) shows FPS, draw calls and triangles for that purpose.

### Not tested
- Playing the Windows build by hand on a physical Windows PC. The CI smoke test launches the exe on a GPU-less Windows VM; it doesn't play a full race there.
- Real-GPU frame rate and frame pacing (see above).
- **Gamepad** input (no device available; the standard-mapping code path is implemented but unverified).
- **Audio by ear.** The synth runs without errors, but nobody has listened to the mix yet.
- The subjective "feel" of driving by a human player. Handling was tuned through the automated metrics above.

## 6. Known limitations / issues

- The exe isn't code-signed, so Windows SmartScreen shows a warning on first launch.
- The download is about 150 MB zipped, mostly the Chromium runtime.
- Changing anti-aliasing (Low ↔ Medium/High) only applies after restarting the game.
- Tracks are flat (no elevation or jumps). Barriers are continuous, so there are no shortcuts in v1.
- No traffic in the streets. The Traffic Challenge and Elimination modes were left for a later version.
- Unfinished rivals' times on the results screen are estimates from their average pace.
- On machines without a working GPU driver the game falls back to software rendering. It works, but it's very slow.
