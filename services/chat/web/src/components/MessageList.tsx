import { useEffect, useMemo, useRef } from 'react';
import type { Account, Conversation, Message } from '../api';
import { mediaUrl } from '../api';
import Avatar from './Avatar';
import { formatBubbleSeparator, formatFullTime, shouldShowSeparator } from '../utils/time';

interface MessageListProps {
  account: Account;
  conversation: Conversation;
  messages: Message[];
  perspective: 'self' | 'contact';
}

interface Row {
  type: 'separator' | 'message';
  key: string;
  message?: Message;
  label?: string;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function MediaContent({ message }: { message: Message }) {
  const url = mediaUrl(message.content);
  switch (message.msg_type) {
    case 'image':
      return <img src={url} alt="图片" className="bubble-media" loading="lazy" />;
    case 'audio':
      return <audio src={url} controls className="bubble-media" />;
    case 'video':
      return <video src={url} controls className="bubble-media" />;
    case 'file':
      return (
        <a href={url} className="bubble-file-link" target="_blank" rel="noopener noreferrer">
          📎 下载文件
        </a>
      );
    default:
      return <span>{message.content}</span>;
  }
}

export default function MessageList({ account, conversation, messages, perspective }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const previousLengthRef = useRef(0);
  const previousConversationRef = useRef<string | null>(null);

  const rows: Row[] = useMemo(() => {
    const out: Row[] = [];
    let previous: Message | null = null;
    for (const message of messages) {
      if (shouldShowSeparator(message.created_at, previous?.created_at ?? null)) {
        out.push({
          type: 'separator',
          key: `sep-${message.id}`,
          label: formatBubbleSeparator(message.created_at),
        });
      }
      out.push({ type: 'message', key: `msg-${message.id}`, message });
      previous = message;
    }
    return out;
  }, [messages]);

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    const conversationChanged = previousConversationRef.current !== conversation.id;
    previousConversationRef.current = conversation.id;
    const grew = messages.length > previousLengthRef.current;
    previousLengthRef.current = messages.length;

    if (conversationChanged) {
      node.scrollTop = node.scrollHeight;
      return;
    }
    if (grew) {
      const distanceFromBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
      if (distanceFromBottom < 120) {
        node.scrollTop = node.scrollHeight;
      }
    }
  }, [messages.length, conversation.id]);

  if (messages.length === 0) {
    return (
      <div className="messages-empty">
        <EmptyChatArt />
        <h3>开始一段对话</h3>
        <p>选择 Enter 发送文本消息，或点击附件按钮发送图片/音频/视频/文件。</p>
      </div>
    );
  }

  return (
    <div className="messages" ref={containerRef}>
      <div className="messages-inner">
        {rows.map((row) => {
          if (row.type === 'separator') {
            return (
              <div key={row.key} className="day-separator">
                <span>{row.label}</span>
              </div>
            );
          }
          const message = row.message!;
          const isOnRight = message.sender_type === perspective;
          const senderName =
            message.sender_type === 'self' ? account.display_name : conversation.contact.display_name;
          const seed = message.sender_type === 'self' ? account.id : conversation.contact.id;
          return (
            <article key={row.key} className={isOnRight ? 'bubble-row right' : 'bubble-row left'}>
              <Avatar name={senderName} seed={seed} size={36} />
              <div className="bubble-stack">
                <div
                  className={
                    message.sender_type === 'self'
                      ? 'bubble bubble-self'
                      : 'bubble bubble-contact'
                  }
                  title={formatFullTime(message.created_at)}
                >
                  {message.msg_type === 'text' ? (
                    message.content
                  ) : (
                    <MediaContent message={message} />
                  )}
                </div>
                {message.source === 'import' && <span className="bubble-tag">导入</span>}
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

function EmptyChatArt() {
  return (
    <svg viewBox="0 0 120 120" width="96" height="96" fill="none" aria-hidden="true">
      <rect x="10" y="20" width="70" height="50" rx="14" fill="#e7f5ea" />
      <rect x="40" y="55" width="70" height="40" rx="14" fill="#cfe9d6" />
      <circle cx="30" cy="42" r="3" fill="#7eb289" />
      <circle cx="44" cy="42" r="3" fill="#7eb289" />
      <circle cx="58" cy="42" r="3" fill="#7eb289" />
    </svg>
  );
}