// frontend-ui/main.js
const { app, BrowserWindow, ipcMain, session, screen } = require('electron');
const path = require('path');

// Web Speech API 네트워크 허용
app.commandLine.appendSwitch('enable-speech-dispatcher');
app.commandLine.appendSwitch('allow-failed-policy-fetch-for-test');
app.commandLine.appendSwitch('unsafely-treat-insecure-origin-as-secure', 'http://localhost:8000');
app.commandLine.appendSwitch('enable-features', 'WebSpeechAPI');

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
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  mainWin.loadFile(path.join(__dirname, 'index.html'));

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
    x: width - 300,
    y: height - 100,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  miniWin.loadFile(path.join(__dirname, 'mini.html'));

  miniWin.on('close', (e) => {
    if (!app.isQuiting) {
      e.preventDefault();
      miniWin.hide();
    }
  });
}

// ── IPC 이벤트 ────────────────────────────────────────────

ipcMain.on('open-main', () => {
  if (mainWin) {
    mainWin.show();
    mainWin.focus();
    if (miniWin) miniWin.hide();
  }
});

ipcMain.on('minimize-to-mini', () => {
  if (mainWin) mainWin.hide();
  if (miniWin) miniWin.show();
});

ipcMain.on('quit-app', () => {
  app.isQuiting = true;
  app.quit();
});

ipcMain.on('wake-state', (event, state) => {
  if (miniWin && !miniWin.isDestroyed()) {
    miniWin.webContents.send('wake-state', state);
  }
});

ipcMain.on('move-mini', (event, { dx, dy }) => {
  if (miniWin) {
    const [x, y] = miniWin.getPosition();
    miniWin.setPosition(x + dx, y + dy);
  }
});

// 미니창에서 음성 인식 결과 → 메인창으로 전달 (창은 열지 않음)
ipcMain.on('mini-voice-command', (event, text) => {
  if (mainWin) {
    // 메인창은 숨긴 상태로 유지, 명령만 전달해서 백그라운드에서 실행
    mainWin.webContents.send('execute-command', text);
  }
});

// ── 앱 초기화 ─────────────────────────────────────────────
app.whenReady().then(() => {
  // ── 권한 허용 (마이크 + Web Speech API) ──
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    const allowed = ['media', 'microphone', 'speech-recognition'];
    callback(allowed.includes(permission));
  });

  // Web Speech API 허용을 위한 체크 핸들러
  session.defaultSession.setPermissionCheckHandler((webContents, permission) => {
    const allowed = ['media', 'microphone', 'speech-recognition'];
    return allowed.includes(permission);
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