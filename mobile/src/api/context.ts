/* What the API needs from the phone, and helpers shared by the route files. */
import type { Database } from '../db/db';
import type { PdfReader } from '../ai/files';
import { HttpError } from '../http';
import { parse, type Model } from '../validate';

export interface Digest { title: string; body: string; counts: Record<string, number> }

/** The parts that differ between Android, iPhone, the browser preview and tests. */
export interface Platform {
  name: 'android' | 'ios' | 'web' | 'test';
  /** Where the data is kept, in words (Settings shows it under "Your data"). */
  dataLabel: string;
  /** The phone's region, like "AU" (picks the suggested currency). */
  region(): string;
  /** Show a notification now. False if it couldn't be (notifications turned off). */
  notify(title: string, body: string): Promise<boolean>;
  /** Called after anything that could change what the daily reminder says, and when its settings change. */
  remindersChanged?(): void;
  /** Backup files in the app's own storage: a copy is kept before a restore and once a day. */
  backups: {
    write(name: string, text: string): Promise<void>;
    list(): Promise<string[]>;
    remove(name: string): Promise<void>;
    folder: string;
  };
  /** AI keys: the Android Keystore / iOS Keychain. Never in the database or backups. */
  secrets: {
    get(key: string): Promise<string | null>;
    set(key: string, value: string): Promise<void>;
    remove(key: string): Promise<void>;
  };
  /** Network access for the AI providers (tests pass a fake). */
  fetch: typeof fetch;
  /** Reads a PDF's pages for attachments (pdf.js). */
  readPdf?: PdfReader;
}

export interface Ctx {
  db: Database;
  version: string;
  platform: Platform;
}

export const APP_NAME = 'EasyUniTrack';

/** Python's round(): halves go to the even neighbour, and the exact binary value decides (round(2.675, 2) == 2.67). */
export function pyRound(x: number, n = 0): number {
  if (!Number.isFinite(x)) return x;
  const exact = Math.abs(x).toFixed(Math.min(100, n + 60));      // the double's decimal expansion, to 60 more places
  const [whole, frac = ''] = exact.split('.');
  const keep = frac.slice(0, n), rest = frac.slice(n);
  let digits = whole + keep;
  const half = rest[0] > '5' || (rest[0] === '5' && /[1-9]/.test(rest.slice(1)));
  const tie = rest[0] === '5' && !/[1-9]/.test(rest.slice(1));
  const lastEven = Number(digits[digits.length - 1]) % 2 === 0;
  if (half || (tie && !lastEven)) {
    const arr = digits.split('').map(Number);
    let i = arr.length - 1;
    while (i >= 0) { if (arr[i] === 9) { arr[i] = 0; i--; } else { arr[i]++; break; } }
    digits = (i < 0 ? '1' : '') + arr.join('');
  }
  const value = Number(n ? `${digits.slice(0, digits.length - n)}.${digits.slice(digits.length - n)}` : digits);
  return x < 0 ? -value : value;
}

export const plural = (n: number, word: string, many?: string) => `${n} ${n === 1 ? word : (many ?? word + 's')}`;

/** A setting stored as JSON (the desktop's _get_setting): its defaults when missing or unreadable. */
export async function getSetting<T>(db: Database, key: string, model: Model): Promise<T> {
  const row = await db.get('SELECT value FROM settings WHERE key=?', key);
  if (row) {
    try {
      return parse<T>(model, JSON.parse(row.value)).data;
    } catch { /* fall through to the defaults */ }
  }
  return parse<T>(model, {}).data;
}

export async function putSetting(db: Database, key: string, value: string) {
  await db.run('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', key, value);
}

/** Pydantic's model_dump_json(): compact JSON, fields in the model's order. */
export function dumpJson(model: Model, data: Record<string, unknown>) {
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(model)) out[k] = data[k];
  return JSON.stringify(out);
}

export async function requireRow(db: Database, table: string, id: number, label = 'Item') {
  if (!(await db.get(`SELECT 1 FROM ${table} WHERE id=?`, id))) throw new HttpError(404, `${label} not found`);
}
