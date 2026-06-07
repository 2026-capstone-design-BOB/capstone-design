// frontend-ui/main.js
// 두 개의 창을 관리:
//   mainWin  — 메인 채팅 창 (index.html)
//   miniWin  — 플로팅 미니 창 (mini.html), 항상 위에 표시

const { app, BrowserWindow, ipcMain, session, screen } = require('electron');
const path = require('path');

let mainWin = null;
let miniWin = null;

// ── 메인 창 ───────────────────────────────────────────────
function createMainWindow() {
  mainWin = new BrowserWindow({
    width: 560,
    height: 740,
    minWidth: 440,
    minHeight: 560,
    frame: false,
    backgroundColor: '#0a0a0f',
    show: false,   // 처음엔 숨김 — 미니창이 기본
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  mainWin.loadFile(path.join(__dirname, 'index.html'));

  // 닫기 버튼 → 숨기고 미니창으로 복귀
  mainWin.on('close', (e) => {
    if (!app.isQuiting) {
      e.preventDefault();
      mainWin.hide();
      if (miniWin) miniWin.show();
    }
  });
}

// ── 미니 플로팅 창 ────────────────────────────────────────
function createMiniWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;

  miniWin = new BrowserWindow({
    width: 280,
    height: 80,
    x: width - 300,   // 우하단 배치
    y: height - 100,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,   // 작업표시줄에 안 나타남
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  miniWin.loadFile(path.join(__dirname, 'mini.html'));

  // 더블클릭 이벤트는 mini.html 내 JS에서 IPC로 전달
  miniWin.on('close', (e) => {
    if (!app.isQuiting) {
      e.preventDefault();
      miniWin.hide();
    }
  });
}

// ── IPC 이벤트 ────────────────────────────────────────────

// 미니창 → 메인창 열기 (더블클릭)
ipcMain.on('open-main', () => {
  if (mainWin) {
    mainWin.show();
    mainWin.focus();
    if (miniWin) miniWin.hide();
  }
});

// 메인창 → 미니창으로 최소화
ipcMain.on('minimize-to-mini', () => {
  if (mainWin) mainWin.hide();
  if (miniWin) miniWin.show();
});

// 완전 종료
ipcMain.on('quit-app', () => {
  app.isQuiting = true;
  app.quit();
});

// wake word 상태 → 미니창 UI 업데이트
ipcMain.on('wake-state', (event, state) => {
  if (miniWin && !miniWin.isDestroyed()) {
    miniWin.webContents.send('wake-state', state);
  }
});

// 미니창 드래그 이동
ipcMain.on('move-mini', (event, { dx, dy }) => {
  if (miniWin) {
    const [x, y] = miniWin.getPosition();
    miniWin.setPosition(x + dx, y + dy);
  }
});

// ── 앱 초기화 ─────────────────────────────────────────────
app.whenReady().then(() => {
  // 마이크 권한 자동 허용
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(permission === 'media');
  });

  createMainWindow();
  createMiniWindow();
});

app.on('window-all-closed', () => {
  // 미니창이 항상 떠있으므로 여기선 아무것도 안 함
});

app.on('before-quit', () => {
  app.isQuiting = true;
});