/* Task tools the study assistant can call: the desktop's ai/tools.py, TaskStore and ActionLog (app.py), on the phone.
   - list_tasks runs straight away (read-only).
   - add_task, update_task and complete_task run straight away and show a card with Undo.
   - delete_task always asks first (a Keep / Delete card).
   - More than 3 changes in one reply: the 4th onwards ask first, together on one card.
   - While a file is attached, every change asks first.
   Every change is recorded in ai_actions with what the task looked like before, so Undo restores it exactly.
   Each database step is its own transaction, like the desktop's, so an undo step is saved before a task is touched. */
import type { Database, Row } from '../db/db';
import { HttpError } from '../http';
import { createTask, updateTask } from '../api/tasks';
import type { ToolCall, ToolSpec } from './providers';

const MAX_DIRECT_CHANGES = 3;
const CHANGE_TOOLS = new Set(['add_task', 'update_task', 'complete_task', 'delete_task']);

const TASK_FIELDS = {
  title: { type: 'string', description: 'Short task title' },
  due_date: { type: 'string', description: 'Due date as YYYY-MM-DD' },
  priority: { type: 'string', enum: ['low', 'medium', 'high', 'urgent'] },
  subject: { type: 'string', description: "Name of one of the student's subjects" },
  estimated_hours: { type: 'number', description: 'Hours the task should take' },
  description: { type: 'string', description: 'Details for the task' },
};

export const TOOLS: ToolSpec[] = [
  { name: 'list_tasks', description: "List the student's tasks. Use this to find a task's id before changing it.",
    parameters: { type: 'object', properties: {
      status: { type: 'string', enum: ['open', 'done', 'all'], description: 'Default open' },
      search: { type: 'string', description: 'Only tasks whose title contains this' } } } },
  { name: 'add_task', description: "Add a task to the student's planner. Only when the student asks for tasks to be added.",
    parameters: { type: 'object', properties: TASK_FIELDS, required: ['title'] } },
  { name: 'update_task', description: "Change a task's title, due date, priority, subject, hours or details.",
    parameters: { type: 'object', properties: { id: { type: 'integer' }, ...TASK_FIELDS }, required: ['id'] } },
  { name: 'complete_task', description: 'Mark a task as done.',
    parameters: { type: 'object', properties: { id: { type: 'integer' } }, required: ['id'] } },
  { name: 'delete_task', description: 'Delete a task. The student is always asked to confirm in the app first.',
    parameters: { type: 'object', properties: { id: { type: 'integer' } }, required: ['id'] } },
];

const PROMPT = `You can manage the student's tasks with tools: list_tasks, add_task, update_task, complete_task and
delete_task. You don't know their tasks until you call list_tasks: call it before you mention, list or change
any task, and never make tasks up. Only change tasks when the student asks you to. Use dates as YYYY-MM-DD
(today is {today}). Changes appear in the app as cards the student can undo; deleting a task, or more than 3
changes at once, waits for the student to confirm in the app, so say that and don't claim it's done.`;

export function systemAddendum(now = new Date()) {
  const pad = (n: number) => String(n).padStart(2, '0');
  const weekday = now.toLocaleDateString('en-AU', { weekday: 'long' });
  return PROMPT.replace('{today}', `${weekday} ${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`);
}

const DASHES = /[‐-―−]/g;              // hyphens, dashes, minus

export class ToolError extends Error {}

/** The assistant's way into tasks: the same functions the app's own screens use. */
export class TaskStore {
  static COLUMNS = ['title', 'description', 'due_date', 'planned_start_date', 'planned_end_date', 'priority', 'status',
    'category_id', 'subject_id', 'unit_id', 'target_grade', 'progress', 'estimated_hours', 'actual_hours', 'notes',
    'is_recurring', 'recurrence_pattern', 'created_at', 'updated_at'];
  static LINKS: [string, string][] = [['category_id', 'categories'], ['subject_id', 'subjects'], ['unit_id', 'units']];

  constructor(private db: Database, private changed: () => void = () => undefined) {}

  private async wrap<T>(fn: () => Promise<T>): Promise<T> {
    try {
      return await this.db.tx(fn);
    } catch (e) {
      if (e instanceof HttpError) {
        if (Array.isArray(e.detail)) {
          const err = e.detail[0] ?? {};
          throw new ToolError(`${(err.loc ?? []).filter((x: unknown) => x !== 'body').join('/')}: ${err.msg ?? 'invalid'}`);
        }
        throw new ToolError(String(e.detail));
      }
      throw e;
    }
  }

