export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '';

  const date = new Date(dateStr);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 24 * 60 * 60 * 1000);
  const targetDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());

  if (targetDate.getTime() === today.getTime()) {
    return formatTime(date);
  }
  if (targetDate.getTime() === yesterday.getTime()) {
    return '昨天 ' + formatTime(date);
  }
  if (date.getFullYear() === now.getFullYear()) {
    return `${date.getMonth() + 1}-${date.getDate()} ${formatTime(date)}`;
  }
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
}

export function formatTime(date: Date): string {
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${hours}:${minutes}`;
}

export function formatCountdown(scheduledForStr: string | null | undefined, now: number): string {
  if (!scheduledForStr || !scheduledForStr.trim()) return '';
  const raw = scheduledForStr.endsWith('Z') ? scheduledForStr : scheduledForStr + 'Z';
  const target = new Date(raw).getTime();
  const diff = Math.round((target - now) / 1000);
  if (diff <= 0) return 'Worker 发送中...';
  if (diff < 60) return diff + '秒后';
  const m = Math.floor(diff / 60);
  const s = diff % 60;
  return s > 0 ? m + '分' + s + '秒后' : m + '分后';
}

export function getQueueBadge(session: { queue_state?: { pending_inbound_events: number; active_generation_jobs: number; pending_dispatch_jobs: number } }): number | null {
  if (!session.queue_state) return null;
  const qs = session.queue_state;
  const total = (qs.pending_inbound_events || 0) + (qs.active_generation_jobs || 0) + (qs.pending_dispatch_jobs || 0);
  return total === 0 ? null : total;
}

export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}
