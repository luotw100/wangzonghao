import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { Account, Conversation, Message } from '../api';
import { contactDisplayName, mediaUrl } from '../api';
import Avatar from './Avatar';
import { formatBubbleSeparator, formatFullTime, shouldShowSeparator } from '../utils/time';

interface MessageListProps {
  account: Account;
  conversation: Conversation;
  messages: Message[];
  perspective: 'self' | 'contact';
  hasMore: boolean;
  loadOlder: () => Promise<void>;
}

interface Row {
  type: 'separator' | 'message';
  key: string;
  message?: Message;
  label?: string;
}

function MediaContent({ message }: { message: Message }) {
  const [loaded, setLoaded] = useState(false);

  if (!loaded) {
    const label =
      message.msg_type === 'image' ? '图片'
      : message.msg_type === 'audio' ? '音频'
      : message.msg_type === 'video' ? '视频'
      : '文件';
    return (
      <button className="media-placeholder" onClick={() => setLoaded(true)} type="button">
        <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        <span>{label}</span>
      </button>
    );
  }

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

export default function MessageList({
  account,
  conversation,
  messages,
  perspective,
  hasMore,
  loadOlder,
}: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const previousLengthRef = useRef(0);
  const previousConversationRef = useRef<string | null>(null);
  const savedScrollHeightRef = useRef(0);
  const pendingPrependRef = useRef(false);
  const loadingOlderRef = useRef(false);
  // True between a conversation switch and the first non-empty render of that conversation.
  const justSwitchedRef = useRef(false);

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

  // Preserve scroll position when older messages are prepended.
  useLayoutEffect(() => {
    if (!pendingPrependRef.current) return;
    pendingPrependRef.current = false;
    const node = containerRef.current;
    if (!node) return;
    const delta = node.scrollHeight - savedScrollHeightRef.current;
    if (delta > 0) node.scrollTop += delta;
  }, [messages]);

  // Auto-scroll on conversation switch or new messages near bottom.
  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    const conversationChanged = previousConversationRef.current !== conversation.id;
    previousConversationRef.current = conversation.id;
    const prevLen = previousLengthRef.current;
    previousLengthRef.current = messages.length;

    if (conversationChanged) {
      if (messages.length > 0) {
        // Messages already available (cache hit) — scroll immediately.
        node.scrollTop = node.scrollHeight;
        justSwitchedRef.current = false;
      } else {
        // Messages not loaded yet — mark so we scroll when they arrive.
        justSwitchedRef.current = true;
      }
      return;
    }

    // First batch of messages after a switch (no cache, initial fetch just landed).
    if (justSwitchedRef.current && messages.length > 0) {
      node.scrollTop = node.scrollHeight;
      justSwitchedRef.current = false;
      return;
    }

    // New messages appended while already viewing the conversation.
    if (messages.length > prevLen && !pendingPrependRef.current) {
      const distanceFromBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
      if (distanceFromBottom < 120) {
        node.scrollTop = node.scrollHeight;
      }
    }
  }, [messages.length, conversation.id]);

  async function handleLoadOlder() {
    if (loadingOlderRef.current || !hasMore) return;
    loadingOlderRef.current = true;
    savedScrollHeightRef.current = containerRef.current?.scrollHeight ?? 0;
    pendingPrependRef.current = true;
    try {
      await loadOlder();
    } finally {
      loadingOlderRef.current = false;
    }
  }

  function handleScroll() {
    const node = containerRef.current;
    if (!node || !hasMore || loadingOlderRef.current) return;
    if (node.scrollTop < 80) {
      handleLoadOlder();
    }
  }

  if (messages.length === 0) {
    return (
      <div className="messages">
        <div className="messages-empty">
          <EmptyChatArt />
          <h3>开始一段对话</h3>
          <p>选择 Enter 发送文本消息，或点击附件按钮发送图片/音频/视频/文件。</p>
        </div>
      </div>
    );
  }

  return (
    <div className="messages" ref={containerRef} onScroll={handleScroll}>
      <div className="messages-inner">
        {hasMore && (
          <div className="messages-load-more">
            <button
              type="button"
              className="messages-load-more-btn"
              onClick={handleLoadOlder}
              disabled={loadingOlderRef.current}
            >
              加载更早的消息
            </button>
          </div>
        )}
        {rows.map((row) => {
          if (row.type === 'separator') {
            return (
              <div key={row.key} className="day-separator">
                <span>{row.label}</span>
              </div>
            );
          }
          const message = row.message!;
          const isSelf = message.sender_id === null;
          const isOnRight = isSelf === (perspective === 'self');
          const senderName = isSelf ? account.nickname : contactDisplayName(conversation.contact);
          const seed = isSelf ? account.id : conversation.contact.id;
          return (
            <article key={row.key} className={isOnRight ? 'bubble-row right' : 'bubble-row left'}>
              <Avatar name={senderName} seed={seed} size={36} />
              <div className="bubble-stack">
                <div className={isSelf ? 'bubble bubble-self' : 'bubble bubble-contact'}>
                  {message.msg_type === 'text' ? (
                    message.content
                  ) : (
                    <MediaContent message={message} />
                  )}
                </div>
                <span className="bubble-time-tip">{formatFullTime(message.created_at)}</span>
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
