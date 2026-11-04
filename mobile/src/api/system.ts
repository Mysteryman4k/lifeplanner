/* Settings, reminders, updates, backup and restore: app.py's routes of the same names, on the phone.
   Windows-only routes (Start with Windows, self-updates, the window) answer as the Store build does. */
import type { Database, Row } from '../db/db';
import { fileStamp, hhmm, nowStamp, today } from '../dates';
import { HttpError, body, type Router } from '../http';
import { bool, lit, parse, str, type Model } from '../validate';
import { ACTIVE_JOB_STATUSES } from './track';
import { APP_NAME, dumpJson, getSetting, plural, putSetting, type Ctx, type Digest } from './context';

const Appearance: Model = {
  theme: lit(['plain', 'sunset', 'midnight', 'cobalt', 'ocean', 'berry', 'graphite'], { default: 'plain' }),
  font: lit(['system', 'rounded', 'modern', 'expressive', 'techy', 'classic'], { default: 'system' }),
  mode: lit(['system', 'light', 'dark'], { default: 'system' }),
};
const UpdateSettings: Model = { auto_check: bool({ default: true }) };
const StartupSettings: Model = { intro: bool({ default: true }) };
const MoneySettings: Model = { currency: str({ pattern: '^([A-Z]{3})?$' }) };
export const ReminderSettings: Model = {
  daily: bool({ default: true }),
  time: str({ default: '08:30', pattern: '^([01]\\d|2[0-3]):[0-5]\\d$' }),
};
const AutostartSettings: Model = { enabled: bool({ required: true }) };

export const REGION_CURRENCY: Record<string, string> = {
  AU: 'AUD', NZ: 'NZD', US: 'USD', GB: 'GBP', IE: 'EUR', CA: 'CAD', ZA: 'ZAR', IN: 'INR',
  SG: 'SGD', MY: 'MYR', HK: 'HKD', CN: 'CNY', JP: 'JPY', KR: 'KRW', PH: 'PHP', ID: 'IDR',
  NG: 'NGN', KE: 'KES', GH: 'GHS', ZW: 'USD', BW: 'BWP', NA: 'NAD', ZM: 'ZMW', AE: 'AED',
  SA: 'SAR', PK: 'PKR', BD: 'BDT', LK: 'LKR', NP: 'NPR', VN: 'VND', TH: 'THB', BR: 'BRL',
  MX: 'MXN', CH: 'CHF', SE: 'SEK', NO: 'NOK', DK: 'DKK', PL: 'PLN',
  ...Object.fromEntries(['DE', 'FR', 'ES', 'IT', 'NL', 'BE', 'AT', 'PT', 'FI', 'GR', 'LU', 'SK', 'SI',
    'EE', 'LV', 'LT', 'MT', 'CY', 'HR'].map(c => [c, 'EUR'])),
};

// Parents before children, so a restore can insert in this order
export const BACKUP_TABLES = ['categories', 'subjects', 'units', 'tasks', 'notes', 'code_folders', 'conversations', 'messages',
  'job_applications', 'transactions', 'budgets', 'settings'];
const COUNTED_TABLES = ['tasks', 'subjects', 'job_applications', 'transactions', 'budgets'];
const KEEP_AUTO_BACKUPS = 10;
/** Settings that belong to this device: never in backups, and kept as they are when one is restored. */
export const LOCAL_SETTINGS = ['reminders_last_sent', 'migrated_sample_budgets', 'ai', 'last_run_version'];

/** What the daily reminder says (reminders.build_digest), or null when there's nothing to do. */
export async function buildDigest(db: Database, day: string): Promise<Digest | null> {
  const overdue = (await db.all("SELECT title FROM tasks WHERE status != 'completed' AND due_date < ? ORDER BY due_date", day))
    .map(r => r.title);
  const dueToday = (await db.all("SELECT title FROM tasks WHERE status != 'completed' AND due_date = ? " +
    "ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END", day)).map(r => r.title);
  const followUps = (await db.all(`SELECT company FROM job_applications WHERE follow_up_date IS NOT NULL
      AND follow_up_date <= ? AND status IN (${ACTIVE_JOB_STATUSES.map(() => '?').join(',')}) ORDER BY follow_up_date`,
  day, ...ACTIVE_JOB_STATUSES)).map(r => r.company);
  if (!(overdue.length || dueToday.length || followUps.length)) return null;
  const parts: string[] = [];
  if (dueToday.length) parts.push(`${plural(dueToday.length, 'task')} due today`);
  if (overdue.length) parts.push(`${overdue.length} overdue`);
  if (followUps.length) parts.push(plural(followUps.length, 'follow-up'));
  let title = parts.join(', ');
  title = title[0].toUpperCase() + title.slice(1);
  const some = (names: string[], n: number) => names.slice(0, n).join(', ') + (names.length > n ? ` +${names.length - n} more` : '');
  const lines: string[] = [];
  if (dueToday.length) lines.push('Today: ' + some(dueToday, 3));
  if (overdue.length) lines.push('Overdue: ' + some(overdue, 2));
  if (followUps.length) lines.push('Follow up with ' + some(followUps, 3));
  return { title, body: lines.join('\n'),
    counts: { due_today: dueToday.length, overdue: overdue.length, follow_ups: followUps.length } };
}

