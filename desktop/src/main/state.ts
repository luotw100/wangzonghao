import { safeStorage } from 'electron'
import { readFileSync, writeFileSync, existsSync } from 'fs'
import { join } from 'path'
import type { Channel } from './daemon/types'

interface PersistedState {
  studioUrl: string
  username: string
  machineId?: string
  bridgeId?: string
  channels: Array<{ baseUrl: string; username: string; passwordB64: string }>
}

/**
 * Local persistence. The Studio session token is reused across restarts;
 * the Studio password is never written to disk and is only handled in
 * memory during the login handshake. Chat-platform passwords must be
 * stored (the daemon needs them to log in) — they are safeStorage-encrypted.
 */
export class Store {
  private path: string
  private tokenPath: string
  private data: PersistedState = {
    studioUrl: 'https://studio.laborster.com',
    username: '',
    channels: [],
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
        this.data = { ...this.data, ...JSON.parse(readFileSync(this.path, 'utf8')) }
      } catch {}
    }
    if (existsSync(this.tokenPath) && safeStorage.isEncryptionAvailable()) {
      try {
        const enc = readFileSync(this.tokenPath)
        if (enc.length > 0) this.token = safeStorage.decryptString(enc)
      } catch {}
    }
  }

  private save(): void {
    writeFileSync(this.path, JSON.stringify(this.data, null, 2), 'utf8')
    if (this.token && safeStorage.isEncryptionAvailable()) {
      writeFileSync(this.tokenPath, safeStorage.encryptString(this.token))
    } else if (!this.token && existsSync(this.tokenPath)) {
      writeFileSync(this.tokenPath, Buffer.alloc(0))
    }
  }

  get studioUrl(): string { return this.data.studioUrl }
  get username(): string { return this.data.username }
  get machineId(): string | undefined { return this.data.machineId }
  get bridgeId(): string | undefined { return this.data.bridgeId }
  hasToken(): boolean { return !!this.token }
  hasChannels(): boolean { return this.data.channels.length > 0 }

  setSession(opts: {
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

  private decrypt(b64: string): string {
    return safeStorage.isEncryptionAvailable()
      ? safeStorage.decryptString(Buffer.from(b64, 'base64'))
      : Buffer.from(b64, 'base64').toString('utf8')
  }

  private encrypt(s: string): string {
    return safeStorage.isEncryptionAvailable()
      ? safeStorage.encryptString(s).toString('base64')
      : Buffer.from(s).toString('base64')
  }

  getChannels(): Channel[] {
    return this.data.channels.map(c => ({
      baseUrl: c.baseUrl,
      username: c.username,
      password: this.decrypt(c.passwordB64),
    }))
  }

  /** Channel rows for the UI — no passwords. */
  getChannelViews(): Array<{ baseUrl: string; username: string }> {
    return this.data.channels.map(c => ({ baseUrl: c.baseUrl, username: c.username }))
  }

  saveChannels(channels: Channel[]): void {
    this.data.channels = channels.map(c => ({
      baseUrl: c.baseUrl,
      username: c.username,
      passwordB64: this.encrypt(c.password),
    }))
    this.save()
  }
}
