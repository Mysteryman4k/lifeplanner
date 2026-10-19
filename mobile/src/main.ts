/* Starts EasyUniTrack on a phone (or in the browser preview). Loaded before app.js: it answers the screens'
   fetch('/api/…') calls from the database on the phone, so the desktop's screens run unchanged. */
import { Capacitor } from '@capacitor/core';
import initSqlJs from 'sql.js';
import { createApi, type Api } from './api';
import type { Ctx, Platform } from './api/context';
import { autoBackup } from './api/system';
import { Database } from './db/db';
import { initDb } from './db/schema';
import { SqlJsDriver } from './db/sqljs';
import { ALL_IDS, planReminders } from './reminders';

declare const __APP_VERSION__: string;

const native = Capacitor.isNativePlatform();
const realFetch = window.fetch.bind(window);

async function start(): Promise<{ api: Api; ctx: Ctx }> {
  let db: Database;
  let platform: Platform;
  if (native) {
    const [{ NativeDriver }, n] = await Promise.all([import('./db/native'), import('./platform/native')]);
    db = new Database(await NativeDriver.open());
    platform = {
      name: Capacitor.getPlatform() as 'android' | 'ios',
      dataLabel: 'On this phone, in the app\'s private storage. Removing the app removes it, so keep a backup.',
      region: n.region,
      notify: n.notifications.show,
      backups: n.nativeBackups,
      secrets: { get: async () => null, set: async () => undefined, remove: async () => undefined },
      fetch: realFetch,
    };
  } else {
    const w = await import('./platform/web');
    const SQL = await initSqlJs({ locateFile: () => '/static/vendor/sql-wasm.wasm' });
    const saved: Uint8Array | undefined = await w.webFiles.read('planner.db');
    db = new Database(await SqlJsDriver.open(SQL, saved, bytes => w.webFiles.write('planner.db', bytes).then(() => undefined)));
    platform = {
      name: 'web',
      dataLabel: 'In this browser (preview). Clearing the site\'s data removes it.',
      region: () => (navigator.language.split('-')[1] || ''),
      notify: w.webNotify,
      backups: w.webBackups,
      secrets: w.webSecrets,
      fetch: realFetch,
    };
  }
  await initDb(db, __APP_VERSION__);
  const ctx: Ctx = { db, version: __APP_VERSION__, platform };
  platform.remindersChanged = () => scheduleReminders(ctx, false);
  const api = createApi(ctx);
  void autoBackup(ctx);
  return { api, ctx };
}

const ready = start();
ready.catch(e => console.error('EasyUniTrack could not open its data', e));

// ── The screens' server calls, answered on the phone ──
window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
  if (url.origin !== location.origin || !url.pathname.startsWith('/api/')) return realFetch(input, init);
  const { api } = await ready;
  const method = (init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
  const b = init?.body;
  let body: string | Uint8Array | null = null;
  if (typeof b === 'string') body = b;
  else if (b instanceof Blob) body = new Uint8Array(await b.arrayBuffer());
  else if (b instanceof ArrayBuffer) body = new Uint8Array(b);
  else if (ArrayBuffer.isView(b)) body = new Uint8Array(b.buffer, b.byteOffset, b.byteLength);
  return api.handle(method, url.pathname + url.search, body, init?.signal ?? undefined);
};

// ── Daily reminders, handed to the system ahead of time (see reminders.ts) ──
let pendingSchedule: ReturnType<typeof setTimeout> | null = null;
function scheduleReminders(ctx: Ctx, ask: boolean) {
  if (!native) return;
  if (pendingSchedule) clearTimeout(pendingSchedule);
  pendingSchedule = setTimeout(async () => {
    pendingSchedule = null;
    try {
      const planned = await ctx.db.tx(() => planReminders(ctx.db));
      const { notifications } = await import('./platform/native');
      await notifications.replace(ALL_IDS, planned, ask);
    } catch (e) {
      console.error("Couldn't schedule reminders", e);
    }
  }, ask ? 0 : 800);
}

// ── What app.js asks of the phone (window.EUT_NATIVE) ──
(window as any).EUT_NATIVE = {
  platform: native ? Capacitor.getPlatform() : 'web',
  /** Save or send a file: the share sheet on a phone, a download in the preview. */
  async saveFile(name: string, text: string): Promise<boolean> {
    if (native) return (await import('./platform/native')).shareFile(name, text);
    return (await import('./platform/web')).downloadFile(name, text);
  },
};

if (native) {
  void (async () => {
    const { App } = await import('@capacitor/app');
    const { ctx } = await ready;
    scheduleReminders(ctx, true);                    // asks for permission to notify the first time
    App.addListener('resume', () => scheduleReminders(ctx, false));
    // Back: close what's open, then go back a screen, then leave the app
    App.addListener('backButton', () => {
      const drawer = document.getElementById('drawer');
      const confirm = document.getElementById('confirm');
      if (confirm && !confirm.hidden) (document.getElementById('confirmNo') as HTMLElement)?.click();
      else if (drawer && !drawer.hidden) (drawer.querySelector('[data-action="close-drawer"]') as HTMLElement)?.click();
      else if (location.hash && !/^#\/?(today)?$/.test(location.hash)) history.back();
      else void App.minimizeApp();
    });
    const { SplashScreen } = await import('@capacitor/splash-screen');
    void SplashScreen.hide();
  })();

  // Links to websites open in the browser, not inside the app
  document.addEventListener('click', e => {
    const a = (e.target as Element)?.closest?.('a[href]') as HTMLAnchorElement | null;
    if (!a || !/^https?:/i.test(a.href) || new URL(a.href).origin === location.origin) return;
    e.preventDefault();
    location.href = a.href;                          // Capacitor hands other sites to the system browser
  }, true);
}
