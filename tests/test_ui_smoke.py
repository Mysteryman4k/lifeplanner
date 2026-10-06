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
