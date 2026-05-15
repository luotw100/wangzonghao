import { safeStorage } from 'electron'
import { readFileSync, writeFileSync, existsSync } from 'fs'
import { join } from 'path'
import type { InboxClaim } from './daemon/types'

interface PersistedState {
  studioUrl: string
  username: string
  machineId?: string
  bridgeId?: string
  inboxes: Array<{ baseUrl: string; username: string; passwordB64: string }>
}

export class CredentialStore {
  private path: string
  private tokenPath: string
  private data: PersistedState = {
    studioUrl: 'https://studio.laborster.com',
    username: '',
    inboxes: [],
  }
  token: string | null = null

  constructor(userDataDir: string) {
    this.path = join(userDataDir, 'bridge-state.json')
    this.tokenPath = join(userDataDir, 'bridge-token.enc')
    this.load()
  }

  private load(): void {
    if (existsSync(this.path)) {
      try {
        this.data = JSON.parse(readFileSync(this.path, 'utf8'))
      } catch {}
    }
    if (existsSync(this.tokenPath) && safeStorage.isEncryptionAvailable()) {
      try {
        const enc = readFileSync(this.tokenPath)
        this.token = safeStorage.decryptString(enc)
      } catch {}
    }
  }

  save(): void {
    writeFileSync(this.path, JSON.stringify(this.data, null, 2), 'utf8')
    if (this.token && safeStorage.isEncryptionAvailable()) {
      const enc = safeStorage.encryptString(this.token)
      writeFileSync(this.tokenPath, enc)
    } else if (!this.token && existsSync(this.tokenPath)) {
      writeFileSync(this.tokenPath, Buffer.alloc(0))
    }
  }

  get studioUrl(): string { return this.data.studioUrl }
  get username(): string { return this.data.username }
  get machineId(): string | undefined { return this.data.machineId }
  get bridgeId(): string | undefined { return this.data.bridgeId }

  setHandshakeResult(opts: {
    studioUrl: string
    username: string
    token: string
    machineId: string
    bridgeId: string
  }): void {
    this.data.studioUrl = opts.studioUrl
    this.data.username = opts.username
    this.data.machineId = opts.machineId
    this.data.bridgeId = opts.bridgeId
    this.token = opts.token
    this.save()
  }

  clearToken(): void {
    this.token = null
    this.save()
  }

  getInboxClaims(): InboxClaim[] {
    return this.data.inboxes.map(ib => ({
      baseUrl: ib.baseUrl,
      username: ib.username,
      password: safeStorage.isEncryptionAvailable()
        ? safeStorage.decryptString(Buffer.from(ib.passwordB64, 'base64'))
        : Buffer.from(ib.passwordB64, 'base64').toString('utf8'),
    }))
  }

  saveInboxes(claims: InboxClaim[]): void {
    this.data.inboxes = claims.map(c => ({
      baseUrl: c.baseUrl,
      username: c.username,
      passwordB64: safeStorage.isEncryptionAvailable()
        ? safeStorage.encryptString(c.password).toString('base64')
        : Buffer.from(c.password).toString('base64'),
    }))
    this.save()
  }

  hasToken(): boolean { return !!this.token }
  hasInboxes(): boolean { return this.data.inboxes.length > 0 }
}
