/* Headless daemon harness — runs the real BridgeRuntime against the
 * local stack (chat :23456 / studio :23457) with the luotw dev creds.
 * Bundled by esbuild and run under plain node (no Electron / no GUI). */
import { mkdtempSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { StudioClient } from '../src/main/daemon/studio-client'
import { BridgeRuntime } from '../src/main/daemon/runtime'

const STUDIO = 'http://localhost:23457'
const CHAT = 'http://localhost:23456'
const USER = 'luotw'
const PASS = 'QXW6rfsd'

function log(...a: unknown[]) { console.log(new Date().toTimeString().slice(0, 8), ...a) }

async function main() {
  log('handshake →', STUDIO)
  const auth = new StudioClient(STUDIO, () => null)
  const hs = await auth.handshake({ username: USER, password: PASS })
  log('handshake ok', { bridgeId: hs.bridgeId, machineId: hs.machineId })

  let token: string | null = hs.token
  const studio = new StudioClient(STUDIO, () => token)
  const dir = mkdtempSync(join(tmpdir(), 'bridge-debug-'))
  log('state dir', dir)

  const rt = new BridgeRuntime(
    studio,
    [{ baseUrl: CHAT, username: USER, password: PASS }],
    dir,
    (evt, payload) => {
      if (evt === 'log') {
        const l = payload as any
        console.log(`${l.t} [${l.src}/${l.level}] ${l.msg}`)
      } else {
        const s = payload as any
        log(`STATE status=${s.status} channels=${s.channels.length} in5m=${s.inCount5m} outPending=${s.outboundPending}` + (s.lastError ? ` err=${s.lastError}` : ''))
      }
    },
    () => ({ studioUrl: STUDIO, username: USER, machineId: hs.machineId, bridgeId: hs.bridgeId }),
  )

  await rt.run({ onAuthError: () => { token = null; log('!! onAuthError (401)') } })

  // Inject a simulated inbound: a fan messages luotw on chat.
  setTimeout(async () => {
    try {
      const r = await fetch(`${CHAT}/api/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: USER, password: PASS }) })
      const ctok = (await r.json()).token
      const cr = await fetch(`${CHAT}/api/contacts`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${ctok}` }, body: JSON.stringify({ nickname: '调试粉丝', username: 'debug_fan' }) })
      const contact = await cr.json()
      const convs = await (await fetch(`${CHAT}/api/conversations`, { headers: { Authorization: `Bearer ${ctok}` } })).json()
      const conv = convs.find((c: any) => c.contact_id === contact.id)
      await fetch(`${CHAT}/api/conversations/${conv.id}/messages`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${ctok}` }, body: JSON.stringify({ sender_type: 'contact', msg_type: 'text', content: '调试：你好' }) })
      log(`>> injected inbound from contact ${contact.id} (conv ${conv.id})`)
    } catch (e) { log('inject failed', e) }
  }, 6000)

  setTimeout(() => { log('-- stopping --'); rt.stop(); process.exit(0) }, 30000)
}

main().catch(e => { console.error('FATAL', e); process.exit(1) })
