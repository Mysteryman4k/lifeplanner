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
import { pdfJsReader } from '../src/ai/files';
import { strToU8 } from 'fflate';

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
    readPdf: pdfJsReader(() => import('pdfjs-dist/legacy/build/pdf.mjs')),
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

// ── A fake network for the AI providers ──
export interface NetCall { method: string; url: URL; headers: Record<string, string>; body: any }
type Reply = [number, unknown] | ((call: NetCall) => [number, unknown]);

/** Replies by "METHOD host/path" prefix. A string reply is sent in small pieces, as a stream arrives. */
export function fakeNet(routes: Record<string, Reply | Reply[]> = {}) {
  const calls: NetCall[] = [];
  const fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const headers = Object.fromEntries(Object.entries(init.headers ?? {}).map(([k, v]) => [k.toLowerCase(), String(v)]));
    const call: NetCall = { method: init.method ?? 'GET', url, headers, body: init.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    const key = `${call.method} ${url.host}${url.pathname}`;
    const match = Object.keys(routes).filter(k => key.startsWith(k)).sort((a, b) => b.length - a.length)[0];
    if (!match) throw new TypeError('offline in tests');
    let reply = routes[match];
    if (Array.isArray(reply) && (Array.isArray(reply[0]) || typeof reply[0] === 'function')) {
      const list = reply as Reply[];
      reply = list.length > 1 ? list.shift()! : list[0];
    }
    const [status, body] = typeof reply === 'function' ? reply(call) : reply as [number, unknown];
    const text = typeof body === 'string' ? body : JSON.stringify(body);
    const bytes = new TextEncoder().encode(text);
    const signal = init.signal;
    const stream = new ReadableStream<Uint8Array>({
      async start(c) {
        for (let i = 0; i < bytes.length; i += 7) {
          if (signal?.aborted) { c.error(new DOMException('aborted', 'AbortError')); return; }
          c.enqueue(bytes.slice(i, i + 7));
          await new Promise(r => setTimeout(r, 0));
        }
        c.close();
      },
    });
    return new Response(stream, { status });
  }) as typeof globalThis.fetch;
  return { fetch, calls, routes };
}

export const sseBody = (...events: unknown[]) => events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('') + 'data: [DONE]\n\n';

/** The events of a streamed chat reply. */
export async function streamEvents(res: { status: number; json: any }) {
  if (typeof res.json !== 'string') return res.json;
  return res.json.split('\n').filter((l: string) => l.startsWith('data:')).map((l: string) => JSON.parse(l.slice(5)));
}

/** A small real PDF with one line of text per page (Helvetica, uncompressed). */
export function minimalPdf(pages: string[]): Uint8Array {
  const objs: string[] = [];
  const kids = pages.map((_, i) => `${4 + i * 2} 0 R`).join(' ');
  objs.push('<< /Type /Catalog /Pages 2 0 R >>');
  objs.push(`<< /Type /Pages /Kids [${kids}] /Count ${pages.length} >>`);
  objs.push('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');
  pages.forEach((text, i) => {
    const stream = text ? `BT /F1 18 Tf 72 720 Td (${text}) Tj ET` : '';
    objs.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents ${5 + i * 2} 0 R >>`);
    objs.push(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
  });
  let out = '%PDF-1.4\n';
  const offsets: number[] = [];
  objs.forEach((o, i) => { offsets.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const xref = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offsets.map(o => `${String(o).padStart(10, '0')} 00000 n \n`).join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return strToU8(out);
}
