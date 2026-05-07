import { KeyboardEvent, useEffect, useRef, useState } from 'react';
import type { Account, Conversation } from '../api';

interface ComposerProps {
  account: Account;
  conversation: Conversation;
  perspective: 'self' | 'contact';
  onChangePerspective: (next: 'self' | 'contact') => void;
  onSend: (content: string, sender: 'self' | 'contact') => Promise<void>;
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

  useEffect(() => {
    setValue('');
    setError('');
    textareaRef.current?.focus();
  }, [conversation.id]);

  async function send() {
    const content = value.trim();
    if (!content || sending) return;
    setSending(true);
    setError('');
    try {
      await onSend(content, perspective);
      setValue('');
      // re-focus once the new message rendered
      requestAnimationFrame(() => textareaRef.current?.focus());
    } catch (err) {
      // Restore the unsent text so user can retry.
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  }

  const speakingAs = perspective === 'self' ? account.display_name : conversation.contact.display_name;

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
          我（{account.display_name}）
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={perspective === 'contact'}
          className={perspective === 'contact' ? 'selected' : ''}
          onClick={() => onChangePerspective('contact')}
        >
          对方（{conversation.contact.display_name}）
        </button>
      </div>

      <div className="composer-hint">
        正在以 <strong>{speakingAs}</strong> 的身份发送 · Enter 发送 · Shift+Enter 换行
      </div>

      <div className="composer-row">
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
