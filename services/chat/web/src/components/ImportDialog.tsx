import { useState, useRef, DragEvent, ChangeEvent } from 'react';
import * as api from '../api';

interface ChatlabMember {
  platformId: string;
  accountName: string;
  groupNickname?: string;
  aliases?: string[];
}

interface ChatlabMessage {
  sender: string;
  timestamp: number;
  type: number;
  content: string | null;
}

interface ChatlabFile {
  chatlab: { version: string; exportedAt: number };
  meta: { name: string; platform: string; type: string; ownerId?: string };
  members: ChatlabMember[];
  messages: ChatlabMessage[];
}

interface Props {
  onDone: (conversationId: string) => void;
  onCancel: () => void;
}

type Step = 'pick' | 'confirm' | 'importing' | 'done';

function memberName(m: ChatlabMember): string {
  return m.groupNickname || m.accountName;
}

function msgTimeRange(msgs: ChatlabMessage[]): string {
  if (msgs.length === 0) return '—';
  const ts = msgs.map((m) => m.timestamp);
  const from = new Date(Math.min(...ts) * 1000).toLocaleDateString('zh-CN');
  const to = new Date(Math.max(...ts) * 1000).toLocaleDateString('zh-CN');
  return from === to ? from : `${from} — ${to}`;
}