  get(id: number) { return this.db.tx(() => this.db.get('SELECT * FROM tasks WHERE id=?', id)); }

  list({ status = 'open', search = '' }: { status?: string; search?: string } = {}) {
    let q = 'SELECT t.id, t.title, t.due_date, t.priority, t.status, s.name AS subject FROM tasks t ' +
      'LEFT JOIN subjects s ON s.id = t.subject_id WHERE 1=1';
    const args: string[] = [];
    if (status === 'open') q += " AND t.status != 'completed'";
    else if (status === 'done') q += " AND t.status = 'completed'";
    if (search) { q += ' AND t.title LIKE ?'; args.push(`%${search}%`); }
    return this.db.tx(() => this.db.all(q + ' ORDER BY t.due_date IS NULL, t.due_date, t.id LIMIT 60', ...args));
  }

  async create(fields: Row) {
    const out = await this.wrap(() => createTask(this.db, fields));
    this.changed();
    return out;
  }

  async update(id: number, fields: Row) {
    const out = await this.wrap(() => updateTask(this.db, id, fields));
    this.changed();
    return out;
  }

  async delete(id: number) {
    await this.db.tx(() => this.db.run('DELETE FROM tasks WHERE id=?', id));
    this.changed();
  }

  async noteIds(id: number) {
    return (await this.db.tx(() => this.db.all('SELECT id FROM notes WHERE task_id=?', id))).map(r => r.id as number);
  }

  relinkNotes(id: number, noteIds: number[]) {
    return this.db.tx(async () => {
      for (const n of noteIds) await this.db.run('UPDATE notes SET task_id=? WHERE id=? AND task_id IS NULL', id, n);
    });
  }

  /** Put a task back exactly as it was (Undo). A category, subject or unit deleted since is left empty. */
  async restore(before: Row) {
    const row = { ...before };
    const cols = TaskStore.COLUMNS.filter(c => c in row);
    await this.db.tx(async () => {
      for (const [col, table] of TaskStore.LINKS) {
        if (row[col] !== null && row[col] !== undefined && !(await this.db.get(`SELECT 1 FROM ${table} WHERE id=?`, row[col]))) row[col] = null;
      }
      if (await this.db.get('SELECT 1 FROM tasks WHERE id=?', row.id)) {
        await this.db.run(`UPDATE tasks SET ${cols.map(c => `${c}=?`).join(', ')} WHERE id=?`, ...cols.map(c => row[c]), row.id);
      } else {
        await this.db.run(`INSERT INTO tasks (id, ${cols.join(', ')}) VALUES (?, ${cols.map(() => '?').join(', ')})`,
          row.id, ...cols.map(c => row[c]));
      }
    });
    this.changed();
  }

  /** A subject by name, ignoring case; a unit code or words that match only one subject count too. */
  async subjectId(name: string): Promise<number | null> {
    const said = name.split(/\s+/).filter(Boolean).join(' ');
    const wanted = said.toLowerCase();
    if (!wanted) return null;
    const rows = (await this.db.tx(() => this.db.all('SELECT id, name FROM subjects')))
      .map(r => [r.id as number, String(r.name).split(/\s+/).filter(Boolean).join(' ')] as const);
    for (const match of [rows.filter(([, n]) => n === said).map(([id]) => id), rows.filter(([, n]) => n.toLowerCase() === wanted).map(([id]) => id)]) {
      if (match.length === 1) return match[0];
      if (match.length) return null;
    }
    const words = new RegExp(`(?<![\\p{L}\\p{N}_])${wanted.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\p{L}\\p{N}_])`, 'u');
    const partial = rows.filter(([, n]) => words.test(n.toLowerCase())).map(([id]) => id);
    return partial.length === 1 ? partial[0] : null;
  }

  async subjectNames() {
    return (await this.db.tx(() => this.db.all('SELECT name FROM subjects ORDER BY name'))).map(r => String(r.name));
  }
}

/** ai_actions: changes made (for Undo) and changes waiting for the student's Keep / Delete. */
export class ActionLog {
  constructor(private db: Database) {}

