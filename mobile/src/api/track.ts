/* Job applications, money and the stats: app.py's routes of the same names, on the phone. */
import type { Database, Row } from '../db/db';
import { addDays, nowStamp, today } from '../dates';
import { HttpError, body, intParam, queryStr, type Req, type Router } from '../http';
import { bool, date, float, hexColor, lit, name, optFloat, parse, sent, str, type Model } from '../validate';
import { pyRound, requireRow, type Ctx } from './context';

export const JOB_STATUSES = ['applied', 'phone_screen', 'interviewing', 'offer', 'accepted', 'rejected', 'withdrawn'] as const;
export const ACTIVE_JOB_STATUSES = ['applied', 'phone_screen', 'interviewing', 'offer'];

const JobCreate: Model = {
  company: name(),
  role: name(),
  status: lit(JOB_STATUSES, { default: 'applied' }),
  applied_date: date(),
  follow_up_date: date(),
  notes: str(),
  url: str({ maxLen: 500 }),
  salary_range: str({ maxLen: 60 }),
  contact_name: str({ maxLen: 120 }),
  contact_email: str({ maxLen: 200 }),
  priority: lit(['low', 'medium', 'high'], { default: 'medium' }),
};
const JobUpdate: Model = Object.fromEntries(Object.entries(JobCreate).map(([k, r]) =>
  [k, { ...r, required: false, nullable: true, default: null }]));

const TransactionCreate: Model = {
  type: lit(['income', 'expense'], { required: true }),
  amount: float({ required: true, gt: 0, le: 10_000_000 }),
  category: name(),
  description: str({ maxLen: 200 }),
  date: date({ required: true, nullable: false }),
  recurring: bool({ default: false }),
};

const BudgetCreate: Model = {
  category: name(),
  monthly_limit: float({ required: true, gt: 0, le: 10_000_000 }),
  color: hexColor(),
};

const BudgetPlan: Model = {
  items: {
    kind: 'list', required: true, maxItems: 100,
    item: { kind: 'model', model: { category: name(), monthly_limit: optFloat({ ge: 0, le: 10_000_000 }) } },
  },
};

const JOB_ORDER = "CASE status WHEN 'interviewing' THEN 0 WHEN 'phone_screen' THEN 1 WHEN 'offer' THEN 2 " +
  "WHEN 'applied' THEN 3 WHEN 'accepted' THEN 4 WHEN 'rejected' THEN 5 ELSE 6 END";

/** The month asked for (YYYY-MM), or this month. */
function monthOrCurrent(month: string | null): string {
  if (!month) return today().slice(0, 7);
  const m = /^(\d{4})-(\d{1,2})$/.exec(month);
  if (!m || +m[2] < 1 || +m[2] > 12) throw new HttpError(400, 'Month must look like YYYY-MM');
  return `${m[1]}-${m[2].padStart(2, '0')}`;
}

