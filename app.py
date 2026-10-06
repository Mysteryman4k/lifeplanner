#!/usr/bin/env python3
"""
LifePlanner — student planner, job tracker and finance manager.
FastAPI backend + SQLite database.

Run directly:  python app.py        (serves on http://127.0.0.1:8585)
Desktop app:   python desktop.py
"""
import os
import shutil
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

# ── App identity (change the name here when renaming the app) ─────────────
APP_NAME = "LifePlanner"
APP_SLUG = "LifePlanner"          # folder name used for user data
APP_VERSION = "3.0.0"

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"


def data_dir() -> Path:
    """Per-user folder that survives updates and the packaged .exe being closed."""
    override = os.environ.get("LIFEPLANNER_DATA_DIR")
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_SLUG
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_SLUG
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_SLUG
    base.mkdir(parents=True, exist_ok=True)
    return base


DB_PATH = data_dir() / "planner.db"

# One-time move of a database created by older versions (stored next to app.py)
_legacy = BASE / "planner.db"
if _legacy.exists() and not DB_PATH.exists():
    shutil.copy2(_legacy, DB_PATH)

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
        raise HTTPException(400, _friendly_integrity(e))
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
                status TEXT DEFAULT 'applied' CHECK(status IN ('applied','phone_screen','interviewing','offer','accepted','rejected','withdrawn')),
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
            INSERT OR IGNORE INTO budgets (id, category, monthly_limit) VALUES
                (1,'Food & Dining',400),(2,'Transport',150),(3,'Entertainment',200),
                (4,'Shopping',250),(5,'Bills & Utilities',300),(6,'Education',100),(7,'Other',100);
        """)
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
        raise ValueError("Use a date in YYYY-MM-DD format")


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
    recurrence_pattern: str = ""


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
    recurrence_pattern: Optional[str] = None


class CategoryCreate(BaseModel):
    name: str = Name
    color: str = HexColor


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
        raise HTTPException(400, "Month must look like YYYY-MM")
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


# ═══════════════════════════════════════════════════════════════════════════
# APP INFO
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/info")
def info():
    return {"name": APP_NAME, "version": APP_VERSION, "data_file": str(DB_PATH), "today": today()}


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
    data["is_recurring"] = int(data["is_recurring"])
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
        updates = normalise_task_status(updates, dict(current))
        if "is_recurring" in updates:
            updates["is_recurring"] = int(updates["is_recurring"])
        if updates:
            updates["updated_at"] = now_stamp()
            conn.execute(f"UPDATE tasks SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?",
                         [*updates.values(), task_id])
        return fetch_task(conn, task_id)


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
# BACKUP
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/export")
def export_all():
    """Everything in one JSON file, for backups."""
    with db() as conn:
        out = {"app": APP_NAME, "version": APP_VERSION, "exported_at": now_stamp()}
        for table in ("categories", "subjects", "units", "tasks", "job_applications", "transactions", "budgets"):
            out[table] = [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
    return out


# ═══════════════════════════════════════════════════════════════════════════
# FRONTEND
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.json")
def manifest():
    sizes = [16, 32, 48, 64, 128, 192, 256, 512]
    return {
        "name": APP_NAME, "short_name": APP_NAME,
        "description": "Student planner, job tracker and money manager",
        "start_url": "/", "display": "standalone",
        "background_color": "#f4f1ea", "theme_color": "#2f5d50",
        "icons": [{"src": f"/static/icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png"} for n in sizes],
    }


app.mount("/static", StaticFiles(directory=STATIC), name="static")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8585))
    # 127.0.0.1 keeps your data private to this computer.
    # Set LIFEPLANNER_HOST=0.0.0.0 only if you deliberately want other devices to reach it.
    host = os.environ.get("LIFEPLANNER_HOST", "127.0.0.1")
    print(f"\n  {APP_NAME} {APP_VERSION} — http://127.0.0.1:{port}\n  Data: {DB_PATH}\n")
    uvicorn.run(app, host=host, port=port, log_level="info")
