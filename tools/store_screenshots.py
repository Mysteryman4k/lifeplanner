#!/usr/bin/env python3
"""Screenshots for the Microsoft Store listing and the README, made from sample data.

Starts the app with a temporary data folder (never your real data), fills it with a sample
student's week and saves PNGs to docs/screenshots/. Needs Playwright:
  pip install playwright && python -m playwright install chromium

  python tools/store_screenshots.py
"""
import os
import socket
import sys
import tempfile
import threading
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
WIDTH, HEIGHT = 1366, 768            # the Store's minimum desktop size, captured at 1.5x for sharpness
SCALE = 1.5

os.environ["TRACKADEMIC_DATA_DIR"] = tempfile.mkdtemp(prefix="easyunitrack-screenshots-")
sys.path.insert(0, str(ROOT))


def d(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def seed(api):
    """A plausible second-year student: four units, assignments, a part-time job hunt and a budget."""
    subjects = {}
    for name, color, units in [
        ("Data Structures", "#6d28d9", ["Week 9: Graphs", "Week 10: Hashing"]),
        ("Marketing Principles", "#b45309", ["Week 9: Pricing", "Week 10: Promotion"]),
        ("Statistics for Business", "#047857", ["Week 9: Regression"]),
        ("Professional Practice", "#0e7490", ["Week 9: Teamwork"]),
    ]:
        s = api("post", "/api/subjects", {"name": name, "color": color})
        subjects[name] = s["id"]
        for u in units:
            api("post", f"/api/subjects/{s['id']}/units", {"name": u})

    a, e, p, r = 1, 2, 3, 4                   # task types: Assignment, Exam, Project, Reading
    for title, sub, cat, due, prio, extra in [
        ("Graph algorithms lab report", "Data Structures", a, -1, "high", {"progress": 60}),
        ("Pricing strategy case study", "Marketing Principles", a, 0, "urgent", {"estimated_hours": 6}),
        ("Read chapter 7: Hash tables", "Data Structures", r, 1, "medium",
         {"is_recurring": True, "recurrence_pattern": "weekly"}),
        ("Regression quiz", "Statistics for Business", e, 2, "high", {}),
        ("Team charter draft", "Professional Practice", p, 3, "medium", {"progress": 30}),
        ("Tutorial prep: Promotion mix", "Marketing Principles", r, 4, "low",
         {"is_recurring": True, "recurrence_pattern": "weekly"}),
        ("Statistics assignment 2", "Statistics for Business", a, 6, "high", {"estimated_hours": 10}),
        ("Portfolio reflection", "Professional Practice", a, 9, "medium", {}),
        ("Hashing practice problems", "Data Structures", p, 12, "low", {}),
        ("Mid-semester exam revision", "Marketing Principles", e, 16, "high", {"estimated_hours": 8}),
        ("Group presentation", "Professional Practice", p, 20, "medium", {}),
    ]:
        api("post", "/api/tasks", {"title": title, "subject_id": subjects[sub], "category_id": cat,
                                   "due_date": d(due), "priority": prio, **extra})
    done = api("post", "/api/tasks", {"title": "Week 8 reading quiz", "subject_id": subjects["Statistics for Business"],
                                      "category_id": e, "due_date": d(-3), "priority": "medium"})
    api("put", f"/api/tasks/{done['id']}", {"status": "completed"})

    for company, role, status, applied, follow in [
        ("Atlassian", "Graduate Software Engineer", "interviewing", -18, 2),
        ("Canva", "Marketing Intern", "phone_screen", -10, 1),
        ("Woolworths Group", "Data Analyst Intern", "applied", -5, 5),
        ("Deloitte", "Summer Vacationer", "applied", -3, 9),
        ("Local café", "Part-time Barista", "offer", -21, None),
    ]:
        api("post", "/api/jobs", {"company": company, "role": role, "status": status,
                                  "applied_date": d(applied), "follow_up_date": d(follow) if follow is not None else None})

    api("put", "/api/settings/money", {"currency": "AUD"})
    api("put", "/api/budget-plan", {"items": [
        {"category": "Rent", "monthly_limit": 1400}, {"category": "Groceries", "monthly_limit": 400},
        {"category": "Transport", "monthly_limit": 120}, {"category": "Eating out", "monthly_limit": 150},
        {"category": "Phone and internet", "monthly_limit": 70}]})
    first = date.today().replace(day=1)
    for kind, amount, category, desc, day in [
        ("income", 1180, "Part-time work", "Café shifts", 1), ("income", 650, "Youth Allowance", "Fortnightly payment", 3),
        ("expense", 1400, "Rent", "Share house", 1), ("expense", 86.40, "Groceries", "Weekly shop", 2),
        ("expense", 64.10, "Groceries", "Weekly shop", 9), ("expense", 50, "Transport", "Myki top-up", 4),
        ("expense", 38.50, "Eating out", "Dinner with friends", 6), ("expense", 65, "Phone and internet", "Phone plan", 7),
        ("expense", 22.90, "Eating out", "Lunch on campus", 10),
    ]:
        when = min(first + timedelta(days=day - 1), date.today())
        api("post", "/api/transactions", {"type": kind, "amount": amount, "category": category,
                                          "description": desc, "date": when.isoformat()})
    api("put", "/api/settings/startup", {"intro": False})


def main():
    import httpx
    import uvicorn
    from playwright.sync_api import sync_playwright

    import app as A
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(A.app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"

    def api(method, path, body=None):
        r = httpx.request(method.upper(), base + path, json=body, timeout=10)
        r.raise_for_status()
        return r.json()

    seed(api)
    OUT.mkdir(parents=True, exist_ok=True)
    shots = [("1-today", "today", "light"), ("2-tasks", "tasks", "light"), ("3-calendar", "calendar", "light"),
             ("4-jobs", "jobs", "light"), ("5-money", "money", "light"), ("6-dark", "today", "dark")]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, route, mode in shots:
            api("put", "/api/settings/appearance", {"theme": "sunset", "font": "rounded", "mode": mode})
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=SCALE,
                                    color_scheme=mode, timezone_id="Australia/Melbourne")
            page.goto(f"{base}/#/{route}")
            page.wait_for_selector("#content > *")
            page.wait_for_timeout(1200)                       # let charts and fades finish
            page.screenshot(path=str(OUT / f"{name}.png"))
            page.close()
            print(f"saved docs/screenshots/{name}.png")
        browser.close()
    server.should_exit = True


if __name__ == "__main__":
    main()
