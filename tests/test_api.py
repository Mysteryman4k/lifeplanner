"""API tests — run with:  pytest -q"""
import datetime as dt
import importlib
import os
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKADEMIC_DATA_DIR", str(tmp_path))
    import app as A
    importlib.reload(A)
    return TestClient(A.app)


def d(n):
    return (dt.date.today() + dt.timedelta(days=n)).isoformat()


def test_full_flow(c):

    s = c.post("/api/subjects", json={"name":"SIT313"}).json()
    assert s["units"] == [], "subject create returns units"
    u = c.post(f"/api/subjects/{s['id']}/units", json={"name":"Week 5"}).json()
    assert c.get("/api/subjects").json()[0]["units"][0]["name"] == "Week 5", "units embedded in subjects list"
    t = c.post("/api/tasks", json={"title":"Late","due_date":d(-2),"subject_id":s["id"],"unit_id":u["id"]}).json()
    assert t["is_overdue"] and t["status"]=="not_started", "overdue computed, not stored"
    t2 = c.put(f"/api/tasks/{t['id']}", json={"due_date":d(5)}).json()
    assert not t2["is_overdue"], "moving due date clears overdue"
    c.put(f"/api/tasks/{t['id']}", json={"due_date":d(-1)})
    c.post("/api/tasks", json={"title":"Fresh","due_date":d(3)})
    r = c.get("/api/tasks", params={"status":"not_started,in_progress"}).json()
    assert len(r)==2, f"multi-status filter returns 2 (got {len(r)})"
    assert len(c.get("/api/tasks", params={"status":"overdue"}).json())==1, "legacy overdue filter"
    assert c.post("/api/tasks", json={"title":"x","priority":"mega"}).status_code==422, "bad priority rejected 422"
    assert c.post("/api/tasks", json={"title":"x","due_date":"tomorrow"}).status_code==422, "bad date rejected"
    assert c.post("/api/tasks", json={"title":""}).status_code==422, "empty title rejected"
    p = c.put(f"/api/tasks/{t['id']}", json={"progress":40}).json()
    assert p["status"]=="in_progress", "progress moves status to in_progress"
    p = c.put(f"/api/tasks/{t['id']}", json={"status":"completed"}).json()
    assert p["progress"]==100 and not p["is_overdue"], "complete sets 100% and clears overdue"
    st = c.get("/api/stats").json()
    assert st["completed"]==1 and st["total"]==2, "stats grouped query"
    bad_tx = {"type": "expense", "amount": -5, "category": "Food & Dining", "date": d(0)}
    assert c.post("/api/transactions", json=bad_tx).status_code == 422, "negative amount rejected"
    # New installs start with no budgets; set two up the way the "Set up your budget" screen does
    assert c.get("/api/budgets").json() == [], "no made-up sample budgets"
    plan = {"items": [{"category": "Transport", "monthly_limit": 150}, {"category": "Food & Dining", "monthly_limit": 400}]}
    assert c.put("/api/budget-plan", json=plan).status_code == 200
    c.post("/api/transactions", json={"type":"expense","amount":50,"category":"Transport","date":d(0)})
    b = c.get("/api/budgets").json()
    tr = [x for x in b if x["category"]=="Transport"][0]
    assert tr["spent"]==50, "budget spent"
    r = c.put(f"/api/budgets/{tr['id']}", json={"category":"Food & Dining","monthly_limit":100})
    assert r.status_code==400, f"duplicate budget name -> 400 ({r.status_code}: {r.json().get('detail')})"
    assert c.get("/api/stats").status_code==200, "no lock after failed write"
    r = c.put(f"/api/budgets/{tr['id']}", json={"category":"Travel","monthly_limit":100}).json()
    assert [x for x in c.get("/api/budgets").json() if x["category"]=="Travel"][0]["spent"]==50, "rename keeps transactions"
    fs = c.get("/api/finance/stats").json()
    assert fs["expenses"] == 50, "finance stats"
    assert c.get("/api/transactions", params={"month":"bad"}).status_code==400, "bad month 400"
    c.post("/api/jobs", json={"company":"Ford","role":"IT","follow_up_date":d(-1)}).json()
    c.post("/api/jobs", json={"company":"BIG W","role":"TM","status":"rejected","follow_up_date":d(-1)})
    assert c.get("/api/jobs/stats").json()["follow_ups_due"]==1, "follow-ups due excludes closed"
    assert c.get("/api/jobs", params={"status":"applied,rejected"}).json().__len__()==2, "jobs multi status"
    assert c.put("/api/jobs/999", json={"role":"x"}).status_code==404, "404 on missing job"
    ap = c.post(f"/api/tasks/{c.get('/api/tasks').json()[-1]['id']}/auto-plan").json()
    assert "plan" in ap, ap["message"]
    assert "tasks" in c.get("/api/export").json(), "export"
    assert c.get("/api/info").json()["data_file"].startswith(os.environ["TRACKADEMIC_DATA_DIR"]), "db in data dir"


