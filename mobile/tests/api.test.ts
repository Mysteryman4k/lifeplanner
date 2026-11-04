/* The desktop's tests/test_api.py, run against the phone's API. */
import { beforeEach, describe, expect, it } from 'vitest';
import { d, makeApp, type App } from './helpers';

let c: App;
beforeEach(async () => { c = await makeApp(); });

describe('API (from test_api.py)', () => {
  it('full flow', async () => {
    const s = (await c.post('/api/subjects', { name: 'SIT313' })).json;
    expect(s.units).toEqual([]);
    const u = (await c.post(`/api/subjects/${s.id}/units`, { name: 'Week 5' })).json;
    expect((await c.get('/api/subjects')).json[0].units[0].name).toBe('Week 5');
    const t = (await c.post('/api/tasks', { title: 'Late', due_date: d(-2), subject_id: s.id, unit_id: u.id })).json;
    expect(t.is_overdue && t.status === 'not_started').toBe(true);
    const t2 = (await c.put(`/api/tasks/${t.id}`, { due_date: d(5) })).json;
    expect(t2.is_overdue).toBe(false);
    await c.put(`/api/tasks/${t.id}`, { due_date: d(-1) });
    await c.post('/api/tasks', { title: 'Fresh', due_date: d(3) });
    expect((await c.get('/api/tasks', { status: 'not_started,in_progress' })).json).toHaveLength(2);
    expect((await c.get('/api/tasks', { status: 'overdue' })).json).toHaveLength(1);
    expect((await c.post('/api/tasks', { title: 'x', priority: 'mega' })).status).toBe(422);
    expect((await c.post('/api/tasks', { title: 'x', due_date: 'tomorrow' })).status).toBe(422);
    expect((await c.post('/api/tasks', { title: '' })).status).toBe(422);
    let p = (await c.put(`/api/tasks/${t.id}`, { progress: 40 })).json;
    expect(p.status).toBe('in_progress');
    p = (await c.put(`/api/tasks/${t.id}`, { status: 'completed' })).json;
    expect(p.progress === 100 && !p.is_overdue).toBe(true);
    const st = (await c.get('/api/stats')).json;
    expect([st.completed, st.total]).toEqual([1, 2]);
    expect((await c.post('/api/transactions', { type: 'expense', amount: -5, category: 'Food & Dining', date: d(0) })).status).toBe(422);
    expect((await c.get('/api/budgets')).json).toEqual([]);
    const plan = { items: [{ category: 'Transport', monthly_limit: 150 }, { category: 'Food & Dining', monthly_limit: 400 }] };
    expect((await c.put('/api/budget-plan', plan)).status).toBe(200);
    await c.post('/api/transactions', { type: 'expense', amount: 50, category: 'Transport', date: d(0) });
    const b = (await c.get('/api/budgets')).json;
    const tr = b.find((x: any) => x.category === 'Transport');
    expect(tr.spent).toBe(50);
    const dup = await c.put(`/api/budgets/${tr.id}`, { category: 'Food & Dining', monthly_limit: 100 });
    expect(dup.status).toBe(400);
    expect(dup.json.detail).toBe('That name is already used.');
    expect((await c.get('/api/stats')).status).toBe(200);
    await c.put(`/api/budgets/${tr.id}`, { category: 'Travel', monthly_limit: 100 });
    expect((await c.get('/api/budgets')).json.find((x: any) => x.category === 'Travel').spent).toBe(50);
    expect((await c.get('/api/finance/stats')).json.expenses).toBe(50);
    expect((await c.get('/api/transactions', { month: 'bad' })).status).toBe(400);
    await c.post('/api/jobs', { company: 'Ford', role: 'IT', follow_up_date: d(-1) });
    await c.post('/api/jobs', { company: 'BIG W', role: 'TM', status: 'rejected', follow_up_date: d(-1) });
    expect((await c.get('/api/jobs/stats')).json.follow_ups_due).toBe(1);
    expect((await c.get('/api/jobs', { status: 'applied,rejected' })).json).toHaveLength(2);
    expect((await c.put('/api/jobs/999', { role: 'x' })).status).toBe(404);
    const tasks = (await c.get('/api/tasks')).json;
    const ap = (await c.post(`/api/tasks/${tasks[tasks.length - 1].id}/auto-plan`)).json;
    expect(ap).toHaveProperty('plan');
    expect((await c.get('/api/export')).json).toHaveProperty('tasks');
  });

  it('appearance settings', async () => {
    expect((await c.get('/api/settings/appearance')).json).toEqual({ theme: 'plain', font: 'system', mode: 'system' });
    expect((await c.put('/api/settings/appearance', { theme: 'midnight', font: 'techy', mode: 'dark' })).status).toBe(200);
    expect((await c.get('/api/settings/appearance')).json.theme).toBe('midnight');
    expect((await c.put('/api/settings/appearance', { theme: 'rainbow' })).status).toBe(422);
    expect((await c.get('/api/info')).json.name).toBe('EasyUniTrack');
  });

  it('currency setting', async () => {
    const m = (await c.get('/api/settings/money')).json;
    expect(m).toEqual({ currency: 'AUD', chosen: false });          // the fake phone is in Australia
    expect((await c.put('/api/settings/money', { currency: 'ZAR' })).json).toEqual({ currency: 'ZAR', chosen: true });
    expect((await c.get('/api/settings/money')).json.currency).toBe('ZAR');
    for (const bad of ['zar', 'RAND', 'R', '12$']) expect((await c.put('/api/settings/money', { currency: bad })).status).toBe(422);
  });

  it('budget plan sets, updates and clears', async () => {
    let r = (await c.put('/api/budget-plan', { items: [
      { category: 'Rent', monthly_limit: 1200 }, { category: 'Groceries', monthly_limit: 320.5 },
      { category: 'Fun', monthly_limit: null }] })).json;
    expect(new Set(r.map((b: any) => `${b.category}:${b.monthly_limit}`))).toEqual(new Set(['Rent:1200', 'Groceries:320.5']));
    await c.post('/api/transactions', { type: 'expense', amount: 80, category: 'Groceries', date: d(0) });
    r = (await c.put('/api/budget-plan', { items: [{ category: 'Rent', monthly_limit: 1100 }, { category: 'Groceries', monthly_limit: 0 }] })).json;
    expect(r.map((b: any) => [b.category, b.monthly_limit])).toEqual([['Rent', 1100]]);
    expect((await c.get('/api/transactions')).json).toHaveLength(1);
    expect((await c.put('/api/budget-plan', { items: [{ category: 'Rent', monthly_limit: -5 }] })).status).toBe(422);
  });
});

