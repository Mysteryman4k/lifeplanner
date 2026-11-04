/* The same tables as the desktop's init_db() in app.py, so a backup from either one restores on the other.
   Keep the two in step: tests/schema.test.ts compares this with the desktop's schema. */
import type { Database } from './db';

export const SCHEMA = `
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL DEFAULT '#6366f1',
    icon TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL DEFAULT '#6366f1',
    icon TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    due_date TEXT,
    planned_start_date TEXT,
    planned_end_date TEXT,
    priority TEXT DEFAULT 'medium' CHECK(priority IN ('low','medium','high','urgent')),
    status TEXT DEFAULT 'not_started' CHECK(status IN ('not_started','in_progress','completed','overdue')),
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    unit_id INTEGER REFERENCES units(id) ON DELETE SET NULL,
    target_grade TEXT DEFAULT '',
    progress INTEGER DEFAULT 0 CHECK(progress >= 0 AND progress <= 100),
    estimated_hours REAL,
    actual_hours REAL DEFAULT 0,
    notes TEXT DEFAULT '',
    is_recurring INTEGER DEFAULT 0,
    recurrence_pattern TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS job_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT DEFAULT 'applied' CHECK(status IN ('applied','phone_screen','interviewing',
                                              'offer','accepted','rejected','withdrawn')),
    applied_date TEXT,
    follow_up_date TEXT,
    notes TEXT DEFAULT '',
    url TEXT DEFAULT '',
    salary_range TEXT DEFAULT '',
    contact_name TEXT DEFAULT '',
    contact_email TEXT DEFAULT '',
    priority TEXT DEFAULT 'medium' CHECK(priority IN ('low','medium','high')),
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK(type IN ('income','expense')),
    amount REAL NOT NULL,
    category TEXT NOT NULL,
    description TEXT DEFAULT '',
    date TEXT NOT NULL,
    recurring INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL UNIQUE,
    monthly_limit REAL NOT NULL,
    icon TEXT DEFAULT '',
    color TEXT DEFAULT '#6366f1'
);

INSERT OR IGNORE INTO categories (id, name, color) VALUES
    (1,'Assignment','#b45309'),(2,'Exam','#b91c1c'),(3,'Project','#6d28d9'),
    (4,'Reading','#047857'),(5,'Personal','#0e7490'),(6,'Other','#57534e');

CREATE INDEX IF NOT EXISTS ix_tasks_due ON tasks(due_date);
CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS ix_tasks_category ON tasks(category_id);
CREATE INDEX IF NOT EXISTS ix_tasks_subject ON tasks(subject_id);
CREATE INDEX IF NOT EXISTS ix_units_subject ON units(subject_id);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON job_applications(status);
CREATE INDEX IF NOT EXISTS ix_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS ix_tx_category ON transactions(category);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_notes_subject ON notes(subject_id);

CREATE TABLE IF NOT EXISTS code_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'assignment',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS file_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id INTEGER NOT NULL REFERENCES code_folders(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    base_hash TEXT,
    new_content TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'edit',
    eol TEXT NOT NULL DEFAULT 'LF',
    backup TEXT NOT NULL DEFAULT '',
    applied_hash TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'study',
    mode TEXT NOT NULL DEFAULT 'explain',
    format TEXT NOT NULL DEFAULT 'auto',
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    folder_id INTEGER REFERENCES code_folders(id) ON DELETE SET NULL,
    tokens INTEGER NOT NULL DEFAULT 0,
    attachment TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_messages_chat ON messages(conversation_id, position);

CREATE TABLE IF NOT EXISTS ai_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
`;

/** Create the tables (new installs) and bring older phone databases up to date. */
export async function initDb(db: Database, version: string) {
  await db.tx(async () => {
    await db.exec(SCHEMA);
    // A change cut off part-way (the app was closed mid-change) keeps the undo steps saved so far: offer Undo
    await db.run("UPDATE ai_actions SET status='done' WHERE status IN ('applying', 'undoing')");
    await db.run('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
      'last_run_version', JSON.stringify(version));
  });
}