export default function ImportDialog({ onDone, onCancel }: Props) {
  const [step, setStep] = useState<Step>('pick');
  const [dragOver, setDragOver] = useState(false);
  const [parsed, setParsed] = useState<ChatlabFile | null>(null);
  const [parseError, setParseError] = useState('');
  const [myId, setMyId] = useState('');
  const [remarkName, setRemarkName] = useState('');
  const [done, setDone] = useState(0);
  const [total, setTotal] = useState(0);
  const [skipped, setSkipped] = useState(0);
  const [importError, setImportError] = useState('');
  const [resultConvId, setResultConvId] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  function loadFile(file: File) {
    setParseError('');
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const raw = JSON.parse(e.target!.result as string);
        if (!raw.chatlab || !raw.meta || !Array.isArray(raw.members) || !Array.isArray(raw.messages)) {
          throw new Error('不是有效的 ChatLab 格式');
        }
        if (raw.meta.type !== 'private') {
          throw new Error('仅支持私聊记录（群聊暂不支持）');
        }
        if (raw.members.length < 2) {
          throw new Error('私聊记录至少需要两名成员');
        }
        const data = raw as ChatlabFile;
        setParsed(data);
        setMyId(data.meta.ownerId || data.members[0].platformId);
        setRemarkName('');
        setStep('confirm');
      } catch (err) {
        setParseError(err instanceof Error ? err.message : '解析失败');
      }
    };
    reader.onerror = () => setParseError('文件读取失败');
    reader.readAsText(file);
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) loadFile(f);
  }

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) loadFile(f);
    e.target.value = '';
  }

  async function runImport() {
    if (!parsed || !myId) return;
    const other = parsed.members.find((m) => m.platformId !== myId)!;
    const textMsgs = parsed.messages.filter((m) => m.type === 0 && m.content != null && m.content !== '');
    const skippedCount = parsed.messages.length - textMsgs.length;

    setTotal(textMsgs.length);
    setSkipped(skippedCount);
    setDone(0);
    setImportError('');
    setStep('importing');

    try {
      const contact = await api.createContact({
        nickname: memberName(other),
        username: other.platformId,
        remark_name: remarkName.trim() || undefined,
      });

      const conversations = await api.listConversations();
      const conv = conversations.find((c) => c.contact_id === contact.id);
      if (!conv) throw new Error('找不到对应的会话');

      for (let i = 0; i < textMsgs.length; i++) {
        const msg = textMsgs[i];
        await api.sendMessage(conv.id, {
          sender_type: msg.sender === myId ? 'self' : 'contact',
          msg_type: 'text',
          content: msg.content!,
          created_at: new Date(msg.timestamp * 1000).toISOString(),
        });
        setDone(i + 1);
      }

      setResultConvId(conv.id);
      setStep('done');
    } catch (err) {
      setImportError(err instanceof Error ? err.message : '导入出错');
    }
  }

  function handleBackdropClick() {
    if (step !== 'importing') onCancel();
  }

  const other = parsed ? parsed.members.find((m) => m.platformId !== myId) : null;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <div className="modal-backdrop" onClick={handleBackdropClick}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>

        {/* ── Step: pick ── */}
        {step === 'pick' && (
          <>
            <div className="modal-header">
              <h2>导入聊天记录</h2>
              <button className="icon-btn modal-close" onClick={onCancel} aria-label="关闭">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                  <path d="M18 6 6 18M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="modal-body">
              <div
                className={`import-dropzone${dragOver ? ' drag-over' : ''}`}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => inputRef.current?.click()}
              >
                <svg viewBox="0 0 24 24" width="36" height="36" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="12" y1="18" x2="12" y2="12" />
                  <line x1="9" y1="15" x2="15" y2="15" />
                </svg>
                <p>拖拽 ChatLab JSON 文件到这里</p>
                <small>或点击选择文件 · 仅支持私聊</small>
                <input ref={inputRef} type="file" accept=".json" onChange={handleFileChange} style={{ display: 'none' }} />
              </div>
              {parseError && <div className="error compact">{parseError}</div>}
            </div>
          </>
        )}

        {/* ── Step: confirm ── */}
        {step === 'confirm' && parsed && (
          <>
            <div className="modal-header">
              <h2>确认导入</h2>
              <button className="icon-btn modal-close" onClick={onCancel} aria-label="关闭">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                  <path d="M18 6 6 18M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="modal-body">
              <div className="import-preview">
                <div className="import-preview-row"><span className="label">会话</span><span>{parsed.meta.name}</span></div>
                <div className="import-preview-row"><span className="label">平台</span><span>{parsed.meta.platform}</span></div>
                <div className="import-preview-row"><span className="label">消息</span><span>{parsed.messages.length} 条（仅文字消息会被导入）</span></div>
                <div className="import-preview-row"><span className="label">时间</span><span>{msgTimeRange(parsed.messages)}</span></div>
              </div>

              <div>
                <div className="section-label">这是谁的聊天记录？选择代表「我」的一方：</div>
                <div className="member-cards">
                  {parsed.members.map((m) => (
                    <button
                      key={m.platformId}
                      type="button"
                      className={`member-card${myId === m.platformId ? ' selected' : ''}`}
                      onClick={() => setMyId(m.platformId)}
                    >
                      <div className="member-name">{memberName(m)}</div>
                      <div className="member-id">@{m.accountName}</div>
                      {myId === m.platformId && <div className="member-role">我</div>}
                      {other && other.platformId === m.platformId && <div className="member-role member-role-other">对方</div>}
                    </button>
                  ))}
                </div>
              </div>

              {other && (
                <div>
                  <div className="section-label">对方备注名（可选）</div>
                  <input
                    placeholder={`默认使用「${memberName(other)}」`}
                    value={remarkName}
                    onChange={(e) => setRemarkName(e.target.value)}
                  />
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button className="ghost" onClick={onCancel}>取消</button>
              <button
                className="primary"
                onClick={runImport}
                disabled={!myId || !other}
              >
                开始导入
              </button>
            </div>
          </>
        )}

        {/* ── Step: importing ── */}
        {step === 'importing' && (
          <>
            <div className="modal-header">
              <h2>正在导入…</h2>
            </div>
            <div className="modal-body">
              <div className="import-progress-track">
                <div className="import-progress-fill" style={{ width: `${pct}%` }} />
              </div>
              <div className="import-progress-text">
                <span>已导入 {done} / {total} 条</span>
                <span>{pct}%</span>
              </div>
              {importError && (
                <>
                  <div className="error compact">{importError}</div>
                  <div className="modal-footer" style={{ padding: 0, border: 0 }}>
                    <button className="ghost" onClick={onCancel}>关闭</button>
                    <button className="primary" onClick={runImport}>重试</button>
                  </div>
                </>
              )}
            </div>
          </>
        )}

        {/* ── Step: done ── */}
        {step === 'done' && (
          <>
            <div className="modal-header">
              <h2>导入完成</h2>
            </div>
            <div className="modal-body">
              <div className="import-done-stats">
                <div className="big-num">{done}</div>
                <div className="big-label">条消息已导入</div>
                {skipped > 0 && (
                  <div className="skip-info">另有 {skipped} 条媒体消息已跳过</div>
                )}
              </div>
            </div>
            <div className="modal-footer">
              <button className="ghost" onClick={onCancel}>关闭</button>
              <button className="primary" onClick={() => onDone(resultConvId)}>
                进入对话
              </button>
            </div>
          </>
        )}

      </div>
    </div>
  );
}