/** First day of the month and of the next one, for index-friendly range queries. */
function monthRange(month: string): [string, string] {
  const [y, m] = month.split('-').map(Number);
  const next = m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`;
  return [`${month}-01`, `${next}-01`];
}

async function listBudgets(db: Database, month: string | null) {
  const [start, end] = monthRange(monthOrCurrent(month));
  return db.all(`
            SELECT b.*, COALESCE(SUM(t.amount), 0) AS spent
            FROM budgets b LEFT JOIN transactions t
              ON t.category = b.category AND t.type = 'expense' AND t.date >= ? AND t.date < ?
            GROUP BY b.id ORDER BY b.category COLLATE NOCASE`, start, end);
}

export function registerTrack(r: Router, { db }: Ctx) {
  // ── Jobs ──
  r.get('/api/jobs', async (req: Req) => {
    const where: string[] = [];
    const params: string[] = [];
    const status = queryStr(req, 'status'), priority = queryStr(req, 'priority'), search = queryStr(req, 'search');
    if (status) {
      const statuses = status.split(',').filter(Boolean);
      where.push(`status IN (${statuses.map(() => '?').join(',')})`);
      params.push(...statuses);
    }
    if (priority) { where.push('priority=?'); params.push(priority); }
    if (search) { where.push('(company LIKE ? OR role LIKE ?)'); params.push(`%${search}%`, `%${search}%`); }
    const q = 'SELECT * FROM job_applications' + (where.length ? ' WHERE ' + where.join(' AND ') : '') +
      ` ORDER BY ${JOB_ORDER}, updated_at DESC`;
    return db.all(q, ...params);
  });

  r.get('/api/jobs/stats', async () => {
    const counts: Record<string, number> = Object.fromEntries(JOB_STATUSES.map(s => [s, 0]));
    for (const row of await db.all('SELECT status, COUNT(*) AS n FROM job_applications GROUP BY status')) counts[row.status] = row.n;
    const followUps = await db.value(`SELECT COUNT(*) FROM job_applications
            WHERE follow_up_date IS NOT NULL AND follow_up_date <= ?
              AND status IN ('applied','phone_screen','interviewing','offer')`, today());
    return { total: Object.values(counts).reduce((a, b) => a + b, 0), by_status: counts, follow_ups_due: followUps };
  });

  r.post('/api/jobs', async req => {
    const { data } = parse<Row>(JobCreate, body(req));
    data.created_at = data.updated_at = nowStamp();
    const cols = Object.keys(data);
    const res = await db.run(`INSERT INTO job_applications (${cols.join(',')}) VALUES (${cols.map(() => '?').join(',')})`,
      ...cols.map(c => data[c]));
    return db.get('SELECT * FROM job_applications WHERE id=?', res.lastId);
  });

  r.put('/api/jobs/:job_id', async req => {
    const id = intParam(req, 'job_id');
    const updates = sent<Row>(JobUpdate, body(req));
    await requireRow(db, 'job_applications', id, 'Application');
    const keys = Object.keys(updates);
    if (keys.length) {
      updates.updated_at = nowStamp();
      keys.push('updated_at');
      await db.run(`UPDATE job_applications SET ${keys.map(k => `${k}=?`).join(', ')} WHERE id=?`, ...keys.map(k => updates[k]), id);
    }
    return db.get('SELECT * FROM job_applications WHERE id=?', id);
  });

  r.delete('/api/jobs/:job_id', async req => {
    await db.run('DELETE FROM job_applications WHERE id=?', intParam(req, 'job_id'));
    return { ok: true };
  });

  // ── Money ──
  r.get('/api/transactions', async req => {
    const [start, end] = monthRange(monthOrCurrent(queryStr(req, 'month')));
    const where = ['date >= ? AND date < ?'];
    const params = [start, end];
    const category = queryStr(req, 'category'), type = queryStr(req, 'type');
    if (category) { where.push('category=?'); params.push(category); }
    if (type) { where.push('type=?'); params.push(type); }
    return db.all(`SELECT * FROM transactions WHERE ${where.join(' AND ')} ORDER BY date DESC, id DESC`, ...params);
  });

  r.post('/api/transactions', async req => {
    const { data: tx } = parse<Row>(TransactionCreate, body(req));
    const res = await db.run('INSERT INTO transactions (type, amount, category, description, date, recurring) VALUES (?,?,?,?,?,?)',
      tx.type, pyRound(tx.amount, 2), tx.category.trim(), tx.description.trim(), tx.date, tx.recurring ? 1 : 0);
    return db.get('SELECT * FROM transactions WHERE id=?', res.lastId);
  });

  r.delete('/api/transactions/:tx_id', async req => {
    await db.run('DELETE FROM transactions WHERE id=?', intParam(req, 'tx_id'));
    return { ok: true };
  });

  r.get('/api/budgets', req => listBudgets(db, queryStr(req, 'month')));

  r.post('/api/budgets', async req => {
    const { data: b } = parse<Row>(BudgetCreate, body(req));
    const res = await db.run('INSERT INTO budgets (category, monthly_limit, color) VALUES (?,?,?)',
      b.category.trim(), b.monthly_limit, b.color);
    return { ...(await db.get('SELECT * FROM budgets WHERE id=?', res.lastId)), spent: 0 };
  });

  r.put('/api/budgets/:budget_id', async req => {
    const id = intParam(req, 'budget_id');
    const { data: b } = parse<Row>(BudgetCreate, body(req));
    const old = await db.get('SELECT category FROM budgets WHERE id=?', id);
    if (!old) throw new HttpError(404, 'Budget not found');
    const newName = b.category.trim();
    await db.run('UPDATE budgets SET category=?, monthly_limit=?, color=? WHERE id=?', newName, b.monthly_limit, b.color, id);
    // Renaming a budget keeps its past transactions attached to it
    if (old.category !== newName) await db.run('UPDATE transactions SET category=? WHERE category=?', newName, old.category);
    return db.get('SELECT * FROM budgets WHERE id=?', id);
  });

  r.delete('/api/budgets/:budget_id', async req => {
    await db.run('DELETE FROM budgets WHERE id=?', intParam(req, 'budget_id'));
    return { ok: true };
  });

  /** Several budgets at once: an amount creates or updates one, empty or 0 removes it (never its transactions). */
  r.put('/api/budget-plan', async req => {
    const { data: plan } = parse<{ items: Row[] }>(BudgetPlan, body(req));
    for (const item of plan.items) {
      const cat = item.category.trim();
      if (item.monthly_limit) {
        await db.run(`INSERT INTO budgets (category, monthly_limit) VALUES (?, ?)
                      ON CONFLICT(category) DO UPDATE SET monthly_limit=excluded.monthly_limit`, cat, pyRound(item.monthly_limit, 2));
      } else {
        await db.run('DELETE FROM budgets WHERE category=?', cat);
      }
    }
    return listBudgets(db, null);
  });

  r.get('/api/finance/stats', async req => {
    const [start, end] = monthRange(monthOrCurrent(queryStr(req, 'month')));
    const totals = (await db.get(`
            SELECT COALESCE(SUM(CASE WHEN type='income' THEN amount END), 0) AS income,
                   COALESCE(SUM(CASE WHEN type='expense' THEN amount END), 0) AS expenses
            FROM transactions WHERE date >= ? AND date < ?`, start, end))!;
    const byCat = await db.all(`SELECT category, SUM(amount) AS total FROM transactions
            WHERE type='expense' AND date >= ? AND date < ? GROUP BY category ORDER BY total DESC`, start, end);
    const budgetTotal = await db.value('SELECT COALESCE(SUM(monthly_limit), 0) FROM budgets');
    return { income: totals.income, expenses: totals.expenses, balance: totals.income - totals.expenses,
      budget_total: budgetTotal, by_category: byCat };
  });

  // ── Stats ──
  r.get('/api/stats', async () => {
    const t = today(), week = addDays(t, 7);
    const s = (await db.get(`
            SELECT COUNT(*) AS total,
              SUM(status='completed') AS completed,
              SUM(status='in_progress') AS in_progress,
              SUM(status='not_started') AS not_started,
              SUM(due_date < ? AND status != 'completed') AS overdue,
              SUM(due_date = ? AND status != 'completed') AS due_today,
              SUM(due_date BETWEEN ? AND ? AND status != 'completed') AS due_this_week
            FROM tasks`, t, t, t, week))!;
    const cb = await db.all(`SELECT c.name, c.color, COUNT(t.id) AS count FROM categories c
            LEFT JOIN tasks t ON t.category_id = c.id GROUP BY c.id ORDER BY count DESC`);
    const pb = await db.all(`SELECT priority, COUNT(*) AS count FROM tasks
            WHERE status != 'completed' GROUP BY priority`);
    const sb = await db.all(`SELECT s.name, s.color, COUNT(t.id) AS count FROM subjects s
            LEFT JOIN tasks t ON t.subject_id = s.id GROUP BY s.id ORDER BY count DESC`);
    const gd = await db.all(`SELECT target_grade, COUNT(*) AS count FROM tasks
            WHERE target_grade != '' AND status != 'completed' GROUP BY target_grade`);
    const stats: Row = Object.fromEntries(Object.entries(s).map(([k, v]) => [k, v || 0]));
    stats.completion_rate = stats.total ? pyRound(stats.completed / stats.total * 100, 1) : 0;
    return { ...stats, category_breakdown: cb, priority_breakdown: pb, subject_breakdown: sb, grade_distribution: gd };
  });
}
