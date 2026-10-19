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
