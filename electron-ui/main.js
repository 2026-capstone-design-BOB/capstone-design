const {
  app, BrowserWindow, globalShortcut, ipcMain, screen, session
} = require('electron');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');

let mainWindow = null;
let wakeProc   = null;
let wakePython = null;   // 웨이크워드용 python 경로 (탐색 결과 캐시)
let wakeFails  = 0;      // 연속 즉시 실패 횟수 — 무한 재시도 방지
let forceQuit  = false;

const SIZE = {
  idle:   { w: 280, h: 64  },
  active: { w: 420, h: 340 },
};

function getPos(w, h) {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  return { x: Math.round((width - w) / 2), y: height - h - 16 };
}

function createWindow() {
  const { w, h } = SIZE.idle;
  const pos = getPos(w, h);

  mainWindow = new BrowserWindow({
    width: w, height: h, x: pos.x, y: pos.y,
    frame: false, transparent: true,
    alwaysOnTop: true, skipTaskbar: true,
    resizable: false, movable: true, show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.setAlwaysOnTop(true, 'screen-saver');
  mainWindow.loadFile('renderer/index.html');
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('close', e => { if (!forceQuit) e.preventDefault(); });
}

function resizeTo(mode) {
  if (!mainWindow) return;
  const { w, h } = SIZE[mode];
  const pos = getPos(w, h);
  mainWindow.setBounds({ x: pos.x, y: pos.y, width: w, height: h }, true);
}

// 웨이크워드용 python 찾기
// ─────────────────────────────────────────────────────────────────
// ⚠️ 그냥 'python'을 쓰면 안 된다. Windows에서 그건 보통 anaconda **base**로
// 잡히는데 거기엔 sounddevice·faster-whisper가 없다. 그래서 2026-09-02 이전까지
// wakeword.py는 뜨자마자 exit(1) 하고 아래 재시도 로직이 5초마다 조용히 다시 띄우기만
// 했다 — 웨이크워드가 한 번도 동작한 적이 없는데 아무도 몰랐다.
// 후보를 실제로 import 시켜보고 되는 놈을 고른다.
function resolvePython() {
  if (wakePython) return wakePython;

  const candidates = [];
  if (process.env.PLUIZ_PYTHON) candidates.push(process.env.PLUIZ_PYTHON);   // 명시 지정이 최우선

  const home = process.env.USERPROFILE || process.env.HOME || '';
  if (home) {
    // conda 환경 'pluiz' (프로젝트 표준 — docs/WORKFLOW.md)
    candidates.push(path.join(home, 'anaconda3', 'envs', 'pluiz', 'python.exe'));
    candidates.push(path.join(home, 'miniconda3', 'envs', 'pluiz', 'python.exe'));
  }
  candidates.push('python');   // 마지막 폴백

  const probe = 'import sounddevice, faster_whisper';
  for (const py of candidates) {
    try {
      const r = spawnSync(py, ['-c', probe], { timeout: 20000 });
      if (r.status === 0) {
        console.log(`[wake] python 확정: ${py}`);
        wakePython = py;
        return py;
      }
      console.log(`[wake] 후보 탈락: ${py} (${r.status})`);
    } catch (e) {
      console.log(`[wake] 후보 실행 불가: ${py}`);
    }
  }
  return null;
}

// 로컬 API 접근 토큰 읽기 (BL-14)
// ─────────────────────────────────────────────────────────────────
// 서버(python main.py)가 기동할 때 cache/.auth_token 에 토큰을 적는다.
// 웹페이지는 로컬 파일을 못 읽으므로, 이 파일을 읽을 수 있다는 것 자체가 신원 증명이다.
//
// ⚠️ 서버는 Electron이 띄우는 게 아니다 — launch.bat 이 둘을 따로 띄운다.
// 그래서 env로 토큰을 건네받을 수 없고, UI가 서버보다 먼저 뜰 수도 있다.
// 파일이 생길 때까지 기다린다.
const TOKEN_FILE = path.join(__dirname, '..', 'cache', '.auth_token');

function readTokenOnce() {
  try {
    return fs.readFileSync(TOKEN_FILE, 'utf8').trim();
  } catch (e) {
    return '';
  }
}

async function waitForToken(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const t = readTokenOnce();
    if (t) return t;
    if (Date.now() >= deadline) {
      console.error('[auth] 토큰 파일을 찾지 못했습니다:', TOKEN_FILE);
      console.error('[auth] 서버(python main.py)가 실행 중인지 확인하세요.');
      return '';
    }
    await new Promise(r => setTimeout(r, 300));
  }
}

function startWakeword() {
  const script = path.join(__dirname, '..', 'services', 'wakeword.py');
  if (!fs.existsSync(script)) {
    console.log('[wake] wakeword.py not found, skipping');
    return;
  }

  const py = resolvePython();
  if (!py) {
    // 조용히 재시도하지 않는다 — 원인이 환경이라 재시도해도 절대 안 고쳐진다.
    const msg = 'sounddevice·faster-whisper가 설치된 python을 찾지 못했습니다. '
              + 'PLUIZ_PYTHON 환경변수로 지정하거나 pluiz 환경에 설치하세요.';
    console.error('[wake]', msg);
    mainWindow?.webContents.send('wakeword-status', 'unavailable');
    return;
  }

  wakeProc = spawn(py, [script], {
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: false,
    // Windows 콘솔이 cp949라 한글 로그가 깨진다. 파이썬 쪽 출력을 UTF-8로 고정한다.
    // (그래도 부모 터미널 표시가 깨질 수 있으므로 정확한 기록은 logs/pluiz.log를 볼 것)
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
  });

  wakeProc.stdout.setEncoding('utf8');
  wakeProc.stderr.setEncoding('utf8');

  const startedAt = Date.now();

  wakeProc.stdout.on('data', data => {
    const out = String(data);
    if (out.includes('WAKEWORD_ERROR')) {
      console.error('[wake] 시작 실패:', out.trim());
      mainWindow?.webContents.send('wakeword-status', 'unavailable');
      return;
    }
    if (out.includes('WAKE')) {
      console.log('[wake] detected');
      mainWindow?.show();
      mainWindow?.focus();
      mainWindow?.webContents.send('wake-detected');
    }
  });

  wakeProc.stderr.on('data', data => {
    const msg = String(data).trim();
    console.log('[wake stderr]', msg);
    if (msg.includes('준비 완료')) {
      wakeFails = 0;                 // 정상 기동 → 실패 카운터 리셋
      mainWindow?.webContents.send('wakeword-status', 'ready');
    }
  });

  wakeProc.on('exit', code => {
    console.log(`[wake] exited ${code}`);
    if (code === 0 || code === null) return;

    // 뜨자마자 죽으면(=환경 문제) 재시도가 의미 없다. 3번까지만 해보고 포기하고 알린다.
    if (Date.now() - startedAt < 10000) {
      wakeFails += 1;
      if (wakeFails >= 3) {
        console.error('[wake] 연속 3회 즉시 종료 — 재시도 중단. 로그를 확인하세요.');
        mainWindow?.webContents.send('wakeword-status', 'unavailable');
        return;
      }
    } else {
      wakeFails = 0;                 // 한동안 돌다 죽은 건 일시적 문제로 본다
    }
    setTimeout(startWakeword, 5000);
  });

  wakeProc.on('error', err => console.error('[wake] error:', err));
}

app.whenReady().then(() => {
  session.defaultSession.setPermissionRequestHandler((wc, permission, cb) => {
    cb(permission === 'media' || permission === 'audioCapture');
  });
  session.defaultSession.setPermissionCheckHandler((wc, permission) => {
    return permission === 'media' || permission === 'audioCapture';
  });

  createWindow();

  globalShortcut.register('Alt+Space', () => {
    mainWindow?.show();
    mainWindow?.focus();
    mainWindow?.webContents.send('toggle-active');
  });

  startWakeword();
});

app.on('before-quit', () => { forceQuit = true; });

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  wakeProc?.kill();
});

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => { mainWindow?.show(); mainWindow?.focus(); });
}

// 렌더러가 API를 부르기 전에 이걸로 토큰을 받아 간다 (BL-14).
// 서버가 늦게 뜨면 여기서 기다리므로, 렌더러는 그냥 await 하면 된다.
ipcMain.handle('get-token', () => waitForToken());

// 화면 감시 알림 — 웨이크워드와 같은 경로로 창을 앞으로 꺼낸다 (Phase 2).
// 사용자가 다른 창을 보고 있을 때 알림이 뒤에 묻히면 감시가 무의미하다.
ipcMain.on('show-window',   () => { mainWindow?.show(); mainWindow?.focus(); });

ipcMain.on('resize-idle',   () => resizeTo('idle'));
ipcMain.on('resize-active', () => resizeTo('active'));
ipcMain.on('quit-app',      () => { forceQuit = true; wakeProc?.kill(); app.quit(); });
