#!/usr/bin/env python3
"""
LifePlanner — Student planner + job tracker + finance manager.
FastAPI backend + SQLite database.
"""
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── App Setup ──────────────────────────────────────────────────────────────

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "planner.db"

app = FastAPI(title="LifePlanner", version="2.0.0")

# ── Database ───────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT NOT NULL DEFAULT '#6366f1',
            icon TEXT DEFAULT '📚'
        );

        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT NOT NULL DEFAULT '#6366f1',
            icon TEXT DEFAULT '📖'
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
            icon TEXT DEFAULT '💰',
            color TEXT DEFAULT '#6366f1'
        );

        -- Defaults
        INSERT OR IGNORE INTO categories (id, name, color, icon) VALUES (1, 'Assignment', '#f59e0b', '📝');
        INSERT OR IGNORE INTO categories (id, name, color, icon) VALUES (2, 'Exam', '#ef4444', '📋');
        INSERT OR IGNORE INTO categories (id, name, color, icon) VALUES (3, 'Project', '#8b5cf6', '🚀');
        INSERT OR IGNORE INTO categories (id, name, color, icon) VALUES (4, 'Reading', '#10b981', '📖');
        INSERT OR IGNORE INTO categories (id, name, color, icon) VALUES (5, 'Personal', '#06b6d4', '👤');
        INSERT OR IGNORE INTO categories (id, name, color, icon) VALUES (6, 'Other', '#6b7280', '📌');

        INSERT OR IGNORE INTO budgets (id, category, monthly_limit, icon, color) VALUES (1, 'Food & Dining', 400, '🍔', '#f59e0b');
        INSERT OR IGNORE INTO budgets (id, category, monthly_limit, icon, color) VALUES (2, 'Transport', 150, '🚌', '#06b6d4');
        INSERT OR IGNORE INTO budgets (id, category, monthly_limit, icon, color) VALUES (3, 'Entertainment', 200, '🎮', '#8b5cf6');
        INSERT OR IGNORE INTO budgets (id, category, monthly_limit, icon, color) VALUES (4, 'Shopping', 250, '🛍', '#ec4899');
        INSERT OR IGNORE INTO budgets (id, category, monthly_limit, icon, color) VALUES (5, 'Bills & Utilities', 300, '⚡', '#ef4444');
        INSERT OR IGNORE INTO budgets (id, category, monthly_limit, icon, color) VALUES (6, 'Education', 100, '📚', '#10b981');
        INSERT OR IGNORE INTO budgets (id, category, monthly_limit, icon, color) VALUES (7, 'Other', 100, '📌', '#6b7280');

        -- Migrate existing tasks table to add v2 columns if missing
    """)
    # Add columns if they don't exist (safe migration)
    cols = [r[1] for r in db.execute("PRAGMA table_info(tasks)").fetchall()]
    if 'subject_id' not in cols:
        db.execute("ALTER TABLE tasks ADD COLUMN subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL")
    if 'unit_id' not in cols:
        db.execute("ALTER TABLE tasks ADD COLUMN unit_id INTEGER REFERENCES units(id) ON DELETE SET NULL")
    if 'target_grade' not in cols:
        db.execute("ALTER TABLE tasks ADD COLUMN target_grade TEXT DEFAULT ''")
    db.commit()
    db.close()

init_db()

# ── Pydantic Models ────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str
    description: str = ""
    due_date: Optional[str] = None
    planned_start_date: Optional[str] = None
    planned_end_date: Optional[str] = None
    priority: str = "medium"
    status: str = "not_started"
    category_id: Optional[int] = None
    subject_id: Optional[int] = None
    unit_id: Optional[int] = None
    target_grade: str = ""
    progress: int = 0
    estimated_hours: Optional[float] = None
    actual_hours: float = 0
    notes: str = ""
    is_recurring: bool = False
    recurrence_pattern: str = ""

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    planned_start_date: Optional[str] = None
    planned_end_date: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    category_id: Optional[int] = None
    subject_id: Optional[int] = None
    unit_id: Optional[int] = None
    target_grade: Optional[str] = None
    progress: Optional[int] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    notes: Optional[str] = None
    is_recurring: Optional[bool] = None
    recurrence_pattern: Optional[str] = None

class CategoryCreate(BaseModel):
    name: str
    color: str = "#6366f1"
    icon: str = "📚"

class SubjectCreate(BaseModel):
    name: str
    color: str = "#6366f1"
    icon: str = "📖"

class UnitCreate(BaseModel):
    name: str

class JobCreate(BaseModel):
    company: str
    role: str
    status: str = "applied"
    applied_date: Optional[str] = None
    follow_up_date: Optional[str] = None
    notes: str = ""
    url: str = ""
    salary_range: str = ""
    contact_name: str = ""
    contact_email: str = ""
    priority: str = "medium"

class JobUpdate(BaseModel):
    company: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    applied_date: Optional[str] = None
    follow_up_date: Optional[str] = None
    notes: Optional[str] = None
    url: Optional[str] = None
    salary_range: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    priority: Optional[str] = None

class TransactionCreate(BaseModel):
    type: str
    amount: float
    category: str
    description: str = ""
    date: str
    recurring: bool = False

class BudgetCreate(BaseModel):
    category: str
    monthly_limit: float
    icon: str = "💰"
    color: str = "#6366f1"

# ── Helpers ────────────────────────────────────────────────────────────────

def task_row(row):
    if row is None:
        return None
    d = dict(row)
    d["is_recurring"] = bool(d["is_recurring"])
    return d

def auto_update_overdue(db):
    today = date.today().isoformat()
    db.execute(
        "UPDATE tasks SET status='overdue' WHERE due_date < ? AND status NOT IN ('completed','overdue')",
        (today,)
    )
    db.commit()

# ═══════════════════════════════════════════════════════════════════════════
# SUBJECTS & UNITS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/subjects")
def list_subjects():
    db = get_db()
    rows = db.execute("SELECT s.*, (SELECT COUNT(*) FROM tasks t WHERE t.subject_id=s.id) as task_count FROM subjects s ORDER BY s.id").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/subjects")
def create_subject(subj: SubjectCreate):
    db = get_db()
    try:
        cur = db.execute("INSERT INTO subjects (name, color, icon) VALUES (?,?,?)", (subj.name, subj.color, subj.icon))
        db.commit()
        row = db.execute("SELECT * FROM subjects WHERE id=?", (cur.lastrowid,)).fetchone()
        db.close()
        return dict(row)
    except sqlite3.IntegrityError:
        db.close()
        raise HTTPException(400, "Subject already exists")

@app.delete("/api/subjects/{subj_id}")
def delete_subject(subj_id: int):
    db = get_db()
    db.execute("DELETE FROM subjects WHERE id=?", (subj_id,))
    db.commit()
    db.close()
    return {"ok": True}

@app.get("/api/subjects/{subj_id}/units")
def list_units(subj_id: int):
    db = get_db()
    rows = db.execute("SELECT * FROM units WHERE subject_id=? ORDER BY id", (subj_id,)).fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/subjects/{subj_id}/units")
def create_unit(subj_id: int, unit: UnitCreate):
    db = get_db()
    cur = db.execute("INSERT INTO units (subject_id, name) VALUES (?,?)", (subj_id, unit.name))
    db.commit()
    row = db.execute("SELECT * FROM units WHERE id=?", (cur.lastrowid,)).fetchone()
    db.close()
    return dict(row)

@app.delete("/api/units/{unit_id}")
def delete_unit(unit_id: int):
    db = get_db()
    db.execute("DELETE FROM units WHERE id=?", (unit_id,))
    db.commit()
    db.close()
    return {"ok": True}

# ═══════════════════════════════════════════════════════════════════════════
# TASKS (extended with subject/unit/grade)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/tasks")
def list_tasks(
    status: Optional[str] = None, category: Optional[int] = None,
    priority: Optional[str] = None, search: Optional[str] = None,
    subject: Optional[int] = None, unit: Optional[int] = None,
    due_before: Optional[str] = None, due_after: Optional[str] = None,
    sort: str = "due_date", order: str = "asc"
):
    db = get_db()
    auto_update_overdue(db)
    query = """SELECT t.*, c.name as category_name, c.color as category_color, c.icon as category_icon,
               s.name as subject_name, s.color as subject_color, u.name as unit_name
               FROM tasks t
               LEFT JOIN categories c ON t.category_id = c.id
               LEFT JOIN subjects s ON t.subject_id = s.id
               LEFT JOIN units u ON t.unit_id = u.id
               WHERE 1=1"""
    params = []
    if status:
        for st in status.split(","): query += " AND t.status=?"; params.append(st)
    if category: query += " AND t.category_id=?"; params.append(category)
    if subject: query += " AND t.subject_id=?"; params.append(subject)
    if unit: query += " AND t.unit_id=?"; params.append(unit)
    if priority: query += " AND t.priority=?"; params.append(priority)
    if search: query += " AND (t.title LIKE ? OR t.description LIKE ?)"; params.extend([f"%{search}%", f"%{search}%"])
    if due_before: query += " AND t.due_date <= ?"; params.append(due_before)
    if due_after: query += " AND t.due_date >= ?"; params.append(due_after)
    if sort == "priority": query += " ORDER BY CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END"
    elif sort in {"due_date","created_at","title","progress","status"}: query += f" ORDER BY t.{sort} {'ASC' if order=='asc' else 'DESC'}"
    else: query += " ORDER BY t.due_date ASC"
    rows = db.execute(query, params).fetchall()
    db.close()
    return [task_row(r) for r in rows]

@app.get("/api/tasks/{task_id}")
def get_task(task_id: int):
    db = get_db()
    row = db.execute("""SELECT t.*, c.name as category_name, c.color as category_color, c.icon as category_icon,
                        s.name as subject_name, s.color as subject_color, u.name as unit_name
                        FROM tasks t LEFT JOIN categories c ON t.category_id=c.id
                        LEFT JOIN subjects s ON t.subject_id=s.id LEFT JOIN units u ON t.unit_id=u.id WHERE t.id=?""", (task_id,)).fetchone()
    db.close()
    if not row: raise HTTPException(404, "Task not found")
    return task_row(row)

@app.post("/api/tasks")
def create_task(task: TaskCreate):
    db = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cur = db.execute("""INSERT INTO tasks (title,description,due_date,planned_start_date,planned_end_date,
        priority,status,category_id,subject_id,unit_id,target_grade,progress,estimated_hours,actual_hours,notes,is_recurring,recurrence_pattern,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (task.title,task.description,task.due_date,task.planned_start_date,task.planned_end_date,
         task.priority,task.status,task.category_id,task.subject_id,task.unit_id,task.target_grade,
         task.progress,task.estimated_hours,task.actual_hours,task.notes,int(task.is_recurring),task.recurrence_pattern,now,now))
    db.commit()
    row = db.execute("""SELECT t.*, c.name as category_name, c.color as category_color, c.icon as category_icon,
                        s.name as subject_name, s.color as subject_color, u.name as unit_name
                        FROM tasks t LEFT JOIN categories c ON t.category_id=c.id
                        LEFT JOIN subjects s ON t.subject_id=s.id LEFT JOIN units u ON t.unit_id=u.id WHERE t.id=?""", (cur.lastrowid,)).fetchone()
    db.close()
    return task_row(row)

