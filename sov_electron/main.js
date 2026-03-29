const { app, BrowserWindow } = require('electron');
const { spawn, execFileSync } = require('child_process');
const path = require('path');
const net = require('net');
const fs = require('fs');

app.disableHardwareAcceleration();

let mainWindow;
let backendProcess = null;

const IS_WIN = process.platform === 'win32';
const IS_PACKAGED = app.isPackaged;

// Resolve backend root:
// - Packaged: electron-builder places extraResources at process.resourcesPath/backend
// - Dev:      parent directory of sov_electron/
const PROJECT_ROOT = IS_PACKAGED
  ? path.join(process.resourcesPath, 'backend')
  : path.resolve(__dirname, '..');

const START_SCRIPT = IS_WIN
  ? path.join(PROJECT_ROOT, 'start.bat')
  : path.join(PROJECT_ROOT, 'start.sh');

const INSTALL_SCRIPT = IS_WIN
  ? path.join(PROJECT_ROOT, 'install.bat')
  : path.join(PROJECT_ROOT, 'install.sh');

const VENV_PYTHON = IS_WIN
  ? path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe')
  : path.join(PROJECT_ROOT, '.venv', 'bin', 'python3');

let TARGET_PORT = 8002;
let TARGET_URL = `http://127.0.0.1:${TARGET_PORT}/`;

function findFreePort(startPort, callback) {
  const server = net.createServer();
  server.listen(startPort, '127.0.0.1', () => {
    const port = server.address().port;
    server.close(() => callback(port));
  });
  server.on('error', () => findFreePort(startPort + 1, callback));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 860,
    minWidth: 900,
    minHeight: 600,
    title: 'Sovereign // engine runtime',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true
    },
    backgroundColor: '#080c09'
  });

  mainWindow.setMenuBarVisibility(false);
  mainWindow.loadURL(TARGET_URL);

  // Retry on connection refused — backend may still be warming up
  mainWindow.webContents.on('did-fail-load', (e, code, desc) => {
    if (code === 0) return;
    console.log(`[SOVEREIGN] Load failed (${code}: ${desc}). Retrying in 1.5s...`);
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.loadURL(TARGET_URL);
    }, 1500);
  });

  mainWindow.webContents.on('did-finish-load', () => {
    console.log('[SOVEREIGN] UI loaded.');
  });
}

function runInstall(callback) {
  console.log('[SOVEREIGN] First run detected — running installer...');
  const installer = IS_WIN
    ? spawn('cmd.exe', ['/c', INSTALL_SCRIPT], { cwd: PROJECT_ROOT, stdio: 'inherit' })
    : spawn('/bin/bash', [INSTALL_SCRIPT], { cwd: PROJECT_ROOT, stdio: 'inherit' });

  installer.on('close', (code) => {
    if (code !== 0) {
      console.error(`[SOVEREIGN] install.sh exited with code ${code}`);
    }
    callback();
  });

  installer.on('error', (err) => {
    console.error('[SOVEREIGN] Failed to run installer:', err);
    callback(); // proceed anyway, let start.sh handle it
  });
}

function startBackend(port) {
  TARGET_PORT = port;
  TARGET_URL = `http://127.0.0.1:${TARGET_PORT}/`;

  const env = Object.assign({}, process.env, { SOV_PORT: TARGET_PORT.toString() });

  console.log(`[SOVEREIGN] Spawning backend on port ${TARGET_PORT} from: ${PROJECT_ROOT}`);

  if (IS_WIN) {
    backendProcess = spawn('cmd.exe', ['/c', START_SCRIPT], {
      cwd: PROJECT_ROOT,
      stdio: 'inherit',
      env
    });
  } else {
    backendProcess = spawn('/bin/bash', [START_SCRIPT], {
      cwd: PROJECT_ROOT,
      stdio: 'inherit',
      env
    });
  }

  backendProcess.on('error', (err) => {
    console.error('[SOVEREIGN] Backend spawn failed:', err);
  });

  // Give guardian 4s to bind before opening the window
  setTimeout(createWindow, 4000);
}

function startBackendAndWindow() {
  findFreePort(8002, (port) => {
    // If venv doesn't exist, run installer first
    if (!fs.existsSync(VENV_PYTHON)) {
      runInstall(() => startBackend(port));
    } else {
      startBackend(port);
    }
  });
}

app.whenReady().then(startBackendAndWindow);

app.on('window-all-closed', () => {
  if (backendProcess) backendProcess.kill();
  if (process.platform !== 'darwin') app.quit();
});
