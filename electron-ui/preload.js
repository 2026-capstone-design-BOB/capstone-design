const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('pluiz', {
  // 로컬 API 접근 토큰 (BL-14). 서버가 아직 안 떴으면 main.js가 기다렸다 준다.
  getToken:     ()   => ipcRenderer.invoke('get-token'),
  quit:         ()   => ipcRenderer.send('quit-app'),
  // 화면 감시가 무언가를 발견했을 때 오버레이를 앞으로 꺼낸다 (Phase 2)
  showWindow:   ()   => ipcRenderer.send('show-window'),
  resizeIdle:   ()   => ipcRenderer.send('resize-idle'),
  resizeActive: ()   => ipcRenderer.send('resize-active'),
  onToggleActive:   (cb) => ipcRenderer.on('toggle-active',    () => cb()),
  onWakeDetected:   (cb) => ipcRenderer.on('wake-detected',    () => cb()),
  onWakewordStatus: (cb) => ipcRenderer.on('wakeword-status',  (_e, s) => cb(s)),
});
