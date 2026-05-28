import { app, BrowserWindow, shell } from "electron";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { startSidecar, killSidecar, type SidecarHandle } from "./sidecar";

const isDev = !app.isPackaged;
const WINDOW_TITLE = "Laborster";
const BG = "#1b1d23";

let mainWindow: BrowserWindow | null = null;
let sidecar: SidecarHandle | null = null;

function windowIcon(): string | undefined {
  const candidate = isDev
    ? join(app.getAppPath(), "build", "icon.png")
    : join(process.resourcesPath, "icon.png");
  return existsSync(candidate) ? candidate : undefined;
}

// Best-effort, synchronous: must finish before the process exits, and must
// take down the PyInstaller child tree (onefile spawns a bootloader child).
function teardownSidecar(): void {
  killSidecar(sidecar);
  sidecar = null;
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
  process.exit(0);
}

app.on("second-instance", () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

async function createWindow(): Promise<void> {
  sidecar = await startSidecar({ packaged: !isDev, resourcesPath: process.resourcesPath });

  mainWindow = new BrowserWindow({
    title: WINDOW_TITLE,
    icon: windowIcon(),
    width: 1180,
    height: 760,
    minWidth: 880,
    minHeight: 600,
    backgroundColor: BG,
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      additionalArguments: [
        `--bridge-base=${sidecar.baseUrl}`,
        `--bridge-token=${sidecar.token}`,
      ],
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.once("ready-to-show", () => mainWindow?.show());

  if (isDev && process.env.VITE_DEV_SERVER_URL) {
    await mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    await mainWindow.loadFile(join(__dirname, "..", "renderer", "index.html"));
  }
}

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  teardownSidecar();
  app.quit();
});

app.on("before-quit", teardownSidecar);
app.on("will-quit", teardownSidecar);
