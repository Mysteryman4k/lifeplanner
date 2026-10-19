/* What only the phone does: reminders handed to the system ahead of time, backups kept in the app's storage. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { autoBackup } from '../src/api/system';
import { planReminders, FIRST_ID } from '../src/reminders';
import { makeApp } from './helpers';

afterEach(() => { vi.useRealTimers(); });

const at = (iso: string) => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(iso));
};

describe('daily reminders', () => {
  it('plans one for each day with something to do, saying what that day holds', async () => {
    at('2026-10-19T07:00:00');                     // Monday, before the 08:30 default
    const c = await makeApp();
    await c.post('/api/tasks', { title: 'Lab report', due_date: '2026-10-19', priority: 'high' });
    await c.post('/api/tasks', { title: 'Quiz', due_date: '2026-10-22' });
    await c.post('/api/jobs', { company: 'Canva', role: 'Intern', follow_up_date: '2026-10-21' });
    const plan = await c.db.tx(() => planReminders(c.db));
    expect(plan.map(p => [p.at.getDate(), p.at.getHours(), p.at.getMinutes()]).slice(0, 4))
      .toEqual([[19, 8, 30], [20, 8, 30], [21, 8, 30], [22, 8, 30]]);
    expect(plan[0]).toMatchObject({ id: FIRST_ID, title: '1 task due today', body: 'Today: Lab report' });
    // Not done by Tuesday, it's overdue from then on, so every later day has a reminder
    expect(plan[1]).toMatchObject({ title: '1 overdue', body: 'Overdue: Lab report' });
    expect(plan[2].title).toBe('1 overdue, 1 follow-up');
    expect(plan[3].title).toBe('1 task due today, 1 overdue, 1 follow-up');
    expect(plan).toHaveLength(14);
  });

  it('plans from the time it is given, not the clock', async () => {
    at('2026-10-19T07:00:00');
    const c = await makeApp();
    await c.post('/api/tasks', { title: 'Essay', due_date: '2026-10-25' });
    const plan = await c.db.tx(() => planReminders(c.db, new Date(2026, 9, 24, 21, 0)));
    expect(plan[0].at).toEqual(new Date(2026, 9, 25, 8, 30));        // the 24th's time had passed: from the 25th
  });

  it('starts tomorrow once today\'s time has passed, and plans none when turned off or nothing is due', async () => {
    at('2026-10-19T09:00:00');
    const c = await makeApp();
    expect(await c.db.tx(() => planReminders(c.db))).toEqual([]);
    await c.post('/api/tasks', { title: 'Essay', due_date: '2026-10-19' });
    const plan = await c.db.tx(() => planReminders(c.db));
    expect(plan[0].at.getDate()).toBe(20);
    expect(plan[0].title).toBe('1 overdue');
    await c.put('/api/settings/reminders', { daily: false, time: '08:30' });
    expect(await c.db.tx(() => planReminders(c.db))).toEqual([]);
  });

  it('asks the phone to reschedule after every change, not after reads', async () => {
    const c = await makeApp();
    const before = c.platform.reminderChanges;
    await c.get('/api/tasks');
    expect(c.platform.reminderChanges).toBe(before);
    await c.post('/api/tasks', { title: 'x' });
    await c.put('/api/settings/reminders', { daily: true, time: '18:45' });
    expect(c.platform.reminderChanges).toBe(before + 2 + 1);       // the settings route also says so itself
  });

  it('sends the test notification through the phone', async () => {
    const c = await makeApp();
    const r = (await c.post('/api/reminders/test')).json;
    expect(r.shown).toBe(true);
    expect(c.platform.notified).toEqual([{ title: 'Nothing due today', body: "You're all caught up. Reminders will look like this." }]);
  });
});

describe('the browser preview\'s saved file', () => {
  it('is only written again when something changed', async () => {
    const SQL = await (await import('sql.js')).default();
    const { SqlJsDriver } = await import('../src/db/sqljs');
    const { Database } = await import('../src/db/db');
    let saves = 0;
    const db = new Database(await SqlJsDriver.open(SQL, null, async () => { saves++; }));
    await db.tx(() => db.exec('CREATE TABLE t (x)'));
    await db.tx(() => db.run('INSERT INTO t VALUES (1)'));
    expect(saves).toBe(2);
    await db.tx(() => db.all('SELECT * FROM t'));
    await db.tx(() => db.all('SELECT * FROM t'));
    expect(saves).toBe(2);                                             // reads don't rewrite the whole file
    await db.tx(() => db.run('UPDATE t SET x = 2'));
    expect(saves).toBe(3);
    await db.tx(() => db.exec('ALTER TABLE t ADD COLUMN y'));            // a new column with no rows written is saved too
    expect(saves).toBe(4);
    expect(await db.tx(() => db.run('INSERT INTO t VALUES (NULL, 1)'))).toMatchObject({ changes: 1 });
  });
});

describe('backups on the phone', () => {
  it('keeps one automatic backup a day, the last 10', async () => {
    const c = await makeApp();
    for (let i = 1; i <= 12; i++) c.platform.files.set(`auto-2026-09-${String(i).padStart(2, '0')}_080000.json`, '{}');
    c.platform.files.set('other.txt', 'not a backup');
    await autoBackup(c.ctx);
    await autoBackup(c.ctx);                                         // the same day: no second copy
    const autos = [...c.platform.files.keys()].filter(n => n.startsWith('auto-')).sort();
    expect(autos).toHaveLength(10);
    expect(autos[0]).toBe('auto-2026-09-04_080000.json');            // the oldest went
    expect(c.platform.files.has('other.txt')).toBe(true);
    const today = autos[autos.length - 1];
    expect(JSON.parse(c.platform.files.get(today)!).app).toBe('EasyUniTrack');
    expect((await c.get('/api/backups')).json).toMatchObject({ latest: today, count: 10 });
  });

  it('saves the current data before a restore replaces it', async () => {
    const c = await makeApp();
    await c.post('/api/tasks', { title: 'Before the restore' });
    const r = (await c.post('/api/import', { app: 'EasyUniTrack', tasks: [] })).json;
    expect(r.safety_backup).toMatch(/^before-restore-\d{4}-\d{2}-\d{2}_\d{6}\.json$/);
    const saved = JSON.parse(c.platform.files.get(r.safety_backup)!);
    expect(saved.tasks.map((t: any) => t.title)).toEqual(['Before the restore']);
    expect((await c.get('/api/tasks')).json).toEqual([]);
  });

  it('keeps device settings (like the AI agreement) out of backups and through a restore', async () => {
    const c = await makeApp();
    await c.db.tx(() => c.db.run("INSERT INTO settings (key, value) VALUES ('ai', '{\"agreed\":true}')"));
    const backup = (await c.get('/api/export')).json;
    expect(backup.settings.map((s: any) => s.key)).not.toContain('ai');
    await c.post('/api/import', { ...backup, settings: [{ key: 'ai', value: '{"agreed":false}' }] });
    expect(await c.db.tx(() => c.db.value("SELECT value FROM settings WHERE key='ai'"))).toBe('{"agreed":true}');
  });

  it('a failed restore changes nothing and the app keeps working', async () => {
    const c = await makeApp();
    await c.post('/api/tasks', { title: 'Keep me' });
    const r = await c.post('/api/import', { app: 'EasyUniTrack', tasks: [{ id: 1, title: 'x', subject_id: 42 }] });
    expect(r.status).toBe(400);
    expect((await c.get('/api/tasks')).json.map((t: any) => t.title)).toEqual(['Keep me']);
    expect((await c.post('/api/tasks', { title: 'Still works', subject_id: 999 })).status).toBe(400);   // foreign keys back on
  });
});

describe('streamed requests through the Android plugin', async () => {
  const { nativeStreamFetch } = await import('../src/platform/streamfetch');

  /** A stand-in for StreamFetchPlugin.java: replies with the given status and pieces. */
  function fakePlugin(status: number, pieces: string[], fail?: 'before' | 'during') {
    const listeners: Record<string, ((e: any) => void)[]> = { chunk: [], end: [] };
    const cancelled: string[] = [];
    const started: any[] = [];
    const plugin = {
      async addListener(event: string, fn: (e: any) => void) { listeners[event].push(fn); return { remove: async () => undefined }; },
      async cancel({ id }: { id: string }) { cancelled.push(id); },
      async start(o: any) {
        started.push(o);
        if (fail === 'before') throw new Error('network');
        // The first piece can arrive before start() resolves in the app: it must not be lost
        listeners.chunk.forEach(f => f({ id: o.id, data: btoa(pieces[0]) }));
        setTimeout(() => {
          for (const p of pieces.slice(1)) listeners.chunk.forEach(f => f({ id: o.id, data: btoa(p) }));
          listeners.end.forEach(f => f({ id: o.id, error: fail === 'during' ? 'network' : undefined }));
        }, 5);
        return { status, headers: { 'content-type': 'text/event-stream' } };
      },
    };
    return { plugin, cancelled, started };
  }

  it('gives a fetch()-like Response whose body arrives in pieces', async () => {
    const { plugin, started } = fakePlugin(200, ['data: 1\n', '\ndata: 2\n\n']);
    const res = await nativeStreamFetch(plugin as any)('https://api.openai.com/v1/chat/completions',
      { method: 'POST', headers: { Authorization: 'Bearer k' }, body: '{"a":1}' });
    expect(res.status).toBe(200);
    expect(await res.text()).toBe('data: 1\n\ndata: 2\n\n');
    expect(started[0]).toMatchObject({ method: 'POST', headers: { authorization: 'Bearer k' }, body: '{"a":1}' });
  });

  it('fails like fetch() when the request can\'t be made, and when the connection drops', async () => {
    await expect(nativeStreamFetch(fakePlugin(200, ['x'], 'before').plugin as any)('https://x.test')).rejects.toThrow(TypeError);
    const res = await nativeStreamFetch(fakePlugin(200, ['a', 'b'], 'during').plugin as any)('https://x.test');
    await expect(res.text()).rejects.toThrow();
  });

  it('drops what arrives for a stopped request instead of keeping it', async () => {
    const listeners: Record<string, ((e: any) => void)[]> = { chunk: [], end: [] };
    let lastId = '';
    const plugin = {
      async addListener(event: string, fn: (e: any) => void) { listeners[event].push(fn); return { remove: async () => undefined }; },
      async cancel() { /* the native side keeps sending for a moment */ },
      async start(o: any) { lastId = o.id; return { status: 200, headers: {} }; },
    };
    const doFetch = nativeStreamFetch(plugin as any);
    const ctrl = new AbortController();
    const res = await doFetch('https://x.test', { signal: ctrl.signal });
    ctrl.abort();
    await expect(res.text()).rejects.toThrow(/abort/i);
    listeners.chunk.forEach(f => f({ id: lastId, data: btoa('late') }));
    listeners.end.forEach(f => f({ id: lastId, error: 'network' }));
    expect(doFetch.buffered()).toBe(0);
  });

  it('stops the request when the student taps Stop', async () => {
    const fake = fakePlugin(200, ['a', 'b', 'c']);
    const ctrl = new AbortController();
    const res = await nativeStreamFetch(fake.plugin as any)('https://x.test', { signal: ctrl.signal });
    ctrl.abort();
    await expect(res.text()).rejects.toThrow(/abort/i);
    expect(fake.cancelled).toHaveLength(1);
  });

  it('works with the providers end to end: a key error comes back in plain words', async () => {
    const { getProvider } = await import('../src/ai/providers');
    const fake = fakePlugin(401, ['{"error":{"message":"invalid x-api-key"}}']);
    const p = getProvider('anthropic', { key: 'sk-ant-12345678', fetch: nativeStreamFetch(fake.plugin as any) });
    const events: unknown[] = [];
    await expect((async () => { for await (const e of p.streamChat('m', 's', [{ role: 'user', content: 'hi' }])) events.push(e); })())
      .rejects.toThrow(/key wasn't accepted/);
  });
});
