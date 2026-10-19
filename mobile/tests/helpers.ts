/* A fresh phone app for each test: an in-memory database (sql.js), a fake phone and a client
   that calls the API the way the screens do. */
import initSqlJs, { type SqlJsStatic } from 'sql.js';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createApi } from '../src/api';
import type { Ctx, Platform } from '../src/api/context';
import { Database } from '../src/db/db';
import { initDb } from '../src/db/schema';
import { SqlJsDriver } from '../src/db/sqljs';

export const VERSION = readFileSync(fileURLToPath(new URL('../../VERSION', import.meta.url)), 'utf8').trim();

let SQL: SqlJsStatic | null = null;

export interface FakePhone extends Platform {
  notified: { title: string; body: string }[];
  files: Map<string, string>;
  vault: Map<string, string>;
  reminderChanges: number;
}

export function fakePlatform(): FakePhone {
  const files = new Map<string, string>();
  const vault = new Map<string, string>();
  const p: FakePhone = {
    name: 'test', dataLabel: 'On this phone', notified: [], files, vault, reminderChanges: 0,
    region: () => 'AU',
    notify: async (title, body) => { p.notified.push({ title, body }); return true; },
    remindersChanged: () => { p.reminderChanges++; },
    backups: {
      folder: 'backups',
      write: async (name, text) => { files.set(name, text); },
      list: async () => [...files.keys()],
      remove: async name => { files.delete(name); },
    },
    secrets: {
      get: async k => vault.get(k) ?? null,
      set: async (k, v) => { vault.set(k, v); },
      remove: async k => { vault.delete(k); },
    },
    fetch: (async () => { throw new TypeError('offline in tests'); }) as typeof fetch,
  };
  return p;
}

export interface Res { status: number; json: any }

export async function makeApp(platform: FakePhone = fakePlatform()) {
  SQL ??= await initSqlJs();
  const driver = await SqlJsDriver.open(SQL);
  const db = new Database(driver);
  await initDb(db, VERSION);
  const ctx: Ctx = { db, version: VERSION, platform };
  const api = createApi(ctx);
  const call = async (method: string, path: string, body?: unknown, params?: Record<string, string>): Promise<Res> => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    const res = await api.handle(method, path + qs, body === undefined ? null : JSON.stringify(body));
    const text = await res.text();
    let json: any = text;
    try { json = JSON.parse(text); } catch { /* not JSON */ }
    return { status: res.status, json };
  };
  return {
    ctx, api, db, driver, platform,
    get: (path: string, params?: Record<string, string>) => call('GET', path, undefined, params),
    post: (path: string, body?: unknown) => call('POST', path, body),
    put: (path: string, body?: unknown) => call('PUT', path, body),
    del: (path: string) => call('DELETE', path),
    call,
  };
}

export type App = Awaited<ReturnType<typeof makeApp>>;

const pad = (n: number) => String(n).padStart(2, '0');
/** Today plus n days, as YYYY-MM-DD (local). */
export function d(n: number) {
  const x = new Date();
  x.setDate(x.getDate() + n);
  return `${x.getFullYear()}-${pad(x.getMonth() + 1)}-${pad(x.getDate())}`;
}
