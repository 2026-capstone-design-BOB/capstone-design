const {
  app, BrowserWindow, globalShortcut, ipcMain, screen, session
} = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');

let mainWindow = null;
let wakeProc   = null;
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

function startWakeword() {
  const script = path.join(__dirname, '..', 'services', 'wakeword.py');
  if (!fs.existsSync(script)) {
    console.log('[wake] wakeword.py not found, skipping');
    return;
  }

  wakeProc = spawn('python', [script], {
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: false,
  });

  wakeProc.stdout.on('data', data => {
    if (data.toString().includes('WAKE')) {
      console.log('[wake] detected');
      mainWindow?.show();
      mainWindow?.focus();
      mainWindow?.webContents.send('wake-detected');
    }
  });

  wakeProc.stderr.on('data', data => {
    const msg = data.toString().trim();
    console.log('[wake stderr]', msg);
    if (msg.includes('준비 완료')) {
      mainWindow?.webContents.send('wakeword-status', 'ready');
    }
  });

  wakeProc.on('exit', code => {
    console.log(`[wake] exited ${code}`);
    if (code !== 0 && code !== null) setTimeout(startWakeword, 5000);
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

ipcMain.on('resize-idle',   () => resizeTo('idle'));
ipcMain.on('resize-active', () => resizeTo('active'));
ipcMain.on('quit-app',      () => { forceQuit = true; wakeProc?.kill(); app.quit(); });
