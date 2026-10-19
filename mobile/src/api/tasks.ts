/* Subjects, units, notes, tasks and task types: app.py's routes of the same names, on the phone. */
import type { Database, Row } from '../db/db';
import { addDays, nowStamp, parseYmd, today, ymd } from '../dates';
import { HttpError, intParam, queryBool, queryInt, queryStr, body, type Req, type Router } from '../http';
import {
  bool, date, float, hexColor, int, lit, name, optFloat, optInt, optStr, parse, sent, str,
  ValueError, type Model,
} from '../validate';
import { pyRound, requireRow, type Ctx } from './context';

const PRIORITY = ['low', 'medium', 'high', 'urgent'] as const;
const STATUS = ['not_started', 'in_progress', 'completed'] as const;
const REPEAT = ['', 'daily', 'weekly', 'fortnightly', 'monthly'] as const;

export const TaskCreate: Model = {
  title: name(),
  description: str(),
  due_date: date(),
  planned_start_date: date(),
  planned_end_date: date(),
  priority: lit(PRIORITY, { default: 'medium' }),
  status: lit(STATUS, { default: 'not_started' }),
  category_id: optInt(),
  subject_id: optInt(),
  unit_id: optInt(),
  target_grade: str({ maxLen: 20 }),
  progress: int({ default: 0, ge: 0, le: 100 }),
  estimated_hours: optFloat({ ge: 0, le: 1000 }),
  actual_hours: float({ default: 0, ge: 0 }),
  notes: str(),
  is_recurring: bool({ default: false }),
  recurrence_pattern: lit(REPEAT, { default: '' }),
};

const opt = (m: Model): Model => Object.fromEntries(Object.entries(m).map(([k, r]) =>
  [k, { ...r, required: false, nullable: true, default: null }]));

export const TaskUpdate: Model = opt(TaskCreate);

const CategoryCreate: Model = { name: name(), color: hexColor() };
const CategoryUpdate: Model = opt({ name: name(), color: hexColor() });
const SubjectCreate: Model = { name: name(), color: hexColor() };
const UnitCreate: Model = { name: name() };

const NoteIn: Model = {
  title: name({
    maxLen: 200,
    check: (v: string) => {
      const t = v.trim();
      if (!t) throw new ValueError('Give the note a title.');
      return t;
    },
  }),
  body: str({ maxLen: 200_000 }),
  subject_id: optInt(),
  task_id: optInt(),
  source: lit(['manual', 'chat', 'topic'], { default: 'manual' }),
};
const NoteUpdate: Model = {
  title: optStr({ minLen: 1, maxLen: 200 }),
  body: optStr({ maxLen: 200_000 }),
  subject_id: optInt(),
};

export const TASK_SELECT = `
    SELECT t.*, c.name AS category_name, c.color AS category_color,
           s.name AS subject_name, s.color AS subject_color, u.name AS unit_name
    FROM tasks t
    LEFT JOIN categories c ON t.category_id = c.id
    LEFT JOIN subjects s ON t.subject_id = s.id
    LEFT JOIN units u ON t.unit_id = u.id
`;

export function taskRow(row: Row, t = today()) {
  const d: Row = { ...row };
  d.is_recurring = !!d.is_recurring;
  d.is_overdue = !!(d.due_date && d.due_date < t && d.status !== 'completed');
  return d;
}

export async function fetchTask(db: Database, id: number) {
  const row = await db.get(TASK_SELECT + ' WHERE t.id=?', id);
  if (!row) throw new HttpError(404, 'Task not found');
  return taskRow(row);
}

/** Keep status and progress consistent with each other. */
export function normaliseTaskStatus(values: Row, current?: Row) {
  const status = 'status' in values ? values.status : current?.status;
  const progress = 'progress' in values ? values.progress : (current?.progress ?? 0);
  if ('status' in values && status === 'completed' && !('progress' in values)) values.progress = 100;
  else if ('progress' in values && progress === 100 && !('status' in values)) values.status = 'completed';
  else if ('progress' in values && progress > 0 && progress < 100 && status === 'not_started' && !('status' in values)) {
    values.status = 'in_progress';
  }
  return values;
}

/** "Repeats" is the recurrence pattern; is_recurring just mirrors whether one is set. */
export function syncRecurrence(values: Row) {
  if ('recurrence_pattern' in values) {
    values.recurrence_pattern = values.recurrence_pattern || '';
    values.is_recurring = values.recurrence_pattern ? 1 : 0;
  } else if ('is_recurring' in values) {
    values.is_recurring = values.is_recurring ? 1 : 0;
    if (!values.is_recurring) values.recurrence_pattern = '';
  }
  return values;
}

