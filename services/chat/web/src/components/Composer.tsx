import { KeyboardEvent, useRef, useState } from 'react';
import type { Account, Conversation, MessageType } from '../api';
import { contactDisplayName, presignUpload, sendMessage, uploadPresignedFile } from '../api';

interface ComposerProps {
  account: Account;
  conversation: Conversation;
  perspective: 'self' | 'contact';
  onChangePerspective: (next: 'self' | 'contact') => void;
  onSend: (content: string, sender: 'self' | 'contact') => Promise<void>;
}

function inferMediaType(mimeType: string): MessageType {
  if (mimeType.startsWith('image/')) return 'image';
  if (mimeType.startsWith('audio/')) return 'audio';
  if (mimeType.startsWith('video/')) return 'video';
  return 'file';
}

export default function Composer({
  account,
  conversation,
  perspective,
  onChangePerspective,
  onSend,
}: ComposerProps) {
  const [value, setValue] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function send() {
    const content = value.trim();
    if (!content || sending) return;
    setSending(true);
    setError('');
    try {
      await onSend(content, perspective);
      setValue('');
      requestAnimationFrame(() => textareaRef.current?.focus());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setSending(true);
    setError('');
    try {
      const presign = await presignUpload(file.name, file.type || 'application/octet-stream');
      await uploadPresignedFile(presign.upload_url, file);
      const msgType = inferMediaType(file.type || 'application/octet-stream');
      await sendMessage(conversation.id, {
        sender_type: perspective,
        msg_type: msgType,
        content: presign.storage_key,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  }

  const speakingAs = perspective === 'self' ? account.nickname : contactDisplayName(conversation.contact);

  return (
    <footer className="composer">
      <div className="sender-toggle" role="tablist" aria-label="选择发送身份">
        <button
          type="button"
          role="tab"
          aria-selected={perspective === 'self'}
          className={perspective === 'self' ? 'selected' : ''}
          onClick={() => onChangePerspective('self')}
        >
          我（{account.nickname}）
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={perspective === 'contact'}
          className={perspective === 'contact' ? 'selected' : ''}
          onClick={() => onChangePerspective('contact')}
        >
          对方（{contactDisplayName(conversation.contact)}）
        </button>
      </div>

      <div className="composer-hint">
        正在以 <strong>{speakingAs}</strong> 的身份发送 · Enter 发送文本 · 📎 发送媒体
      </div>

      <div className="composer-row">
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*,audio/*,video/*,*.*"
          style={{ display: 'none' }}
          onChange={handleFileChange}
          disabled={sending}
        />
        <button
          type="button"
          className="attach-btn"
          onClick={() => fileInputRef.current?.click()}
          disabled={sending}
          title="发送媒体文件"
        >
          📎
        </button>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={`以 ${speakingAs} 的身份说点什么…`}
          rows={3}
          disabled={sending}
        />
        <button
          type="button"
          className="send"
          onClick={send}
          disabled={!value.trim() || sending}
        >
          {sending ? '…' : '发送'}
        </button>
      </div>

      {error && (
        <div className="error compact" role="alert">
          {error}
        </div>
      )}
    </footer>
  );
}