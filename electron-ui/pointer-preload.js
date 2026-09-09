// 포인팅 오버레이 전용 preload (M4).
// 메인 창의 preload.js와 분리한 이유: 이 창은 **그리기만** 하므로 토큰·설정 같은
// 나머지 API를 노출할 이유가 없다. 창이 화면 전체를 덮으니 표면은 좁을수록 좋다.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('pointer', {
  onDraw:  (cb) => ipcRenderer.on('point-draw',  (_e, p) => cb(p)),
  onClear: (cb) => ipcRenderer.on('point-clear', () => cb()),
});
