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


STUDY_REPLY = r"""## Dijkstra's algorithm

Dijkstra finds the shortest path from one start vertex to every other vertex, as long as no edge weight is negative.

**The idea:** keep a tentative distance for each vertex, settle the closest unsettled vertex next, and *relax* its edges:

$$d(v) \leftarrow \min\big(d(v),\; d(u) + w(u, v)\big)$$

```mermaid
flowchart LR
  A["A (0)"] -- 4 --> B["B (3)"]
  A -- 1 --> C["C (1)"]
  C -- 2 --> B
  B -- 5 --> D["D (8)"]
  C -- 8 --> D
```

{walk}

With a binary heap it runs in $O((V + E)\log V)$.

**Quick check:** if the edge C to B had weight 5 instead, what would B's shortest distance be?""".format(
    walk="Starting at **A**: C is closest (1), so it's settled first. Through C, B costs $1 + 2 = 3$, which beats 4. "
         "Then B is settled, and D costs $3 + 5 = 8$.")

CODE_FILE = """def shortest_paths(graph, start):
    \"\"\"Dijkstra: the shortest distance from start to every vertex.\"\"\"
    import heapq
    dist = {start: 0}
    queue = [(0, start)]
    done = set()
    while queue:
        d, node = heapq.heappop(queue)
        if node in done:
            continue
        done.add(node)
        for neighbour, weight in graph[node]:
            if d + weight < dist.get(neighbour, float("inf")):
                dist[neighbour] = d + weight
                heapq.heappush(queue, (dist[neighbour], neighbour))
    return dist


graph = {"A": [("B", 4), ("C", 1)], "B": [("D", 5)], "C": [("B", 2), ("D", 8)], "D": [("E", 2)]}
print(shortest_paths(graph, "A"))
"""

CODE_ERROR = """Traceback (most recent call last):
  File "dijkstra.py", line 20, in <module>
    print(shortest_paths(graph, "A"))
  File "dijkstra.py", line 12, in shortest_paths
    for neighbour, weight in graph[node]:
KeyError: 'E'"""

CODE_REPLY = "\n\n".join([
    "**What it means:** `KeyError: 'E'` says the program looked up `'E'` in the `graph` dictionary, and there's no "
    "key `'E'`.",
    "**Where:** `dijkstra.py`, line 12: `for neighbour, weight in graph[node]:`",
    "**Why there:** `E` only appears as a neighbour of `D` (line 19), so it never got its own entry. When `E` comes off "
    "the queue, looking up its edges fails.",
    "**A question to guide you:** what should `graph[node]` give for a vertex with no outgoing edges, and how could you "
    "get that without an error? Look at what `dict.get` does with a second argument.",
])


def seed_ai(api, folder: Path):
    """The optional AI features, with sample chats (no AI provider is contacted: the replies are written here)."""
    terms = api("get", "/api/ai/terms")
    api("post", "/api/ai/terms/agree", {"version": terms["version"], "ticks": {k: True for k in terms["ticks"]}})
    api("put", "/api/ai/settings", {"provider": "ollama", "model": "qwen2.5:7b", "code_enabled": True})
    study = api("post", "/api/ai/chats", {"mode": "explain", "tokens": 1840, "messages": [
        {"role": "user", "content": "Can you explain Dijkstra's algorithm with a small example?"},
        {"role": "assistant", "content": STUDY_REPLY}]})
    (folder / "dijkstra.py").write_text(CODE_FILE, encoding="utf-8")
    (folder / "README.md").write_text("# Lab 9: shortest paths\n", encoding="utf-8")
    subjects = {s["name"]: s["id"] for s in api("get", "/api/subjects")}
    linked = api("post", "/api/code/folders", {"path": str(folder), "mode": "assignment",
                                               "subject_id": subjects.get("Data Structures")})
    code = api("post", "/api/ai/chats", {"kind": "code", "mode": "code", "folder_id": linked["id"], "tokens": 2310,
                                         "messages": [{"role": "user", "content": CODE_ERROR,
                                                       "meta": {"files": ["dijkstra.py"]}},
                                                      {"role": "assistant", "content": CODE_REPLY}]})
    return study["id"], code["id"]


def main():
    import httpx
    import uvicorn
    from playwright.sync_api import sync_playwright

    import app as A
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(A.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started:
        if not thread.is_alive():
            sys.exit("The app's server stopped during start-up (see the error above).")
        if time.time() > deadline:
            sys.exit("The app's server didn't start within 30 seconds.")
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
            api("put", "/api/settings/appearance", {"theme": "plain", "font": "system", "mode": mode})
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=SCALE,
                                    color_scheme=mode, timezone_id="Australia/Melbourne")
            page.goto(f"{base}/#/{route}")
            page.wait_for_selector("#content > *")
            page.wait_for_timeout(1200)                       # let charts and fades finish
            page.screenshot(path=str(OUT / f"{name}.png"))
            page.close()
            print(f"saved docs/screenshots/{name}.png")
        # The AI features are off by default, so they're only set up for their own screenshots
        lab = Path(tempfile.mkdtemp(prefix="easyunitrack-screenshots-")) / "graph-lab"
        lab.mkdir()
        study_chat, code_chat = seed_ai(api, lab)
        api("put", "/api/settings/appearance", {"theme": "plain", "font": "system", "mode": "light"})
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=SCALE,
                                color_scheme="light", timezone_id="Australia/Melbourne")
        page.goto(f"{base}/#/study")
        page.wait_for_selector("#content .chat")
        page.evaluate(f"chatOpen({study_chat})")
        page.wait_for_selector(".chat-msg.ai .katex")
        page.wait_for_selector(".chat-diagram .diagram-svg svg", timeout=30000)   # drawn after the reply
        page.evaluate("document.querySelector('#chatLog').scrollTop = 0")
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "7-study.png"))
        print("saved docs/screenshots/7-study.png")
        page.goto(f"{base}/#/code")
        page.wait_for_selector(".code-tree .tree-row >> text=dijkstra.py")
        page.evaluate(f"chatOpen({code_chat})")
        page.wait_for_selector(".chat-msg.ai >> text=A question to guide you")
        page.evaluate("codeOpen('dijkstra.py').then(() => { codeMarkErrors(chatState().messages[0].content); codeRender(); })")
        page.wait_for_selector(".code-mark")
        page.evaluate("document.querySelector('#chatLog').scrollTop = 0")   # the error, then the start of the reply
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "8-code.png"))
        print("saved docs/screenshots/8-code.png")
        page.close()
        browser.close()
    server.should_exit = True


if __name__ == "__main__":
    main()
