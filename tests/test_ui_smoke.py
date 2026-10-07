"""Browser smoke test: every screen loads without errors and the main flows work.

Runs in CI. Locally it needs:  pip install playwright && python -m playwright install chromium
"""
import importlib
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.ui
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import uvicorn
    os.environ["TRACKADEMIC_DATA_DIR"] = str(tmp_path_factory.mktemp("data"))
    import app as A
    importlib.reload(A)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(A.app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True


@pytest.fixture(scope="module")
def page(server):
    with sync_api.sync_playwright() as p:
        executable = os.environ.get("CHROMIUM_PATH")             # optional: use a preinstalled Chromium
        try:
            browser = p.chromium.launch(executable_path=executable) if executable else p.chromium.launch()
        except Exception as e:
            pytest.skip(f"Chromium isn't available: {e}")
        ctx = browser.new_context(timezone_id="Australia/Melbourne", viewport={"width": 1280, "height": 800})
        pg = ctx.new_page()
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" else None)
        yield pg
        browser.close()


@pytest.mark.parametrize("route", ["today", "tasks", "calendar", "subjects", "jobs", "money", "settings"])
def test_screen_loads(server, page, route):
    page.goto(f"{server}/#/{route}")
    page.wait_for_selector("#content > *")
    assert page.inner_text("#pageTitle").strip()
    assert page.errors == [], page.errors


def test_add_and_complete_task(server, page):
    page.goto(f"{server}/#/tasks")
    page.click("[data-action=new-task] >> nth=0")
    page.fill("[name=title]", "<b>Smoke</b> test task")
    page.click("#drawerFoot [type=submit]")
    page.wait_for_selector("text=<b>Smoke</b> test task")          # shown as text, not HTML
    page.click(".task .check >> nth=0")
    page.wait_for_function("document.querySelectorAll('.task').length === 0")
    assert page.errors == [], page.errors


def test_change_theme_is_saved(server, page):
    page.goto(f"{server}/#/settings")
    page.click("[data-action=set-appearance][data-key=theme][data-value=ocean]")
    page.wait_for_function("document.documentElement.dataset.theme === 'ocean'")
    page.reload()
    page.wait_for_function("document.documentElement.dataset.theme === 'ocean'")
    assert page.errors == [], page.errors


def test_splash_hand_off_fades_into_the_app(server, page):
    """Launched from the desktop splash: the overlay shows in the passed-in theme, then gets out of the way."""
    import json
    from urllib.parse import urlencode
    ap = {"theme": "berry", "font": "techy", "mode": "dark"}
    # In the real app the splash passes the saved look, so save it first to match
    assert page.request.put(f"{server}/api/settings/appearance", data=ap).ok
    page.goto(f"{server}/?{urlencode({'from': 'splash', 't': 2700, 'ap': json.dumps(ap)})}#/today")
    assert page.evaluate("document.documentElement.dataset.theme") == "berry"     # right look on the first frame
    page.wait_for_selector("#intro", state="hidden", timeout=5000)
    assert "from=splash" not in page.url
    assert page.errors == [], page.errors


def test_budget_setup_and_currency(server, page):
    """No made-up budget: Money starts with a set-up prompt; amounts use the chosen currency."""
    page.goto(f"{server}/#/money")
    page.wait_for_selector(".onboard")
    page.click(".onboard [data-action=budget-plan]")
    page.select_option("#planCurrency", "EUR")
    page.fill('[data-category="Rent"] input', "900")
    page.fill('[data-category="Groceries"] input', "250")
    assert "1,150" in page.inner_text("#planTotal") and "€" in page.inner_text("#planTotal")
    page.click("#drawerFoot [type=submit]")
    page.wait_for_selector(".budget")
    assert page.locator(".onboard").count() == 0
    text = page.inner_text("#content")
    assert "€900" in text.replace("\u00a0", "") or "900" in text
    assert "EUR" in page.inner_text("#eyebrow")
    page.goto(f"{server}/#/today")
    page.wait_for_selector(".tile")
    assert "€" in page.inner_text(".tiles")
    assert page.errors == [], page.errors


def test_repeating_task_adds_the_next_one(server, page):
    page.goto(f"{server}/#/tasks")
    page.click("[data-action=new-task] >> nth=0")
    page.fill("[name=title]", "Weekly reading")
    page.fill("[name=due_date]", time.strftime("%Y-%m-%d"))
    page.select_option("[name=recurrence_pattern]", "weekly")
    page.click("#drawerFoot [type=submit]")
    row = page.locator(".task", has_text="Weekly reading")
    row.locator(".repeats").wait_for()
    row.locator(".check").click()
    page.wait_for_selector("#toast.show >> text=Next one added")
    page.wait_for_function("[...document.querySelectorAll('.task')]"
                           ".filter(t => t.textContent.includes('Weekly reading')).length === 1")
    assert page.errors == [], page.errors


def test_task_types_can_be_added_and_renamed(server, page):
    page.goto(f"{server}/#/settings")
    page.click("[data-action=new-type]")
    page.fill("#drawerForm [name=name]", "Lab report")
    page.click("#drawerForm .swatch >> nth=3")
    page.click("#drawerFoot [type=submit]")
    page.wait_for_selector(".type-row >> text=Lab report")
    page.click(".type-row:has-text('Lab report') [data-action=edit-type]")
    page.fill("#drawerForm [name=name]", "Lab write-up")
    page.click("#drawerFoot [type=submit]")
    page.wait_for_selector(".type-row >> text=Lab write-up")
    page.goto(f"{server}/#/tasks")
    page.click("[data-action=new-task] >> nth=0")
    assert "Lab write-up" in page.inner_text("[name=category_id]")
    page.keyboard.press("Escape")
    assert page.errors == [], page.errors


def test_reminder_and_startup_settings(server, page):
    page.goto(f"{server}/#/settings")
    page.wait_for_selector("#reminderTime")
    page.fill("#reminderTime", "18:45")
    page.dispatch_event("#reminderTime", "change")
    page.wait_for_selector("#toast.show >> text=18:45")
    assert page.locator("[data-action=toggle-autostart]").is_disabled()    # not the installed Windows app
    page.click("[data-action=toggle-reminders]")
    page.wait_for_selector("#reminderTime", state="detached")
    page.click("[data-action=toggle-reminders]")
    page.wait_for_selector("#reminderTime")
    assert page.input_value("#reminderTime") == "18:45"
    assert page.errors == [], page.errors


def test_restore_from_backup(server, page, tmp_path):
    import json
    import urllib.request
    backup = json.load(urllib.request.urlopen(f"{server}/api/export"))
    backup["tasks"] = [{"id": 1, "title": "Restored task", "priority": "medium", "status": "not_started", "progress": 0}]
    f = tmp_path / "backup.json"
    f.write_text(json.dumps(backup))
    page.goto(f"{server}/#/settings")
    page.set_input_files("#importFile", str(f))
    page.wait_for_selector("#confirm:not([hidden])")
    assert "1 task" in page.inner_text("#confirmText")
    page.click("#confirmYes")
    page.wait_for_selector("#toast.show >> text=Backup restored")
    page.goto(f"{server}/#/tasks")
    page.wait_for_selector(".task >> text=Restored task")
    assert page.locator(".task").count() == 1
    assert page.errors == [], page.errors
