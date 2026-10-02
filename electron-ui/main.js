const {
  app, BrowserWindow, globalShortcut, ipcMain, screen, session
} = require('electron');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');

let mainWindow = null;
let pointerWindow = null;   // 포인팅 오버레이 (M4) — 전체화면 · 클릭 통과
let pointerTimer  = null;
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
      // 🚨 BL-33 — 발화 종료 감지가 렌더러의 setInterval(50ms)로 돈다.
      //    창이 뒤로 가면 Chromium이 타이머를 1초에 한 번으로 줄이는데,
      //    그러면 «무음 1.2초»를 제때 못 봐서 녹음이 상한(30초)까지 간다.
      //    사용자가 말하면서 다른 창을 누르는 건 흔한 일이다.
      backgroundThrottling: false,
    },
  });

  mainWindow.setAlwaysOnTop(true, 'screen-saver');
  mainWindow.loadFile('renderer/index.html');
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('close', e => { if (!forceQuit) e.preventDefault(); });
}

// 🚨 **사용자가 옮겨 놓은 자리를 기억한다** (BL-85 · 2026-10-02 실기).
//
//   예전엔 여기서 `getPos()` 를 불러 **화면 하단 중앙을 매번 다시 계산**했다.
//   그래서 창을 끌어다 옮겨 놔도 **접었다 펴면 제자리로 돌아갔다** — 옮긴 자리를
//   아무도 기억하지 않았다.
//
// 🔑 **«아래 가운데»를 고정점으로 삼는다.** 접힌 알약과 펼친 창은 너비·높이가
//   다른데, 왼쪽 위를 맞추면 펼칠 때 오른쪽 아래로 흘러내리고, 가운데를 맞추면
//   아래로 자란다. 이 UI 는 **화면 아래쪽에 두고 쓰는 물건**이라 아래 가장자리가
//   제자리에 있는 것이 자연스럽다.
function anchorBounds(cur, w, h) {
  // 지금 창의 **아래 가운데**가 그대로 있도록 새 좌표를 만든다.
  return {
    x: Math.round(cur.x + cur.width / 2 - w / 2),
    y: Math.round(cur.y + cur.height - h),
    width: w, height: h,
  };
}

// 🚨 **화면 밖으로 내보내지 않는다.** 모니터를 뽑았거나 해상도가 바뀌었거나,
//   가장자리에 바짝 붙여 둔 채 창이 커지면 **창이 안 보이게 된다** — 그러면
//   사용자는 프로그램이 죽은 줄 안다. 되돌릴 방법도 눈에 안 보인다.
function clampToArea(b, area) {
  const x = Math.min(Math.max(b.x, area.x), area.x + area.width - b.width);
  const y = Math.min(Math.max(b.y, area.y), area.y + area.height - b.height);
  return { x: Math.round(x), y: Math.round(y), width: b.width, height: b.height };
}

