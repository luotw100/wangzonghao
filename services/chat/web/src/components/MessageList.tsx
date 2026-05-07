import { useEffect, useMemo, useRef } from 'react';
import type { Account, Conversation, Message } from '../api';
import Avatar from './Avatar';
import { formatBubbleSeparator, formatFullTime, shouldShowSeparator } from '../utils/time';

interface MessageListProps {
  account: Account;
  conversation: Conversation;
  messages: Message[];
  /** Whose perspective is the user adopting right now? Determines which side
   * is rendered on the right (the active speaker is always on the right). */
  perspective: 'self' | 'contact';
}

interface Row {
  type: 'separator' | 'message';
  key: string;
  message?: Message;
  label?: string;
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

  // Scroll-to-bottom strategy:
  //  - Always jump to bottom on conversation switch.
  //  - When new messages arrive, only auto-scroll if the user is already near
  //    the bottom (within 120px); otherwise leave their scroll position alone.
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
        <p>选择 Enter 发送，Shift+Enter 换行。可切换发送身份模拟两端对话。</p>
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
          // The "perspective" determines orientation: whichever side the user
          // is currently speaking *as* gets rendered on the right.
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
                  {message.content}
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
