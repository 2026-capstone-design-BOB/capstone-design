const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('pluiz', {
  // 로컬 API 접근 토큰 (BL-14). 서버가 아직 안 떴으면 main.js가 기다렸다 준다.
  getToken:     ()   => ipcRenderer.invoke('get-token'),
  quit:         ()   => ipcRenderer.send('quit-app'),
  // 화면 감시가 무언가를 발견했을 때 오버레이를 앞으로 꺼낸다 (Phase 2)
  showWindow:   ()   => ipcRenderer.send('show-window'),
  resizeIdle:   ()   => ipcRenderer.send('resize-idle'),
  resizeActive: ()   => ipcRenderer.send('resize-active'),
  pointShow:    (p)  => ipcRenderer.send('point-show', p),
  pointHide:    ()   => ipcRenderer.send('point-hide'),
  // 말 거는 단축키를 **실제로 잡게** 한다 (2026-10-02).
  // 🚨 `{ ok, hotkey }` 를 돌려받아 UI 가 말한다 — 다른 프로그램이 그 키를 쓰고 있으면
  //   등록이 실패하는데, 그걸 안 보면 «저장은 됐는데 눌러도 아무 일 없는» BL-13 이 된다.
  setHotkey:    (k)  => ipcRenderer.invoke('set-hotkey', k),
  onToggleActive:   (cb) => ipcRenderer.on('toggle-active',    () => cb()),
  onWakeDetected:   (cb) => ipcRenderer.on('wake-detected',    () => cb()),
  onWakewordStatus: (cb) => ipcRenderer.on('wakeword-status',  (_e, s) => cb(s)),
  // 🗣 지금 사람 말이 나오고 있나 (M10) — 녹음을 끝내는 **두 번째** 조건이다.
  onVadSpeech:      (cb) => ipcRenderer.on('vad-speech',       (_e, on) => cb(on)),
});