  async start(summary: string) {
    return (await this.db.tx(() => this.db.run("INSERT INTO ai_actions (status, summary, data) VALUES ('applying', ?, '[]')", summary))).lastId;
  }
  progress(id: number, ops: unknown[]) {
    return this.db.tx(() => this.db.run('UPDATE ai_actions SET data=? WHERE id=?', JSON.stringify(ops), id));
  }
  async pending(calls: ToolCall[], summaries: string[]) {
    return (await this.db.tx(() => this.db.run("INSERT INTO ai_actions (status, summary, data) VALUES ('pending', ?, ?)",
      summaries.join('; '), JSON.stringify(calls)))).lastId;
  }
  /** Claim the action in one step, so a double tap can't apply (or undo) it twice. */
  private async take(id: number, status: 'pending' | 'done'): Promise<any[]> {
    const [row, claimed] = await this.db.tx(async () => {
      const r = await this.db.get('SELECT status, data FROM ai_actions WHERE id=?', id);
      const c = r ? (await this.db.run("UPDATE ai_actions SET status=?, data=CASE WHEN ?='pending' THEN '[]' ELSE data END WHERE id=? AND status=?",
        status === 'pending' ? 'applying' : 'undoing', status, id, status)).changes : 0;
      return [r, c] as const;
    });
    if (!row) throw new HttpError(404, "That change isn't known any more.");
    if (!claimed) {
      throw new HttpError(409, status === 'pending' ? 'That change was already confirmed or declined.'
        : "That change can't be undone now (it was already undone).");
    }
    return JSON.parse(row.data);
  }
  takePending(id: number) { return this.take(id, 'pending'); }
  takeDone(id: number) { return this.take(id, 'done'); }
  completePending(id: number, ops: unknown[]) {
    return this.db.tx(() => this.db.run("UPDATE ai_actions SET status='done', data=? WHERE id=?", JSON.stringify(ops), id));
  }
  setStatus(id: number, status: string) {
    return this.db.tx(() => this.db.run('UPDATE ai_actions SET status=? WHERE id=?', status, id));
  }
}

export interface AppEvent { type: string; [k: string]: unknown }

export class TaskTools {
  schema = TOOLS;
  constructor(private store: TaskStore, private log: ActionLog) {}

  /** The tool instructions, with the student's subjects, so a task gets a subject's real name. */
  async addendum() {
    const names = await this.store.subjectNames();
    return systemAddendum() + (names.length ? `\nThe student's subjects: ${names.join('; ')}.` : '');
  }

  private async fields(args: Row) {
    const out: Row = {};
    for (const key of ['title', 'due_date', 'priority', 'estimated_hours', 'description']) {
      if (args[key] !== null && args[key] !== undefined && args[key] !== '') out[key] = args[key];
    }
    if (typeof out.due_date === 'string') out.due_date = out.due_date.replace(DASHES, '-').trim();
    if (args.subject) {
      const sid = await this.store.subjectId(String(args.subject));
      if (sid === null) {
        throw new ToolError(`'${args.subject}' isn't one of the student's subjects. Leave it out or use one of: ` +
          (await this.store.subjectNames()).join(', ') + '.');
      }
      out.subject_id = sid;
    }
    return out;
  }

  private async task(id: unknown) {
    const n = typeof id === 'number' ? id : typeof id === 'string' && /^\s*-?\d+\s*$/.test(id) ? parseInt(id, 10) : NaN;
    const row = Number.isInteger(n) ? await this.store.get(n) : undefined;
    if (!row) throw new ToolError(`There's no task with id ${id}. Use list_tasks to find it.`);
    return row;
  }

  /** One plain line for a card: what this change does. */
  async describe(call: ToolCall) {
    const a = call.args || {};
    if (call.name === 'add_task') return `Add “${a.title ?? 'task'}”` + (a.due_date ? ` (due ${a.due_date})` : '');
    const title = a.id !== undefined && a.id !== null && a.id !== ''
      ? ((await this.store.get(Number(a.id)))?.title ?? `task ${a.id}`) : 'task';
    return ({ update_task: `Change “${title}”`, complete_task: `Mark “${title}” done`, delete_task: `Delete “${title}”` } as Record<string, string>)[call.name] ?? call.name;
  }