describe('validation errors look like FastAPI\'s', () => {
  it('names the field and gives the message app.js shows', async () => {
    const r = await c.post('/api/tasks', { title: 'x', due_date: 'tomorrow' });
    expect(r.json.detail[0].loc).toEqual(['body', 'due_date']);
    expect(r.json.detail[0].msg).toBe('Value error, Use a date in YYYY-MM-DD format');
    const empty = await c.post('/api/tasks', { title: '' });
    expect(empty.json.detail[0].msg).toBe('String should have at least 1 character');
    const missing = await c.post('/api/jobs', { company: 'Ford' });
    expect(missing.json.detail[0]).toMatchObject({ loc: ['body', 'role'], msg: 'Field required' });
    const prio = await c.post('/api/tasks', { title: 'x', priority: 'mega' });
    expect(prio.json.detail[0].msg).toBe("Input should be 'low', 'medium', 'high' or 'urgent'");
  });

  it('turns numbers sent as text into numbers, like Pydantic', async () => {
    const t = (await c.post('/api/tasks', { title: 'x', progress: '40', estimated_hours: '2.5' })).json;
    expect([t.progress, t.estimated_hours]).toEqual([40, 2.5]);
    expect((await c.post('/api/tasks', { title: 'x', progress: 'lots' })).status).toBe(422);
    expect((await c.post('/api/tasks', { title: 'x', progress: 4.5 })).status).toBe(422);
  });

  it('answers 404 for an unknown route and 422 for a bad id', async () => {
    expect((await c.get('/api/nope')).status).toBe(404);
    expect((await c.get('/api/tasks/abc')).status).toBe(422);
    expect((await c.get('/api/tasks/99')).json).toEqual({ detail: 'Task not found' });
  });
});