/** The due date of the next copy of a repeating task (monthly: same day next month, or its last day). */
export function nextDueDate(due: string, pattern: string): string {
  if (pattern === 'daily') return addDays(due, 1);
  if (pattern === 'weekly') return addDays(due, 7);
  if (pattern === 'fortnightly') return addDays(due, 14);
  if (pattern === 'monthly') {
    const d = parseYmd(due);
    const y = d.getMonth() === 11 ? d.getFullYear() + 1 : d.getFullYear();
    const m = (d.getMonth() + 1) % 12;
    const last = new Date(y, m + 1, 0).getDate();
    return ymd(new Date(y, m, Math.min(d.getDate(), last)));
  }
  throw new Error(pattern);
}

const REPEAT_COPY_FIELDS = ['title', 'description', 'priority', 'category_id', 'subject_id', 'unit_id',
  'target_grade', 'estimated_hours', 'notes', 'is_recurring', 'recurrence_pattern'];

async function insert(db: Database, table: string, data: Row) {
  const cols = Object.keys(data);
  return db.run(`INSERT INTO ${table} (${cols.join(',')}) VALUES (${cols.map(() => '?').join(',')})`,
    ...cols.map(c => data[c]));
}

/** Completing a repeating task adds the next one and stops the finished one repeating (so no duplicates). */
async function spawnNextOccurrence(db: Database, task: Row) {
  const pattern = task.recurrence_pattern;
  if (!pattern) return null;
  let nxt = nextDueDate(task.due_date || today(), pattern);
  while (nxt < today()) nxt = nextDueDate(nxt, pattern);         // catching up after a while away
  const data: Row = {};
  for (const k of REPEAT_COPY_FIELDS) data[k] = task[k];
  Object.assign(data, { due_date: nxt, status: 'not_started', progress: 0, actual_hours: 0,
    created_at: nowStamp(), updated_at: nowStamp() });
  const res = await insert(db, 'tasks', data);
  await db.run("UPDATE tasks SET is_recurring=0, recurrence_pattern='' WHERE id=?", task.id);
  return fetchTask(db, res.lastId);
}

export async function createTask(db: Database, input: unknown) {
  const { data: all, set } = parse<Row>(TaskCreate, input);
  const values: Row = {};
  for (const k of set) values[k] = all[k];
  const data: Row = { ...all, ...normaliseTaskStatus(values) };
  data.title = data.title.trim();
  syncRecurrence(data);
  if (data.recurrence_pattern && !data.due_date) data.due_date = today();     // a repeating task needs a date
  data.created_at = data.updated_at = nowStamp();
  const res = await insert(db, 'tasks', data);
  return fetchTask(db, res.lastId);
}

export async function updateTask(db: Database, id: number, input: unknown) {
  let updates = sent<Row>(TaskUpdate, input);
  const current = await db.get('SELECT status, progress FROM tasks WHERE id=?', id);
  if (!current) throw new HttpError(404, 'Task not found');
  updates = syncRecurrence(normaliseTaskStatus(updates, current));
  if (Object.keys(updates).length) {
    updates.updated_at = nowStamp();
    const keys = Object.keys(updates);
    await db.run(`UPDATE tasks SET ${keys.map(k => `${k}=?`).join(', ')} WHERE id=?`, ...keys.map(k => updates[k]), id);
  }
  const task = await fetchTask(db, id);
  if (task.status === 'completed' && current.status !== 'completed' && task.recurrence_pattern) {
    task.next_task = await spawnNextOccurrence(db, task);
    task.is_recurring = false;
    task.recurrence_pattern = '';
  }
  return task;
}

const SORTABLE = new Set(['due_date', 'created_at', 'title', 'progress', 'status']);