  /** One round of tool calls: results for the model, and events (cards) for the app. */
  async runRound(calls: ToolCall[], state: { changes: number; ask_first: boolean }): Promise<[[ToolCall, string][], AppEvent[]]> {
    const results: [ToolCall, string][] = [], events: AppEvent[] = [], waiting: ToolCall[] = [];
    for (const call of calls) {
      try {
        if (call.name === 'list_tasks') {
          results.push([call, JSON.stringify(await this.store.list(call.args || {}))]);
          continue;
        }
        if (!CHANGE_TOOLS.has(call.name)) throw new ToolError(`There's no tool called ${call.name}.`);
        if (call.name === 'delete_task') await this.task((call.args || {}).id);
        if (call.name === 'delete_task' || state.ask_first || state.changes >= MAX_DIRECT_CHANGES) {
          await this.prepare(call);
          waiting.push(call);
          results.push([call, "Waiting for the student to confirm this in the app. Tell them; don't say it's done."]);
          continue;
        }
        const summary = await this.describe(call);
        const actionId = await this.log.start(summary);
        let ops: unknown[];
        try {
          ops = [await this.apply(call, op => this.log.progress(actionId, [op]))];
        } catch (e) {
          await this.log.setStatus(actionId, e instanceof ToolError ? 'rejected' : 'done');
          throw e;
        }
        await this.log.completePending(actionId, ops);
        state.changes += 1;
        events.push({ type: 'action', action_id: actionId, summary });
        results.push([call, `Done: ${summary}.`]);
      } catch (e) {
        if (!(e instanceof ToolError)) throw e;
        results.push([call, `Couldn't do that: ${e.message}`]);
      }
    }
    if (waiting.length) {
      const summaries = await Promise.all(waiting.map(c => this.describe(c)));
      const actionId = await this.log.pending(waiting, summaries);
      events.push({ type: 'confirm', action_id: actionId, items: summaries, danger: waiting.some(c => c.name === 'delete_task') });
    }
    return [results, events];
  }

  private async prepare(call: ToolCall) {
    const a = call.args || {};
    if (call.name === 'add_task') {
      if (!String(a.title ?? '').trim()) throw new ToolError('A task needs a title.');
      await this.fields(a);
    } else if (['update_task', 'complete_task', 'delete_task'].includes(call.name)) {
      await this.task(a.id);
      if (call.name === 'update_task') await this.fields(a);
    }
  }

  /** Make one change and return what's needed to undo it; save(op) stores the undo step before the task is touched. */
  private async apply(call: ToolCall, save: (op: Row) => Promise<unknown> = async () => undefined): Promise<Row> {
    const a = call.args || {};
    if (call.name === 'add_task') {
      if (!String(a.title ?? '').trim()) throw new ToolError('A task needs a title.');
      const row = await this.store.create(await this.fields(a));
      const op = { op: 'add', task_id: row.id };
      await save(op);
      return op;
    }
    const before = await this.task(a.id);
    if (call.name === 'update_task') {
      const fields = await this.fields(a);
      if (!Object.keys(fields).length) throw new ToolError('Say what to change.');
      const op = { op: 'update', task_id: before.id, before };
      await save(op);
      await this.store.update(before.id, fields);
      return op;
    }
    if (call.name === 'complete_task') {
      const op: Row = { op: 'complete', task_id: before.id, before, spawned: null };
      await save(op);
      const after = await this.store.update(before.id, { status: 'completed' });
      op.spawned = after.next_task?.id ?? null;
      if (op.spawned) await save(op);
      return op;
    }
    if (call.name === 'delete_task') {
      const op = { op: 'delete', task_id: before.id, before, notes: await this.store.noteIds(before.id) };
      await save(op);
      await this.store.delete(before.id);
      return op;
    }
    throw new ToolError(`There's no tool called ${call.name}.`);
  }

  /** The student's Keep / Delete (or Do it / Don't) on a change the assistant asked about. */
  async confirm(actionId: number, approve: boolean) {
    const calls: ToolCall[] = await this.log.takePending(actionId);
    if (!approve) {
      await this.log.setStatus(actionId, 'rejected');
      return { status: 'rejected' };
    }
    const ops: Row[] = [], failed: string[] = [];
    try {
      for (const call of calls) {
        try {
          ops.push(await this.apply(call, op => this.log.progress(actionId, [...ops, op])));
        } catch (e) {
          if (!(e instanceof ToolError)) throw e;
          failed.push(e.message);
        }
      }
    } catch (e) {
      await this.log.setStatus(actionId, 'done');               // the undo steps saved so far can still be used
      throw e;
    }
    await this.log.completePending(actionId, ops);
    return { status: 'done', done: ops.length, failed };
  }

  /** Undo a change: the task goes back exactly as it was. */
  async undo(actionId: number) {
    const ops: Row[] = await this.log.takeDone(actionId);
    try {
      for (const op of [...ops].reverse()) {
        if (op.op === 'add') await this.store.delete(op.task_id);
        else if (op.op === 'update' || op.op === 'complete') {
          if (op.spawned) await this.store.delete(op.spawned);
          await this.store.restore(op.before);
        } else if (op.op === 'delete') {
          await this.store.restore(op.before);
          await this.store.relinkNotes(op.task_id, op.notes || []);
        }
      }
    } catch (e) {
      await this.log.setStatus(actionId, 'done');              // not undone: let the student try again
      throw e;
    }
    await this.log.setStatus(actionId, 'undone');
    return { status: 'undone' };
  }
}
