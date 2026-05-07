import { ChangeEvent, DragEvent, FormEvent, useMemo, useState } from 'react';
import type { Conversation } from '../api';

interface ImportModalProps {
  conversation: Conversation;
  onClose: () => void;
  onSubmit: (filename: string, messages: ParsedMessage[]) => Promise<void>;
}

export interface ParsedMessage {
  sender_type: 'self' | 'contact';
  msg_type: string;
  content: string;
  created_at: string;
}

const SAMPLE = JSON.stringify(
  [
    { sender_type: 'contact', msg_type: 'text', content: '你今天在忙吗？', created_at: '2026-05-06T12:00:00' },
    { sender_type: 'self', msg_type: 'text', content: '刚忙完，怎么啦', created_at: '2026-05-06T12:00:12' },
  ],
  null,
  2
);

function tryParse(text: string): { ok: true; messages: ParsedMessage[] } | { ok: false; error: string } {
  if (!text.trim()) return { ok: false, error: '内容为空' };
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (err) {
    return { ok: false, error: `JSON 解析失败：${err instanceof Error ? err.message : String(err)}` };
  }
  if (!Array.isArray(raw)) return { ok: false, error: '顶层必须是数组' };
  const out: ParsedMessage[] = [];
  for (let i = 0; i < raw.length; i += 1) {
    const item = raw[i] as Record<string, unknown>;
    if (!item || typeof item !== 'object') return { ok: false, error: `第 ${i + 1} 条不是对象` };
    const sender = item.sender_type;
    if (sender !== 'self' && sender !== 'contact')
      return { ok: false, error: `第 ${i + 1} 条 sender_type 必须是 self 或 contact` };
    const content = item.content;
    if (typeof content !== 'string') return { ok: false, error: `第 ${i + 1} 条 content 必须是字符串` };
    const created = item.created_at;
    if (typeof created !== 'string') return { ok: false, error: `第 ${i + 1} 条 created_at 必须是字符串` };
    const msgType = typeof item.msg_type === 'string' ? item.msg_type : 'text';
    out.push({ sender_type: sender, msg_type: msgType, content, created_at: created });
  }
  return { ok: true, messages: out };
}

export default function ImportModal({ conversation, onClose, onSubmit }: ImportModalProps) {
  const [text, setText] = useState(SAMPLE);
  const [filename, setFilename] = useState('manual-import.json');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [dragOver, setDragOver] = useState(false);

  const parsed = useMemo(() => tryParse(text), [text]);

  function handleFile(file: File) {
    setFilename(file.name);
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || '');
      setText(result);
    };
    reader.onerror = () => setError('文件读取失败');
    reader.readAsText(file);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragOver(false);
    const file = event.dataTransfer.files?.[0];
    if (!file) return;
    if (!/\.json$/i.test(file.name) && file.type !== 'application/json') {
      setError('请拖拽 .json 文件');
      return;
    }
    setError('');
    handleFile(file);
  }

  function handlePicker(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setError('');
    handleFile(file);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      await onSubmit(filename.trim() || 'manual-import.json', parsed.messages);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  const preview = parsed.ok ? parsed.messages.slice(0, 3) : [];

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="import-modal" onSubmit={handleSubmit} onClick={(event) => event.stopPropagation()}>
        <header className="import-header">
          <div>
            <p className="eyebrow">批量导入</p>
            <h2>导入到 {conversation.contact.display_name}</h2>
          </div>
          <button type="button" className="icon-btn" aria-label="关闭" onClick={onClose}>
            ×
          </button>
        </header>

        <label className="import-row">
          <span>文件名</span>
          <input
            value={filename}
            onChange={(event) => setFilename(event.target.value)}
            placeholder="manual-import.json"
          />
        </label>

        <div
          className={dragOver ? 'drop-zone over' : 'drop-zone'}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
        >
          <span>把 .json 拖到这里，或</span>
          <label className="file-pick">
            选择文件
            <input type="file" accept=".json,application/json" onChange={handlePicker} hidden />
          </label>
        </div>

        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          spellCheck={false}
        />

        <div className="import-status">
          {parsed.ok ? (
            <span className="ok">
              将导入 {parsed.messages.length} 条
              {preview.length > 0 && (
                <em>
                  · 预览：
                  {preview
                    .map((m) => `[${m.sender_type === 'self' ? '我' : '对方'}] ${truncate(m.content, 18)}`)
                    .join(' / ')}
                </em>
              )}
            </span>
          ) : (
            <span className="bad">{parsed.error}</span>
          )}
        </div>

        <div className="modal-actions">
          <button type="button" className="ghost" onClick={onClose}>
            取消
          </button>
          <button className="primary" disabled={!parsed.ok || submitting}>
            {submitting ? '导入中…' : '导入'}
          </button>
        </div>

        {error && (
          <div className="error compact" role="alert">
            {error}
          </div>
        )}
      </form>
    </div>
  );
}

function truncate(text: string, n: number): string {
  return text.length > n ? `${text.slice(0, n)}…` : text;
}
