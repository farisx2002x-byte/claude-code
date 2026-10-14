// Electron shell for the Windows build. Loads the bundled game from dist/,
// offline only: no remote content, no node access in the page, no telemetry.
const { app, BrowserWindow, ipcMain, Menu, screen } = require('electron');
const path = require('node:path');

// Let the synthesized audio start without a click, and keep frame pacing smooth.
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
app.commandLine.appendSwitch('disable-renderer-backgrounding');
// The game only ever renders its own bundled, local content, so allowing the
// software WebGL fallback is safe; it lets the game start (slowly) on PCs whose
// GPU driver is missing or blocklisted instead of showing a WebGL error.
app.commandLine.appendSwitch('enable-unsafe-swiftshader');

// Saves + settings live in %APPDATA%\NeonRush (fixed name, independent of exe name).
app.setPath('userData', path.join(app.getPath('appData'), 'NeonRush'));

if (!app.requestSingleInstanceLock()) app.quit();

let win = null;

function createWindow() {
  Menu.setApplicationMenu(null);
  win = new BrowserWindow({
    width: 1280,
    height: 720,
    minWidth: 960,
    minHeight: 540,
    useContentSize: true,
    backgroundColor: '#05040f',
    title: 'Neon Rush',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
      spellcheck: false,
    },
  });
  win.once('ready-to-show', () => win.show());
  win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  // Never navigate away from the game or open other windows.
  win.webContents.on('will-navigate', (e) => e.preventDefault());
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  // F11 toggles fullscreen as a convenience.
  win.webContents.on('before-input-event', (e, input) => {
    if (input.type === 'keyDown' && input.key === 'F11') {
      win.setFullScreen(!win.isFullScreen());
      e.preventDefault();
    }
  });
  win.on('closed', () => (win = null));
}

ipcMain.handle('window-mode', (_e, mode) => {
  if (!win) return;
  const fs = !!mode.fullscreen;
  if (fs !== win.isFullScreen()) win.setFullScreen(fs);
  if (!fs) {
    const area = screen.getDisplayMatching(win.getBounds()).workAreaSize;
    const w = Math.min(Number(mode.width) || 1280, area.width);
    const h = Math.min(Number(mode.height) || 720, area.height);
    win.setContentSize(w, h);
    win.center();
  }
});
ipcMain.handle('quit', () => app.quit());

app.on('second-instance', () => {
  if (win) {
    if (win.isMinimized()) win.restore();
    win.focus();
  }
});
app.whenReady().then(createWindow);
app.on('window-all-closed', () => app.quit());
