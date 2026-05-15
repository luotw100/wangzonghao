import Database from 'better-sqlite3'
import { createHash } from 'crypto'
import { join } from 'path'
import type { MsgType } from './types'

export interface LocalMessage {
  id: number
  inboxId: string
  peerId: string
  peerDisplayName: string
  platformMsgId: string | null
  senderId: string
  sentAt: string
  msgType: MsgType
  content: string
  mimeType: string | null
  localHash: string
  sent: 0 | 1
}

export class LocalStore {
  private db: Database.Database

  constructor(dbPath: string) {
    this.db = new Database(dbPath)
    this.db.pragma('journal_mode = WAL')
    this.migrate()
  }

  private migrate(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS local_messages (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        inbox_id         TEXT NOT NULL,
        peer_id          TEXT NOT NULL,
        peer_display_name TEXT NOT NULL,
        platform_msg_id  TEXT,
        sender_id        TEXT NOT NULL,
        sent_at          TEXT NOT NULL,
        msg_type         TEXT NOT NULL,
        content          TEXT NOT NULL,
        mime_type        TEXT,
        local_hash       TEXT NOT NULL,
        sent             INTEGER NOT NULL DEFAULT 0,
        UNIQUE(inbox_id, local_hash)
      );
      CREATE INDEX IF NOT EXISTS idx_unsent ON local_messages(sent, id);
      CREATE INDEX IF NOT EXISTS idx_cursor  ON local_messages(inbox_id, peer_id, id);
    `)
  }

  static localHash(
    inboxId: string,
    peerId: string,
    senderId: string,
    sentAt: string,
    msgType: string,
    content: string,
  ): string {
    return createHash('sha256')
      .update([inboxId, peerId, senderId, sentAt, msgType, content].join('\x00'))
      .digest('hex')
  }

  getCursors(inboxId: string): Record<string, string | null> {
    const rows = this.db
      .prepare(
        `SELECT peer_id, MAX(platform_msg_id) as last_id
         FROM local_messages
         WHERE inbox_id = ? AND platform_msg_id IS NOT NULL
         GROUP BY peer_id`,
      )
      .all(inboxId) as Array<{ peer_id: string; last_id: string | null }>
    return Object.fromEntries(rows.map(r => [r.peer_id, r.last_id]))
  }

  insertMessage(msg: Omit<LocalMessage, 'id' | 'sent'>): boolean {
    const info = this.db
      .prepare(
        `INSERT OR IGNORE INTO local_messages
         (inbox_id, peer_id, peer_display_name, platform_msg_id, sender_id,
          sent_at, msg_type, content, mime_type, local_hash)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        msg.inboxId,
        msg.peerId,
        msg.peerDisplayName,
        msg.platformMsgId,
        msg.senderId,
        msg.sentAt,
        msg.msgType,
        msg.content,
        msg.mimeType,
        msg.localHash,
      )
    return info.changes > 0
  }

  getUnsent(
    limit: number,
    activePeers: Set<string> | null,
  ): LocalMessage[] {
    if (activePeers !== null && activePeers.size === 0) return []

    if (activePeers === null) {
      return this.db
        .prepare(`SELECT * FROM local_messages WHERE sent = 0 ORDER BY id LIMIT ?`)
        .all(limit) as LocalMessage[]
    }

    // SQLite doesn't support array binding; build placeholders manually
    const keys = [...activePeers]
    const placeholders = keys.map(() => '(?,?)').join(',')
    return this.db
      .prepare(
        `SELECT * FROM local_messages
         WHERE sent = 0 AND (inbox_id, peer_id) IN (${placeholders})
         ORDER BY id LIMIT ?`,
      )
      .all(...keys.flatMap(k => k.split('|')), limit) as LocalMessage[]
  }

  markSent(id: number): void {
    this.db.prepare(`UPDATE local_messages SET sent = 1 WHERE id = ?`).run(id)
  }

  countUnsent(): number {
    const row = this.db
      .prepare(`SELECT COUNT(*) as n FROM local_messages WHERE sent = 0`)
      .get() as { n: number }
    return row.n
  }

  countRecentIncoming(sinceMs: number): number {
    const since = new Date(Date.now() - sinceMs).toISOString()
    const row = this.db
      .prepare(`SELECT COUNT(*) as n FROM local_messages WHERE sent_at >= ? AND sent = 1`)
      .get(since) as { n: number }
    return row.n
  }

  close(): void {
    this.db.close()
  }
}
