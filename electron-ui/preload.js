const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('pluiz', {
  // 로컬 API 접근 토큰 (BL-14). 서버가 아직 안 떴으면 main.js가 기다렸다 준다.
  getToken:     ()   => ipcRenderer.invoke('get-token'),
  quit:         ()   => ipcRenderer.send('quit-app'),
  resizeIdle:   ()   => ipcRenderer.send('resize-idle'),
  resizeActive: ()   => ipcRenderer.send('resize-active'),
  onToggleActive:   (cb) => ipcRenderer.on('toggle-active',    () => cb()),
  onWakeDetected:   (cb) => ipcRenderer.on('wake-detected',    () => cb()),
  onWakewordStatus: (cb) => ipcRenderer.on('wakeword-status',  (_e, s) => cb(s)),
});
