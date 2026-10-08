#!/usr/bin/env python3
"""
Trackademic — student planner, job tracker and money manager.
FastAPI backend + SQLite database.

Run directly:  python app.py        (serves on http://127.0.0.1:8585)
Desktop app:   python desktop.py
"""
import os
import re
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import reminders
import system_integration
import updater

# ── App identity (change the name here when renaming the app) ─────────────
APP_NAME = "Trackademic"
APP_SLUG = "Trackademic"          # folder name used for user data
PREVIOUS_SLUGS = ["LifePlanner"]  # data folders of earlier names, migrated automatically

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
# The version lives in one place: the VERSION file (bumped with tools/bump_version.py)
APP_VERSION = (BASE / "VERSION").read_text(encoding="utf-8").strip() if (BASE / "VERSION").exists() else "0.0.0"


def _user_data_root() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def data_dir() -> Path:
    """Per-user folder that survives updates and the packaged .exe being closed."""
    override = os.environ.get("TRACKADEMIC_DATA_DIR") or os.environ.get("LIFEPLANNER_DATA_DIR")
    base = Path(override) if override else _user_data_root() / APP_SLUG
    base.mkdir(parents=True, exist_ok=True)
    return base


DB_PATH = data_dir() / "planner.db"


def _migrate_old_data():
    """Bring across data from earlier versions (old app name, or stored next to app.py)."""
    if DB_PATH.exists():
        return
    candidates = [_user_data_root() / slug / "planner.db" for slug in PREVIOUS_SLUGS] + [BASE / "planner.db"]
    for old in candidates:
        if old.exists() and old.stat().st_size > 0:
            src = sqlite3.connect(str(old))
            dst = sqlite3.connect(str(DB_PATH))
            with dst:
                src.backup(dst)          # safe copy even if the old file is in WAL mode
            src.close()
            dst.close()
            return


if not (os.environ.get("TRACKADEMIC_DATA_DIR") or os.environ.get("LIFEPLANNER_DATA_DIR")):
    _migrate_old_data()

app = FastAPI(title=APP_NAME, version=APP_VERSION)

# ── Database ───────────────────────────────────────────────────────────────


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    """Open a connection, commit on success, roll back on error, always close.

    Older versions leaked the connection whenever a query failed, which kept the
    database locked and made the next requests hang and fail.
    """
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise HTTPException(400, _friendly_integrity(e)) from e
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _friendly_integrity(e: Exception) -> str:
    msg = str(e)
    if "UNIQUE" in msg:
        return "That name is already used."
    if "FOREIGN KEY" in msg:
        return "A linked item no longer exists."
    return "That value isn't allowed."


# Earlier versions created these sample budgets for everyone (a made-up $1,500/month).
SAMPLE_BUDGETS = {("Food & Dining", 400), ("Transport", 150), ("Entertainment", 200), ("Shopping", 250),
                  ("Bills & Utilities", 300), ("Education", 100), ("Other", 100)}


def _remove_untouched_sample_budgets(conn):
    """Remove the old sample budgets, but only if they were never changed and no money has been
    recorded, so the user sets up their own instead. Anything the user entered is kept."""
    if conn.execute("SELECT 1 FROM settings WHERE key='migrated_sample_budgets'").fetchone():
        return
    rows = {(r["category"], r["monthly_limit"]) for r in conn.execute("SELECT category, monthly_limit FROM budgets")}
    no_money = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    if rows == SAMPLE_BUDGETS and no_money:
        conn.execute("DELETE FROM budgets")
    conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('migrated_sample_budgets', 'true')")


def init_db():
    with db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
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
        """)
        _remove_untouched_sample_budgets(conn)
        # Columns added in v2
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        for col, ddl in [
            ("subject_id", "INTEGER REFERENCES subjects(id) ON DELETE SET NULL"),
            ("unit_id", "INTEGER REFERENCES units(id) ON DELETE SET NULL"),
            ("target_grade", "TEXT DEFAULT ''"),
        ]:
            if col not in cols:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {ddl}")
        # v3: overdue is now worked out from the due date instead of being saved,
        # so tasks stop being stuck as overdue after their date is moved.
        conn.execute("""UPDATE tasks SET status = CASE WHEN progress > 0 THEN 'in_progress' ELSE 'not_started' END
                        WHERE status = 'overdue'""")
        # Older versions stored emoji icons; the new UI uses its own icons.
        conn.execute("UPDATE categories SET icon=''")
        conn.execute("UPDATE budgets SET icon=''")
        conn.execute("UPDATE subjects SET icon=''")
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS ix_tasks_due ON tasks(due_date);
            CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS ix_tasks_category ON tasks(category_id);
            CREATE INDEX IF NOT EXISTS ix_tasks_subject ON tasks(subject_id);
            CREATE INDEX IF NOT EXISTS ix_units_subject ON units(subject_id);
            CREATE INDEX IF NOT EXISTS ix_jobs_status ON job_applications(status);
            CREATE INDEX IF NOT EXISTS ix_tx_date ON transactions(date);
            CREATE INDEX IF NOT EXISTS ix_tx_category ON transactions(category);
        """)


init_db()

# ── Validation models ──────────────────────────────────────────────────────

Priority = Literal["low", "medium", "high", "urgent"]
TaskStatus = Literal["not_started", "in_progress", "completed"]
Repeat = Literal["", "daily", "weekly", "fortnightly", "monthly"]
JobStatus = Literal["applied", "phone_screen", "interviewing", "offer", "accepted", "rejected", "withdrawn"]
JobPriority = Literal["low", "medium", "high"]
HexColor = Field(default="#2f5d50", pattern=r"^#[0-9a-fA-F]{6}$")
Name = Field(min_length=1, max_length=120)


def _check_date(v):
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except (TypeError, ValueError):
        raise ValueError("Use a date in YYYY-MM-DD format") from None


class DatesMixin(BaseModel):
    @field_validator("due_date", "planned_start_date", "planned_end_date",
                     "applied_date", "follow_up_date", "date", check_fields=False, mode="before")
    @classmethod
    def valid_date(cls, v):
        return _check_date(v)


