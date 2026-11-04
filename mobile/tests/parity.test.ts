/* Differential tests: each scenario runs on the phone's API and on the real desktop server (app.py, started
   fresh with an empty data folder), and every response must match, status and body. This is what keeps the
   two backends in step as either one changes.

   Needs Python with the desktop's requirements. Set EUT_PYTHON to that python (CI does); without it these
   tests are skipped locally. */
import { spawn, type ChildProcess } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, describe, expect, it } from 'vitest';
import { d, makeApp } from './helpers';

const PYTHON = process.env.EUT_PYTHON;
const ROOT = fileURLToPath(new URL('../..', import.meta.url));

/** Values that differ every run (times, file names) are compared by shape only. */
const VOLATILE = new Set(['created_at', 'updated_at', 'exported_at', 'safety_backup']);

function normalise(v: any, key = ''): any {
  if (VOLATILE.has(key)) return v === null ? null : typeof v;
  if (Array.isArray(v)) return v.map(x => normalise(x));
  if (v && typeof v === 'object') {
    if ('loc' in v && 'msg' in v && 'type' in v) return { type: v.type, loc: v.loc, msg: v.msg };   // a validation error
    return Object.fromEntries(Object.keys(v).sort().map(k => [k, normalise(v[k], k)]));
  }
  return v;
}

const freePort = () => new Promise<number>((resolve, reject) => {
  const s = createServer();
  s.listen(0, '127.0.0.1', () => {
    const port = (s.address() as any).port;
    s.close(() => resolve(port));
  });
  s.on('error', reject);
});

const servers: { proc: ChildProcess; dir: string }[] = [];
afterAll(() => {
  for (const s of servers) {
    s.proc.kill();
    rmSync(s.dir, { recursive: true, force: true });
  }
});

async function desktopServer() {
  const dir = mkdtempSync(join(tmpdir(), 'eut-parity-'));
  const port = await freePort();
  const proc = spawn(PYTHON!, ['-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', String(port), '--log-level', 'warning'],
    { cwd: ROOT, env: { ...process.env, TRACKADEMIC_DATA_DIR: dir, PYTHONUTF8: '1' }, stdio: ['ignore', 'ignore', 'pipe'] });
  let err = '';
  proc.stderr!.on('data', b => { err += b; });
  servers.push({ proc, dir });
  const base = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 150; i++) {
    try {
      if ((await fetch(base + '/api/categories')).ok) return base;
    } catch { /* not up yet */ }
    if (proc.exitCode !== null) throw new Error(`The desktop server stopped: ${err}`);
    await new Promise(r => setTimeout(r, 100));
  }
  throw new Error(`The desktop server didn't start: ${err}`);
}

type Call = (method: string, path: string, body?: unknown) => Promise<any>;

/** Run a scenario on both backends, comparing each response; returns the phone's responses to the scenario. */
async function both(scenario: (call: Call) => Promise<void>) {
  const phone = await makeApp();
  const base = await desktopServer();
  const steps: string[] = [];
  const call: Call = async (method, path, body) => {
    const sent = body === undefined ? undefined : JSON.stringify(body);
    const mine = await phone.call(method, path, body);
    const res = await fetch(base + path, { method, body: sent, headers: sent ? { 'Content-Type': 'application/json' } : {} });
    const text = await res.text();
    let theirs: any = text;
    try { theirs = JSON.parse(text); } catch { /* not JSON */ }
    const label = `${method} ${path} ${sent ?? ''}`.slice(0, 200);
    steps.push(label);
    expect({ status: mine.status, body: normalise(mine.json) }, `phone and desktop differ at step ${steps.length}: ${label}`)
      .toEqual({ status: res.status, body: normalise(theirs) });
    return mine.json;
  };
  await scenario(call);
}

