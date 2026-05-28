import { spawn, type ChildProcessByStdio } from "node:child_process";
import type { Readable } from "node:stream";
import { join } from "node:path";
import { app } from "electron";

type SidecarProc = ChildProcessByStdio<null, Readable, Readable>;

export interface SidecarHandle {
  proc: SidecarProc;
  baseUrl: string;
  token: string;
}

interface StartOpts {
  packaged: boolean;
  resourcesPath: string;
}

// Sidecar prints exactly one line in this shape on stdout once it is
// listening, then keeps streaming logs. Main blocks on that handshake
// so the renderer never loads with a stale baseUrl/token.
const READY_RE = /^BRIDGE_READY port=(\d+) token=(\S+)$/;
const HANDSHAKE_TIMEOUT_MS = 8000;

interface Launch {
  command: string;
  args: string[];
  cwd: string;
}

// Packaged: run the PyInstaller-frozen binary (no Python on the user's
// machine). Dev: run server.py with the local interpreter, cwd at the
// sidecar dir so `import laborster_bridge` resolves.
function launchSpec(opts: StartOpts): Launch {
  const binName = process.platform === "win32" ? "laborster-sidecar.exe" : "laborster-sidecar";
  if (opts.packaged) {
    const dir = join(opts.resourcesPath, "sidecar");
    return { command: join(dir, binName), args: [], cwd: dir };
  }
  const dir = join(app.getAppPath(), "sidecar");
  const python =
    process.env.LABORSTER_PYTHON || (process.platform === "win32" ? "python" : "python3");
  return { command: python, args: ["server.py"], cwd: dir };
}

export function startSidecar(opts: StartOpts): Promise<SidecarHandle> {
  return new Promise((resolve, reject) => {
    const { command, args, cwd } = launchSpec(opts);
    const proc = spawn(command, args, {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });

    let settled = false;
    let buf = "";

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      proc.kill();
      reject(new Error("sidecar handshake timeout"));
    }, HANDSHAKE_TIMEOUT_MS);

    proc.stdout.on("data", (chunk: Buffer) => {
      buf += chunk.toString("utf8");
      let nl: number;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!settled) {
          const m = line.match(READY_RE);
          if (m) {
            settled = true;
            clearTimeout(timer);
            resolve({
              proc,
              baseUrl: `http://127.0.0.1:${m[1]}`,
              token: m[2],
            });
            continue;
          }
        }
        if (line) console.log(`[sidecar] ${line}`);
      }
    });

    proc.stderr.on("data", (chunk: Buffer) => {
      process.stderr.write(`[sidecar] ${chunk.toString("utf8")}`);
    });

    proc.on("exit", (code, signal) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(new Error(`sidecar exited before ready (code=${code} signal=${signal})`));
      } else {
        console.log(`[sidecar] exited code=${code} signal=${signal}`);
      }
    });

    proc.on("error", (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(err);
    });
  });
}

export async function stopSidecar(handle: SidecarHandle | null): Promise<void> {
  if (!handle || handle.proc.exitCode !== null) return;
  await new Promise<void>((resolve) => {
    const proc = handle.proc;
    const done = () => resolve();
    proc.once("exit", done);
    try {
      proc.kill("SIGTERM");
    } catch {
      resolve();
      return;
    }
    setTimeout(() => {
      if (proc.exitCode === null) {
        try {
          proc.kill("SIGKILL");
        } catch {
          /* ignore */
        }
      }
    }, 2000);
  });
}