class TaskCreate(DatesMixin):
    title: str = Name
    description: str = ""
    due_date: Optional[str] = None
    planned_start_date: Optional[str] = None
    planned_end_date: Optional[str] = None
    priority: Priority = "medium"
    status: TaskStatus = "not_started"
    category_id: Optional[int] = None
    subject_id: Optional[int] = None
    unit_id: Optional[int] = None
    target_grade: str = Field(default="", max_length=20)
    progress: int = Field(default=0, ge=0, le=100)
    estimated_hours: Optional[float] = Field(default=None, ge=0, le=1000)
    actual_hours: float = Field(default=0, ge=0)
    notes: str = ""
    is_recurring: bool = False
    recurrence_pattern: Repeat = ""


class TaskUpdate(DatesMixin):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None
    due_date: Optional[str] = None
    planned_start_date: Optional[str] = None
    planned_end_date: Optional[str] = None
    priority: Optional[Priority] = None
    status: Optional[TaskStatus] = None
    category_id: Optional[int] = None
    subject_id: Optional[int] = None
    unit_id: Optional[int] = None
    target_grade: Optional[str] = Field(default=None, max_length=20)
    progress: Optional[int] = Field(default=None, ge=0, le=100)
    estimated_hours: Optional[float] = Field(default=None, ge=0, le=1000)
    actual_hours: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None
    is_recurring: Optional[bool] = None
    recurrence_pattern: Optional[Repeat] = None


class CategoryCreate(BaseModel):
    name: str = Name
    color: str = HexColor


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    color: Optional[str] = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class SubjectCreate(BaseModel):
    name: str = Name
    color: str = HexColor


class UnitCreate(BaseModel):
    name: str = Name


class JobCreate(DatesMixin):
    company: str = Name
    role: str = Name
    status: JobStatus = "applied"
    applied_date: Optional[str] = None
    follow_up_date: Optional[str] = None
    notes: str = ""
    url: str = Field(default="", max_length=500)
    salary_range: str = Field(default="", max_length=60)
    contact_name: str = Field(default="", max_length=120)
    contact_email: str = Field(default="", max_length=200)
    priority: JobPriority = "medium"


class JobUpdate(DatesMixin):
    company: Optional[str] = Field(default=None, min_length=1, max_length=120)
    role: Optional[str] = Field(default=None, min_length=1, max_length=120)
    status: Optional[JobStatus] = None
    applied_date: Optional[str] = None
    follow_up_date: Optional[str] = None
    notes: Optional[str] = None
    url: Optional[str] = Field(default=None, max_length=500)
    salary_range: Optional[str] = Field(default=None, max_length=60)
    contact_name: Optional[str] = Field(default=None, max_length=120)
    contact_email: Optional[str] = Field(default=None, max_length=200)
    priority: Optional[JobPriority] = None


class TransactionCreate(DatesMixin):
    type: Literal["income", "expense"]
    amount: float = Field(gt=0, le=10_000_000)
    category: str = Name
    description: str = Field(default="", max_length=200)
    date: str
    recurring: bool = False


class BudgetCreate(BaseModel):
    category: str = Name
    monthly_limit: float = Field(gt=0, le=10_000_000)
    color: str = HexColor


# ── Helpers ────────────────────────────────────────────────────────────────

TASK_SELECT = """
    SELECT t.*, c.name AS category_name, c.color AS category_color,
           s.name AS subject_name, s.color AS subject_color, u.name AS unit_name
    FROM tasks t
    LEFT JOIN categories c ON t.category_id = c.id
    LEFT JOIN subjects s ON t.subject_id = s.id
    LEFT JOIN units u ON t.unit_id = u.id
"""


def today() -> str:
    return date.today().isoformat()


def task_row(row, today_str=None):
    if row is None:
        return None
    d = dict(row)
    d["is_recurring"] = bool(d["is_recurring"])
    t = today_str or today()
    d["is_overdue"] = bool(d["due_date"] and d["due_date"] < t and d["status"] != "completed")
    return d


def fetch_task(conn, task_id):
    row = conn.execute(TASK_SELECT + " WHERE t.id=?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Task not found")
    return task_row(row)


def require(conn, table, item_id, label="Item"):
    if not conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (item_id,)).fetchone():
        raise HTTPException(404, f"{label} not found")


def month_or_current(month: Optional[str]) -> str:
    if not month:
        return date.today().strftime("%Y-%m")
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(400, "Month must look like YYYY-MM") from None
    return month


def month_range(month: str):
    """First day of the month and first day of the next month, for index-friendly range queries."""
    start = datetime.strptime(month, "%Y-%m").date()
    nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start.isoformat(), nxt.isoformat()


def now_stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def normalise_task_status(values: dict, current: Optional[dict] = None):
    """Keep status and progress consistent with each other."""
    status = values.get("status", (current or {}).get("status"))
    progress = values.get("progress", (current or {}).get("progress", 0))
    if "status" in values and status == "completed" and "progress" not in values:
        values["progress"] = 100
    elif "progress" in values and progress == 100 and "status" not in values:
        values["status"] = "completed"
    elif "progress" in values and 0 < progress < 100 and status == "not_started" and "status" not in values:
        values["status"] = "in_progress"
    return values


def sync_recurrence(values: dict):
    """"Repeats" is the recurrence pattern; is_recurring just mirrors whether one is set."""
    if "recurrence_pattern" in values:
        values["recurrence_pattern"] = values["recurrence_pattern"] or ""
        values["is_recurring"] = int(bool(values["recurrence_pattern"]))
    elif "is_recurring" in values:
        values["is_recurring"] = int(values["is_recurring"])
        if not values["is_recurring"]:
            values["recurrence_pattern"] = ""
    return values