export function registerTasks(r: Router, { db }: Ctx) {
  // ── Subjects & units ──
  r.get('/api/subjects', async () => {
    const subjects = await db.all(`
            SELECT s.*, COUNT(t.id) AS task_count,
                   SUM(CASE WHEN t.status != 'completed' THEN 1 ELSE 0 END) AS open_count
            FROM subjects s LEFT JOIN tasks t ON t.subject_id = s.id
            GROUP BY s.id ORDER BY s.name COLLATE NOCASE`);
    const units = await db.all('SELECT * FROM units ORDER BY name COLLATE NOCASE');
    const bySubject = new Map<number, Row[]>();
    for (const u of units) {
      if (!bySubject.has(u.subject_id)) bySubject.set(u.subject_id, []);
      bySubject.get(u.subject_id)!.push(u);
    }
    for (const s of subjects) {
      s.units = bySubject.get(s.id) ?? [];
      s.open_count = s.open_count || 0;
    }
    return subjects;
  });

  r.post('/api/subjects', async req => {
    const { data } = parse<Row>(SubjectCreate, body(req));
    const res = await db.run('INSERT INTO subjects (name, color) VALUES (?,?)', data.name.trim(), data.color);
    const row = await db.get('SELECT * FROM subjects WHERE id=?', res.lastId);
    return { ...row, units: [], task_count: 0, open_count: 0 };
  });

  r.put('/api/subjects/:subj_id', async req => {
    const id = intParam(req, 'subj_id');
    const { data } = parse<Row>(SubjectCreate, body(req));
    await requireRow(db, 'subjects', id, 'Subject');
    await db.run('UPDATE subjects SET name=?, color=? WHERE id=?', data.name.trim(), data.color, id);
    return { ok: true };
  });

  r.delete('/api/subjects/:subj_id', async req => {
    await db.run('DELETE FROM subjects WHERE id=?', intParam(req, 'subj_id'));
    return { ok: true };
  });

  r.get('/api/subjects/:subj_id/units', async req =>
    db.all('SELECT * FROM units WHERE subject_id=? ORDER BY name COLLATE NOCASE', intParam(req, 'subj_id')));

  r.post('/api/subjects/:subj_id/units', async req => {
    const id = intParam(req, 'subj_id');
    const { data } = parse<Row>(UnitCreate, body(req));
    await requireRow(db, 'subjects', id, 'Subject');
    const res = await db.run('INSERT INTO units (subject_id, name) VALUES (?,?)', id, data.name.trim());
    return db.get('SELECT * FROM units WHERE id=?', res.lastId);
  });

  r.delete('/api/units/:unit_id', async req => {
    await db.run('DELETE FROM units WHERE id=?', intParam(req, 'unit_id'));
    return { ok: true };
  });

  // ── Notes ──
  const checkNoteLinks = async (subjectId: number | null, taskId: number | null = null) => {
    if (subjectId !== null && !(await db.get('SELECT 1 FROM subjects WHERE id=?', subjectId))) {
      throw new HttpError(400, "That subject doesn't exist any more.");
    }
    if (taskId !== null && !(await db.get('SELECT 1 FROM tasks WHERE id=?', taskId))) {
      throw new HttpError(400, "That task doesn't exist any more.");
    }
  };
  const note = async (id: number) => {
    const row = await db.get('SELECT * FROM notes WHERE id=?', id);
    if (!row) throw new HttpError(404, 'Note not found');
    return row;
  };

  r.get('/api/notes', async req => {
    const subjectId = queryInt(req, 'subject_id');
    return subjectId === null
      ? db.all('SELECT * FROM notes ORDER BY updated_at DESC, id DESC')
      : db.all('SELECT * FROM notes WHERE subject_id=? ORDER BY updated_at DESC, id DESC', subjectId);
  });

  r.post('/api/notes', async req => {
    const { data: n } = parse<Row>(NoteIn, body(req));
    await checkNoteLinks(n.subject_id, n.task_id);
    const res = await db.run('INSERT INTO notes (subject_id, task_id, title, body, source, created_at, updated_at) ' +
      'VALUES (?, ?, ?, ?, ?, ?, ?)', n.subject_id, n.task_id, n.title, n.body, n.source, nowStamp(), nowStamp());
    return note(res.lastId);
  });

  r.put('/api/notes/:note_id', async req => {
    const id = intParam(req, 'note_id');
    const changes = sent<Row>(NoteUpdate, body(req));
    await note(id);
    if ('subject_id' in changes) await checkNoteLinks(changes.subject_id);
    if ('title' in changes) {
      changes.title = (changes.title || '').trim();
      if (!changes.title) throw new HttpError(400, 'Give the note a title.');
    }
    if (Object.keys(changes).length) {
      changes.updated_at = nowStamp();
      const keys = Object.keys(changes);
      await db.run(`UPDATE notes SET ${keys.map(k => `${k}=?`).join(', ')} WHERE id=?`, ...keys.map(k => changes[k]), id);
    }
    return note(id);
  });

  r.delete('/api/notes/:note_id', async req => {
    const id = intParam(req, 'note_id');
    await note(id);
    await db.run('DELETE FROM notes WHERE id=?', id);
    return { ok: true };
  });

  // ── Tasks ──
  r.get('/api/tasks', async (req: Req) => {
    const where: string[] = [];
    const params: unknown[] = [];
    const t = today();
    const status = queryStr(req, 'status');
    let overdue = queryBool(req, 'overdue');
    const category = queryInt(req, 'category'), subject = queryInt(req, 'subject'), unit = queryInt(req, 'unit');
    const priority = queryStr(req, 'priority'), search = queryStr(req, 'search');
    const dueBefore = queryStr(req, 'due_before'), dueAfter = queryStr(req, 'due_after');
    const sort = queryStr(req, 'sort') ?? 'due_date', order = queryStr(req, 'order') ?? 'asc';
    if (status) {
      const statuses = status.split(',').filter(Boolean);
      const i = statuses.indexOf('overdue');
      if (i >= 0) {                                  // old clients asked for the stored 'overdue' status
        statuses.splice(i, 1);
        overdue = true;
      }
      if (statuses.length) {
        where.push(`t.status IN (${statuses.map(() => '?').join(',')})`);
        params.push(...statuses);
      }
    }
    if (overdue === true) {
      where.push("t.due_date < ? AND t.status != 'completed'");
      params.push(t);
    }
    for (const [col, val] of [['t.category_id', category], ['t.subject_id', subject], ['t.unit_id', unit], ['t.priority', priority]] as const) {
      if (val !== null && val !== '') {
        where.push(`${col}=?`);
        params.push(val);
      }
    }
    if (search) {
      where.push('(t.title LIKE ? OR t.description LIKE ?)');
      params.push(`%${search}%`, `%${search}%`);
    }
    if (dueBefore) { where.push('t.due_date <= ?'); params.push(dueBefore); }
    if (dueAfter) { where.push('t.due_date >= ?'); params.push(dueAfter); }
    let q = TASK_SELECT + (where.length ? ' WHERE ' + where.join(' AND ') : '');
    if (sort === 'priority') {
      q += " ORDER BY CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END";
    } else if (SORTABLE.has(sort)) {
      q += ` ORDER BY t.${sort} IS NULL, t.${sort} ${order === 'desc' ? 'DESC' : 'ASC'}`;
    } else {
      q += ' ORDER BY t.due_date IS NULL, t.due_date ASC';
    }
    const rows = await db.all(q, ...(params as any[]));
    return rows.map(row => taskRow(row, t));
  });

  r.get('/api/tasks/:task_id', req => fetchTask(db, intParam(req, 'task_id')));
  r.post('/api/tasks', req => createTask(db, body(req)));
  r.put('/api/tasks/:task_id', req => {
    const id = intParam(req, 'task_id');
    return updateTask(db, id, body(req));
  });
  r.delete('/api/tasks/:task_id', async req => {
    await db.run('DELETE FROM tasks WHERE id=?', intParam(req, 'task_id'));
    return { ok: true };
  });

  r.post('/api/tasks/:task_id/auto-plan', async req => {
    const id = intParam(req, 'task_id');
    const task = await db.get('SELECT * FROM tasks WHERE id=?', id);
    if (!task) throw new HttpError(404, 'Task not found');
    const due = task.due_date;
    if (!due) return { plan: [], message: 'Set a due date first.' };
    const hrs = task.estimated_hours || 4;
    const t = today();
    const days = Math.round((parseYmd(due).getTime() - parseYmd(t).getTime()) / 86400000);
    if (days <= 0) return { plan: [], message: 'This is due today or already past — start now.' };
    const sessions = Math.min(Math.max(1, pyRound(hrs / 2)), days);         // ~2 hour sessions
    const step = days / sessions;
    const plan = [];
    for (let i = 0; i < sessions; i++) {
      plan.push({ date: addDays(t, Math.trunc(i * step)), hours: pyRound(hrs / sessions, 1),
        label: `Session ${i + 1} of ${sessions}`, target: Math.trunc((i + 1) / sessions * 100) });
    }
    await db.run('UPDATE tasks SET planned_start_date=?, planned_end_date=?, updated_at=? WHERE id=?',
      plan[0].date, plan[plan.length - 1].date, nowStamp(), id);
    return { plan, planned_start_date: plan[0].date, planned_end_date: plan[plan.length - 1].date,
      message: `${sessions} session${sessions > 1 ? 's' : ''} over ${days} days` };
  });

  // ── Task types (categories) ──
  r.get('/api/categories', () => db.all('SELECT * FROM categories ORDER BY id'));

  r.post('/api/categories', async req => {
    const { data } = parse<Row>(CategoryCreate, body(req));
    const res = await db.run('INSERT INTO categories (name, color) VALUES (?,?)', data.name.trim(), data.color);
    return db.get('SELECT * FROM categories WHERE id=?', res.lastId);
  });

  r.put('/api/categories/:cat_id', async req => {
    const id = intParam(req, 'cat_id');
    const updates = Object.fromEntries(Object.entries(sent<Row>(CategoryUpdate, body(req))).filter(([, v]) => v !== null));
    if ('name' in updates) {
      updates.name = updates.name.trim();
      if (!updates.name) throw new HttpError(400, 'Give it a name.');
    }
    await requireRow(db, 'categories', id, 'Task type');
    const keys = Object.keys(updates);
    if (keys.length) {
      await db.run(`UPDATE categories SET ${keys.map(k => `${k}=?`).join(', ')} WHERE id=?`, ...keys.map(k => updates[k]), id);
    }
    return db.get('SELECT * FROM categories WHERE id=?', id);
  });

  r.delete('/api/categories/:cat_id', async req => {
    await db.run('DELETE FROM categories WHERE id=?', intParam(req, 'cat_id'));
    return { ok: true };
  });
}
