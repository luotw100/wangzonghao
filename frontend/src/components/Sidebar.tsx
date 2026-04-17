import { cn, getQueueBadge } from '../lib/utils';
import { LaborsterLogo, IconPlus, IconSettings, IconClose, IconEdit, IconChevronRight, IconLayers } from './Icons';
import type { Robot, Session } from '../lib/api';

interface SidebarProps {
  sidebarOpen: boolean;
  setSidebarOpen: (v: boolean) => void;
  robots: Robot[];
  sessionsByRobot: Record<string, Session[]>;
  collapsedRobots: Record<string, boolean>;
  activeSessionId: string | null;
  showDeletedItems: boolean;
  setShowDeletedItems: (v: boolean) => void;
  onToggleRobot: (robotId: string) => void;
  onSelectSession: (sessionId: string) => void;
  onEditRobot: (robot: Robot) => void;
  onCreateSession: (robotId: string | null) => void;
  onEditSession: (session: Session) => void;
  onOpenSettings: () => void;
}

export function Sidebar({
  sidebarOpen,
  setSidebarOpen,
  robots,
  sessionsByRobot,
  collapsedRobots,
  activeSessionId,
  showDeletedItems,
  setShowDeletedItems,
  onToggleRobot,
  onSelectSession,
  onEditRobot,
  onCreateSession,
  onEditSession,
  onOpenSettings,
}: SidebarProps) {
  return (
    <>
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          onClick={() => setSidebarOpen(false)}
          className="fixed inset-0 bg-black/30 z-40 md:hidden backdrop-blur-sm"
        />
      )}

      <aside
        className={cn(
          'w-80 bg-[#fafafa] flex flex-col fixed md:relative inset-y-0 left-0 z-50',
          'transform transition-transform duration-300 ease-out',
          'md:translate-x-0 md:bg-white md:border-r md:border-border',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 h-14 border-b border-border">
          <div className="flex items-center gap-3">
            <LaborsterLogo />
            <span className="font-medium text-text-primary">Laborster</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={onOpenSettings}
              className="w-10 h-10 flex items-center justify-center rounded-full hover:bg-bg-tertiary transition"
              title="设置"
            >
              <IconSettings />
            </button>
            <button
              onClick={() => setSidebarOpen(false)}
              className="md:hidden w-10 h-10 flex items-center justify-center rounded-full hover:bg-bg-tertiary"
            >
              <IconClose size={20} />
            </button>
          </div>
        </div>

        {/* New Session Button */}
        <div className="px-3 mt-4 space-y-2">
          <button
            onClick={() => onCreateSession(null)}
            className="w-full px-4 py-2.5 flex items-center gap-3 rounded-full border border-border hover:bg-bg-tertiary transition"
          >
            <IconPlus />
            <span className="text-sm font-medium">新建 Session</span>
          </button>
        </div>

        <label className="mx-4 mt-3 flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
          <input
            type="checkbox"
            checked={showDeletedItems}
            onChange={(e) => setShowDeletedItems(e.target.checked)}
            className="rounded border-border text-accent focus:ring-accent"
          />
          <span>显示已删除项</span>
        </label>

        {/* Robot + Session list */}
        <div className="flex-1 overflow-y-auto mt-4 px-2 scrollbar-hide">
          {robots.map((robot) => (
            <div key={robot.id} className="mb-2">
              {/* Robot header */}
              <div
                className={cn(
                  'flex items-center gap-1 px-3 py-2 rounded-lg hover:bg-bg-tertiary cursor-pointer transition',
                  robot.is_deleted && 'opacity-70'
                )}
                onClick={() => onToggleRobot(robot.id)}
              >
                <span
                  className={cn('transition-transform', !collapsedRobots[robot.id] && 'rotate-90')}
                >
                  <IconChevronRight />
                </span>
                <span className="font-medium text-sm flex-1">{robot.name}</span>
                {robot.is_deleted && (
                  <span className="px-2 py-0.5 rounded-full bg-danger-bg text-danger text-[10px] shrink-0">
                    已删除
                  </span>
                )}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onEditRobot(robot);
                  }}
                  className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-bg-tertiary shrink-0"
                  title="编辑 Robot"
                >
                  <IconEdit />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onCreateSession(robot.id);
                  }}
                  disabled={robot.is_deleted}
                  className="w-8 h-8 flex items-center justify-center rounded-full shrink-0 disabled:opacity-30 disabled:cursor-not-allowed hover:bg-bg-tertiary"
                  title="新建 Session"
                >
                  <IconPlus size={14} />
                </button>
              </div>

              {/* Sessions under robot */}
              {!collapsedRobots[robot.id] && (
                <div className="ml-3 pl-3 border-l border-border">
                  {(sessionsByRobot[robot.id] || []).map((session) => {
                    const badge = getQueueBadge(session);
                    return (
                      <div
                        key={session.id}
                        onClick={() => {
                          onSelectSession(session.id);
                          setSidebarOpen(false);
                        }}
                        className={cn(
                          'group px-3 py-2 rounded-lg cursor-pointer transition text-sm',
                          activeSessionId === session.id
                            ? 'bg-[#e8f0fe] text-accent'
                            : 'hover:bg-bg-tertiary text-text-secondary'
                        )}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2 min-w-0 flex-1">
                            <span
                              className={cn(
                                'truncate flex-1',
                                session.status === 'deleted' && 'opacity-80'
                              )}
                            >
                              {session.title || '未命名'}
                            </span>
                            {session.status === 'deleted' && (
                              <span className="px-2 py-0.5 rounded-full bg-danger-bg text-danger text-[10px] shrink-0">
                                已删除
                              </span>
                            )}
                            {session.status === 'orphaned' && (
                              <span className="px-2 py-0.5 rounded-full bg-[#fef7e0] text-[#e37400] text-[10px] shrink-0">
                                孤立
                              </span>
                            )}
                            {badge && (
                              <span className="w-5 h-5 flex items-center justify-center rounded-full bg-accent text-white text-[10px] shrink-0">
                                {badge}
                              </span>
                            )}
                          </div>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onEditSession(session);
                            }}
                            className="w-6 h-6 flex items-center justify-center rounded shrink-0 opacity-30 group-hover:opacity-100 hover:bg-border transition"
                          >
                            <IconEdit size={12} />
                          </button>
                        </div>
                        <div className="text-[11px] mt-0.5 opacity-60">
                          {session.contact?.name || '—'}
                        </div>
                      </div>
                    );
                  })}
                  {(!sessionsByRobot[robot.id] || sessionsByRobot[robot.id].length === 0) && (
                    <div className="px-3 py-2 text-xs text-text-tertiary">暂无 Session</div>
                  )}
                </div>
              )}
            </div>
          ))}

          {robots.length === 0 && (
            <div className="text-center py-8 text-text-tertiary">
              <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-bg-tertiary flex items-center justify-center">
                <IconLayers />
              </div>
              <p className="text-sm">还没有 Robot</p>
              <p className="text-xs mt-1">点击 ⚙️ 设置创建一个</p>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