/** Everything in one JSON object (Download backup, and the copies kept on the phone). */
export async function exportAll(ctx: Ctx) {
  const out: Row = { app: APP_NAME, version: ctx.version, exported_at: nowStamp() };
  for (const table of BACKUP_TABLES) {
    const rows = await ctx.db.all(`SELECT * FROM ${table}`);
    out[table] = table === 'settings' ? rows.filter(r => !LOCAL_SETTINGS.includes(r.key)) : rows;
  }
  return out;
}

/** Save a copy of everything in the app's backups folder (the phone's version of snapshot_database). */
export async function snapshot(ctx: Ctx, kind: string): Promise<string> {
  const name = `${kind}-${fileStamp()}.json`;
  await ctx.platform.backups.write(name, JSON.stringify(await exportAll(ctx)));
  return name;
}

const newestFirst = (names: string[]) => [...names].sort((a, b) => b.slice(-22).localeCompare(a.slice(-22)));

async function listBackups(ctx: Ctx, kind?: string) {
  const names = (await ctx.platform.backups.list()).filter(n => /-\d{4}-\d{2}-\d{2}_\d{6}\.json$/.test(n));
  return newestFirst(kind ? names.filter(n => n.startsWith(kind + '-')) : names);
}

/** One automatic backup a day, keeping the last few (run when the app starts; never stops it). */
export async function autoBackup(ctx: Ctx) {
  try {
    const stamp = today();
    const auto = await listBackups(ctx, 'auto');
    if (!auto.some(n => n.startsWith(`auto-${stamp}`))) await ctx.db.tx(() => snapshot(ctx, 'auto'));
    for (const kind of ['auto', 'before-restore']) {
      for (const old of (await listBackups(ctx, kind)).slice(KEEP_AUTO_BACKUPS)) await ctx.platform.backups.remove(old);
    }
  } catch (e) {
    console.error('Automatic backup failed', e);
  }
}

function checkBackup(data: unknown): Row {
  const d = data as Row;
  if (!d || typeof d !== 'object' || Array.isArray(d) || !['EasyUniTrack', 'Trackademic', 'LifePlanner'].includes(d.app) ||
      !Array.isArray(d.tasks)) {
    throw new HttpError(400, "That file isn't an EasyUniTrack backup.");
  }
  for (const table of BACKUP_TABLES) {
    const rows = d[table] ?? [];
    if (!Array.isArray(rows) || !rows.every(r => r && typeof r === 'object' && !Array.isArray(r))) {
      throw new HttpError(400, `The backup's ${table.replace(/_/g, ' ')} section is damaged.`);
    }
  }
  return d;
}

function dictBody(input: unknown): Row {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    throw new HttpError(422, [{ type: 'dict_type', loc: ['body'], msg: 'Input should be a valid dictionary', input }]);
  }
  return input as Row;
}

