import { app, BrowserWindow, shell } from "electron";
import { join } from "node:path";
import { startSidecar, stopSidecar, type SidecarHandle } from "./sidecar";

const isDev = !app.isPackaged;
const WINDOW_TITLE = "Laborster";
const BG = "#1b1d23";

let mainWindow: BrowserWindow | null = null;
let sidecar: SidecarHandle | null = null;

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

app.on("window-all-closed", async () => {
  await stopSidecar(sidecar);
  sidecar = null;
  app.quit();
});

app.on("before-quit", async () => {
  await stopSidecar(sidecar);
  sidecar = null;
});