describe.skipIf(!PYTHON)('phone API matches the desktop server', () => {
  it.concurrent('tasks: create, validate, filter, status rules', () => both(async call => {
    const s = await call('POST', '/api/subjects', { name: 'COMP2001 Data Structures', color: '#3B6EA8' });
    await call('POST', '/api/subjects', { name: 'business stats' });
    await call('POST', '/api/subjects', { name: 'Accounting' });
    const u = await call('POST', `/api/subjects/${s.id}/units`, { name: 'Week 5' });
    await call('POST', `/api/subjects/${s.id}/units`, { name: '  week 2 ' });
    await call('POST', '/api/subjects/99/units', { name: 'x' });
    await call('POST', '/api/subjects', { name: 'Accounting' });               // already used
    await call('POST', '/api/subjects', { name: 'Bad colour', color: 'red' });
    await call('GET', '/api/subjects');
    const t = await call('POST', '/api/tasks', { title: '  Lab report ', due_date: d(-2), subject_id: s.id, unit_id: u.id,
      priority: 'high', estimated_hours: 6, category_id: 1, target_grade: 'HD' });
    await call('POST', '/api/tasks', { title: 'Reading', due_date: d(0), progress: 100 });
    await call('POST', '/api/tasks', { title: 'Quiz', due_date: d(3), progress: 30, status: 'not_started' });
    await call('POST', '/api/tasks', { title: 'No date', priority: 'low' });
    await call('POST', '/api/tasks', { title: 'Typed numbers', progress: '25', estimated_hours: '1.5', is_recurring: 'yes' });
    for (const bad of [{ title: '' }, { title: 'x'.repeat(121) }, { title: 'x', priority: 'mega' }, { title: 'x', due_date: 'tomorrow' },
      { title: 'x', due_date: '2026-02-30' }, { title: 'x', progress: 101 }, { title: 'x', progress: 4.5 }, { title: 'x', estimated_hours: -1 },
      { title: 'x', recurrence_pattern: 'yearly' }, { title: 5 }, {}, { title: 'x', subject_id: 'abc' }, { title: 'x', category_id: 999 },
      { title: 'x', target_grade: 'x'.repeat(21) }, { title: 'x', status: 'overdue' }]) {
      await call('POST', '/api/tasks', bad);
    }
    await call('POST', '/api/tasks', [1, 2]);
    await call('PUT', `/api/tasks/${t.id}`, { progress: 40 });
    await call('PUT', `/api/tasks/${t.id}`, { due_date: d(5) });
    await call('PUT', `/api/tasks/${t.id}`, { title: null });
    await call('PUT', `/api/tasks/${t.id}`, { subject_id: 999 });
    await call('PUT', `/api/tasks/${t.id}`, { status: 'completed' });
    await call('PUT', `/api/tasks/${t.id}`, { progress: 50 });
    await call('PUT', '/api/tasks/999', { title: 'x' });
    await call('GET', '/api/tasks/abc');
    for (const q of ['', '?status=not_started,in_progress', '?status=overdue', '?overdue=true', `?subject=${s.id}`, '?priority=low',
      '?search=re', '?sort=priority', '?sort=title&order=desc', '?sort=progress', '?sort=bogus', `?due_before=${d(1)}&due_after=${d(-1)}`,
      '?category=1', '?category=x', '?overdue=maybe']) {
      await call('GET', '/api/tasks' + q);
    }
    await call('GET', '/api/stats');
    await call('DELETE', `/api/subjects/${s.id}`);
    await call('GET', '/api/tasks');
    await call('GET', '/api/subjects');
  }));

  it.concurrent('repeating tasks and study plans', () => both(async call => {
    const w = await call('POST', '/api/tasks', { title: 'Weekly reading', due_date: d(-1), recurrence_pattern: 'weekly' });
    const next = await call('PUT', `/api/tasks/${w.id}`, { status: 'completed' });
    await call('PUT', `/api/tasks/${next.next_task.id}`, { progress: 100 });
    const m = await call('POST', '/api/tasks', { title: 'Rent', due_date: '2026-01-31', recurrence_pattern: 'monthly' });
    await call('PUT', `/api/tasks/${m.id}`, { status: 'completed' });
    const daily = await call('POST', '/api/tasks', { title: 'Flashcards', recurrence_pattern: 'daily' });
    await call('PUT', `/api/tasks/${daily.id}`, { is_recurring: false });
    await call('PUT', `/api/tasks/${daily.id}`, { recurrence_pattern: 'fortnightly' });
    await call('PUT', `/api/tasks/${daily.id}`, { status: 'completed' });
    await call('GET', '/api/tasks');
    for (const [hours, days] of [[5, 10], [3, 10], [1, 4], [7, 3], [null, 9], [0.4, 2], [12, 20], [9, 1]] as const) {
      const t = await call('POST', '/api/tasks', { title: `Plan ${hours}`, due_date: d(days), estimated_hours: hours });
      await call('POST', `/api/tasks/${t.id}/auto-plan`);
    }
    const past = await call('POST', '/api/tasks', { title: 'Past', due_date: d(0) });
    await call('POST', `/api/tasks/${past.id}/auto-plan`);
    const none = await call('POST', '/api/tasks', { title: 'Undated' });
    await call('POST', `/api/tasks/${none.id}/auto-plan`);
    await call('POST', '/api/tasks/999/auto-plan');
  }));

  it.concurrent('task types and notes', () => both(async call => {
    await call('GET', '/api/categories');
    const c = await call('POST', '/api/categories', { name: ' Lab ', color: '#123456' });
    await call('POST', '/api/categories', { name: 'Lab' });
    await call('PUT', `/api/categories/${c.id}`, { name: '  ' });
    await call('PUT', `/api/categories/${c.id}`, { name: 'Prac', color: null });
    await call('PUT', `/api/categories/${c.id}`, { color: '#abcdef' });
    await call('PUT', '/api/categories/99', { name: 'x' });
    await call('PUT', `/api/categories/${c.id}`, { name: 'Exam' });
    const t = await call('POST', '/api/tasks', { title: 'Uses type', category_id: c.id });
    await call('DELETE', `/api/categories/${c.id}`);
    await call('GET', `/api/tasks/${t.id}`);
    const s = await call('POST', '/api/subjects', { name: 'Physics' });
    const n = await call('POST', '/api/notes', { title: '  Kinematics ', body: 'v = u + at', subject_id: s.id, task_id: t.id });
    await call('POST', '/api/notes', { title: '   ' });
    await call('POST', '/api/notes', { title: 'x', subject_id: 999 });
    await call('POST', '/api/notes', { title: 'x', task_id: 999 });
    await call('POST', '/api/notes', { title: 'x', source: 'web' });
    await call('POST', '/api/notes', { title: 'Loose note' });
    await call('PUT', `/api/notes/${n.id}`, { title: ' ' });
    await call('PUT', `/api/notes/${n.id}`, { title: '' });
    await call('PUT', `/api/notes/${n.id}`, { body: 'changed', subject_id: null });
    await call('PUT', `/api/notes/${n.id}`, { subject_id: 999 });
    await call('PUT', '/api/notes/999', { body: 'x' });
    await call('GET', `/api/notes?subject_id=${s.id}`);
    await call('DELETE', `/api/tasks/${t.id}`);
    await call('GET', '/api/notes');
    await call('DELETE', `/api/notes/${n.id}`);
    await call('DELETE', `/api/notes/${n.id}`);
  }));

  it.concurrent('jobs', () => both(async call => {
    const a = await call('POST', '/api/jobs', { company: 'Atlassian', role: 'Graduate', follow_up_date: d(-1), applied_date: d(-10) });
    await call('POST', '/api/jobs', { company: 'Canva', role: 'Intern', status: 'interviewing', follow_up_date: d(0) });
    await call('POST', '/api/jobs', { company: 'BIG W', role: 'TM', status: 'rejected', follow_up_date: d(-1) });
    await call('POST', '/api/jobs', { company: 'Ford', role: 'IT', status: 'offer', priority: 'high' });
    for (const bad of [{ company: 'x' }, { company: 'x', role: 'y', status: 'ghosted' }, { company: 'x', role: 'y', priority: 'urgent' },
      { company: 'x', role: 'y', url: 'x'.repeat(501) }, { company: 'x', role: 'y', follow_up_date: 'soon' }]) {
      await call('POST', '/api/jobs', bad);
    }
    await call('PUT', `/api/jobs/${a.id}`, { status: 'phone_screen', notes: 'Call went well' });
    await call('PUT', `/api/jobs/${a.id}`, {});
    await call('PUT', `/api/jobs/${a.id}`, { company: null });
    await call('PUT', '/api/jobs/999', { role: 'x' });
    for (const q of ['', '?status=applied,rejected', '?priority=high', '?search=an']) await call('GET', '/api/jobs' + q);
    await call('GET', '/api/jobs/stats');
    await call('DELETE', `/api/jobs/${a.id}`);
    await call('GET', '/api/jobs/stats');
  }));

  it.concurrent('money', () => both(async call => {
    await call('GET', '/api/budgets');
    await call('PUT', '/api/budget-plan', { items: [{ category: 'Rent', monthly_limit: 1200 }, { category: ' Groceries ', monthly_limit: 320.555 },
      { category: 'Fun', monthly_limit: null }, { category: 'Transport', monthly_limit: 150 }] });
    await call('PUT', '/api/budget-plan', { items: [{ category: 'Rent', monthly_limit: -5 }] });
    await call('PUT', '/api/budget-plan', { items: Array.from({ length: 101 }, (_, i) => ({ category: `C${i}`, monthly_limit: 1 })) });
    await call('PUT', '/api/budget-plan', { items: [{ category: '', monthly_limit: 5 }] });
    await call('PUT', '/api/budget-plan', {});
    const tx = await call('POST', '/api/transactions', { type: 'expense', amount: 50.125, category: ' Transport ', description: ' Opal ', date: d(0) });
    await call('POST', '/api/transactions', { type: 'income', amount: 312, category: 'Wages', date: d(0), recurring: true });
    await call('POST', '/api/transactions', { type: 'expense', amount: 80, category: 'Groceries', date: '2026-01-15' });
    for (const bad of [{ type: 'expense', amount: -5, category: 'x', date: d(0) }, { type: 'gift', amount: 5, category: 'x', date: d(0) },
      { type: 'expense', amount: 5, category: 'x', date: '' }, { type: 'expense', amount: 5, category: 'x' },
      { type: 'expense', amount: 10_000_001, category: 'x', date: d(0) }, { type: 'expense', amount: 'five', category: 'x', date: d(0) }]) {
      await call('POST', '/api/transactions', bad);
    }
    for (const q of ['', '?month=2026-01', '?month=2026-1', '?month=bad', '?month=2026-13', '?type=income', '?category=Transport']) {
      await call('GET', '/api/transactions' + q);
    }
    const budgets = await call('GET', '/api/budgets');
    const transport = budgets.find((b: any) => b.category === 'Transport');
    await call('PUT', `/api/budgets/${transport.id}`, { category: 'Rent', monthly_limit: 100 });
    await call('PUT', `/api/budgets/${transport.id}`, { category: 'Travel', monthly_limit: 100, color: '#123abc' });
    await call('PUT', '/api/budgets/999', { category: 'x', monthly_limit: 1 });
    await call('POST', '/api/budgets', { category: 'Phone', monthly_limit: 40 });
    await call('POST', '/api/budgets', { category: 'Phone', monthly_limit: 40 });
    await call('GET', '/api/budgets?month=2026-01');
    await call('GET', '/api/finance/stats');
    await call('GET', '/api/finance/stats?month=2026-01');
    await call('DELETE', `/api/transactions/${tx.id}`);
    await call('DELETE', `/api/budgets/${transport.id}`);
    await call('GET', '/api/transactions');
  }));

  it.concurrent('settings', () => both(async call => {
    await call('GET', '/api/settings/appearance');
    await call('PUT', '/api/settings/appearance', { theme: 'ocean', font: 'classic', mode: 'dark' });
    await call('PUT', '/api/settings/appearance', { theme: 'rainbow' });
    await call('PUT', '/api/settings/appearance', { theme: 'berry' });
    await call('GET', '/api/settings/appearance');
    await call('PUT', '/api/settings/money', { currency: 'ZAR' });
    for (const bad of ['zar', 'RAND', '12$']) await call('PUT', '/api/settings/money', { currency: bad });
    await call('GET', '/api/settings/reminders');
    await call('PUT', '/api/settings/reminders', { daily: false, time: '07:15' });
    await call('PUT', '/api/settings/reminders', { daily: true, time: '25:00' });
    await call('GET', '/api/settings/reminders');
    await call('GET', '/api/settings/startup');
    await call('PUT', '/api/settings/startup', { intro: false });
    await call('GET', '/api/settings/updates');
    await call('PUT', '/api/settings/updates', { auto_check: false });
    await call('GET', '/api/settings/updates');
    await call('PUT', '/api/settings/autostart', {});
  }));

  it.concurrent('what the daily reminder says', () => both(async call => {
    await call('GET', '/api/reminders/preview');
    for (const [title, due, priority] of [['Essay', d(0), 'low'], ['Lab', d(0), 'urgent'], ['Quiz', d(0), 'high'], ['Poster', d(0), 'medium'],
      ['Old 1', d(-3), 'low'], ['Old 2', d(-2), 'low'], ['Old 3', d(-1), 'low'], ['Later', d(2), 'low']] as const) {
      await call('POST', '/api/tasks', { title, due_date: due, priority });
    }
    await call('POST', '/api/jobs', { company: 'Canva', role: 'Intern', follow_up_date: d(0) });
    await call('POST', '/api/jobs', { company: 'Closed', role: 'x', status: 'withdrawn', follow_up_date: d(0) });
    await call('GET', '/api/reminders/preview');
  }));

  it.concurrent('backup and restore', () => both(async call => {
    const s = await call('POST', '/api/subjects', { name: 'Maths' });
    await call('POST', `/api/subjects/${s.id}/units`, { name: 'Calculus' });
    await call('POST', '/api/tasks', { title: 'Integrals', subject_id: s.id, due_date: d(1) });
    await call('POST', '/api/notes', { title: 'Rules', subject_id: s.id });
    await call('POST', '/api/jobs', { company: 'Canva', role: 'Intern' });
    await call('PUT', '/api/budget-plan', { items: [{ category: 'Rent', monthly_limit: 900 }] });
    await call('PUT', '/api/settings/appearance', { theme: 'ocean', font: 'system', mode: 'light' });
    const backup = await call('GET', '/api/export');
    await call('POST', '/api/import/preview', backup);
    for (const bad of [{ app: 'Other', tasks: [] }, { app: 'EasyUniTrack' }, { app: 'EasyUniTrack', tasks: [], notes: 'x' },
      { app: 'EasyUniTrack', tasks: [1] }, [1], 'text']) {
      await call('POST', '/api/import/preview', bad);
      await call('POST', '/api/import', bad);
    }
    // A task pointing at a subject that isn't in the backup: nothing changes
    await call('POST', '/api/import', { ...backup, subjects: [], units: [], notes: [] });
    await call('GET', '/api/tasks');
    // An old-format task (stored 'overdue', missing newer columns) and a backup from the old app name
    await call('POST', '/api/import', { app: 'Trackademic', version: '2.0.0', tasks: [
      { id: 7, title: 'Old', status: 'overdue', progress: 20, due_date: d(-1), priority: 'high', removed_column: 'x' },
      { id: 8, title: 'Older', status: 'overdue', progress: 0 }] });
    await call('GET', '/api/tasks');
    await call('GET', '/api/subjects');
    await call('POST', '/api/import', backup);
    await call('GET', '/api/tasks');
    await call('GET', '/api/notes');
    await call('GET', '/api/settings/appearance');
    await call('GET', '/api/budgets');
  }));
});

