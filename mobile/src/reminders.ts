/* The daily reminder on the phone. The desktop sends it from its open window each morning; a phone app
   isn't running then, so the next two weeks of reminders are handed to the system ahead of time, each
   saying what's due that day. They're worked out again whenever the app opens or anything changes. */
import type { Database } from './db/db';
import { addDays, hhmm, ymd } from './dates';
import { getSetting, type Digest } from './api/context';
import { ReminderSettings, buildDigest } from './api/system';

export const FIRST_ID = 1000;
export const DAYS_AHEAD = 14;

export interface Planned { id: number; at: Date; title: string; body: string }

/** The reminders to hand to the system: one per day with something to do, at the chosen time. */
export async function planReminders(db: Database, now = new Date()): Promise<Planned[]> {
  const settings = await getSetting<{ daily: boolean; time: string }>(db, 'reminders', ReminderSettings);
  if (!settings.daily) return [];
  const [h, m] = settings.time.split(':').map(Number);
  const start = hhmm(now) < settings.time ? ymd(now) : addDays(ymd(now), 1);    // today's time has passed: from tomorrow
  const out: Planned[] = [];
  for (let i = 0; i < DAYS_AHEAD; i++) {
    const day = addDays(start, i);
    const digest: Digest | null = await buildDigest(db, day);
    if (!digest) continue;
    const [y, mo, d] = day.split('-').map(Number);
    out.push({ id: FIRST_ID + i, at: new Date(y, mo - 1, d, h, m), title: digest.title, body: digest.body });
  }
  return out;
}

/** All the ids this app uses for daily reminders (cancelled before scheduling again). */
export const ALL_IDS = Array.from({ length: DAYS_AHEAD + 1 }, (_, i) => FIRST_ID + i);