def next_due_date(due: str, pattern: str) -> str:
    """The due date of the next copy of a repeating task. Monthly moves to the same day next month,
    or that month's last day if it's shorter (31 Jan -> 28 Feb)."""
    d = date.fromisoformat(due)
    if pattern == "daily":
        return (d + timedelta(days=1)).isoformat()
    if pattern == "weekly":
        return (d + timedelta(weeks=1)).isoformat()
    if pattern == "fortnightly":
        return (d + timedelta(weeks=2)).isoformat()
    if pattern == "monthly":
        year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        last_day = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
        return date(year, month, min(d.day, last_day)).isoformat()
    raise ValueError(pattern)


REPEAT_COPY_FIELDS = ("title", "description", "priority", "category_id", "subject_id", "unit_id",
                      "target_grade", "estimated_hours", "notes", "is_recurring", "recurrence_pattern")


def spawn_next_occurrence(conn, task: dict):
    """When a repeating task is completed, add the next one and stop the finished one repeating,
    so completing it twice (or un-completing and re-completing) never makes duplicates."""
    pattern = task.get("recurrence_pattern")
    if not pattern:
        return None
    base = task.get("due_date") or today()
    nxt = next_due_date(base, pattern)
    while nxt < today():                          # catching up after a while away: skip missed ones
        nxt = next_due_date(nxt, pattern)
    data = {k: task[k] for k in REPEAT_COPY_FIELDS}
    data.update(due_date=nxt, status="not_started", progress=0, actual_hours=0,
                created_at=now_stamp(), updated_at=now_stamp())
    cols = list(data)
    cur = conn.execute(f"INSERT INTO tasks ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                       [data[c] for c in cols])
    conn.execute("UPDATE tasks SET is_recurring=0, recurrence_pattern='' WHERE id=?", (task["id"],))
    return fetch_task(conn, cur.lastrowid)


# ═══════════════════════════════════════════════════════════════════════════
# APP INFO
# ═══════════════════════════════════════════════════════════════════════════

# ── Start-up diagnostics: when the window actually showed the app (used by the log and CI) ──
STARTUP = {"server_started": time.time(), "client_ready": None, "app_js_loads": []}


@app.post("/api/diag/client-ready")
def client_ready():
    if STARTUP["client_ready"] is None:
        STARTUP["client_ready"] = time.time()
        print(f"App on screen {STARTUP['client_ready'] - STARTUP['server_started']:.1f}s after the server started", flush=True)
    return get_startup_status()


@app.get("/api/diag/startup")
def get_startup_status():
    ready = STARTUP["client_ready"]
    loads = STARTUP["app_js_loads"]
    return {"version": APP_VERSION, "client_ready": ready is not None,
            "seconds_to_ready": round(ready - STARTUP["server_started"], 2) if ready else None,
            # Which app.js the window asked the server for. If this doesn't include the current
            # version, the window ran a cached copy of the old screens (the 3.5.0 update bug).
            "app_js_versions": sorted(set(loads)),
            "screens_current": f"{APP_VERSION}" in loads}


@app.get("/api/info")
def info():
    return {"name": APP_NAME, "version": APP_VERSION, "data_file": str(DB_PATH), "today": today(),
            "installed": updater.is_installed_build()}


# ═══════════════════════════════════════════════════════════════════════════
# SUBJECTS & UNITS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/subjects")
def list_subjects():
    """Subjects with their units and task counts in one round trip."""
    with db() as conn:
        subjects = [dict(r) for r in conn.execute("""
            SELECT s.*, COUNT(t.id) AS task_count,
                   SUM(CASE WHEN t.status != 'completed' THEN 1 ELSE 0 END) AS open_count
            FROM subjects s LEFT JOIN tasks t ON t.subject_id = s.id
            GROUP BY s.id ORDER BY s.name COLLATE NOCASE""")]
        units = conn.execute("SELECT * FROM units ORDER BY name COLLATE NOCASE").fetchall()
    by_subject = {}
    for u in units:
        by_subject.setdefault(u["subject_id"], []).append(dict(u))
    for s in subjects:
        s["units"] = by_subject.get(s["id"], [])
        s["open_count"] = s["open_count"] or 0
    return subjects


@app.post("/api/subjects")
def create_subject(subj: SubjectCreate):
    with db() as conn:
        cur = conn.execute("INSERT INTO subjects (name, color) VALUES (?,?)", (subj.name.strip(), subj.color))
        row = dict(conn.execute("SELECT * FROM subjects WHERE id=?", (cur.lastrowid,)).fetchone())
    row.update(units=[], task_count=0, open_count=0)
    return row


@app.put("/api/subjects/{subj_id}")
def update_subject(subj_id: int, subj: SubjectCreate):
    with db() as conn:
        require(conn, "subjects", subj_id, "Subject")
        conn.execute("UPDATE subjects SET name=?, color=? WHERE id=?", (subj.name.strip(), subj.color, subj_id))
    return {"ok": True}


@app.delete("/api/subjects/{subj_id}")
def delete_subject(subj_id: int):
    with db() as conn:
        conn.execute("DELETE FROM subjects WHERE id=?", (subj_id,))
    return {"ok": True}


@app.get("/api/subjects/{subj_id}/units")
def list_units(subj_id: int):
    with db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM units WHERE subject_id=? ORDER BY name COLLATE NOCASE", (subj_id,))]


@app.post("/api/subjects/{subj_id}/units")
def create_unit(subj_id: int, unit: UnitCreate):
    with db() as conn:
        require(conn, "subjects", subj_id, "Subject")
        cur = conn.execute("INSERT INTO units (subject_id, name) VALUES (?,?)", (subj_id, unit.name.strip()))
        return dict(conn.execute("SELECT * FROM units WHERE id=?", (cur.lastrowid,)).fetchone())


@app.delete("/api/units/{unit_id}")
def delete_unit(unit_id: int):
    with db() as conn:
        conn.execute("DELETE FROM units WHERE id=?", (unit_id,))
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════
# TASKS
# ═══════════════════════════════════════════════════════════════════════════

SORTABLE = {"due_date", "created_at", "title", "progress", "status"}


@app.get("/api/tasks")
def list_tasks(
    status: Optional[str] = None, category: Optional[int] = None,
    priority: Optional[str] = None, search: Optional[str] = None,
    subject: Optional[int] = None, unit: Optional[int] = None,
    due_before: Optional[str] = None, due_after: Optional[str] = None,
    overdue: Optional[bool] = None,
    sort: str = "due_date", order: str = "asc",
):
    where, params = [], []
    t = today()
    if status:
        statuses = [s for s in status.split(",") if s]
        if "overdue" in statuses:          # old clients asked for the stored 'overdue' status
            statuses.remove("overdue")
            overdue = True
        if statuses:
            where.append(f"t.status IN ({','.join('?' * len(statuses))})")
            params += statuses
    if overdue is True:
        where.append("t.due_date < ? AND t.status != 'completed'")
        params.append(t)
    for col, val in (("t.category_id", category), ("t.subject_id", subject),
                     ("t.unit_id", unit), ("t.priority", priority)):
        if val is not None and val != "":
            where.append(f"{col}=?")
            params.append(val)
    if search:
        where.append("(t.title LIKE ? OR t.description LIKE ?)")
        params += [f"%{search}%"] * 2
    if due_before:
        where.append("t.due_date <= ?")
        params.append(due_before)
    if due_after:
        where.append("t.due_date >= ?")
        params.append(due_after)

    q = TASK_SELECT + (" WHERE " + " AND ".join(where) if where else "")
    if sort == "priority":
        q += " ORDER BY CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END"
    elif sort in SORTABLE:
        q += f" ORDER BY t.{sort} IS NULL, t.{sort} {'DESC' if order == 'desc' else 'ASC'}"
    else:
        q += " ORDER BY t.due_date IS NULL, t.due_date ASC"
    with db() as conn:
        rows = conn.execute(q, params).fetchall()
    return [task_row(r, t) for r in rows]


@app.get("/api/tasks/{task_id}")
def get_task(task_id: int):
    with db() as conn:
        return fetch_task(conn, task_id)


@app.post("/api/tasks")
def create_task(task: TaskCreate):
    values = normalise_task_status(task.model_dump(exclude_unset=True))
    data = task.model_dump()
    data.update(values)
    data["title"] = data["title"].strip()
    sync_recurrence(data)
    if data["recurrence_pattern"] and not data["due_date"]:
        data["due_date"] = today()               # a repeating task needs a date to repeat from
    data["created_at"] = data["updated_at"] = now_stamp()
    cols = list(data)
    with db() as conn:
        cur = conn.execute(f"INSERT INTO tasks ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                           [data[c] for c in cols])
        return fetch_task(conn, cur.lastrowid)


@app.put("/api/tasks/{task_id}")
def update_task(task_id: int, task: TaskUpdate):
    updates = task.model_dump(exclude_unset=True)
    with db() as conn:
        current = conn.execute("SELECT status, progress FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not current:
            raise HTTPException(404, "Task not found")
        updates = sync_recurrence(normalise_task_status(updates, dict(current)))
        if updates:
            updates["updated_at"] = now_stamp()
            conn.execute(f"UPDATE tasks SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?",
                         [*updates.values(), task_id])
        task = fetch_task(conn, task_id)
        if task["status"] == "completed" and current["status"] != "completed" and task["recurrence_pattern"]:
            task["next_task"] = spawn_next_occurrence(conn, task)
            task.update(is_recurring=False, recurrence_pattern="")
        return task


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int):
    with db() as conn:
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    return {"ok": True}


@app.post("/api/tasks/{task_id}/auto-plan")
def auto_plan(task_id: int):
    """Spread the estimated hours into study sessions between today and the due date."""
    with db() as conn:
        task = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone() or {})
        if not task:
            raise HTTPException(404, "Task not found")
        due = task.get("due_date")
        if not due:
            return {"plan": [], "message": "Set a due date first."}
        hrs = task.get("estimated_hours") or 4
        days = (date.fromisoformat(due) - date.today()).days
        if days <= 0:
            return {"plan": [], "message": "This is due today or already past — start now."}
        sessions = min(max(1, round(hrs / 2)), days)       # ~2 hour sessions
        step = days / sessions
        plan = []
        for i in range(sessions):
            day = date.today() + timedelta(days=int(i * step))
            plan.append({"date": day.isoformat(), "hours": round(hrs / sessions, 1),
                         "label": f"Session {i + 1} of {sessions}",
                         "target": int((i + 1) / sessions * 100)})
        conn.execute("UPDATE tasks SET planned_start_date=?, planned_end_date=?, updated_at=? WHERE id=?",
                     (plan[0]["date"], plan[-1]["date"], now_stamp(), task_id))
        return {"plan": plan, "planned_start_date": plan[0]["date"], "planned_end_date": plan[-1]["date"],
                "message": f"{sessions} session{'s' if sessions > 1 else ''} over {days} days"}


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORIES
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/categories")
def list_categories():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM categories ORDER BY id")]


@app.post("/api/categories")
def create_category(cat: CategoryCreate):
    with db() as conn:
        cur = conn.execute("INSERT INTO categories (name, color) VALUES (?,?)", (cat.name.strip(), cat.color))
        return dict(conn.execute("SELECT * FROM categories WHERE id=?", (cur.lastrowid,)).fetchone())


@app.put("/api/categories/{cat_id}")
def update_category(cat_id: int, cat: CategoryUpdate):
    updates = cat.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in updates:
        updates["name"] = updates["name"].strip()
        if not updates["name"]:
            raise HTTPException(400, "Give it a name.")
    with db() as conn:
        require(conn, "categories", cat_id, "Task type")
        if updates:
            conn.execute(f"UPDATE categories SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?",
                         [*updates.values(), cat_id])
        return dict(conn.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone())


@app.delete("/api/categories/{cat_id}")
def delete_category(cat_id: int):
    with db() as conn:
        conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════
# JOB APPLICATIONS
# ═══════════════════════════════════════════════════════════════════════════

JOB_ORDER = ("CASE status WHEN 'interviewing' THEN 0 WHEN 'phone_screen' THEN 1 WHEN 'offer' THEN 2 "
             "WHEN 'applied' THEN 3 WHEN 'accepted' THEN 4 WHEN 'rejected' THEN 5 ELSE 6 END")


@app.get("/api/jobs")
def list_jobs(status: Optional[str] = None, priority: Optional[str] = None, search: Optional[str] = None):
    where, params = [], []
    if status:
        statuses = [s for s in status.split(",") if s]
        where.append(f"status IN ({','.join('?' * len(statuses))})")
        params += statuses
    if priority:
        where.append("priority=?")
        params.append(priority)
    if search:
        where.append("(company LIKE ? OR role LIKE ?)")
        params += [f"%{search}%"] * 2
    q = "SELECT * FROM job_applications" + (" WHERE " + " AND ".join(where) if where else "")
    q += f" ORDER BY {JOB_ORDER}, updated_at DESC"
    with db() as conn:
        return [dict(r) for r in conn.execute(q, params)]


@app.get("/api/jobs/stats")
def job_stats():
    with db() as conn:
        counts = {s: 0 for s in JobStatus.__args__}
        for r in conn.execute("SELECT status, COUNT(*) AS n FROM job_applications GROUP BY status"):
            counts[r["status"]] = r["n"]
        follow_ups = conn.execute("""SELECT COUNT(*) FROM job_applications
            WHERE follow_up_date IS NOT NULL AND follow_up_date <= ?
              AND status IN ('applied','phone_screen','interviewing','offer')""", (today(),)).fetchone()[0]
    return {"total": sum(counts.values()), "by_status": counts, "follow_ups_due": follow_ups}


@app.post("/api/jobs")
def create_job(job: JobCreate):
    data = job.model_dump()
    data["created_at"] = data["updated_at"] = now_stamp()
    cols = list(data)
    with db() as conn:
        cur = conn.execute(f"INSERT INTO job_applications ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                           [data[c] for c in cols])
        return dict(conn.execute("SELECT * FROM job_applications WHERE id=?", (cur.lastrowid,)).fetchone())


@app.put("/api/jobs/{job_id}")
def update_job(job_id: int, job: JobUpdate):
    updates = job.model_dump(exclude_unset=True)
    with db() as conn:
        require(conn, "job_applications", job_id, "Application")
        if updates:
            updates["updated_at"] = now_stamp()
            conn.execute(f"UPDATE job_applications SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?",
                         [*updates.values(), job_id])
        return dict(conn.execute("SELECT * FROM job_applications WHERE id=?", (job_id,)).fetchone())


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int):
    with db() as conn:
        conn.execute("DELETE FROM job_applications WHERE id=?", (job_id,))
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════
# FINANCE
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/transactions")
def list_transactions(month: Optional[str] = None, category: Optional[str] = None, type: Optional[str] = None):
    start, end = month_range(month_or_current(month))
    where, params = ["date >= ? AND date < ?"], [start, end]
    if category:
        where.append("category=?")
        params.append(category)
    if type:
        where.append("type=?")
        params.append(type)
    with db() as conn:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM transactions WHERE {' AND '.join(where)} ORDER BY date DESC, id DESC", params)]


@app.post("/api/transactions")
def create_transaction(tx: TransactionCreate):
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO transactions (type, amount, category, description, date, recurring) VALUES (?,?,?,?,?,?)",
            (tx.type, round(tx.amount, 2), tx.category.strip(), tx.description.strip(), tx.date, int(tx.recurring)))
        return dict(conn.execute("SELECT * FROM transactions WHERE id=?", (cur.lastrowid,)).fetchone())


