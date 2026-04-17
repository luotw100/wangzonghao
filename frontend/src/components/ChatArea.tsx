import { useRef, useEffect, useCallback, useState } from 'react';
import { cn, formatCountdown } from '../lib/utils';
import { LaborsterLogo, LaborsterAvatar, IconSend, IconMenu, IconProvider, IconChevronDown, IconCheck } from './Icons';
import type { Session, Message, ReplyPlan, ProviderConfig } from '../lib/api';

interface ChatAreaProps {
  activeSession: Session | null;
  activeSessionId: string | null;
  isActiveSessionDeleted: boolean;
  isActiveSessionReadOnly: boolean;
  currentMessages: Message[];
  plannedReplies: ReplyPlan[];
  inputText: string;
  setInputText: (v: string) => void;
  errorMessage: string;
  setErrorMessage: (v: string) => void;
  currentTime: number;
  onSendMessage: () => void;
  onOpenSidebar: () => void;
  providerConfigs: ProviderConfig[];
  activeSessionProviderName: string | null;
  onSwitchProvider: (providerId: string) => void;
}

export function ChatArea({
  activeSession,
  activeSessionId,
  isActiveSessionDeleted,
  isActiveSessionReadOnly,
  currentMessages,
  plannedReplies,
  inputText,
  setInputText,
  errorMessage,
  setErrorMessage,
  currentTime,
  onSendMessage,
  onOpenSidebar,
  providerConfigs,
  activeSessionProviderName,
  onSwitchProvider,
}: ChatAreaProps) {
  const chatBoxRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [showProviderDropdown, setShowProviderDropdown] = useState(false);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      if (chatBoxRef.current) {
        chatBoxRef.current.scrollTop = chatBoxRef.current.scrollHeight;
      }
    });
  }, []);

  // Scroll on new messages
  useEffect(() => {
    scrollToBottom();
  }, [currentMessages.length, plannedReplies.length, scrollToBottom]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSendMessage();
    }
  };

  const autoResize = (e: React.FormEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget;
    el.style.height = 'auto';
    const maxH = window.innerHeight * 0.3;
    el.style.height = Math.min(el.scrollHeight, maxH) + 'px';
  };

  // Reset textarea height when input is cleared
  useEffect(() => {
    if (!inputText && textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [inputText]);

  const sessionTitle = activeSession
    ? activeSession.title || '未命名 Session'
    : '选择或创建一个 Session';

  return (
    <main className="flex-1 flex flex-col min-h-0 bg-white">
      {/* Mobile hamburger */}
      <div className="md:hidden">
        <button
          onClick={onOpenSidebar}
          className="fixed top-4 left-4 z-30 w-11 h-11 flex items-center justify-center rounded-full bg-white/80 backdrop-blur-sm shadow-sm"
          aria-label="打开菜单"
        >
          <IconMenu />
        </button>
      </div>

      {/* Header */}
      <header className="h-14 flex items-center justify-between px-4 md:px-6 border-b border-border shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="font-medium text-text-primary">{sessionTitle}</h2>
          {isActiveSessionDeleted && (
            <span className="px-2 py-0.5 rounded-full bg-danger-bg text-danger text-[10px]">
              只读
            </span>
          )}
        </div>
        {activeSession && (
          <div className="text-xs text-text-secondary truncate max-w-[50%]">
            Robot: {activeSession.robot?.name} → 联系人: {activeSession.contact?.name}
          </div>
        )}
      </header>

      {/* Error */}
      {errorMessage && (
        <div className="mx-4 mt-3 px-4 py-3 bg-danger-bg rounded-xl text-sm text-danger flex items-center justify-between">
          <span>{errorMessage}</span>
          <button onClick={() => setErrorMessage('')} className="ml-2 text-danger hover:opacity-70">
            &times;
          </button>
        </div>
      )}

      {/* Messages */}
      <div ref={chatBoxRef} className="flex-1 overflow-y-auto overscroll-contain scrollbar-hide min-h-0">
        <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
          {!activeSessionId ? (
            <div className="flex flex-col items-center justify-center h-full min-h-[60vh] text-center">
              <div className="laborster-empty-logo w-16 h-16 mb-6 rounded-full bg-bg-tertiary flex items-center justify-center">
                <LaborsterLogo size={32} id="laborsterEmptyGrad" />
              </div>
              <h3 className="text-xl font-medium mb-2 text-text-primary">有什么可以帮你的？</h3>
              <p className="text-text-secondary text-sm">选择或创建一个 Session 开始对话</p>
            </div>
          ) : (
            <>
              {currentMessages.map((msg) => (
                <div
                  key={msg.id}
                  className={cn('flex message-enter', msg.role === 'user' ? 'justify-end' : 'justify-start')}
                >
                  {msg.role === 'robot' ? (
                    <div className="flex gap-3 max-w-[85%] md:max-w-[80%]">
                      <LaborsterAvatar />
                      <div className="pt-1">
                        <p className="whitespace-pre-wrap break-words leading-relaxed text-[15px]">
                          {msg.content}
                        </p>
                      </div>
                    </div>
                  ) : (
                    <div className="max-w-[85%] md:max-w-[80%]">
                      <div className="bg-bg-tertiary rounded-2xl rounded-tr-md px-4 py-3">
                        <p className="whitespace-pre-wrap break-words leading-relaxed text-[15px]">
                          {msg.content}
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              ))}

              {/* Planned replies */}
              {plannedReplies.length > 0 && (
                <div className="mt-2 space-y-3">
                  <div className="pl-11 text-xs text-text-tertiary">
                    Robot Worker 正在消费队列，以下是待发送回复预览。
                  </div>
                  {plannedReplies.map((reply) => (
                    <div key={reply.id} className="flex justify-start">
                      <div className="flex gap-3 max-w-[85%] md:max-w-[80%] opacity-40">
                        <LaborsterAvatar />
                        <div className="pt-1">
                          <p className="whitespace-pre-wrap break-words leading-relaxed text-[15px]">
                            {reply.content}
                          </p>
                          <p className="text-xs text-text-tertiary mt-1">
                            {formatCountdown(reply.scheduled_for, currentTime)}
                          </p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Input area */}
      <div className="shrink-0 px-4 pb-4 md:px-6 md:pb-6">
        <div className="max-w-3xl mx-auto">
          {isActiveSessionDeleted && (
            <div className="mb-3 px-4 py-3 bg-bg-tertiary rounded-xl text-sm text-text-secondary">
              该 Session 已删除，只能查看历史消息；如需继续聊天，请先恢复该 Session。
            </div>
          )}

          <div className="bg-bg-tertiary rounded-3xl shadow-sm border border-border overflow-hidden">
            <textarea
              ref={textareaRef}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              onInput={autoResize}
              rows={1}
              disabled={isActiveSessionReadOnly || !activeSessionId}
              className="w-full bg-transparent resize-none outline-none text-[15px] leading-relaxed max-h-[30vh] px-6 pt-4 pb-2 scrollbar-hide"
              placeholder={
                !activeSessionId
                  ? '请先选择一个 Session'
                  : isActiveSessionReadOnly
                  ? '该 Session 已删除，需恢复后才能发消息'
                  : '输入消息...'
              }
            />

            {/* Toolbar */}
            <div className="flex items-center justify-between px-4 pb-3">
              <div className="flex items-center gap-1" />
              <div className="flex items-center gap-2">
                {/* Provider picker */}
                {activeSessionId && !isActiveSessionReadOnly && providerConfigs.length > 0 && (
                  <div className="relative">
                    <button
                      onClick={() => setShowProviderDropdown(!showProviderDropdown)}
                      className="h-8 px-2.5 flex items-center gap-1 rounded-lg text-xs text-text-secondary hover:bg-[#e8eaed] transition max-w-[120px] truncate"
                      title="切换 LLM Provider"
                    >
                      <IconProvider />
                      <span className="truncate">{activeSessionProviderName || '选择 Provider'}</span>
                      <IconChevronDown />
                    </button>
                    {showProviderDropdown && (
                      <>
                        <div className="absolute bottom-full mb-1 right-0 bg-white rounded-xl shadow-lg border border-border min-w-[180px] py-1 z-40">
                          {providerConfigs.map((p) => (
                            <button
                              key={p.id}
                              onClick={() => {
                                onSwitchProvider(p.id);
                                setShowProviderDropdown(false);
                              }}
                              className={cn(
                                'w-full text-left px-4 py-2 text-sm hover:bg-bg-tertiary flex items-center justify-between gap-2',
                                activeSession?.provider_config_id === p.id && 'text-accent font-medium'
                              )}
                            >
                              <span className="truncate">{p.name}</span>
                              {activeSession?.provider_config_id === p.id && <IconCheck />}
                            </button>
                          ))}
                        </div>
                        <div
                          onClick={() => setShowProviderDropdown(false)}
                          className="fixed inset-0 z-30"
                        />
                      </>
                    )}
                  </div>
                )}

                {/* Send button */}
                <button
                  onClick={onSendMessage}
                  disabled={!inputText.trim() || !activeSessionId || isActiveSessionReadOnly}
                  className={cn(
                    'w-10 h-10 flex items-center justify-center rounded-full transition',
                    inputText.trim() && activeSessionId && !isActiveSessionReadOnly
                      ? 'bg-accent text-white hover:bg-accent-hover'
                      : 'bg-border text-text-tertiary'
                  )}
                >
                  <IconSend />
                </button>
              </div>
            </div>
          </div>
          <p className="text-center text-xs text-text-tertiary mt-3">
            消息发送后由 Robot Worker 异步消费队列生成回复。
          </p>
        </div>
      </div>
    </main>
  );
}
