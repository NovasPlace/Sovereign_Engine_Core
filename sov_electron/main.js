const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const net = require('net');

app.disableHardwareAcceleration();

let mainWindow;
let backendProcess = null;

let PROJECT_ROOT = path.resolve(__dirname, '..');
// When packaged as an AppImage, the application files are mounted in a temp dir.
// The actual executable location from the user's perspective is process.env.APPIMAGE,
if (process.env.APPIMAGE) {
  PROJECT_ROOT = path.dirname(process.env.APPIMAGE);
} else if (__dirname.includes('app.asar')) {
  // If unpacked from asar but no APPIMAGE (e.g., Windows/Mac), fallback to the executable dir
  PROJECT_ROOT = path.dirname(process.execPath);
}
const START_SCRIPT = path.join(PROJECT_ROOT, 'start.sh');
let TARGET_PORT = 8002;
let TARGET_URL = `http://localhost:${TARGET_PORT}/`;

function findFreePort(startPort, callback) {
  const server = net.createServer();
  server.listen(startPort, '127.0.0.1', () => {
    const port = server.address().port;
    server.close(() => callback(port));
  });
  server.on('error', () => {
    findFreePort(startPort + 1, callback);
  });
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
    backgroundColor: '#0a0a0c',
    show: true
  });

  mainWindow.setMenuBarVisibility(false);
  mainWindow.loadURL(TARGET_URL);

  // Retry on failure — backend may still be warming up
  mainWindow.webContents.on('did-fail-load', (e, code, desc) => {
    // Codes -3 (aborted), -6 (connection refused) — keep retrying until backend is back
    if (code === 0) return; // normal navigation, not an error
    console.log(`[SOVEREIGN-ELECTRON] Load failed (${code}: ${desc}). Retrying in 1.5s...`);
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.loadURL(TARGET_URL);
    }, 1500);
  });

  mainWindow.webContents.on('did-finish-load', () => {
    console.log('[SOVEREIGN-ELECTRON] UI loaded successfully.');
  });
}

function startBackendAndWindow() {
  findFreePort(8002, (port) => {
    TARGET_PORT = port;
    TARGET_URL = `http://localhost:${TARGET_PORT}/`;
    console.log(`[SOVEREIGN-ELECTRON] Auto-port selected: ${TARGET_PORT}`);
    console.log(`[SOVEREIGN-ELECTRON] Spawning Guardian: ${START_SCRIPT}`);
    
    const env = Object.assign({}, process.env, { SOV_PORT: TARGET_PORT.toString() });
    
    backendProcess = spawn('/bin/bash', [START_SCRIPT], {
      cwd: PROJECT_ROOT,
      stdio: 'inherit',
      env: env
    });
    
    backendProcess.on('error', (err) => {
      console.error(`[SOVEREIGN-ELECTRON] Failed to start backend:`, err);
    });
    
    // Give the backend 2s to bind before opening the window
    setTimeout(createWindow, 2000);
  });
}

app.whenReady().then(startBackendAndWindow);

app.on('window-all-closed', () => {
  if (backendProcess) backendProcess.kill();
  if (process.platform !== 'darwin') app.quit();
});