@app.delete("/api/transactions/{tx_id}")
def delete_transaction(tx_id: int):
    with db() as conn:
        conn.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
    return {"ok": True}


@app.get("/api/budgets")
def list_budgets(month: Optional[str] = None):
    start, end = month_range(month_or_current(month))
    with db() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT b.*, COALESCE(SUM(t.amount), 0) AS spent
            FROM budgets b LEFT JOIN transactions t
              ON t.category = b.category AND t.type = 'expense' AND t.date >= ? AND t.date < ?
            GROUP BY b.id ORDER BY b.category COLLATE NOCASE""", (start, end))]


@app.post("/api/budgets")
def create_budget(b: BudgetCreate):
    with db() as conn:
        cur = conn.execute("INSERT INTO budgets (category, monthly_limit, color) VALUES (?,?,?)",
                           (b.category.strip(), b.monthly_limit, b.color))
        row = dict(conn.execute("SELECT * FROM budgets WHERE id=?", (cur.lastrowid,)).fetchone())
    row["spent"] = 0
    return row


@app.put("/api/budgets/{budget_id}")
def update_budget(budget_id: int, b: BudgetCreate):
    with db() as conn:
        old = conn.execute("SELECT category FROM budgets WHERE id=?", (budget_id,)).fetchone()
        if not old:
            raise HTTPException(404, "Budget not found")
        new_name = b.category.strip()
        conn.execute("UPDATE budgets SET category=?, monthly_limit=?, color=? WHERE id=?",
                     (new_name, b.monthly_limit, b.color, budget_id))
        # Renaming a budget keeps its past transactions attached to it
        if old["category"] != new_name:
            conn.execute("UPDATE transactions SET category=? WHERE category=?", (new_name, old["category"]))
        return dict(conn.execute("SELECT * FROM budgets WHERE id=?", (budget_id,)).fetchone())


@app.delete("/api/budgets/{budget_id}")
def delete_budget(budget_id: int):
    with db() as conn:
        conn.execute("DELETE FROM budgets WHERE id=?", (budget_id,))
    return {"ok": True}


class BudgetPlanItem(BaseModel):
    category: str = Name
    monthly_limit: Optional[float] = Field(default=None, ge=0, le=10_000_000)   # empty/0 = no budget


class BudgetPlan(BaseModel):
    items: list[BudgetPlanItem] = Field(max_length=100)


@app.put("/api/budget-plan")
def save_budget_plan(plan: BudgetPlan):
    """Set several budgets at once (the "Set up your budget" screen).
    A category with an amount is created or updated; one left empty or 0 is removed.
    Past transactions are never deleted."""
    with db() as conn:
        for item in plan.items:
            name = item.category.strip()
            if item.monthly_limit:
                conn.execute("""INSERT INTO budgets (category, monthly_limit) VALUES (?, ?)
                                ON CONFLICT(category) DO UPDATE SET monthly_limit=excluded.monthly_limit""",
                             (name, round(item.monthly_limit, 2)))
            else:
                conn.execute("DELETE FROM budgets WHERE category=?", (name,))
    return list_budgets()


@app.get("/api/finance/stats")
def finance_stats(month: Optional[str] = None):
    start, end = month_range(month_or_current(month))
    with db() as conn:
        totals = conn.execute("""
            SELECT COALESCE(SUM(CASE WHEN type='income' THEN amount END), 0) AS income,
                   COALESCE(SUM(CASE WHEN type='expense' THEN amount END), 0) AS expenses
            FROM transactions WHERE date >= ? AND date < ?""", (start, end)).fetchone()
        by_cat = conn.execute("""SELECT category, SUM(amount) AS total FROM transactions
            WHERE type='expense' AND date >= ? AND date < ? GROUP BY category ORDER BY total DESC""",
                              (start, end)).fetchall()
        budget_total = conn.execute("SELECT COALESCE(SUM(monthly_limit), 0) FROM budgets").fetchone()[0]
    income, expenses = totals["income"], totals["expenses"]
    return {"income": income, "expenses": expenses, "balance": income - expenses,
            "budget_total": budget_total, "by_category": [dict(r) for r in by_cat]}


# ═══════════════════════════════════════════════════════════════════════════
# STATS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/stats")
def get_stats():
    t = today()
    week = (date.today() + timedelta(days=7)).isoformat()
    with db() as conn:
        s = conn.execute("""
            SELECT COUNT(*) AS total,
              SUM(status='completed') AS completed,
              SUM(status='in_progress') AS in_progress,
              SUM(status='not_started') AS not_started,
              SUM(due_date < :t AND status != 'completed') AS overdue,
              SUM(due_date = :t AND status != 'completed') AS due_today,
              SUM(due_date BETWEEN :t AND :w AND status != 'completed') AS due_this_week
            FROM tasks""", {"t": t, "w": week}).fetchone()
        cb = conn.execute("""SELECT c.name, c.color, COUNT(t.id) AS count FROM categories c
            LEFT JOIN tasks t ON t.category_id = c.id GROUP BY c.id ORDER BY count DESC""").fetchall()
        pb = conn.execute("""SELECT priority, COUNT(*) AS count FROM tasks
            WHERE status != 'completed' GROUP BY priority""").fetchall()
        sb = conn.execute("""SELECT s.name, s.color, COUNT(t.id) AS count FROM subjects s
            LEFT JOIN tasks t ON t.subject_id = s.id GROUP BY s.id ORDER BY count DESC""").fetchall()
        gd = conn.execute("""SELECT target_grade, COUNT(*) AS count FROM tasks
            WHERE target_grade != '' AND status != 'completed' GROUP BY target_grade""").fetchall()
    stats = {k: (s[k] or 0) for k in s.keys()}
    stats["completion_rate"] = round(stats["completed"] / stats["total"] * 100, 1) if stats["total"] else 0
    stats.update(category_breakdown=[dict(r) for r in cb], priority_breakdown=[dict(r) for r in pb],
                 subject_breakdown=[dict(r) for r in sb], grade_distribution=[dict(r) for r in gd])
    return stats


# ═══════════════════════════════════════════════════════════════════════════
# SETTINGS (appearance etc.) — kept in the database so they survive restarts
# ═══════════════════════════════════════════════════════════════════════════

class Appearance(BaseModel):
    theme: Literal["sunset", "midnight", "cobalt", "ocean", "berry", "graphite"] = "sunset"
    font: Literal["rounded", "modern", "expressive", "techy", "classic"] = "rounded"
    mode: Literal["system", "light", "dark"] = "system"


@app.get("/api/settings/appearance")
def get_appearance():
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='appearance'").fetchone()
    if row:
        try:
            return Appearance.model_validate_json(row["value"]).model_dump()
        except Exception:
            pass
    return Appearance().model_dump()


@app.put("/api/settings/appearance")
def set_appearance(a: Appearance):
    with db() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('appearance', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (a.model_dump_json(),))
    return a.model_dump()


# ═══════════════════════════════════════════════════════════════════════════
# UPDATES — checks GitHub Releases; the installed Windows app can update itself
# ═══════════════════════════════════════════════════════════════════════════

class UpdateSettings(BaseModel):
    auto_check: bool = True


class StartupSettings(BaseModel):
    intro: bool = True        # play the animated intro when the desktop app opens


def _get_setting(key, model):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    try:
        return model.model_validate_json(row["value"]) if row else model()
    except Exception:
        return model()


def _put_setting(key: str, value: str):
    with db() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


class MoneySettings(BaseModel):
    currency: str = Field(default="", pattern=r"^([A-Z]{3})?$")   # ISO 4217 code; "" = not chosen yet


def suggested_currency() -> str:
    """Best guess from the computer's region (Windows "Region" setting, or LANG elsewhere)."""
    region = ""
    try:
        if os.name == "nt":
            import ctypes
            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
                region = buf.value.split("-")[-1]                 # "en-AU" -> "AU"
        else:
            region = (os.environ.get("LC_ALL") or os.environ.get("LC_MONETARY") or os.environ.get("LANG") or "")
            region = region.split(".")[0].split("_")[-1] if "_" in region else ""
    except Exception:
        region = ""
    return REGION_CURRENCY.get(region.upper(), "USD")


