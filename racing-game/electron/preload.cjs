// Minimal, explicit bridge between the game page and the Electron shell.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('neonRushNative', {
  setWindowMode: (mode) => ipcRenderer.invoke('window-mode', mode),
  quit: () => ipcRenderer.invoke('quit'),
  platform: process.platform,
});