describe('the phone answers every route the screens call', () => {
  it('has a route for each call in app.js (the desktop test_consistency check, for the phone)', async () => {
    const { readFileSync } = await import('node:fs');
    const appJs = readFileSync(join(ROOT, 'static', 'app.js'), 'utf8');
    const app = await makeApp();
    const routes = app.api.list().map(r => {
      const [method, path] = r.split(' ');
      return { method, rx: new RegExp('^' + path.replace(/\{[^}]+\}/g, '[^/]+') + '$') };
    });
    const calls = [...appJs.matchAll(/api\(\s*[`'](\/api\/[^`'?]*)[^`']*[`'](?:\s*\+[^,)]*)?\s*(?:,\s*\{\s*method:\s*'([A-Z]+)')?/g)];
    expect(calls.length).toBeGreaterThan(20);
    // The code workspace's routes are the desktop's alone: it works with project folders on a computer
    const missing = calls
      .map(m => ({ path: m[1].replace(/\$\{[^}]+\}/g, '1'), method: m[2] || 'GET' }))
      .filter(c => !c.path.startsWith('/api/code/') || (c.path === '/api/code/folders' && c.method === 'GET'))
      .filter(c => !routes.some(r => r.method === c.method && r.rx.test(c.path)))
      .map(c => `${c.method} ${c.path}`);
    expect(missing).toEqual([]);
  });
});

describe.skipIf(!PYTHON)('phone database matches the desktop one', () => {
  it('has the same tables and columns, so backups restore both ways', async () => {
    const { execFileSync } = await import('node:child_process');
    const dir = mkdtempSync(join(tmpdir(), 'eut-schema-'));
    try {
      const script = 'import json, app\nc = app._connect()\nprint(json.dumps({t: [[r[1], r[2], r[3], r[4], r[5]] for r in c.execute(f"PRAGMA table_info({t})")] ' +
        'for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type=\'table\' AND name NOT LIKE \'sqlite_%\' ORDER BY name")}))';
      const desktop = JSON.parse(execFileSync(PYTHON!, ['-c', script], { cwd: ROOT, env: { ...process.env, TRACKADEMIC_DATA_DIR: dir } }).toString());
      const phone = await makeApp();
      const tables = await phone.db.all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name");
      const mine: Record<string, unknown[]> = {};
      for (const { name } of tables) {
        mine[name] = (await phone.db.all(`PRAGMA table_info(${name})`)).map(r => [r.name, r.type, r.notnull, r.dflt_value, r.pk]);
      }
      expect(mine).toEqual(desktop);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