def test_appearance_settings(c):
    assert c.get("/api/settings/appearance").json() == {"theme": "sunset", "font": "rounded", "mode": "system"}
    r = c.put("/api/settings/appearance", json={"theme": "midnight", "font": "techy", "mode": "dark"})
    assert r.status_code == 200
    assert c.get("/api/settings/appearance").json()["theme"] == "midnight"
    assert c.put("/api/settings/appearance", json={"theme": "rainbow"}).status_code == 422
    assert c.get("/api/info").json()["name"] == "Trackademic"


def test_currency_setting(c):
    m = c.get("/api/settings/money").json()
    assert m["chosen"] is False and len(m["currency"]) == 3        # a suggestion until the user picks one
    assert c.put("/api/settings/money", json={"currency": "ZAR"}).json() == {"currency": "ZAR", "chosen": True}
    assert c.get("/api/settings/money").json()["currency"] == "ZAR"
    for bad in ("zar", "RAND", "R", "12$"):
        assert c.put("/api/settings/money", json={"currency": bad}).status_code == 422, bad


def test_budget_plan_sets_updates_and_clears(c):
    r = c.put("/api/budget-plan", json={"items": [
        {"category": "Rent", "monthly_limit": 1200}, {"category": "Groceries", "monthly_limit": 320.5},
        {"category": "Fun", "monthly_limit": None}]}).json()
    assert {(b["category"], b["monthly_limit"]) for b in r} == {("Rent", 1200), ("Groceries", 320.5)}
    c.post("/api/transactions", json={"type": "expense", "amount": 80, "category": "Groceries", "date": d(0)})
    r = c.put("/api/budget-plan", json={"items": [
        {"category": "Rent", "monthly_limit": 1100}, {"category": "Groceries", "monthly_limit": 0}]}).json()
    assert [(b["category"], b["monthly_limit"]) for b in r] == [("Rent", 1100)]
    assert len(c.get("/api/transactions").json()) == 1, "clearing a budget keeps its transactions"
    assert c.put("/api/budget-plan", json={"items": [{"category": "Rent", "monthly_limit": -5}]}).status_code == 422


def _old_db_with_samples(path, with_transaction):
    import sqlite3
    db = sqlite3.connect(path / "planner.db")
    db.executescript("""
        CREATE TABLE budgets (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL UNIQUE,
            monthly_limit REAL NOT NULL, icon TEXT DEFAULT '', color TEXT DEFAULT '#6366f1');
        CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, amount REAL NOT NULL,
            category TEXT NOT NULL, description TEXT DEFAULT '', date TEXT NOT NULL,
            recurring INTEGER DEFAULT 0, created_at TEXT);
        INSERT INTO budgets (id, category, monthly_limit) VALUES (1,'Food & Dining',400),(2,'Transport',150),
            (3,'Entertainment',200),(4,'Shopping',250),(5,'Bills & Utilities',300),(6,'Education',100),(7,'Other',100);""")
    if with_transaction:
        db.execute("INSERT INTO transactions (type, amount, category, date) VALUES ('expense', 12, 'Transport', '2026-10-01')")
    db.commit()
    db.close()


@pytest.mark.parametrize("with_transaction,expected", [(False, 0), (True, 7)])
def test_old_sample_budgets_removed_only_if_untouched(tmp_path, monkeypatch, with_transaction, expected):
    _old_db_with_samples(tmp_path, with_transaction)
    monkeypatch.setenv("TRACKADEMIC_DATA_DIR", str(tmp_path))
    import app as A
    importlib.reload(A)
    assert len(TestClient(A.app).get("/api/budgets").json()) == expected