REGION_CURRENCY = {
    "AU": "AUD", "NZ": "NZD", "US": "USD", "GB": "GBP", "IE": "EUR", "CA": "CAD", "ZA": "ZAR", "IN": "INR",
    "SG": "SGD", "MY": "MYR", "HK": "HKD", "CN": "CNY", "JP": "JPY", "KR": "KRW", "PH": "PHP", "ID": "IDR",
    "NG": "NGN", "KE": "KES", "GH": "GHS", "ZW": "USD", "BW": "BWP", "NA": "NAD", "ZM": "ZMW", "AE": "AED",
    "SA": "SAR", "PK": "PKR", "BD": "BDT", "LK": "LKR", "NP": "NPR", "VN": "VND", "TH": "THB", "BR": "BRL",
    "MX": "MXN", "CH": "CHF", "SE": "SEK", "NO": "NOK", "DK": "DKK", "PL": "PLN",
    **{c: "EUR" for c in ("DE", "FR", "ES", "IT", "NL", "BE", "AT", "PT", "FI", "GR", "LU", "SK", "SI",
                          "EE", "LV", "LT", "MT", "CY", "HR")},
}


@app.get("/api/settings/money")
def get_money_settings():
    m = _get_setting("money", MoneySettings)
    return {"currency": m.currency or suggested_currency(), "chosen": bool(m.currency)}


