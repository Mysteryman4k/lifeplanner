/* Dates as the desktop handles them: local calendar dates as YYYY-MM-DD, never UTC. */
const pad = (n: number) => String(n).padStart(2, '0');

export const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const today = () => ymd(new Date());

/** date.fromisoformat for YYYY-MM-DD, as a local Date at midnight. */
export function parseYmd(s: string): Date {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function addDays(s: string, n: number): string {
  const d = parseYmd(s);
  d.setDate(d.getDate() + n);
  return ymd(d);
}

/** Whole days from a to b (b - a). */
export const daysBetween = (a: string, b: string) => Math.round((parseYmd(b).getTime() - parseYmd(a).getTime()) / 86400000);

/** "YYYY-MM-DD HH:MM", local time (the desktop's now_stamp). */
export function nowStamp(d = new Date()) {
  return `${ymd(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** "YYYY-MM-DD_HHMMSS", for backup file names. */
export function fileStamp(d = new Date()) {
  return `${ymd(d)}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

export const hhmm = (d = new Date()) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