export function registerSystem(r: Router, ctx: Ctx, opts: { snapshotBeforeRestore?: boolean } = {}) {
  const { db, platform } = ctx;

  r.get('/api/info', () => ({
    name: APP_NAME, version: ctx.version, data_file: platform.dataLabel, today: today(),
    installed: true, store: true, mobile: true, platform: platform.name,
  }));

  r.post('/api/diag/client-ready', () => ({ version: ctx.version, client_ready: true }));
  r.get('/api/diag/startup', () => ({ version: ctx.version, client_ready: true }));

  // ── Appearance, money, start-up ──
  r.get('/api/settings/appearance', () => getSetting(db, 'appearance', Appearance));
  r.put('/api/settings/appearance', async req => {
    const { data } = parse<Row>(Appearance, body(req));
    await putSetting(db, 'appearance', dumpJson(Appearance, data));
    return data;
  });

  const money = async () => {
    const m = await getSetting<Row>(db, 'money', MoneySettings);
    return { currency: m.currency || REGION_CURRENCY[platform.region().toUpperCase()] || 'USD', chosen: !!m.currency };
  };
  r.get('/api/settings/money', money);
  r.put('/api/settings/money', async req => {
    const { data } = parse<Row>(MoneySettings, body(req));
    await putSetting(db, 'money', dumpJson(MoneySettings, data));
    return money();
  });

  r.get('/api/settings/updates', () => getSetting(db, 'updates', UpdateSettings));
  r.put('/api/settings/updates', async req => {
    const { data } = parse<Row>(UpdateSettings, body(req));
    await putSetting(db, 'updates', dumpJson(UpdateSettings, data));
    return data;
  });

  r.get('/api/settings/startup', () => getSetting(db, 'startup', StartupSettings));
  r.put('/api/settings/startup', async req => {
    const { data } = parse<Row>(StartupSettings, body(req));
    await putSetting(db, 'startup', dumpJson(StartupSettings, data));
    return data;
  });

  // ── Reminders: the phone schedules them with the system, so they come even while the app is closed ──
  r.get('/api/settings/reminders', () => getSetting(db, 'reminders', ReminderSettings));
  r.put('/api/settings/reminders', async req => {
    const { data } = parse<Row>(ReminderSettings, body(req));
    await putSetting(db, 'reminders', dumpJson(ReminderSettings, data));
    if (data.daily && hhmm() < data.time) await putSetting(db, 'reminders_last_sent', '""');
    platform.remindersChanged?.();
    return data;
  });
  r.get('/api/reminders/preview', async () => ({ digest: await buildDigest(db, today()) }));
  r.post('/api/reminders/test', async () => {
    const digest = (await buildDigest(db, today())) ??
      { title: 'Nothing due today', body: "You're all caught up. Reminders will look like this.", counts: {} };
    return { shown: await platform.notify(digest.title, digest.body), digest };
  });

  // ── Windows-only features, answered as the Store build does ──
  r.get('/api/settings/autostart', () => ({ supported: false, enabled: false }));
  r.put('/api/settings/autostart', req => {
    parse(AutostartSettings, body(req));
    throw new HttpError(400, 'Starting with Windows only works in the installed Windows app.');
  });
  r.post('/api/window/show', () => ({ ok: false }));
  r.get('/api/update/check', () => ({ current: ctx.version, available: false, store_managed: true }));
  r.post('/api/update/install', () => {
    throw new HttpError(400, platform.name === 'ios' ? 'Updates come from the App Store.' : 'Updates come from Google Play.');
  });

  // ── Backup ──
  r.get('/api/export', () => exportAll(ctx));
  r.get('/api/backups', async () => {
    const files = await listBackups(ctx);
    return { folder: platform.backups.folder, latest: files[0] ?? null, count: files.length };
  });
  r.post('/api/import/preview', req => {
    const data = checkBackup(dictBody(body(req)));
    return { exported_at: data.exported_at ?? null, version: data.version ?? null,
      counts: Object.fromEntries(COUNTED_TABLES.map(t => [t, (data[t] ?? []).length])) };
  });
  r.post('/api/import', async req => {
    const data = checkBackup(dictBody(body(req)));
    const safety = opts.snapshotBeforeRestore === false ? '' : await snapshot(ctx, 'before-restore');
    await restore(db, data);
    platform.remindersChanged?.();
    return { ok: true, safety_backup: safety, counts: Object.fromEntries(COUNTED_TABLES.map(t => [t, (data[t] ?? []).length])) };
  });
}

/**
 * Replace everything with a backup. Nothing changes unless the whole backup goes in cleanly.
 * Runs inside the request's lock but manages its own transaction: foreign keys have to be switched off
 * before it starts (SQLite ignores the switch inside one) and checked as a whole at the end.
 */
export async function restore(db: Database, data: Row) {
  const d = db.driver;
  await d.commit();                                   // close the request's transaction (nothing written yet)
  await d.exec('PRAGMA foreign_keys=OFF');
  await d.begin();
  try {
    for (const table of [...BACKUP_TABLES].reverse()) {
      if (table === 'settings') {
        await d.run(`DELETE FROM settings WHERE key NOT IN (${LOCAL_SETTINGS.map(() => '?').join(',')})`, LOCAL_SETTINGS);
      } else {
        await d.run(`DELETE FROM ${table}`, []);
      }
    }
    for (const table of BACKUP_TABLES) {
      const columns = new Set((await d.all(`PRAGMA table_info(${table})`, [])).map(r => r.name));
      for (const row of data[table] ?? []) {
        if (table === 'settings' && LOCAL_SETTINGS.includes(row.key)) continue;
        const cols = Object.keys(row).filter(c => columns.has(c));    // backups from older versions may lack columns
        if (!cols.length) continue;
        const values = cols.map(c => row[c]);
        const bad = values.find(v => v !== null && typeof v === 'object');
        if (bad !== undefined) throw new HttpError(400, `That backup couldn't be restored (Error binding parameter: type '${Array.isArray(bad) ? 'list' : 'dict'}' is not supported). Nothing was changed.`);
        await d.run(`INSERT INTO ${table} (${cols.join(',')}) VALUES (${cols.map(() => '?').join(',')})`,
          values.map(v => (typeof v === 'boolean' ? (v ? 1 : 0) : v)));
      }
    }
    if ((await d.all('PRAGMA foreign_key_check', [])).length) {
      throw new HttpError(400, "The backup has items linked to things that aren't in it, so nothing was changed.");
    }
    await d.run("UPDATE tasks SET status = CASE WHEN progress > 0 THEN 'in_progress' ELSE 'not_started' END WHERE status = 'overdue'", []);
    await d.commit();
  } catch (e) {
    await d.rollback();
    if (e instanceof HttpError) throw e;
    throw new HttpError(400, `That backup couldn't be restored (${(e as Error).message}). Nothing was changed.`);
  } finally {
    await d.exec('PRAGMA foreign_keys=ON');
    await d.begin();                                   // the request's transaction, committed as usual
  }
}
