// frontend-ui/preload.js
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // 렌더러 → 메인
  openMain:           ()        => ipcRenderer.send('open-main'),
  minimizeToMini:     ()        => ipcRenderer.send('minimize-to-mini'),
  quitApp:            ()        => ipcRenderer.send('quit-app'),
  moveMini:           (dx, dy)  => ipcRenderer.send('move-mini', { dx, dy }),
  miniVoiceCommand:   (text)    => ipcRenderer.send('mini-voice-command', text),

  // 메인 → 렌더러
  onWakeState:        (cb) => ipcRenderer.on('wake-state',       (_, state) => cb(state)),
  onExecuteCommand:   (cb) => ipcRenderer.on('execute-command',  (_, text)  => cb(text)),
});