@app.put("/api/tasks/{task_id}")
def update_task(task_id: int, task: TaskUpdate):
    db = get_db()
    if not db.execute("SELECT id FROM tasks WHERE id=?", (task_id,)).fetchone():
        db.close(); raise HTTPException(404, "Task not found")
    updates = {}
    for f, v in task.model_dump(exclude_unset=True).items():
        updates[f] = int(v) if f == "is_recurring" else v
    if updates:
        updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        db.execute(f"UPDATE tasks SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?", list(updates.values()) + [task_id])
        db.commit()
    row = db.execute("""SELECT t.*, c.name as category_name, c.color as category_color, c.icon as category_icon,
                        s.name as subject_name, s.color as subject_color, u.name as unit_name
                        FROM tasks t LEFT JOIN categories c ON t.category_id=c.id
                        LEFT JOIN subjects s ON t.subject_id=s.id LEFT JOIN units u ON t.unit_id=u.id WHERE t.id=?""", (task_id,)).fetchone()
    db.close()
    return task_row(row)

@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int):
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    db.commit(); db.close()
    return {"ok": True}

@app.post("/api/tasks/{task_id}/auto-plan")
def auto_plan(task_id: int):
    db = get_db()
    row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row: db.close(); raise HTTPException(404, "Task not found")
    task = dict(row)
    due = task.get("due_date")
    hrs = task.get("estimated_hours") or 4
    if not due: db.close(); return {"plan":[],"message":"Set a due date first."}
    due_dt = datetime.strptime(due,"%Y-%m-%d").date()
    days = (due_dt - date.today()).days
    if days <= 0: db.close(); return {"plan":[],"message":"Due date is today or past — start immediately!"}
    sessions = max(1, int(hrs/3))
    sd = min(sessions, days)
    plan = []
    if sd <= 1:
        plan = [{"date":due,"hours":round(hrs,1),"milestone":f"Complete: {task['title']}"}]
    else:
        interval = max(1, days//sd)
        for i in range(sd):
            plan.append({"date":(date.today()+timedelta(days=i*interval)).isoformat(),"hours":round(hrs/sd,1),"milestone":f"Session {i+1}/{sd} — {int((i+1)/sd*100)}% complete"})
    db.execute("UPDATE tasks SET planned_start_date=?,planned_end_date=?,updated_at=datetime('now','localtime') WHERE id=?",(plan[0]["date"],plan[-1]["date"],task_id))
    db.commit(); db.close()
    return {"plan":plan,"planned_start_date":plan[0]["date"],"planned_end_date":plan[-1]["date"],"message":f"Plan: {sd} session(s) across {days} days"}

# ═══════════════════════════════════════════════════════════════════════════
# CATEGORIES
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/categories")
def list_categories():
    db = get_db()
    rows = db.execute("SELECT * FROM categories ORDER BY id").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/categories")
def create_category(cat: CategoryCreate):
    db = get_db()
    try:
        cur = db.execute("INSERT INTO categories (name,color,icon) VALUES (?,?,?)",(cat.name,cat.color,cat.icon))
        db.commit()
        row = db.execute("SELECT * FROM categories WHERE id=?",(cur.lastrowid,)).fetchone()
        db.close(); return dict(row)
    except sqlite3.IntegrityError: db.close(); raise HTTPException(400,"Name exists")

@app.delete("/api/categories/{cat_id}")
def delete_category(cat_id: int):
    db = get_db()
    db.execute("DELETE FROM categories WHERE id=?",(cat_id,))
    db.commit(); db.close()
    return {"ok":True}

# ═══════════════════════════════════════════════════════════════════════════
# JOB APPLICATIONS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/jobs")
def list_jobs(status: Optional[str] = None, priority: Optional[str] = None, search: Optional[str] = None):
    db = get_db()
    q = "SELECT * FROM job_applications WHERE 1=1"
    p = []
    if status:
        for s in status.split(","): q += " AND status=?"; p.append(s)
    if priority: q += " AND priority=?"; p.append(priority)
    if search: q += " AND (company LIKE ? OR role LIKE ?)"; p.extend([f"%{search}%",f"%{search}%"])
    q += " ORDER BY CASE status WHEN 'interviewing' THEN 0 WHEN 'phone_screen' THEN 1 WHEN 'applied' THEN 2 WHEN 'offer' THEN 3 WHEN 'accepted' THEN 4 WHEN 'rejected' THEN 5 WHEN 'withdrawn' THEN 6 END, updated_at DESC"
    rows = db.execute(q, p).fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.get("/api/jobs/stats")
def job_stats():
    db = get_db()
    counts = {}
    for s in ['applied','phone_screen','interviewing','offer','accepted','rejected','withdrawn']:
        counts[s] = db.execute("SELECT COUNT(*) FROM job_applications WHERE status=?",(s,)).fetchone()[0]
    total = sum(counts.values())
    db.close()
    return {"total": total, "by_status": counts}

@app.post("/api/jobs")
def create_job(job: JobCreate):
    db = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cur = db.execute("""INSERT INTO job_applications (company,role,status,applied_date,follow_up_date,notes,url,salary_range,contact_name,contact_email,priority,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (job.company,job.role,job.status,job.applied_date,job.follow_up_date,job.notes,job.url,job.salary_range,job.contact_name,job.contact_email,job.priority,now,now))
    db.commit()
    row = db.execute("SELECT * FROM job_applications WHERE id=?",(cur.lastrowid,)).fetchone()
    db.close()
    return dict(row)

@app.put("/api/jobs/{job_id}")
def update_job(job_id: int, job: JobUpdate):
    db = get_db()
    if not db.execute("SELECT id FROM job_applications WHERE id=?",(job_id,)).fetchone():
        db.close(); raise HTTPException(404,"Not found")
    updates = {k:v for k,v in job.model_dump(exclude_unset=True).items()}
    if updates:
        updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        db.execute(f"UPDATE job_applications SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?", list(updates.values())+[job_id])
        db.commit()
    row = db.execute("SELECT * FROM job_applications WHERE id=?",(job_id,)).fetchone()
    db.close()
    return dict(row)

@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int):
    db = get_db()
    db.execute("DELETE FROM job_applications WHERE id=?",(job_id,))
    db.commit(); db.close()
    return {"ok":True}

# ═══════════════════════════════════════════════════════════════════════════
# FINANCE — TRANSACTIONS & BUDGETS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/transactions")
def list_transactions(month: Optional[str] = None, category: Optional[str] = None, type: Optional[str] = None):
    db = get_db()
    q = "SELECT * FROM transactions WHERE 1=1"
    p = []
    if month:
        q += " AND strftime('%Y-%m', date) = ?"; p.append(month)
    else:
        q += " AND strftime('%Y-%m', date) = ?"; p.append(date.today().strftime("%Y-%m"))
    if category: q += " AND category=?"; p.append(category)
    if type: q += " AND type=?"; p.append(type)
    q += " ORDER BY date DESC, id DESC"
    rows = db.execute(q, p).fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/transactions")
def create_transaction(tx: TransactionCreate):
    db = get_db()
    cur = db.execute("INSERT INTO transactions (type,amount,category,description,date,recurring) VALUES (?,?,?,?,?,?)",
        (tx.type,tx.amount,tx.category,tx.description,tx.date,int(tx.recurring)))
    db.commit()
    row = db.execute("SELECT * FROM transactions WHERE id=?",(cur.lastrowid,)).fetchone()
    db.close()
    return dict(row)

@app.delete("/api/transactions/{tx_id}")
def delete_transaction(tx_id: int):
    db = get_db()
    db.execute("DELETE FROM transactions WHERE id=?",(tx_id,))
    db.commit(); db.close()
    return {"ok":True}

@app.get("/api/budgets")
def list_budgets():
    db = get_db()
    month = date.today().strftime("%Y-%m")
    rows = db.execute("""SELECT b.*, COALESCE(SUM(t.amount),0) as spent
        FROM budgets b LEFT JOIN transactions t ON t.category=b.category AND t.type='expense' AND strftime('%Y-%m',t.date)=?
        GROUP BY b.id ORDER BY b.id""", (month,)).fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/budgets")
def create_budget(b: BudgetCreate):
    db = get_db()
    try:
        cur = db.execute("INSERT INTO budgets (category,monthly_limit,icon,color) VALUES (?,?,?,?)",(b.category,b.monthly_limit,b.icon,b.color))
        db.commit()
        row = db.execute("SELECT * FROM budgets WHERE id=?",(cur.lastrowid,)).fetchone()
        db.close(); return dict(row)
    except sqlite3.IntegrityError: db.close(); raise HTTPException(400,"Budget category exists")

@app.put("/api/budgets/{budget_id}")
def update_budget(budget_id: int, b: BudgetCreate):
    db = get_db()
    db.execute("UPDATE budgets SET category=?,monthly_limit=?,icon=?,color=? WHERE id=?",(b.category,b.monthly_limit,b.icon,b.color,budget_id))
    db.commit()
    row = db.execute("SELECT * FROM budgets WHERE id=?",(budget_id,)).fetchone()
    db.close()
    return dict(row) if row else None

@app.delete("/api/budgets/{budget_id}")
def delete_budget(budget_id: int):
    db = get_db()
    db.execute("DELETE FROM budgets WHERE id=?",(budget_id,))
    db.commit(); db.close()
    return {"ok":True}

@app.get("/api/finance/stats")
def finance_stats(month: Optional[str] = None):
    if not month: month = date.today().strftime("%Y-%m")
    db = get_db()
    income = db.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='income' AND strftime('%Y-%m',date)=?",(month,)).fetchone()[0]
    expenses = db.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='expense' AND strftime('%Y-%m',date)=?",(month,)).fetchone()[0]
    by_cat = db.execute("SELECT category, SUM(amount) as total FROM transactions WHERE type='expense' AND strftime('%Y-%m',date)=? GROUP BY category ORDER BY total DESC",(month,)).fetchall()
    budget_total = db.execute("SELECT COALESCE(SUM(monthly_limit),0) FROM budgets").fetchone()[0]
    db.close()
    return {"income":income,"expenses":expenses,"balance":income-expenses,"budget_total":budget_total,
            "by_category":[dict(r) for r in by_cat]}

# ═══════════════════════════════════════════════════════════════════════════
# STATS (extended)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/stats")
def get_stats():
    db = get_db()
    auto_update_overdue(db)
    today = date.today().isoformat()
    wl = (date.today()+timedelta(days=7)).isoformat()
    total = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    completed = db.execute("SELECT COUNT(*) FROM tasks WHERE status='completed'").fetchone()[0]
    ip = db.execute("SELECT COUNT(*) FROM tasks WHERE status='in_progress'").fetchone()[0]
    ov = db.execute("SELECT COUNT(*) FROM tasks WHERE status='overdue'").fetchone()[0]
    ns = db.execute("SELECT COUNT(*) FROM tasks WHERE status='not_started'").fetchone()[0]
    dt = db.execute("SELECT COUNT(*) FROM tasks WHERE due_date=? AND status!='completed'",(today,)).fetchone()[0]
    dw = db.execute("SELECT COUNT(*) FROM tasks WHERE due_date BETWEEN ? AND ? AND status!='completed'",(today,wl)).fetchone()[0]
    cr = round((completed/total*100),1) if total else 0
    cb = db.execute("SELECT c.name,c.color,COUNT(t.id) as count FROM categories c LEFT JOIN tasks t ON t.category_id=c.id GROUP BY c.id ORDER BY count DESC").fetchall()
    pb = db.execute("SELECT priority,COUNT(*) as count FROM tasks WHERE status!='completed' GROUP BY priority").fetchall()
    # Subject breakdown
    sb = db.execute("SELECT s.name,s.color,COUNT(t.id) as count FROM subjects s LEFT JOIN tasks t ON t.subject_id=s.id GROUP BY s.id ORDER BY count DESC").fetchall()
    # Grade distribution
    gd = db.execute("SELECT target_grade,COUNT(*) as count FROM tasks WHERE target_grade!='' AND status!='completed' GROUP BY target_grade").fetchall()
    db.close()
    return {"total":total,"completed":completed,"in_progress":ip,"overdue":ov,"not_started":ns,
            "due_today":dt,"due_this_week":dw,"completion_rate":cr,
            "category_breakdown":[dict(r) for r in cb],"priority_breakdown":[dict(r) for r in pb],
            "subject_breakdown":[dict(r) for r in sb],"grade_distribution":[dict(r) for r in gd]}

# ═══════════════════════════════════════════════════════════════════════════
# SERVE FRONTEND + PWA
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")

@app.get("/manifest.json")
def manifest():
    return {
        "name": "LifePlanner",
        "short_name": "LifePlanner",
        "description": "Student planner, job tracker & finance manager",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f1117",
        "theme_color": "#6366f1",
        "icons": [{"src":"/static/icon-192.png","sizes":"192x192","type":"image/png"},
                  {"src":"/static/icon-512.png","sizes":"512x512","type":"image/png"}]
    }

app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print(f"\n  📚 LifePlanner v2 — http://localhost:8585\n")
    uvicorn.run(app, host="0.0.0.0", port=8585, log_level="info")