@app.put("/api/settings/money")
def set_money_settings(m: MoneySettings):
    with db() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('money', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (m.model_dump_json(),))
    return get_money_settings()


@app.get("/api/settings/updates")
def get_update_settings():
    return _get_setting("updates", UpdateSettings).model_dump()


@app.put("/api/settings/updates")
def set_update_settings(u: UpdateSettings):
    with db() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('updates', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (u.model_dump_json(),))
    return u.model_dump()


@app.get("/api/settings/startup")
def get_startup_settings():
    return _get_setting("startup", StartupSettings).model_dump()


@app.put("/api/settings/startup")
def set_startup_settings(st: StartupSettings):
    with db() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('startup', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (st.model_dump_json(),))
    return st.model_dump()


# ── Reminders: one notification a day with what's due ──────────────────

class ReminderSettings(BaseModel):
    daily: bool = True
    time: str = Field(default="08:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@app.get("/api/settings/reminders")
def get_reminder_settings():
    return _get_setting("reminders", ReminderSettings).model_dump()


@app.put("/api/settings/reminders")
def set_reminder_settings(r: ReminderSettings):
    _put_setting("reminders", r.model_dump_json())
    now = datetime.now()
    if r.daily and now.strftime("%H:%M") < r.time:
        set_reminder_last_sent("")       # moved to later today: send today's at the new time
    return r.model_dump()


def reminder_last_sent() -> str:
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='reminders_last_sent'").fetchone()
    return row["value"].strip('"') if row else ""


def set_reminder_last_sent(day: str):
    _put_setting("reminders_last_sent", f'"{day}"')


def todays_digest(day: Optional[date] = None):
    with db() as conn:
        return reminders.build_digest(conn, day or date.today())


@app.get("/api/reminders/preview")
def reminder_preview():
    return {"digest": todays_digest()}


@app.post("/api/reminders/test")
def reminder_test():
    """Show today's reminder now, so the user can see what it looks like (and that Windows allows it)."""
    digest = todays_digest() or {"title": "Nothing due today",
                                 "body": "You're all caught up. Reminders will look like this.", "counts": {}}
    shown = reminders.notify(digest["title"], digest["body"])
    return {"shown": shown, "digest": digest}


def start_reminders():
    """Called by the desktop app (not the plain web server) to send the daily reminder."""
    return reminders.start_scheduler(get_reminder_settings, reminder_last_sent,
                                     set_reminder_last_sent, todays_digest)


# ── Start with Windows ───────────────────────────────────────────────

class AutostartSettings(BaseModel):
    enabled: bool


@app.get("/api/settings/autostart")
def get_autostart():
    return {"supported": system_integration.autostart_supported(),
            "enabled": system_integration.autostart_enabled()}


@app.put("/api/settings/autostart")
def set_autostart(a: AutostartSettings):
    if not system_integration.autostart_supported():
        raise HTTPException(400, "Starting with Windows only works in the installed Windows app.")
    try:
        system_integration.set_autostart(a.enabled)
    except OSError as e:
        raise HTTPException(500, f"Windows didn't allow that change: {e}") from e
    return get_autostart()


# ── The desktop window (set by desktop.py) ──────────────────────────

WINDOW = {"show": None}


@app.post("/api/window/show")
def show_window():
    """Another copy of Trackademic was opened: bring this window to the front instead."""
    if WINDOW["show"]:
        threading.Thread(target=WINDOW["show"], daemon=True).start()
        return {"ok": True}
    return {"ok": False}


@app.get("/api/update/check")
def update_check(force: bool = False):
    """force=true is a manual "Check now"; otherwise respects the auto-check setting."""
    if not force and not _get_setting("updates", UpdateSettings).auto_check:
        return {"current": APP_VERSION, "available": False, "disabled": True}
    return updater.check(APP_VERSION, force=force)


@app.post("/api/update/install")
def update_install():
    if not updater.is_installed_build():
        raise HTTPException(400, "Automatic updates only work in the installed Windows app. "
                                 "Download the new version from the release page instead.")
    status = updater.check(APP_VERSION)
    latest = updater.latest_cached()
    if not status.get("available") or not latest:
        raise HTTPException(400, "You're already on the latest version.")
    try:
        path = updater.download_installer(latest)
    except Exception as e:
        raise HTTPException(502, f"Couldn't download the update: {e}") from e
    updater.run_installer(path)
    # Give the response time to reach the window, then quit so the installer can replace files
    threading.Timer(1.5, lambda: os._exit(0)).start()
    return {"ok": True, "version": latest["version"]}


# ═══════════════════════════════════════════════════════════════════════════
# BACKUP
# ═══════════════════════════════════════════════════════════════════════════

# Parents before children, so a restore can insert in this order
BACKUP_TABLES = ("categories", "subjects", "units", "tasks", "job_applications", "transactions", "budgets", "settings")
COUNTED_TABLES = ("tasks", "subjects", "job_applications", "transactions", "budgets")
BACKUP_DIR = DB_PATH.parent / "backups"
KEEP_AUTO_BACKUPS = 10
# Settings that belong to this computer rather than to your data, so a restore keeps the current ones
LOCAL_SETTINGS = ("reminders_last_sent", "migrated_sample_budgets")


@app.get("/api/export")
def export_all():
    """Everything in one JSON file, for backups."""
    with db() as conn:
        out = {"app": APP_NAME, "version": APP_VERSION, "exported_at": now_stamp()}
        for table in BACKUP_TABLES:
            out[table] = [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
    return out


def snapshot_database(kind: str) -> Path:
    """Copy the whole database into backups/ (sqlite's backup API is safe while the app is running)."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"{kind}-{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.db"
    src, dst = _connect(), sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def list_backups(kind: Optional[str] = None):
    if not BACKUP_DIR.exists():
        return []
    files = sorted(BACKUP_DIR.glob(f"{kind or '*'}-*.db"), key=lambda f: f.name[-20:], reverse=True)   # newest first
    return files


def auto_backup():
    """One automatic backup a day, keeping the last few. Runs when the app starts."""
    try:
        stamp = date.today().isoformat()
        if not any(f.name.startswith(f"auto-{stamp}") for f in list_backups("auto")):
            snapshot_database("auto")
        for old in list_backups("auto")[KEEP_AUTO_BACKUPS:]:
            old.unlink(missing_ok=True)
        for old in list_backups("before-restore")[KEEP_AUTO_BACKUPS:]:
            old.unlink(missing_ok=True)
    except Exception as e:                                  # a backup problem must never stop the app
        print(f"Automatic backup failed: {e!r}", flush=True)


@app.get("/api/backups")
def get_backups():
    files = list_backups()
    return {"folder": str(BACKUP_DIR),
            "latest": files[0].name if files else None,
            "count": len(files)}


def _check_backup(data) -> dict:
    if not isinstance(data, dict) or data.get("app") not in (APP_NAME, "LifePlanner") \
            or not isinstance(data.get("tasks"), list):
        raise HTTPException(400, "That file isn't a Trackademic backup.")
    for table in BACKUP_TABLES:
        rows = data.get(table, [])
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise HTTPException(400, f"The backup's {table.replace('_', ' ')} section is damaged.")
    return data


@app.post("/api/import/preview")
def import_preview(data: dict):
    data = _check_backup(data)
    return {"exported_at": data.get("exported_at"), "version": data.get("version"),
            "counts": {t: len(data.get(t, [])) for t in COUNTED_TABLES}}


@app.post("/api/import")
def import_all(data: dict):
    """Replace everything with a backup made by Download backup. The current data is saved
    to backups/ first, and nothing changes unless the whole backup goes in cleanly."""
    data = _check_backup(data)
    safety = snapshot_database("before-restore")
    conn = _connect()
    try:
        conn.execute("PRAGMA foreign_keys=OFF")          # checked as a whole at the end instead
        conn.execute("BEGIN")
        for table in reversed(BACKUP_TABLES):
            if table == "settings":
                conn.execute(f"DELETE FROM settings WHERE key NOT IN ({','.join('?' * len(LOCAL_SETTINGS))})",
                             LOCAL_SETTINGS)
            else:
                conn.execute(f"DELETE FROM {table}")
        for table in BACKUP_TABLES:
            columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            for row in data.get(table, []):
                if table == "settings" and row.get("key") in LOCAL_SETTINGS:
                    continue
                cols = [c for c in row if c in columns]     # backups from older versions may lack columns
                if cols:
                    conn.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                                 [row[c] for c in cols])
        problems = conn.execute("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise HTTPException(400, "The backup has items linked to things that aren't in it, so nothing was changed.")
        conn.execute("UPDATE tasks SET status = CASE WHEN progress > 0 THEN 'in_progress' ELSE 'not_started' END "
                     "WHERE status = 'overdue'")
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except sqlite3.Error as e:
        conn.rollback()
        raise HTTPException(400, f"That backup couldn't be restored ({e}). Nothing was changed.") from e
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()
    return {"ok": True, "safety_backup": safety.name,
            "counts": {t: len(data.get(t, [])) for t in COUNTED_TABLES}}


# ═══════════════════════════════════════════════════════════════════════════
# FRONTEND
# ═══════════════════════════════════════════════════════════════════════════

NO_CACHE = {"Cache-Control": "no-cache"}


@app.get("/")
def index():
    """The page, with the version added to its script and style links (app.js?v=3.5.1), so after an
    update the window always loads the new files instead of copies cached from the old version.
    (3.5.0 shipped without this: updated installs kept running the old screens.)"""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = re.sub(r'(/static/[\w./-]+\.(?:js|css))(?=")', rf"\1?v={APP_VERSION}", html)
    return HTMLResponse(html, headers=NO_CACHE)


@app.middleware("http")
async def revalidate_static_files(request, call_next):
    """Files are local, so checking they're current costs nothing; never use a stale cached copy."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
        if request.url.path == "/static/app.js":
            STARTUP["app_js_loads"].append(request.query_params.get("v", "unversioned"))
            del STARTUP["app_js_loads"][:-50]
    return response


@app.get("/manifest.json")
def manifest():
    sizes = [16, 32, 48, 64, 128, 192, 256, 512]
    return {
        "name": APP_NAME, "short_name": APP_NAME,
        "description": "Student planner, job tracker and money manager",
        "start_url": "/", "display": "standalone",
        "background_color": "#FFF7F2", "theme_color": "#D2461A",
        "icons": [{"src": f"/static/icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png"} for n in sizes],
    }


app.mount("/static", StaticFiles(directory=STATIC), name="static")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8585))
    # 127.0.0.1 keeps your data private to this computer.
    # Set TRACKADEMIC_HOST=0.0.0.0 only if you deliberately want other devices to reach it.
    host = os.environ.get("TRACKADEMIC_HOST", "127.0.0.1")
    print(f"\n  {APP_NAME} {APP_VERSION} — http://127.0.0.1:{port}\n  Data: {DB_PATH}\n")
    auto_backup()
    uvicorn.run(app, host=host, port=port, log_level="info")
