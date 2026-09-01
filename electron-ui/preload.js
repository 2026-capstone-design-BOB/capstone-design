const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('pluiz', {
  quit:         ()   => ipcRenderer.send('quit-app'),
  resizeIdle:   ()   => ipcRenderer.send('resize-idle'),
  resizeActive: ()   => ipcRenderer.send('resize-active'),
  onToggleActive:   (cb) => ipcRenderer.on('toggle-active',    () => cb()),
  onWakeDetected:   (cb) => ipcRenderer.on('wake-detected',    () => cb()),
  onWakewordStatus: (cb) => ipcRenderer.on('wakeword-status',  (_e, s) => cb(s)),
});