function resizeTo(mode) {
  if (!mainWindow) return;
  const { w, h } = SIZE[mode];
  const cur = mainWindow.getBounds();
  // 🔑 **지금 창이 올라가 있는 모니터**의 작업 영역을 쓴다. 주 모니터로 고정하면
  //   보조 모니터에 올려 둔 창이 펼칠 때 주 모니터로 튀어 간다.
  const area = screen.getDisplayMatching(cur).workArea;
  mainWindow.setBounds(clampToArea(anchorBounds(cur, w, h), area), true);
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
    // 🗣 말 판정 상태 (M10). 🚨 **`WAKE` 검사보다 먼저 본다** — 이 줄에는
    //   `WAKE` 가 안 들어가지만, 순서를 지켜야 다음에 이름을 바꿔도 안 터진다.
    //   🔑 한 번에 여러 줄이 뭉쳐 올 수 있어서 **마지막 상태만** 쓴다.
    const sp = out.match(/VAD_SPEECH ([01])/g);
    if (sp) {
      const on = sp[sp.length - 1].endsWith('1');
      mainWindow?.webContents.send('vad-speech', on);
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

// ── 말 거는 단축키 (2026-10-02) ───────────────────────────────────
//
// 🔑 **호출어를 끄지 않고 둘 다 쓴다.** 전시장처럼 「남의 말소리」가 많은 자리는
//   호출어의 헛깨어남을 임계로 못 죽이는 조건이고, 단축키는 그게 **구조적으로 0** 이다.
//
// 🚨 **등록은 실패할 수 있다.** 다른 프로그램이 이미 그 키를 잡고 있으면
//   `globalShortcut.register()` 가 **false 를 돌려준다.** 그걸 안 보면
//   «설정에 저장은 됐는데 눌러도 아무 일이 없는» 상태가 된다 —
//   [BL-13](../docs/BACKLOG.md)이 막으려던 바로 그 모양이다. 그래서 **말한다.**
//
// ⚠️ **여기에 기본값을 두지 않는다.** 주인은 `config/settings.py` 하나다 —
//   두 곳에 있으면 «설정은 바뀌었는데 실제로 듣는 키는 그대로»가 된다(BL-13).
let currentHotkey = null;

/** 단축키를 실제로 잡는다. `{ ok, hotkey, previous }` 를 돌려준다. */
function applyHotkey(key) {
  const want = (key || '').trim();
  if (!want) return { ok: false, hotkey: currentHotkey, previous: currentHotkey };
  if (want === currentHotkey) return { ok: true, hotkey: want, previous: currentHotkey };

  const previous = currentHotkey;
  if (previous) globalShortcut.unregister(previous);

  let ok = false;
  try {
    ok = globalShortcut.register(want, () => {
      mainWindow?.show();
      mainWindow?.focus();
      mainWindow?.webContents.send('toggle-active');
    });
  } catch (e) {
    // 문법이 틀린 accelerator 는 예외를 던진다 ('Ctrl+' 같은 것)
    console.error('[hotkey] 등록 예외:', e.message);
    ok = false;
  }

  if (ok) {
    currentHotkey = want;
    console.log('[hotkey] 등록:', want);
    return { ok: true, hotkey: want, previous };
  }

  // 🔑 **실패했으면 쓰던 키로 되돌린다.** 안 그러면 «새 키는 안 되고 옛 키도 없는»
  //   상태가 되어, 사용자가 말 걸 길을 하나 잃는다.
  console.error('[hotkey] 등록 실패:', want);
  if (previous && globalShortcut.register(previous, () => {
    mainWindow?.show();
    mainWindow?.focus();
    mainWindow?.webContents.send('toggle-active');
  })) {
    currentHotkey = previous;
  } else {
    currentHotkey = null;
  }
  return { ok: false, hotkey: currentHotkey, previous };
}

app.whenReady().then(() => {
  session.defaultSession.setPermissionRequestHandler((wc, permission, cb) => {
    cb(permission === 'media' || permission === 'audioCapture');
  });
  session.defaultSession.setPermissionCheckHandler((wc, permission) => {
    return permission === 'media' || permission === 'audioCapture';
  });

  createWindow();

  // 🔑 **여기서 아무 키도 안 잡는다.** 기본값의 주인은 `config/settings.py` 하나고,
  //   이 프로세스는 서버를 모른다(토큰 파일만 읽는다). 설정을 읽는 렌더러가
  //   곧바로 `setHotkey` 로 알려 준다 — 못 읽어도 기본값으로 한 번은 잡는다.
  // 🚨 여기에 기본값을 적어 두면 **잠깐이라도 틀린 키를 전역으로 가로챈다.**

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

// ── 포인팅 오버레이 (M4) ──────────────────────────────────────────
// *"블루투스 어디 있어?"* → 화면의 그 자리에 고리를 그린다.
// 설계 근거는 docs/design/M4_포인팅_확대.md. 여기서 중요한 것은 두 줄이다:
//
//   focusable: false        — 포커스를 절대 뺏지 않는다
//   setIgnoreMouseEvents    — 클릭을 통과시킨다
//
// ⚠️ 둘 중 하나라도 빠지면 **가리키려던 버튼을 우리가 덮어서 못 누르게 된다.**
//    도우려다 방해하는, 이 기능 최악의 실패다 (ADR §4-1).
//    자동 테스트가 못 잡는 자리이므로 손대면 반드시 사람이 눌러 봐야 한다.
//
// ⚠️ 주 모니터에만 띄운다. Vision이 주 모니터만 보므로(BL-18) 좌표도 주 모니터
//    것이다. 보조 모니터로 넓히면 **틀린 화면에 그린다.**
function ensurePointerWindow() {
  if (pointerWindow && !pointerWindow.isDestroyed()) return pointerWindow;

  const b = screen.getPrimaryDisplay().bounds;
  pointerWindow = new BrowserWindow({
    x: b.x, y: b.y, width: b.width, height: b.height,
    frame: false, transparent: true, hasShadow: false,
    alwaysOnTop: true, skipTaskbar: true,
    focusable: false,          // ★ 포커스를 뺏지 않는다
    resizable: false, movable: false, show: false,
    webPreferences: {
      preload: path.join(__dirname, 'pointer-preload.js'),
      contextIsolation: true, nodeIntegration: false,
    },
  });
  pointerWindow.setIgnoreMouseEvents(true, { forward: true });   // ★ 클릭 통과
  pointerWindow.setAlwaysOnTop(true, 'screen-saver');
  pointerWindow.loadFile('renderer/pointer.html');
  pointerWindow.on('closed', () => { pointerWindow = null; });
  return pointerWindow;
}

// 🚨 파이썬이 주는 좌표는 **물리 픽셀**이고 Electron의 창·CSS는 **DIP**다.
// 2026-09-09 실측: 이 PC는 물리 3072×1920 / DIP 1536×960 — **배율 2.0**.
// 변환하지 않으면 고리가 정확히 배율만큼 어긋난 자리에 그려진다(실기에서 그랬다).
//   물리 (974, 778)  →  DIP (487, 389)
// ⚠️ 「화면이 크니까 대충 맞겠지」로 넘길 수 없다. 배율 100%인 PC에서는 이 버그가
//    **보이지 않으므로**, 여기를 고치면서 배율 없는 환경만 보고 판단하지 말 것.
function toDip(x, y) {
  try {
    const p = screen.screenToDipPoint({ x: Math.round(x), y: Math.round(y) });
    if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) return p;
  } catch (e) { /* 아래 배율 나눗셈으로 폴백 */ }
  const sf = screen.getPrimaryDisplay().scaleFactor || 1;
  return { x: x / sf, y: y / sf };
}

function showPointer(p) {
  const win = ensurePointerWindow();
  const b = screen.getPrimaryDisplay().bounds;      // DIP

  // 물리 픽셀 → DIP 로 옮긴 뒤에 보낸다. 렌더러는 CSS px(=DIP)로만 계산한다.
  const conv = { ...p };
  if (Array.isArray(p.rect) && p.rect.length === 4) {
    const a = toDip(p.rect[0], p.rect[1]);
    const c = toDip(p.rect[2], p.rect[3]);
    conv.rect = [a.x, a.y, c.x, c.y];
  }
  if (Array.isArray(p.center) && p.center.length === 2) {
    const m = toDip(p.center[0], p.center[1]);
    conv.center = [m.x, m.y];
  }

  // 돋보기가 «잘라 온 영역»도 물리 픽셀이다. 화면에 그릴 지름을 여기서 정한다.
  if (conv.zoomImage && conv.zoomSrcPx) {
    const sf = screen.getPrimaryDisplay().scaleFactor || 1;
    conv.zoomDip = (conv.zoomSrcPx / sf) * (conv.zoomMag || 3);
  }

  const send = () => {
    // 화면 좌표 → 오버레이 창 기준 좌표. 원점이 (0,0)이 아닌 배치가 있어 뺀다.
    win.webContents.send('point-draw', { ...conv, originX: b.x, originY: b.y });
    win.showInactive();        // ★ show()가 아니다 — 포커스를 가져오지 않는다
  };
  if (win.webContents.isLoading()) win.webContents.once('did-finish-load', send);
  else send();

  // 해제 ① 자동 — **마지막 방어선이다.** always-on-top 전체화면 오버레이가
  // 남으면 PC를 못 쓰게 만든다. 이 타이머를 «사용자가 끄면 되니까»로 빼지 말 것.
  clearTimeout(pointerTimer);
  const ms = Math.max(1, Number(p.seconds) || 8) * 1000;
  pointerTimer = setTimeout(hidePointer, ms);
}

function hidePointer() {
  clearTimeout(pointerTimer);
  pointerTimer = null;
  if (pointerWindow && !pointerWindow.isDestroyed()) pointerWindow.hide();
}

ipcMain.on('point-show', (_e, p) => { try { showPointer(p); } catch (e) { console.error('[point]', e); } });
ipcMain.on('point-hide', () => hidePointer());

// 렌더러가 API를 부르기 전에 이걸로 토큰을 받아 간다 (BL-14).
// 서버가 늦게 뜨면 여기서 기다리므로, 렌더러는 그냥 await 하면 된다.
ipcMain.handle('get-token', () => waitForToken());

// 화면 감시 알림 — 웨이크워드와 같은 경로로 창을 앞으로 꺼낸다 (Phase 2).
// 사용자가 다른 창을 보고 있을 때 알림이 뒤에 묻히면 감시가 무의미하다.
ipcMain.on('show-window',   () => { mainWindow?.show(); mainWindow?.focus(); });

ipcMain.on('resize-idle',   () => resizeTo('idle'));
ipcMain.on('resize-active', () => resizeTo('active'));
// 렌더러가 설정을 읽거나 저장하면 이걸로 **실제 적용**을 시킨다.
// 🚨 돌려주는 값을 UI 가 그대로 말한다 — «저장됨»과 «잡혔음»은 다른 일이다.
ipcMain.handle('set-hotkey', (_e, key) => applyHotkey(key));

ipcMain.on('quit-app',      () => { forceQuit = true; hidePointer(); wakeProc?.kill(); app.quit(); });
