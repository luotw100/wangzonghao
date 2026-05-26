// Time utilities — mirrors WeChat behaviour:
// - bubbles never show timestamps inline (hover only via title attribute)
// - day separators appear when gap > 5 minutes from previous bubble
// - separator labels: "刚刚" / HH:mm / "昨天 HH:mm" / "周三 HH:mm" / "M月D日 HH:mm" / "YYYY年M月D日 HH:mm"
// - sidebar previews show: HH:mm / 昨天 / 周三 / YYYY/M/D

const WEEK_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

function startOfDay(d: Date): number {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x.getTime();
}

export function formatFullTime(value: string | Date): string {
  const d = typeof value === 'string' ? new Date(value) : value;
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Inline separator between message bubbles (WeChat-style). */
export function formatBubbleSeparator(value: string | Date, now: Date = new Date()): string {
  const d = typeof value === 'string' ? new Date(value) : value;
  const today = startOfDay(now);
  const target = startOfDay(d);
  const dayDiff = Math.round((today - target) / 86400000);
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;

  if (dayDiff === 0) return hm;
  if (dayDiff === 1) return `昨天 ${hm}`;
  if (dayDiff < 7) return `${WEEK_LABELS[d.getDay()]} ${hm}`;
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`;
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${hm}`;
}

/** Compact preview shown in conversation list. */
export function formatListPreview(value: string | Date, now: Date = new Date()): string {
  const d = typeof value === 'string' ? new Date(value) : value;
  const today = startOfDay(now);
  const target = startOfDay(d);
  const dayDiff = Math.round((today - target) / 86400000);

  if (dayDiff === 0) return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (dayDiff === 1) return '昨天';
  if (dayDiff < 7) return WEEK_LABELS[d.getDay()];
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}/${d.getDate()}`;
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
}

export function shouldShowSeparator(
  current: string | Date,
  previous: string | Date | null,
  thresholdMs = 5 * 60 * 1000
): boolean {
  if (!previous) return true;
  const a = typeof current === 'string' ? new Date(current) : current;
  const b = typeof previous === 'string' ? new Date(previous) : previous;
  return a.getTime() - b.getTime() >= thresholdMs;
}
