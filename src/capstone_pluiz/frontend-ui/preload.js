// frontend-ui/preload.js
// contextIsolation 환경에서 렌더러가 ipcRenderer를 안전하게 쓸 수 있도록 노출
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // 렌더러 → 메인
  openMain:       ()        => ipcRenderer.send('open-main'),
  minimizeToMini: ()        => ipcRenderer.send('minimize-to-mini'),
  quitApp:        ()        => ipcRenderer.send('quit-app'),
  moveMini:       (dx, dy)  => ipcRenderer.send('move-mini', { dx, dy }),

  // 메인 → 렌더러 (이벤트 수신)
  onWakeState: (cb) => ipcRenderer.on('wake-state', (event, state) => cb(state)),
});