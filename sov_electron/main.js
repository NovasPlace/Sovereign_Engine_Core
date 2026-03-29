const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const net = require('net');
const fs = require('fs');

app.disableHardwareAcceleration();

let mainWindow;
let backendProcess = null;

const IS_WIN    = process.platform === 'win32';
const IS_PACKED = app.isPackaged;

// Source files — read-only inside AppImage squashfs
// (safe to resolve at module level — doesn't call app.getPath)
const RESOURCE_BACKEND = IS_PACKED
  ? path.join(path.dirname(process.execPath), '..', 'Resources', 'backend')
  : path.resolve(__dirname, '..');

let TARGET_PORT = 8002;
let TARGET_URL  = `http://127.0.0.1:${TARGET_PORT}/`;

// ── Port finder ───────────────────────────────────────────
function findFreePort(start, cb) {
  const s = net.createServer();
  s.listen(start, '127.0.0.1', () => { const p = s.address().port; s.close(() => cb(p)); });
  s.on('error', () => findFreePort(start + 1, cb));
}

// ── Window ────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400, height: 860,
    minWidth: 900, minHeight: 600,
    title: 'Sovereign // engine runtime',
    webPreferences: { nodeIntegration: false, contextIsolation: true },
    backgroundColor: '#080c09',
  });

  mainWindow.setMenuBarVisibility(false);
  mainWindow.loadURL(TARGET_URL);

  // Retry until backend is up
  mainWindow.webContents.on('did-fail-load', (e, code, desc) => {
    if (code === 0) return;
    console.log(`[SOVEREIGN] Load failed (${code}). Retrying in 1.5s...`);
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.loadURL(TARGET_URL);
    }, 1500);
  });
}

// ── First-run: copy read-only resources → writable dir ───
function extractBackend(workDir, cb) {
  const resourceBackend = IS_PACKED
    ? path.join(process.resourcesPath, 'backend')
    : path.resolve(__dirname, '..');

  console.log(`[SOVEREIGN] Extracting backend from: ${resourceBackend}`);
  console.log(`[SOVEREIGN] Extracting backend to:   ${workDir}`);
  try {
    fs.mkdirSync(workDir, { recursive: true });
    fs.cpSync(resourceBackend, workDir, { recursive: true });
    console.log('[SOVEREIGN] Backend extracted OK.');
  } catch (err) {
    console.error('[SOVEREIGN] Extract error:', err.message);
  }
  cb();
}

// ── Install venv if missing ───────────────────────────────
function runInstall(workDir, cb) {
  console.log('[SOVEREIGN] Installing dependencies in:', workDir);
  const args = IS_WIN ? ['cmd.exe', ['/c', 'install.bat']] : ['/bin/bash', ['install.sh']];
  const proc = spawn(args[0], args[1], { cwd: workDir, stdio: 'inherit' });
  proc.on('close', (code) => { console.log('[SOVEREIGN] install exit:', code); cb(); });
  proc.on('error', (err) => { console.error('[SOVEREIGN] Install error:', err.message); cb(); });
}

// ── Start backend guardian ────────────────────────────────
function startBackend(workDir, port) {
  TARGET_PORT = port;
  TARGET_URL  = `http://127.0.0.1:${port}/`;

  const env = Object.assign({}, process.env, {
    SOV_PORT: String(port),
    SOV_ELECTRON: '1'
  });

  const args = IS_WIN ? ['cmd.exe', ['/c', 'start.bat']] : ['/bin/bash', ['start.sh']];
  console.log(`[SOVEREIGN] Starting backend on port ${port} from: ${workDir}`);
  backendProcess = spawn(args[0], args[1], { cwd: workDir, stdio: 'inherit', env });
  backendProcess.on('error', (err) => console.error('[SOVEREIGN] Backend error:', err.message));

  // Give guardian time to bind, then open window
  setTimeout(createWindow, 4000);
}

// ── Boot sequence (runs AFTER app.whenReady) ──────────────
function boot() {
  // Safe to call app.getPath now — app is ready
  const workDir = IS_PACKED
    ? path.join(app.getPath('userData'), 'engine')
    : path.resolve(__dirname, '..');

  const venvPython = path.join(workDir, '.venv', IS_WIN ? 'Scripts/python.exe' : 'bin/python3');
  const venvUvicorn = path.join(workDir, '.venv', IS_WIN ? 'Scripts/uvicorn.exe' : 'bin/uvicorn');
  const startScript = path.join(workDir, IS_WIN ? 'start.bat' : 'start.sh');

  console.log('[SOVEREIGN] workDir:', workDir);
  console.log('[SOVEREIGN] IS_PACKED:', IS_PACKED);

  findFreePort(8002, (port) => {
    const needsExtract = IS_PACKED && !fs.existsSync(startScript);
    const needsInstall = !fs.existsSync(venvPython) || !fs.existsSync(venvUvicorn);


    console.log('[SOVEREIGN] needsExtract:', needsExtract, '| needsInstall:', needsInstall);

    if (needsExtract) {
      extractBackend(workDir, () => runInstall(workDir, () => startBackend(workDir, port)));
    } else if (needsInstall) {
      runInstall(workDir, () => startBackend(workDir, port));
    } else {
      startBackend(workDir, port);
    }
  });
}

app.whenReady().then(boot);

app.on('window-all-closed', () => {
  if (backendProcess) backendProcess.kill();
  if (process.platform !== 'darwin') app.quit();
});
