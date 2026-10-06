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
    monkeypatch.setenv("LIFEPLANNER_DATA_DIR", str(tmp_path))
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
    assert c.post("/api/transactions", json={"type":"expense","amount":-5,"category":"Food & Dining","date":d(0)}).status_code==422, "negative amount rejected"
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
    j = c.post("/api/jobs", json={"company":"Ford","role":"IT","follow_up_date":d(-1)}).json()
    c.post("/api/jobs", json={"company":"BIG W","role":"TM","status":"rejected","follow_up_date":d(-1)})
    assert c.get("/api/jobs/stats").json()["follow_ups_due"]==1, "follow-ups due excludes closed"
    assert c.get("/api/jobs", params={"status":"applied,rejected"}).json().__len__()==2, "jobs multi status"
    assert c.put("/api/jobs/999", json={"role":"x"}).status_code==404, "404 on missing job"
    ap = c.post(f"/api/tasks/{c.get('/api/tasks').json()[-1]['id']}/auto-plan").json()
    assert "plan" in ap, ap["message"]
    assert "tasks" in c.get("/api/export").json(), "export"
    assert c.get("/api/info").json()["data_file"].startswith(os.environ["LIFEPLANNER_DATA_DIR"]), "db in data dir"
