import { contextBridge } from "electron";

function readArg(prefix: string): string {
  const hit = process.argv.find((a) => a.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : "";
}

const baseUrl = readArg("--bridge-base=");
const token = readArg("--bridge-token=");

contextBridge.exposeInMainWorld("bridge", {
  baseUrl,
  token,
});
