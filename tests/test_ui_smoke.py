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
    import updater
    importlib.reload(A)
    # Every page load checks for updates. Never ask the real GitHub from tests: it's slow, rate-limited
    # on shared CI machines and made this test fail at random. Pretend the running version is the latest.
    real_fetch, real_cache = updater.fetch_latest, dict(updater._cache)
    updater.fetch_latest = lambda: {"version": A.APP_VERSION, "name": f"v{A.APP_VERSION}", "notes": "",
                                    "url": "https://github.com/Mysteryman4k/lifeplanner/releases",
                                    "published_at": "2026-01-01T00:00:00Z", "assets": {}}
    updater._cache.update({"at": 0.0, "data": None})
    A.enable_lockdown()          # test the real screens with the server protection on, as users get it
    # AI features: an in-memory key store (never the real Credential Manager) and a fake network
    import httpx
    import keyring
    from test_ai_setup import MemoryKeyring
    real_vault = keyring.get_keyring()
    A.vault = MemoryKeyring()
    keyring.set_keyring(A.vault)
    A.fake_net = {}

    A.fake_net_seen = []

    def fake_net(request):
        A.fake_net_seen.append(request)
        key = f"{request.method} {request.url.host}{request.url.path}"
        for prefix, (status, body) in A.fake_net.items():
            if key.startswith(prefix):
                if isinstance(body, list):                 # a sequence of replies, one per request
                    body = body.pop(0) if len(body) > 1 else body[0]
                return httpx.Response(status, text=body) if isinstance(body, str) else httpx.Response(status, json=body)
        raise httpx.ConnectError("offline in tests", request=request)
    A.AI_TRANSPORT["value"] = httpx.MockTransport(fake_net)
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
    A.LOCKDOWN["on"] = False
    A.AI_TRANSPORT["value"] = None
    keyring.set_keyring(real_vault)
    updater.fetch_latest = real_fetch
    updater._cache.clear()
    updater._cache.update(real_cache)


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
    # The theme shows at once and is saved just after: wait for the save, or a fast reload can beat it
    with page.expect_response(lambda r: r.url.endswith("/api/settings/appearance") and r.request.method == "PUT"):
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
    import app as A
    assert page.request.put(f"{server}/api/settings/appearance", data=ap,
                            headers={A.TOKEN_HEADER: A.SESSION_TOKEN}).ok
    page.goto(f"{server}/?{urlencode({'from': 'splash', 't': 2700, 'ap': json.dumps(ap)})}#/today")
    assert page.evaluate("document.documentElement.dataset.theme") == "berry"     # right look on the first frame
    # The overlay leaves as soon as the data has loaded, and by itself after 6.65 s at the latest.
    # Allow for slow CI machines rather than racing that safety net.
    page.wait_for_selector("#intro", state="hidden", timeout=15000)
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


def test_download_backup_gives_a_valid_backup_file(server, page):
    import json
    page.goto(f"{server}/#/settings")
    with page.expect_download() as dl:
        page.click("[data-action=export]")
    f = dl.value
    assert f.suggested_filename.endswith(".json")
    data = json.loads(Path(f.path()).read_text(encoding="utf-8"))
    assert data["app"] == "EasyUniTrack" and isinstance(data["tasks"], list)
    assert page.errors == [], page.errors


def test_window_loads_new_screens_after_an_update(server, page):
    """The 3.5.0 bug: after updating, the window kept running the old version's cached app.js.
    Simulate an update by changing the version, then check the page asks for the new files."""
    import app as A
    page.goto(f"{server}/#/today")
    page.wait_for_selector(".tile")
    real = A.APP_VERSION
    try:
        A.APP_VERSION = "99.0.0"
        page.reload()
        page.wait_for_selector(".tile")
        status = page.evaluate("fetch('/api/diag/startup').then(r => r.json())")
        assert "99.0.0" in status["app_js_versions"], status
        assert status["screens_current"] is True
    finally:
        A.APP_VERSION = real
    assert page.errors == [], page.errors


def test_server_refuses_changes_without_the_window_token(server, page):
    """The protection is really on in these tests: a request without the token (as another website or
    program would send) is refused, while the app's own screens keep working."""
    page.goto(f"{server}/#/tasks")
    page.wait_for_selector("#content > *")
    status = page.evaluate("""fetch('/api/tasks', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                                   body: JSON.stringify({title: 'Sneaky'})}).then(r => r.status)""")
    assert status == 403
    added = page.evaluate("api('/api/tasks', {method: 'POST', body: {title: 'From the app'}}).then(t => t.title)")
    assert added == "From the app"
    page.errors.clear()                                           # the refused request is logged as an error


def test_ai_is_hidden_until_turned_on_then_set_up(server, page):
    """Off by default (nothing in the sidebar), then About -> Terms (all three ticks) -> setup."""
    import app as A
    page.goto(f"{server}/#/today")
    page.wait_for_selector("#nav a")
    nav = page.inner_text("#nav").lower()
    assert "study" not in nav and "assistant" not in nav and "code" not in nav

    page.goto(f"{server}/#/settings")
    page.wait_for_selector("#aiCard [data-action=ai-start]")
    assert "preview" in page.inner_text(".settings").lower()
    page.click("#aiCard [data-action=ai-start]")
    page.wait_for_selector("#drawer:not([hidden]) .ai-about")
    assert "can be wrong" in page.inner_text("#drawerBody").lower()
    page.click("[data-action=ai-terms-next]")
    page.wait_for_selector(".terms-box")
    assert "Australian Consumer Law" in page.inner_text(".terms-box")
    agree = page.locator("#aiAgree")
    ticks = page.locator(".ai-tick")
    assert ticks.count() == 3 and agree.is_disabled()
    ticks.nth(0).check()
    ticks.nth(1).check()
    assert agree.is_disabled()                                  # all three are needed
    ticks.nth(2).check()
    assert agree.is_enabled()
    agree.click()
    page.wait_for_selector("#aiCard [data-action=toggle-ai-assistant]")
    assert page.get_attribute("[data-action=toggle-ai-assistant]", "aria-checked") == "true"
    assert page.get_attribute("[data-action=toggle-ai-code]", "aria-checked") == "false"

    # Ollama: this PC check, then models from the (fake) local Ollama
    A.fake_net.update({"GET localhost/api/version": (200, {"version": "0.40.3"}),
                       "GET localhost/api/tags": (200, {"models": [{"name": "qwen2.5:7b"}]}),
                       "POST localhost/api/show": (200, {"capabilities": ["completion", "tools"]})})
    page.click("[data-action=ai-provider][data-id=ollama]")
    page.wait_for_selector("text=Ollama 0.40.3 is running")
    page.click("[data-action=ai-test]")
    page.wait_for_selector("#aiTestResult.ai-ok")
    assert page.input_value("#aiModel") == "qwen2.5:7b"

    # OpenAI: the key goes to the (in-memory) vault and only its last 4 characters come back
    page.click("[data-action=ai-provider][data-id=openai]")
    page.fill("#aiKey", "sk-test-abcd9876")
    page.click("[data-action=ai-save-key]")
    page.wait_for_selector("text=Saved in Windows Credential Manager (…9876)")
    assert A.vault.store[("EasyUniTrack AI", "openai")] == "sk-test-abcd9876"
    assert "sk-test-abcd9876" not in page.content()
    page.click("[data-action=ai-test]")                          # offline in tests
    page.wait_for_selector("#aiTestResult.ai-bad")

    # Turn off: back to the start, and the sidebar never changed
    page.click("[data-action=ai-withdraw]")
    page.click("#confirmYes")
    page.wait_for_selector("#aiCard [data-action=ai-start]")
    assert "assistant" not in page.inner_text("#nav").lower()
    page.click("[data-action=ai-start]")                         # clean up for other tests
    page.keyboard.press("Escape")
    assert page.errors == [], page.errors


def test_study_assistant_chat_streams_safely_and_helps_with_a_task(server, page):
    """With AI on: the Study page streams a reply, renders it safely, counts tokens, and the task panel works."""
    import json

    import app as A
    tok = {A.TOKEN_HEADER: A.SESSION_TOKEN}
    terms = page.request.get(f"{server}/api/ai/terms").json()
    page.request.post(f"{server}/api/ai/terms/agree", headers=tok,
                      data={"version": terms["version"], "ticks": {k: True for k in terms["ticks"]}})
    page.request.put(f"{server}/api/ai/settings", headers=tok, data={"provider": "ollama", "model": "qwen2.5:7b"})
    reply = ["## Recursion\n", "A function that **calls itself**.\n\n", "- base case\n- recursive case\n\n",
             "<script>window.hacked=1</script> ",
             "[Search YouTube: recursion](https://www.youtube.com/results?search_query=recursion) ",
             "[not this](https://evil.example/x)"]
    sse = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': t}}]})}\n\n" for t in reply)
    sse += f"data: {json.dumps({'choices': [], 'usage': {'prompt_tokens': 40, 'completion_tokens': 20}})}\n\ndata: [DONE]\n\n"
    A.fake_net["POST localhost/v1/chat/completions"] = (200, sse)

    page.goto(f"{server}/#/today")
    page.reload()                                                 # pick up the AI state set through the API
    page.wait_for_selector("#nav a[href='#/study']")              # appears only once AI is on
    page.click("#nav a[href='#/study']")
    page.wait_for_selector("#chatInput")
    page.fill("#chatInput", "What is recursion?")
    page.keyboard.press("Enter")
    page.wait_for_selector(".chat-msg.ai .chat-tools")            # finished streaming
    text = page.locator(".chat-msg.ai .chat-text")
    assert text.locator("h4").inner_text() == "Recursion"          # "##" is a sub-heading inside a reply
    assert text.locator("strong").inner_text() == "calls itself"
    assert text.locator("li").count() == 2
    assert page.evaluate("window.hacked") is None                 # model output can't run code
    assert "<script>" in text.inner_text()                        # shown as text instead
    links = text.locator("a")
    assert links.count() == 1 and "youtube.com/results" in links.get_attribute("href")
    assert "evil.example" in text.inner_text() and text.locator("a[href*='evil']").count() == 0
    assert page.inner_text("#chatTokens") == "60"
    assert "issues/new" in page.get_attribute(".chat-tools a", "href")
    assert "Preview" in page.inner_text(".chat-foot")

    # Help me with this: open a task, ask from the slide-in panel, then move to the full page
    t = page.request.post(f"{server}/api/tasks", headers=tok, data={"title": "Recursion worksheet"}).json()
    page.goto(f"{server}/#/tasks")
    page.reload()                                                 # pick up the task made through the API
    page.wait_for_function(f"state.tasks.some(x => x.id === {t['id']})")
    page.evaluate(f"openTask({t['id']})")
    page.click("[data-action=chat-help]")
    page.wait_for_selector("#drawer .chat-attached >> text=Recursion worksheet")
    page.fill("#drawer #chatInput", "Where do I start?")
    page.keyboard.press("Enter")
    page.wait_for_selector("#drawer .chat-msg.ai .chat-tools")
    sent = [r for r in A.fake_net_seen if r.url.path.endswith("/chat/completions")][-1]
    assert "Recursion worksheet" in json.loads(sent.content)["messages"][0]["content"]
    page.click("[data-action=chat-full]")
    page.wait_for_selector("#content .chat-attached >> text=Recursion worksheet")
    assert page.locator("#content .chat-msg.me").count() == 1

    # Turning AI off hides the page and the sidebar item again
    page.request.post(f"{server}/api/ai/terms/withdraw", headers=tok)
    page.goto(f"{server}/#/study")
    page.reload()
    page.wait_for_selector("#content > *")
    assert page.inner_text("#pageTitle") != "Study assistant"     # sent to Today instead
    assert page.locator("#nav a[href='#/study']").count() == 0
    page.errors.clear()                                            # the offline Ollama check logs a failed fetch


def test_long_chats_and_switching_tasks_mid_reply(server, page):
    """Only the last 20 messages are sent, and a reply still streaming for an old chat can't touch the new one."""
    import json

    import app as A
    tok = {A.TOKEN_HEADER: A.SESSION_TOKEN}
    terms = page.request.get(f"{server}/api/ai/terms").json()
    page.request.post(f"{server}/api/ai/terms/agree", headers=tok,
                      data={"version": terms["version"], "ticks": {k: True for k in terms["ticks"]}})
    page.request.put(f"{server}/api/ai/settings", headers=tok, data={"provider": "ollama", "model": "qwen2.5:7b"})
    nl = chr(10)
    sse = ("data: " + json.dumps({"choices": [{"delta": {"content": "ok"}}]}) + nl + nl + "data: "
           + json.dumps({"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}) + nl + nl)
    A.fake_net["POST localhost/v1/chat/completions"] = (200, sse)
    page.goto(f"{server}/#/today")
    page.reload()
    page.wait_for_selector("#nav a[href='#/study']")

    # 150 earlier messages, none summarised yet: the request carries the last 40, starting with the student's
    page.evaluate("""() => { chatReset(); const c = chatState();
        for (let i = 0; i < 150; i++) c.messages.push({ role: i % 2 ? 'assistant' : 'user', content: 'm' + i }); }""")
    seen = len(A.fake_net_seen)
    page.evaluate("chatSend('latest question')")
    page.wait_for_function("!chatState().streaming && !chatState().summarising")
    bodies = [json.loads(r.content) for r in A.fake_net_seen[seen:] if r.url.path.endswith("/chat/completions")]
    summaries = [b for b in bodies if b["messages"][0]["content"].startswith("You keep a running summary")]
    body = next(b for b in bodies if b not in summaries)
    sent = body["messages"][1:]                                    # after the system prompt
    assert len(sent) == 39 and sent[0]["content"] == "m112" and sent[-1]["content"] == "latest question"
    assert not any(e for e in page.errors if "422" in e)
    # The 132 messages before the window (150, the question and its reply, less 20) are summarised, 60 at a time
    assert [b["messages"][1]["content"].count("Student: ") + b["messages"][1]["content"].count("Assistant: ")
            for b in summaries] == [60, 60, 12]
    assert page.evaluate("chatState().messages.filter(m => m.summarised).length") == 132

    # A reply for the old chat is still arriving when another chat starts: it must be ignored
    state = page.evaluate("""async () => {
        chatReset();
        const pending = chatSend('old chat question');
        chatReset(42);                                             // e.g. Help me with this on another task
        await pending;
        const c = chatState();
        return { tokens: c.tokens, messages: c.messages.length, streaming: c.streaming, taskId: c.taskId };
    }""")
    assert state == {"tokens": 0, "messages": 0, "streaming": False, "taskId": 42}
    page.evaluate("chatReset()")
    page.request.post(f"{server}/api/ai/terms/withdraw", headers=tok)
    page.errors.clear()


def test_notes_inside_subjects(server, page):
    """Notes on subject cards: write one, save a reply as a note, write notes on a topic, edit and delete."""
    import json

    import app as A
    tok = {A.TOKEN_HEADER: A.SESSION_TOKEN}
    terms = page.request.get(f"{server}/api/ai/terms").json()
    page.request.post(f"{server}/api/ai/terms/agree", headers=tok,
                      data={"version": terms["version"], "ticks": {k: True for k in terms["ticks"]}})
    page.request.put(f"{server}/api/ai/settings", headers=tok, data={"provider": "ollama", "model": "qwen2.5:7b"})
    algo = page.request.post(f"{server}/api/subjects", headers=tok, data={"name": "Algorithms 101", "color": "#3B6EA8"}).json()
    empty = page.request.post(f"{server}/api/subjects", headers=tok, data={"name": "Ethics 101", "color": "#7B4FA3"}).json()
    nl = chr(10)

    def reply(*parts):
        return "".join("data: " + json.dumps({"choices": [{"delta": {"content": t}}]}) + nl + nl for t in parts)

    page.goto(f"{server}/#/subjects")
    page.reload()
    card = page.locator("article.subject", has_text="Algorithms 101")
    card.locator(".subject-notes").wait_for()
    assert "Save replies from the study assistant here" in card.inner_text()

    # Write a note by hand
    card.locator("[data-action=new-note]").click()
    page.fill("#drawerForm [name=title]", "Big-O basics")
    page.fill("#drawerForm [name=body]", "## Growth" + nl + "- O(1) constant" + nl + "- O(n) linear")
    page.click("#drawerFoot [type=submit]")
    card.locator(".note-row >> text=Big-O basics").wait_for()
    card.locator(".note-row >> text=Big-O basics").click()
    page.wait_for_selector("#drawer .note-body h4 >> text=Growth")
    assert page.locator("#drawer .note-body li").count() == 2
    page.click("[data-action=edit-note]")
    page.fill("#drawerForm [name=title]", "Big-O cheat sheet")
    page.click("#drawerFoot [type=submit]")
    card.locator(".note-row >> text=Big-O cheat sheet").wait_for()

    # Save a study assistant reply as a note
    A.fake_net["POST localhost/v1/chat/completions"] = (200, reply("## Merge sort" + nl, "Split, sort, **merge**."))
    page.goto(f"{server}/#/study")
    page.wait_for_selector("#chatInput")
    page.evaluate("chatReset(); chatRefresh()")
    page.fill("#chatInput", "Explain merge sort")
    page.keyboard.press("Enter")
    page.wait_for_selector(".chat-msg.ai .chat-tools")
    page.click("[data-action=chat-save-note]")
    assert page.input_value("#drawerForm [name=title]") == "Merge sort"          # from the reply's heading
    page.select_option("#drawerForm [name=subject_id]", str(algo["id"]))
    page.click("#drawerFoot [type=submit]")
    page.wait_for_selector("#toast.show >> text=Algorithms 101")

    # Write notes on a topic
    A.fake_net["POST localhost/v1/chat/completions"] = (200, reply("## Hash tables" + nl, "- buckets" + nl, "- collisions"))
    page.goto(f"{server}/#/subjects")
    card.locator("[data-action=note-topic]").click()
    page.fill("#noteTopicInput", "Hash tables")
    page.keyboard.press("Enter")
    page.wait_for_selector("#noteTopicSave:not([hidden])")
    asked = json.loads([r for r in A.fake_net_seen if r.url.path.endswith("/chat/completions")][-1].content)
    assert "Mode: Notes" in asked["messages"][0]["content"] and "Hash tables" in asked["messages"][1]["content"]
    page.click("#noteTopicSave")
    assert page.input_value("#drawerForm [name=title]") == "Hash tables"
    page.click("#drawerFoot [type=submit]")
    card.locator(".note-row >> text=Hash tables").wait_for()
    notes = page.request.get(f"{server}/api/notes?subject_id={algo['id']}").json()
    assert sorted(n["source"] for n in notes) == ["chat", "manual", "topic"]

    # Delete one
    card.locator(".note-row >> text=Big-O cheat sheet").click()
    page.click("[data-action=delete-note]")
    page.click("#confirmYes")
    page.wait_for_selector("#toast.show >> text=Note deleted")
    assert card.locator(".note-row").count() == 2

    # With AI off: a subject that has notes still shows them; one without notes shows nothing new
    page.request.post(f"{server}/api/ai/terms/withdraw", headers=tok)
    page.reload()
    card.locator(".note-row").first.wait_for()
    assert card.locator("[data-action=note-topic]").count() == 0            # no AI buttons
    assert page.locator("article.subject", has_text="Ethics 101").locator(".subject-notes").count() == 0
    for n in page.request.get(f"{server}/api/notes").json():
        page.request.delete(f"{server}/api/notes/{n['id']}", headers=tok)
    for s in (algo, empty):
        page.request.delete(f"{server}/api/subjects/{s['id']}", headers=tok)
    page.errors.clear()


def test_reply_formatting_rules(server, page):
    """chatMarkdown: dividers, lists and escaping (used for chat replies and notes)."""
    page.goto(f"{server}/#/today")
    page.wait_for_selector("#content > *")
    nl = chr(10)
    md = lambda s: page.evaluate("s => chatMarkdown(s)", s)  # noqa: E731
    assert md("a" + nl + "---" + nl + "b") == "<p>a</p><hr><p>b</p>"
    assert md("* * *") == "<hr>" and md("-- not a rule") == "<p>-- not a rule</p>"
    assert md("- a" + nl + "- b") == "<ul><li>a</li><li>b</li></ul>"
    assert "&lt;img" in md("<img src=x onerror=alert(1)>")


def test_closing_write_notes_stops_the_request(server, page):
    """Closing the panel (or starting another topic) aborts the stream, so it stops using tokens."""
    import app as A
    tok = {A.TOKEN_HEADER: A.SESSION_TOKEN}
    terms = page.request.get(f"{server}/api/ai/terms").json()
    page.request.post(f"{server}/api/ai/terms/agree", headers=tok,
                      data={"version": terms["version"], "ticks": {k: True for k in terms["ticks"]}})
    s = page.request.post(f"{server}/api/subjects", headers=tok, data={"name": "Networks 101", "color": "#3B6EA8"}).json()
    page.goto(f"{server}/#/subjects")
    page.reload()
    page.wait_for_selector("[data-action=note-topic]")
    aborted = page.evaluate(f"""() => {{
        openNoteTopic({s["id"]});
        const first = new AbortController(); state.noteTopic.controller = first;
        openNoteTopic({s["id"]});                                  // another topic replaces it
        const second = new AbortController(); state.noteTopic.controller = second;
        closeDrawer();                                             // closing the panel
        return [first.signal.aborted, second.signal.aborted, state.noteTopic];
    }}""")
    assert aborted == [True, True, None]
    page.request.delete(f"{server}/api/subjects/{s['id']}", headers=tok)
    page.request.post(f"{server}/api/ai/terms/withdraw", headers=tok)


def test_task_actions_from_the_chat(server, page):
    """The assistant adds a task (Undo works), and deleting needs Keep/Delete (and can be undone too)."""
    import json

    import app as A
    tok = {A.TOKEN_HEADER: A.SESSION_TOKEN}
    terms = page.request.get(f"{server}/api/ai/terms").json()
    page.request.post(f"{server}/api/ai/terms/agree", headers=tok,
                      data={"version": terms["version"], "ticks": {k: True for k in terms["ticks"]}})
    page.request.put(f"{server}/api/ai/settings", headers=tok, data={"provider": "ollama", "model": "qwen2.5:7b"})
    nl = chr(10)

    def sse(*objs):
        return "".join("data: " + json.dumps(o) + nl + nl for o in objs)

    def tool(name, args):
        call = {"index": 0, "id": "c1", "function": {"name": name, "arguments": json.dumps(args)}}
        return sse({"choices": [{"delta": {"tool_calls": [call]}}]})

    say = lambda text: sse({"choices": [{"delta": {"content": text}}]})  # noqa: E731
    A.fake_net["POST localhost/api/show"] = (200, {"capabilities": ["completion", "tools"]})
    added = tool("add_task", {"title": "Draft intro", "due_date": "2026-11-03"})
    A.fake_net["POST localhost/v1/chat/completions"] = (200, [added, say("Added it.")])

    page.goto(f"{server}/#/study")
    page.reload()
    page.wait_for_selector("#chatInput")
    page.evaluate("chatReset(); chatRefresh()")
    page.fill("#chatInput", "Add a task to draft my intro")
    page.keyboard.press("Enter")
    page.locator(".chat-card.ok", has_text="Draft intro").wait_for()
    page.wait_for_function("state.tasks.some(t => t.title === 'Draft intro')")     # the list refreshes when the reply ends
    page.click("[data-action=chat-undo]")
    page.locator(".chat-card.muted-card", has_text="Undone").wait_for()
    assert not page.evaluate("state.tasks.some(t => t.title === 'Draft intro')")

    # Delete asks first: Keep leaves it, Delete removes it, and Undo brings it back
    old = page.request.post(f"{server}/api/tasks", headers=tok, data={"title": "Old draft"}).json()
    for choice in ("Keep", "Delete"):
        replies = [tool("delete_task", {"id": old["id"]}), say("Confirm it in the card.")]
        A.fake_net["POST localhost/v1/chat/completions"] = (200, replies)
        page.evaluate("chatReset(); chatRefresh()")
        page.fill("#chatInput", "Delete my old draft")
        page.keyboard.press("Enter")
        page.locator(".chat-card.danger", has_text="Old draft").wait_for()
        assert page.request.get(f"{server}/api/tasks/{old['id']}").ok                 # still there until you choose
        page.click(f".chat-card.danger button:has-text('{choice}')")
        if choice == "Keep":
            page.locator(".chat-card.muted-card", has_text="Left as it was").wait_for()
            assert page.request.get(f"{server}/api/tasks/{old['id']}").ok
    page.locator(".chat-card.ok", has_text="Done: Delete").wait_for()
    assert page.request.get(f"{server}/api/tasks/{old['id']}").status == 404
    page.click("[data-action=chat-undo]")
    page.locator(".chat-card.muted-card", has_text="Undone").wait_for()
    assert page.locator(".chat-card.danger").count() == 0                         # doesn't ask again after Undo
    assert page.request.get(f"{server}/api/tasks/{old['id']}").json()["title"] == "Old draft"
    page.request.delete(f"{server}/api/tasks/{old['id']}", headers=tok)
    page.evaluate("chatReset()")
    page.request.post(f"{server}/api/ai/terms/withdraw", headers=tok)
    page.errors.clear()


@pytest.mark.ui
def test_maths_code_and_diagrams_in_replies(server, page):
    """Maths with KaTeX, highlighted code with Copy, Mermaid diagrams drawn after the reply, a broken diagram
    offering Try again, the format choice, and AI text that tries to inject HTML or script staying inert."""
    import json
    import os

    import app as A
    tok = {A.TOKEN_HEADER: A.SESSION_TOKEN}
    terms = page.request.get(f"{server}/api/ai/terms").json()
    page.request.post(f"{server}/api/ai/terms/agree", headers=tok,
                      data={"version": terms["version"], "ticks": {k: True for k in terms["ticks"]}})
    page.request.put(f"{server}/api/ai/settings", headers=tok, data={"provider": "ollama", "model": "qwen2.5:7b"})
    nl, f = chr(10), chr(96) * 3

    def say(*parts):
        return "".join("data: " + json.dumps({"choices": [{"delta": {"content": t}}]}) + nl + nl for t in parts)

    reply = nl.join([
        "## Stacks", "Push is $O(1)$, and in total:", r"$$\sum_{i=1}^{n} i = \frac{n(n+1)}{2}$$",
        "It costs $5 and $10 at the shop.",
        f + "python", "def push(x):", "    stack.append(x)  # O(1)", f,
        f + "mermaid", "flowchart LR", '  A["Push (O(1))"] --> B["Pop"]', f,
        f + "mermaid", "sequenceDiagram", "  Student->>App: Ask", "  App-->>Student: Answer", f,
        f + "mermaid", "flowchart LR", "  A --> [[[", f,
        f + "mermaid", "graph TD", "    A[Stack: []] --> B(Push 5);", "    B --> C[Stack: [5]];", "    C --> D{Top: 5}", f,
        f + "mermaid", "flowchart LR", '  A["<img src=x onerror=window.pwned=1>"] --> B',
        '  click A href "javascript:window.pwned=1"', f,
        r'<img src=x onerror="window.pwned=1"> and $\href{javascript:window.pwned=1}{x}$',
        "and [click](javascript:window.pwned=1)",
    ])
    replies = [say(reply[:200], reply[200:]), say("Fixed it."), say("Here it is.")]
    A.fake_net["POST localhost/v1/chat/completions"] = (200, replies)

    page.goto(f"{server}/#/study")
    page.reload()
    page.wait_for_selector("#chatInput")
    page.evaluate("chatReset(); chatRefresh()")
    assert page.evaluate("typeof window.mermaid") == "undefined"        # loaded only when a diagram appears
    page.select_option("#chatFormat", "both")
    page.fill("#chatInput", "Explain stacks")
    page.keyboard.press("Enter")
    page.wait_for_selector(".chat-msg.ai .chat-tools")
    page.wait_for_selector(".chat-msg.ai .diagram-svg svg")
    page.wait_for_function("document.querySelectorAll('.chat-msg.ai .chat-diagram:not(.drawing)').length === 5")
    msg = page.locator(".chat-msg.ai").first

    asked = json.loads([r for r in A.fake_net_seen if r.url.path.endswith("/chat/completions")][-1].content)
    assert "Format: notes and diagram" in asked["messages"][0]["content"]
    assert msg.locator(".katex").count() >= 2 and msg.locator(".katex-display").count() == 1
    assert "It costs $5 and $10 at the shop." in msg.inner_text()            # prices aren't maths
    assert msg.locator(".code-head", has_text="python").count() == 1
    assert msg.locator("pre code .hljs-keyword", has_text="def").count() == 1
    assert msg.locator(".diagram-svg svg").count() == 4                       # the injection attempt draws as text
    assert msg.locator(".diagram-src summary", has_text="labels put in quotes").count() == 1   # A[Stack: [5]] repaired
    broken = msg.locator(".chat-diagram", has_text="couldn't be drawn")
    assert broken.count() == 1 and broken.locator("[data-action=diagram-retry]").count() == 1
    assert page.evaluate("window.pwned") is None
    unsafe = ".chat-msg.ai [onerror], .chat-msg.ai img, .chat-msg.ai a[href^='javascript'], .chat-msg.ai foreignObject"
    assert page.locator(unsafe).count() == 0
    if os.environ.get("EUT_SHOTS"):
        for name, where in (("top", "0"), ("bottom", "log.scrollHeight")):
            page.evaluate(f"(() => {{ const log = document.querySelector('#chatLog'); log.scrollTop = {where}; }})()")
            page.screenshot(path=os.path.join(os.environ["EUT_SHOTS"], f"stage5-{name}.png"))
        page.emulate_media(color_scheme="dark")
        page.evaluate("chatRefresh()")
        page.wait_for_function("document.querySelectorAll('.chat-msg.ai .chat-diagram:not(.drawing)').length === 5")
        page.wait_for_timeout(300)
        page.evaluate("document.querySelector('#chatLog').scrollTop = 120")
        page.screenshot(path=os.path.join(os.environ["EUT_SHOTS"], "stage5-dark.png"))
        page.emulate_media(color_scheme="light")
        page.evaluate("chatRefresh()")

    # The diagram's CSS and attributes can't load anything from elsewhere, even written with CSS escapes
    cleaned = page.evaluate(r"""cleanSvg('<svg xmlns="http://www.w3.org/2000/svg"><style>.a{background:u\\72l(http://x.test/a)}'
        + '.b{background-image:image-set(\"http://x.test/b\" 1x)}@import \"http://x.test/c\";</style>'
        + '<rect style="fill:URL(http://x.test/d)" fill="url(http://x.test/e)" marker-end="url(#arrow)"/></svg>')""")
    assert "x.test" not in cleaned and 'marker-end="url(#arrow)"' in cleaned
    assert msg.locator(".diagram-svg [marker-end^='url(#']").count() > 0                # arrowheads kept

    # If the diagram library fails to load, that isn't remembered: Try again draws it
    page.evaluate("""() => { window.savedLoad = mermaidLoading;
        mermaidLoading = Promise.reject(new Error("The diagram library couldn't load."));
        const box = document.createElement('div'); box.className = 'chat-text'; box.id = 'loadTest';
        box.innerHTML = chatMarkdown(['```mermaid', 'flowchart LR', '  X --> Y', '```'].join(String.fromCharCode(10)));
        document.querySelector('#chatLog').append(box); }""")
    page.wait_for_selector("#loadTest [data-action=diagram-redraw]")
    page.evaluate("mermaidLoading = window.savedLoad")
    page.click("#loadTest [data-action=diagram-redraw]")
    page.wait_for_selector("#loadTest .diagram-svg svg")
    page.evaluate("document.querySelector('#loadTest').remove()")

    # Saved as a note, the diagrams draw there too (Try again is only for the chat)
    page.click("[data-action=chat-save-note]")
    page.click("#drawerFoot [type=submit]")
    page.wait_for_selector("#toast.show >> text=Note saved")
    page.evaluate("openNote(state.notes[0].id)")
    page.wait_for_selector("#drawer .note-body .diagram-svg svg")
    page.wait_for_function("document.querySelectorAll('#drawer .chat-diagram:not(.drawing)').length === 5")
    assert page.locator("#drawer .katex-display").count() == 1
    assert page.locator("#drawer [data-action=diagram-retry]").count() == 0
    page.evaluate("closeDrawer()")

    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.click("[data-action=code-copy]")
    page.wait_for_selector("#toast.show >> text=Copied")
    copied = page.evaluate("navigator.clipboard.readText()").replace(chr(13), "")
    assert copied == "def push(x):" + nl + "    stack.append(x)  # O(1)"

    # Try again asks the assistant to fix the diagram
    broken.locator("[data-action=diagram-retry]").click()
    page.wait_for_selector(".chat-msg.me >> text=didn't draw")
    page.wait_for_function("document.querySelectorAll('.chat-msg.ai .chat-tools').length === 2")

    # Show as… asks for the last answer again in another format
    page.select_option(".chat-reformat", "diagram")
    page.wait_for_selector(".chat-msg.me >> text=Show that again as a diagram.")
    page.wait_for_function("document.querySelectorAll('.chat-msg.ai .chat-tools').length === 3")
    asked = json.loads([r for r in A.fake_net_seen if r.url.path.endswith("/chat/completions")][-1].content)
    assert "Format: diagram" in asked["messages"][0]["content"]
    assert page.input_value("#chatFormat") == "diagram"

    page.evaluate("chatReset()")
    page.request.post(f"{server}/api/ai/terms/withdraw", headers=tok)


@pytest.mark.ui
def test_code_workspace(server, page, tmp_path_factory):
    """Link a folder, see hidden files greyed out, read a file with line numbers, see which files go with a
    question, explain a pasted error (its line gets marked), Explain only for SQL, and unlink."""
    import json
    import os

    import app as A
    tok = {A.TOKEN_HEADER: A.SESSION_TOKEN}
    root = tmp_path_factory.mktemp("lab3")
    (root / "main.py").write_text("from helpers import add\n\nprint(add(1, '2'))\n", encoding="utf-8")
    (root / "helpers.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / ".env").write_text("API_KEY=secret\n", encoding="utf-8")
    (root / "db").mkdir()
    (root / "db" / "queries.sql").write_text("SELECT * FROM marks;\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    terms = page.request.get(f"{server}/api/ai/terms").json()
    page.request.post(f"{server}/api/ai/terms/agree", headers=tok,
                      data={"version": terms["version"], "ticks": {k: True for k in terms["ticks"]}})
    page.request.put(f"{server}/api/ai/settings", headers=tok,
                     data={"provider": "ollama", "model": "qwen2.5:7b", "code_enabled": True})
    nl = chr(10)
    hint = "Line 2 adds a number and a string. What type is '2'?"
    reply = "data: " + json.dumps({"choices": [{"delta": {"content": hint}}]}) + nl + nl
    A.fake_net["POST localhost/v1/chat/completions"] = (200, reply)

    page.goto(f"{server}/#/code")
    page.reload()
    page.wait_for_selector("text=Link a code folder")
    assert page.locator("#nav a[href='#/code']").count() == 1
    page.click("[data-action=code-link]")
    page.click("[data-action=code-browse]")                       # no picker outside the desktop app
    page.wait_for_selector("#toast.show >> text=desktop app")
    page.fill("#drawerForm [name=path]", str(root))
    page.click("#drawerFoot [type=submit]")
    page.wait_for_selector(".code-tree .tree-row >> text=main.py")
    assert page.locator(".hidden-row", has_text=".env").count() == 1
    assert page.locator(".hidden-row", has_text="node_modules").count() == 1
    assert page.locator(".code-modes button.on").inner_text().startswith("Assignment")

    page.click(".tree-row >> text=main.py")
    page.wait_for_selector(".code-file-head >> text=main.py")
    assert page.locator(".code-gutter span").count() == 4 and page.locator(".code-text .hljs-keyword").count() >= 1
    chips = "[...document.querySelectorAll('#codeSend .file-chip')].map(c => c.textContent.trim()).join()"
    page.wait_for_function(f"{chips} === 'main.py,helpers.py'")          # the open file and what it imports

    # A pasted traceback: Explain the error sends it, and the line it points at gets marked
    tb = nl.join(["Traceback (most recent call last):", r'  File "C:\lab3\main.py", line 3, in <module>',
                  r'  File "C:\lab3\helpers.py", line 2, in add', "TypeError: unsupported operand type(s) for +"])
    page.fill("#chatInput", tb)
    page.dispatch_event("#chatInput", "input")
    page.click("[data-action=code-explain-error]")
    page.wait_for_selector(".chat-msg.ai .chat-tools")
    assert page.locator(".chat-sent").inner_text() == "Sent with this: main.py, helpers.py"
    asked = json.loads([r for r in A.fake_net_seen if r.url.path.endswith("/chat/completions")][-1].content)
    system = asked["messages"][0]["content"]
    assert "give hints first" in system and "--- helpers.py (Python) ---" in system and "API_KEY" not in system
    assert "Explain this error" in asked["messages"][-1]["content"]

    # Taking a file off the list keeps it off, even when the next error names it
    page.click("#codeSend [data-action=code-unsend][data-path='helpers.py']")
    page.wait_for_function(f"{chips} === 'main.py'")
    page.fill("#chatInput", tb)
    page.dispatch_event("#chatInput", "input")
    page.click("[data-action=code-explain-error]")
    page.wait_for_function("document.querySelectorAll('.chat-msg.ai .chat-tools').length === 2")
    assert page.locator(".chat-sent").last.inner_text() == "Sent with this: main.py"
    assert page.locator(".code-mark").count() == 1 and page.locator(".code-gutter .marked").inner_text() == "3"

    # Personal mode, Explain only for SQL, and the note about cloud providers
    page.click("[data-action=code-mode][data-mode=personal]")
    page.wait_for_selector(".code-modes button.on >> text=Personal")
    page.click(".tree-row >> text=db")
    page.click(".tree-row >> text=queries.sql")
    page.wait_for_selector(".code-file-head >> text=queries.sql")
    assert "main.py" in page.input_value("#runCommand")          # SQL itself can't run; the project's main.py can
    assert page.locator(".code-cloud-note").count() == 0
    page.evaluate("state.ai.provider = 'openai'; chatRefresh()")
    assert "Code you send goes to OpenAI" in page.locator(".code-cloud-note").inner_text()
    page.evaluate("state.ai.provider = 'ollama'; chatRefresh()")
    if os.environ.get("EUT_SHOTS"):
        page.click(".tree-row >> text=main.py")
        page.wait_for_selector(".code-file-head >> text=main.py")
        page.screenshot(path=os.path.join(os.environ["EUT_SHOTS"], "stage6-workspace.png"))

    page.click("[data-action=code-unlink]")
    page.click("#confirmYes")
    page.wait_for_selector("text=Link a code folder")
    assert (root / "main.py").exists()
    page.evaluate("chatReset()")
    page.request.post(f"{server}/api/ai/terms/withdraw", headers=tok)


@pytest.mark.ui
def test_proposed_changes(server, page, tmp_path_factory):
    """A proposed change shows as a diff; Apply writes it (the viewer updates), Undo puts the file back exactly,
    and a change to a file edited since is refused."""
    import json
    import os

    import app as A
    tok = {A.TOKEN_HEADER: A.SESSION_TOKEN}
    root = tmp_path_factory.mktemp("lab4")
    original = b"def add(a, b):\r\n    return a - b\r\n"
    (root / "calc.py").write_bytes(original)
    terms = page.request.get(f"{server}/api/ai/terms").json()
    page.request.post(f"{server}/api/ai/terms/agree", headers=tok,
                      data={"version": terms["version"], "ticks": {k: True for k in terms["ticks"]}})
    page.request.put(f"{server}/api/ai/settings", headers=tok,
                     data={"provider": "ollama", "model": "qwen2.5:7b", "code_enabled": True})
    page.request.post(f"{server}/api/code/folders", headers=tok, data={"path": str(root), "mode": "personal"})
    nl = chr(10)

    def sse(*objs):
        return "".join("data: " + json.dumps(o) + nl + nl for o in objs)

    args = {"path": "calc.py", "find": "    return a - b", "replace": "    return a + b", "summary": "Add, don't subtract"}
    call = {"index": 0, "id": "c1", "function": {"name": "propose_change", "arguments": json.dumps(args)}}
    proposal = sse({"choices": [{"delta": {"tool_calls": [call]}}]})
    say = sse({"choices": [{"delta": {"content": "Here's the fix: review it and click Apply."}}]})
    A.fake_net["POST localhost/api/show"] = (200, {"capabilities": ["completion", "tools"]})
    A.fake_net["POST localhost/v1/chat/completions"] = (200, [proposal, say, proposal, say])

    page.goto(f"{server}/#/code")
    page.reload()
    page.click(".tree-row >> text=calc.py")
    page.wait_for_selector(".code-file-head >> text=calc.py")
    page.fill("#chatInput", "Fix the add function")
    page.keyboard.press("Enter")
    card = page.locator(".change-card.proposed")
    card.wait_for()
    assert card.locator(".diff-line.del").inner_text().endswith("return a - b")
    assert card.locator(".diff-line.add").inner_text().endswith("return a + b")
    assert (root / "calc.py").read_bytes() == original                        # nothing until Apply
    if os.environ.get("EUT_SHOTS"):
        page.screenshot(path=os.path.join(os.environ["EUT_SHOTS"], "stage7-proposed.png"))

    card.locator("[data-action=code-change-apply]").click()
    page.locator(".change-card.applied").wait_for()
    assert (root / "calc.py").read_bytes() == original.replace(b"a - b", b"a + b")
    page.wait_for_selector(".code-text >> text=a + b")                       # the viewer shows the file as it is now
    page.click("[data-action=code-change-undo]")
    page.locator(".change-card.undone").wait_for()
    assert (root / "calc.py").read_bytes() == original

    # A file edited after the proposal: Apply refuses
    page.fill("#chatInput", "Fix it again")
    page.keyboard.press("Enter")
    page.locator(".change-card.proposed").wait_for()
    (root / "calc.py").write_bytes(original + b"# mine\r\n")
    page.click(".change-card.proposed [data-action=code-change-apply]")
    page.locator(".change-card.stale").wait_for()
    assert (root / "calc.py").read_bytes() == original + b"# mine\r\n"
    page.evaluate("chatReset()")
    page.request.post(f"{server}/api/ai/terms/withdraw", headers=tok)


@pytest.mark.ui
def test_running_code(server, page, tmp_path_factory):
    """The Run notice once, a program that asks for input, a server kept running with an Open in browser link
    and Stop, and a crash whose line is linked and explained."""
    import json
    import os
    import sys

    import app as A
    tok = {A.TOKEN_HEADER: A.SESSION_TOKEN}
    root = tmp_path_factory.mktemp("lab8")
    (root / "hello.py").write_text("name = input('Name? ')\nprint('Hello,', name)\n", encoding="utf-8")
    (root / "server.py").write_text("import time\nprint('Running on http://127.0.0.1:5057/', flush=True)\ntime.sleep(60)\n")
    (root / "crash.py").write_text("marks = []\nprint(sum(marks) / len(marks))\n")
    terms = page.request.get(f"{server}/api/ai/terms").json()
    page.request.post(f"{server}/api/ai/terms/agree", headers=tok,
                      data={"version": terms["version"], "ticks": {k: True for k in terms["ticks"]}})
    page.request.put(f"{server}/api/ai/settings", headers=tok,
                     data={"provider": "ollama", "model": "qwen2.5:7b", "code_enabled": True})
    folder = page.request.post(f"{server}/api/code/folders", headers=tok, data={"path": str(root), "mode": "assignment"}).json()
    nl = chr(10)
    say = "data: " + json.dumps({"choices": [{"delta": {"content": "You divide by len(marks), which is 0."}}]}) + nl + nl
    A.fake_net["POST localhost/v1/chat/completions"] = (200, say)
    py = f'"{sys.executable}"'

    page.goto(f"{server}/#/code")
    page.reload()
    page.wait_for_selector(".code-tree")
    if page.locator("#codeFolder").count():                    # other tests' folders may be linked too
        page.select_option("#codeFolder", str(folder["id"]))
    page.click(".tree-row >> text=hello.py")
    page.wait_for_selector("#runCommand")
    assert "hello.py" in page.input_value("#runCommand")
    page.fill("#runCommand", f"{py} hello.py")
    page.click("[data-action=code-run]")
    page.wait_for_selector("#confirm:not([hidden]) >> text=Only run code you trust")         # the Run notice, once
    page.click("#confirmYes")
    page.wait_for_selector("#runText >> text=Name?")
    page.fill("#runInput input", "Sean")
    page.keyboard.press("Enter")
    page.wait_for_selector("#runStatus >> text=Finished")
    assert page.inner_text("#runText").strip() == "Name? Sean\nHello, Sean"

    # A server: Keep running, an Open in browser link, then Stop
    page.click(".tree-row >> text=server.py")
    page.wait_for_selector(".code-file-head >> text=server.py")
    page.fill("#runCommand", f"{py} server.py")
    page.check("#runKeep")
    page.click("[data-action=code-run]")
    page.wait_for_selector("#runLinks a >> text=127.0.0.1:5057")
    assert page.get_attribute("#runLinks a", "href") == "http://127.0.0.1:5057/"
    page.click("[data-action=code-run-stop]")
    page.wait_for_selector("#runStatus >> text=Stopped")
    assert page.locator("#confirm:not([hidden])").count() == 0                                # not asked again

    # A double-click starts one run, not two
    started = page.evaluate("c => Promise.all([codeStartRun(c), codeStartRun(c)])", f"{py} hello.py")
    assert sorted(started) == [False, True]
    page.click("[data-action=code-run-stop]")
    page.wait_for_selector("#runStatus >> text=Stopped")

    # A crash: the line is linked and marked, and Explain the error sends the output
    page.click(".tree-row >> text=crash.py")
    page.wait_for_selector(".code-file-head >> text=crash.py")
    page.uncheck("#runKeep")
    page.fill("#runCommand", f"{py} crash.py")
    page.click("[data-action=code-run]")
    page.wait_for_selector("#runStatus >> text=exit code 1")
    page.wait_for_selector(".run-links >> text=crash.py line 2")
    assert page.locator(".code-gutter .marked").inner_text() == "2"
    if os.environ.get("EUT_SHOTS"):
        page.screenshot(path=os.path.join(os.environ["EUT_SHOTS"], "stage8-run.png"))
    page.click("[data-action=code-explain-error]")
    page.wait_for_selector(".chat-msg.ai .chat-tools")
    asked = json.loads([r for r in A.fake_net_seen if r.url.path.endswith("/chat/completions")][-1].content)
    assert "ZeroDivisionError" in asked["messages"][-1]["content"] and "from running" in asked["messages"][-1]["content"]
    page.evaluate("chatReset()")
    page.request.post(f"{server}/api/ai/terms/withdraw", headers=tok)


@pytest.mark.ui
def test_cs_quick_actions(server, page, tmp_path_factory):
    """Trace, Big-O, Visualise, tests, practice and Explain my change send their action (and the diff)."""
    import json
    import os

    import app as A
    tok = {A.TOKEN_HEADER: A.SESSION_TOKEN}
    root = tmp_path_factory.mktemp("lab9")
    code = ["def find(xs, t):", "    for i, x in enumerate(xs):", "        if x == t:", "            return i",
            "    return -1", ""]
    (root / "search.py").write_text("\n".join(code), encoding="utf-8")
    terms = page.request.get(f"{server}/api/ai/terms").json()
    page.request.post(f"{server}/api/ai/terms/agree", headers=tok,
                      data={"version": terms["version"], "ticks": {k: True for k in terms["ticks"]}})
    page.request.put(f"{server}/api/ai/settings", headers=tok,
                     data={"provider": "ollama", "model": "qwen2.5:7b", "code_enabled": True})
    folder = page.request.post(f"{server}/api/code/folders", headers=tok, data={"path": str(root)}).json()
    nl = chr(10)
    say = "data: " + json.dumps({"choices": [{"delta": {"content": "| Step | Line | i | x |"}}]}) + nl + nl
    A.fake_net["POST localhost/v1/chat/completions"] = (200, say)

    def last_request():
        return json.loads([r for r in A.fake_net_seen if r.url.path.endswith("/chat/completions")][-1].content)

    try:
        page.goto(f"{server}/#/code")
        page.reload()
        page.wait_for_selector(".code-tree")
        if page.locator("#codeFolder").count():
            page.select_option("#codeFolder", str(folder["id"]))
        page.click(".tree-row >> text=search.py")
        page.wait_for_selector(".code-file-head >> text=search.py")
        assert page.locator(".chat-quick [data-kind=tests]").inner_text().strip() == "Plan tests"     # an Assignment
        for kind, task, said in (("trace", "dry-run table", "Trace search.py step by step"),
                                 ("big_o", "Big-O", "What's the Big-O of search.py?"),
                                 ("visualise", "Mermaid diagram", "Visualise the data structures in search.py"),
                                 ("tests", "Don't write the test code", "Help me plan tests for search.py"),
                                 ("practice", "Don't give the solution", "Give me a practice problem like search.py")):
            n = page.locator(".chat-msg.ai .chat-tools").count()
            page.click(f".chat-quick [data-kind={kind}]")
            page.wait_for_function(f"document.querySelectorAll('.chat-msg.ai .chat-tools').length > {n}")
            asked = last_request()
            assert task in asked["messages"][0]["content"] and said in asked["messages"][-1]["content"], kind

        # Explain my change: nothing changed yet, then an edit made outside the app
        page.click(".chat-quick [data-kind=explain_change]")
        page.wait_for_selector("#toast.show >> text=hasn't changed")
        (root / "search.py").write_text((root / "search.py").read_text().replace("return -1", "return None"), encoding="utf-8")
        n = page.locator(".chat-msg.ai .chat-tools").count()
        page.click(".chat-quick [data-kind=explain_change]")
        page.wait_for_function(f"document.querySelectorAll('.chat-msg.ai .chat-tools').length > {n}")
        system = last_request()["messages"][0]["content"]
        assert "Task: explain my change" in system and "-    return -1" in system and "+    return None" in system
        page.wait_for_selector(".code-text >> text=return None")                        # the viewer shows it as it is now
        # A long change: only its first part goes, and both the student and the assistant are told
        import ai.codediff
        ai.codediff.MAX_DIFF, kept = 40, ai.codediff.MAX_DIFF
        try:
            (root / "search.py").write_text((root / "search.py").read_text().replace("return None", "return -3"),
                                            encoding="utf-8")
            n = page.locator(".chat-msg.ai .chat-tools").count()
            page.click(".chat-quick [data-kind=explain_change]")
            page.wait_for_selector("#toast.show >> text=only its first part")
            page.wait_for_function(f"document.querySelectorAll('.chat-msg.ai .chat-tools').length > {n}")
            assert "only its first part is included" in last_request()["messages"][-1]["content"]
        finally:
            ai.codediff.MAX_DIFF = kept
        # Leaving for the Study page while it's being worked out: nothing is sent there
        sent = len([r for r in A.fake_net_seen if r.url.path.endswith("/chat/completions")])
        (root / "search.py").write_text((root / "search.py").read_text().replace("return None", "return -2"), encoding="utf-8")
        page.route("**/diff", lambda route: (page.wait_for_timeout(800), route.continue_()))
        page.click(".chat-quick [data-kind=explain_change]")
        page.evaluate("location.hash = '#/study'")
        page.wait_for_timeout(1500)
        page.unroute("**/diff")
        assert len([r for r in A.fake_net_seen if r.url.path.endswith("/chat/completions")]) == sent
        assert page.locator(".chat-msg.me").count() == 0
        if os.environ.get("EUT_SHOTS"):
            page.screenshot(path=os.path.join(os.environ["EUT_SHOTS"], "stage9-actions.png"))
    finally:                                                  # leave the shared server as it was
        page.evaluate("chatReset()")
        page.request.post(f"{server}/api/ai/terms/withdraw", headers=tok)
        A.fake_net.pop("POST localhost/v1/chat/completions", None)


@pytest.mark.ui
def test_saved_chats_quiz_and_videos(server, page):
    """A chat is kept after the reply, listed under Recent chats after a reload, and opens again. Quiz me shows
    answer buttons, Videos asks for YouTube searches, and a chat can be deleted."""
    import json
    import os

    import app as A
    tok = {A.TOKEN_HEADER: A.SESSION_TOKEN}
    terms = page.request.get(f"{server}/api/ai/terms").json()
    page.request.post(f"{server}/api/ai/terms/agree", headers=tok,
                      data={"version": terms["version"], "ticks": {k: True for k in terms["ticks"]}})
    page.request.put(f"{server}/api/ai/settings", headers=tok, data={"provider": "ollama", "model": "qwen2.5:7b"})
    for ch in page.request.get(f"{server}/api/ai/chats").json():                # start from no saved chats
        page.request.delete(f"{server}/api/ai/chats/{ch['id']}", headers=tok)
    nl = chr(10)

    def say(text):
        return "data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + nl + nl
    question = nl.join(["Question 1: What does a stack return first?", "A) The oldest item", "B) The newest item",
                        "C) A random item", "D) The smallest item"])
    A.fake_net["POST localhost/v1/chat/completions"] = (200, [say(question), say("Correct! Stacks are last in, first out."),
                                                              say("[Search YouTube: stacks](https://www.youtube.com/results?search_query=stack+data+structure)")])

    def last_request():
        return json.loads([r for r in A.fake_net_seen if r.url.path.endswith("/chat/completions")][-1].content)
    try:
        page.goto(f"{server}/#/study")
        page.reload()
        page.click("[data-action=chat-new]")
        page.click("[data-action=chat-mode][data-mode=quiz]")
        page.fill("#chatInput", "Quiz me on stacks")
        page.keyboard.press("Enter")
        page.wait_for_selector(".quiz-choices button >> text=B")
        assert "Mode: Quiz me" in last_request()["messages"][0]["content"]
        assert page.locator(".quiz-choices button").count() == 4
        page.click(".quiz-choices button >> text=B")
        page.wait_for_selector(".chat-msg.ai >> text=Correct!")
        assert last_request()["messages"][-1]["content"] == "B"
        page.click(".chat-msg.ai:last-child [data-action=chat-videos]")
        page.wait_for_selector(".chat-msg.ai a.link >> text=Search YouTube: stacks")
        assert "Task: suggest videos" in last_request()["messages"][0]["content"]
        page.wait_for_selector(".nav-chat >> text=Quiz me on stacks")
        for _ in range(100):                                    # saving happens just after each reply
            if [x["count"] for x in page.request.get(f"{server}/api/ai/chats").json()] == [6]:
                break
            page.wait_for_timeout(100)
        else:
            pytest.fail("The chat wasn't saved with all six messages")

        # After a reload the chat is still there, and opens with its messages and mode
        page.reload()
        page.wait_for_selector(".nav-chat >> text=Quiz me on stacks")
        page.click("[data-action=chat-new]")
        assert page.locator(".chat-msg").count() == 0
        page.click(".nav-chat >> text=Quiz me on stacks")
        page.wait_for_selector(".chat-msg.ai >> text=Correct!")
        assert page.locator(".chat-msg.me").count() == 3
        assert page.locator("[data-action=chat-mode].on").inner_text() == "Quiz me"
        if os.environ.get("EUT_SHOTS"):
            page.screenshot(path=os.path.join(os.environ["EUT_SHOTS"], "stage10-chats.png"))

        # Saves still queued for one chat can't land on another opened meanwhile
        other = page.request.post(f"{server}/api/ai/chats", headers=tok, data={"title": "Other chat", "messages": [
            {"role": "user", "content": "Other question"}, {"role": "assistant", "content": "Other answer"}]}).json()
        page.route("**/api/ai/chats/*", lambda route: (page.wait_for_timeout(1500), route.continue_())
                   if route.request.method == "PUT" else route.continue_())
        page.evaluate(f"async () => {{ chatSave(); chatSave(); await chatOpen({other['id']}); }}")
        page.wait_for_selector(".chat-msg.ai >> text=Other answer")
        page.wait_for_timeout(4000)
        page.unroute("**/api/ai/chats/*")
        kept = page.request.get(f"{server}/api/ai/chats/{other['id']}").json()
        assert [m["content"] for m in kept["messages"]] == ["Other question", "Other answer"]
        # A save for a chat deleted elsewhere doesn't clear the id of the chat opened meanwhile
        gone = page.request.post(f"{server}/api/ai/chats", headers=tok, data={"messages": [
            {"role": "user", "content": "Gone"}, {"role": "assistant", "content": "soon"}]}).json()
        page.evaluate(f"chatOpen({gone['id']})")
        page.wait_for_selector(".chat-msg.ai >> text=soon")
        page.request.delete(f"{server}/api/ai/chats/{gone['id']}", headers=tok)
        page.route("**/api/ai/chats/*", lambda route: (page.wait_for_timeout(1500), route.continue_())
                   if route.request.method == "PUT" else route.continue_())
        page.evaluate(f"async () => {{ chatSave(); await chatOpen({other['id']}); }}")
        page.wait_for_selector(".chat-msg.ai >> text=Other answer")
        page.wait_for_timeout(2500)
        page.unroute("**/api/ai/chats/*")
        assert page.evaluate("chatState().id") == other["id"]
        # Two chats clicked quickly: the second one shows, even if the first answers later
        slow = page.request.post(f"{server}/api/ai/chats", headers=tok, data={"messages": [
            {"role": "user", "content": "Slow one"}, {"role": "assistant", "content": "slow answer"}]}).json()
        page.route(f"**/api/ai/chats/{slow['id']}", lambda route: (page.wait_for_timeout(1500), route.continue_())
                   if route.request.method == "GET" else route.continue_())
        page.evaluate(f"chatOpen({slow['id']}); chatOpen({other['id']})")
        page.wait_for_selector(".chat-msg.ai >> text=Other answer")
        page.wait_for_timeout(2500)
        page.unroute(f"**/api/ai/chats/{slow['id']}")
        assert page.evaluate("chatState().id") == other["id"] and page.locator(".chat-msg.ai >> text=slow answer").count() == 0
        # New chat while one is still opening: the new chat stays
        page.route(f"**/api/ai/chats/{slow['id']}", lambda route: (page.wait_for_timeout(1500), route.continue_())
                   if route.request.method == "GET" else route.continue_())
        page.evaluate(f"() => {{ chatOpen({slow['id']}); }}")           # not waited for: it's still loading
        page.click("[data-action=chat-new]")
        page.wait_for_timeout(2500)
        page.unroute(f"**/api/ai/chats/{slow['id']}")
        assert page.evaluate("chatState().id") is None and page.locator(".chat-msg").count() == 0
        page.request.delete(f"{server}/api/ai/chats/{slow['id']}", headers=tok)
        page.request.delete(f"{server}/api/ai/chats/{other['id']}", headers=tok)
        page.evaluate("loadChats()")

        # A very long chat keeps saving (the newest 400 messages, the server's limit)
        long = page.evaluate("""async () => {
            chatReset();
            const c = chatState();
            for (let i = 0; i < 230; i++) {
                c.messages.push({ role: 'user', content: 'q' + i }, { role: 'assistant', content: 'a' + i });
            }
            await chatSave();
            return c.id;
        }""")
        saved = page.request.get(f"{server}/api/ai/chats/{long}").json()["messages"]
        assert len(saved) == 400 and saved[-1]["content"] == "a229"
        page.request.delete(f"{server}/api/ai/chats/{long}", headers=tok)
        page.evaluate("chatReset(); loadChats()")

        # The Chats list, and deleting one
        page.click("[data-action=chats-all]")
        page.wait_for_selector("#drawer .chat-list-row >> text=Quiz me on stacks")
        page.click("#drawer [data-action=chat-delete]")
        page.click("#confirmYes")
        page.wait_for_selector("#drawer >> text=No saved chats yet")
        assert page.request.get(f"{server}/api/ai/chats").json() == []
    finally:
        page.evaluate("chatReset()")
        page.request.post(f"{server}/api/ai/terms/withdraw", headers=tok)
        A.fake_net.pop("POST localhost/v1/chat/completions", None)


@pytest.mark.ui
def test_attached_files(server, page):
    """A PDF is attached with the paperclip: only the pages that fit Ollama's context go (and the page says so), the
    range can be changed, Summarise sends the chosen pages, the file stays with the saved chat, and files can be
    dropped on the chat. Unreadable files are explained."""
    import json
    import os

    import app as A
    from test_attachments import make_pdf
    tok = {A.TOKEN_HEADER: A.SESSION_TOKEN}
    terms = page.request.get(f"{server}/api/ai/terms").json()
    page.request.post(f"{server}/api/ai/terms/agree", headers=tok,
                      data={"version": terms["version"], "ticks": {k: True for k in terms["ticks"]}})
    page.request.put(f"{server}/api/ai/settings", headers=tok, data={"provider": "ollama", "model": "qwen2.5:7b"})
    nl = chr(10)

    def say(text):
        return "data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + nl + nl
    # Ollama reads 4,096 tokens at once here: about 6,500 characters, so two of the four pages fit
    A.fake_net["GET localhost/api/ps"] = (200, {"models": [{"name": "qwen2.5:7b", "context_length": 4096}]})
    A.fake_net["POST localhost/v1/chat/completions"] = (200, [say("Pages 3 and 4 cover heaps."), say("Heaps again."),
                                                              say("Notes on heaps.")])
    pdf = make_pdf([f"Page {n} topic {name} " + "word " * 500 for n, name in
                    enumerate(["stacks", "queues", "heaps", "tries"], 1)])

    def last_request():
        return json.loads([r for r in A.fake_net_seen if r.url.path.endswith("/chat/completions")][-1].content)
    page.errors.clear()                                         # only this test's
    try:
        page.goto(f"{server}/#/study")
        page.reload()
        page.click("[data-action=chat-new]")
        page.fill("#chatInput", "What is on page 3?")
        page.set_input_files("#chatFile", files=[{"name": "Week 3.pdf", "mimeType": "application/pdf", "buffer": pdf}])
        page.wait_for_selector(".chat-file-head >> text=Week 3.pdf")
        chip = page.locator(".chat-file")
        assert "Pages 1–2" in chip.inner_text() and "too long for one question" in chip.inner_text()
        assert "raise Context length in Ollama's settings (it's 4,096 tokens now)" in chip.inner_text()
        assert page.input_value("#chatInput") == "What is on page 3?"              # what was typed is kept
        # More than fits: a warning, and Send waits
        page.select_option("[data-file-range=to]", label="Page 4")
        page.wait_for_selector(".chat-file.over >> text=more than Ollama can read with one question")
        assert page.locator("#chatForm [type=submit]").is_disabled()
        # Starting from page 3 takes as many pages as fit from there
        page.select_option("[data-file-range=from]", label="Page 3")
        page.wait_for_selector(".chat-file:not(.over) >> text=Pages 3–4")
        assert page.input_value("[data-file-range=to]") == "3" and not page.locator("#chatForm [type=submit]").is_disabled()
        if os.environ.get("EUT_SHOTS"):
            page.screenshot(path=os.path.join(os.environ["EUT_SHOTS"], "stage11-attach.png"))
        page.fill("#chatInput", "")
        page.click("[data-action=chat-file-ask][data-kind=summary]")
        page.wait_for_selector(".chat-msg.ai >> text=Pages 3 and 4 cover heaps.")
        system = last_request()["messages"][0]["content"]
        assert "attached a file: Week 3.pdf (Pages 3–4)" in system and "[Page 3]" in system and "[Page 1]" not in system
        assert last_request()["messages"][-1]["content"].startswith("Summarise the attached file")
        for _ in range(100):                                    # saved with the chat
            chats = page.request.get(f"{server}/api/ai/chats").json()
            if chats and chats[0]["attachment_name"] == "Week 3.pdf":
                break
            page.wait_for_timeout(100)
        else:
            pytest.fail("The chat wasn't saved with its file")

        # Reopened later, the file's chosen pages still go with each question
        page.reload()
        page.click(".nav-chat >> text=Summarise the attached file")
        page.wait_for_selector(".chat-file >> text=Pages 3–4")
        assert page.locator("[data-file-range]").count() == 0                     # the other pages weren't kept
        page.click("[data-action=chat-file-ask][data-kind=quiz]")
        page.wait_for_selector(".chat-msg.ai >> text=Heaps again.")
        assert page.locator("[data-action=chat-mode].on").inner_text() == "Quiz me"
        assert "[Page 4]" in last_request()["messages"][0]["content"]
        page.click("[data-action=chat-file-ask][data-kind=notes]")
        page.wait_for_selector(".chat-msg.ai >> text=Notes on heaps.")
        assert "Mode: Notes" in last_request()["messages"][0]["content"]
        assert page.locator("[data-action=chat-mode].on").inner_text() == "Quiz me"   # notes are written once
        chat_id = page.evaluate("chatState().id")
        page.click("[data-action=chat-file-remove]")
        assert page.locator(".chat-file").count() == 0
        for _ in range(100):
            if page.request.get(f"{server}/api/ai/chats/{chat_id}").json()["attachment"] is None:
                break
            page.wait_for_timeout(100)
        else:
            pytest.fail("Removing the file didn't save")

        # A file dropped on the chat is attached; an old Word file is explained
        page.evaluate("""() => {
            const dt = new DataTransfer();
            dt.items.add(new File(['Queues are first in, first out.'], 'queues.txt', { type: 'text/plain' }));
            const drop = new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true });
            document.querySelector('#chatLog').dispatchEvent(drop);
        }""")
        page.wait_for_selector(".chat-file-head >> text=queues.txt")
        assert page.locator("[data-file-range]").count() == 0                     # one section: nothing to choose
        assert not page.errors, page.errors
        page.set_input_files("#chatFile", files=[{"name": "old.doc", "mimeType": "application/msword", "buffer": b"x"}])
        page.wait_for_selector(".toast >> text=Save it as PDF, .docx or .pptx")
        assert page.locator(".chat-file >> text=queues.txt").count() == 1          # the attached file stays
        page.click("[data-action=chat-new]")
        assert page.locator(".chat-file").count() == 0
        assert [e for e in page.errors if "status of 400" not in e] == []         # only the refused .doc file
        page.errors.clear()
    finally:
        page.evaluate("chatReset()")
        for ch in page.request.get(f"{server}/api/ai/chats").json():
            page.request.delete(f"{server}/api/ai/chats/{ch['id']}", headers=tok)
        page.request.post(f"{server}/api/ai/terms/withdraw", headers=tok)
        A.fake_net.pop("POST localhost/v1/chat/completions", None)
        A.fake_net.pop("GET localhost/api/ps", None)


@pytest.mark.ui
def test_long_chats_keep_chats_and_linked_folders(server, page, tmp_path_factory):
    """A long chat's older messages are summarised for the assistant (and the summary is shown and saved); Keep
    chats deletes older chats after asking; code folders can be linked from a subject and managed in Settings."""
    import json

    import app as A
    tok = {A.TOKEN_HEADER: A.SESSION_TOKEN}
    terms = page.request.get(f"{server}/api/ai/terms").json()
    page.request.post(f"{server}/api/ai/terms/agree", headers=tok,
                      data={"version": terms["version"], "ticks": {k: True for k in terms["ticks"]}})
    page.request.put(f"{server}/api/ai/settings", headers=tok,
                     data={"provider": "ollama", "model": "qwen2.5:7b", "code_enabled": True})
    nl = chr(10)

    def say(text):
        return "data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + nl + nl
    A.fake_net["POST localhost/v1/chat/completions"] = (200, [say("Answer 13."), say("Answer 14."),
                                                              say("The student revised stacks and heaps."), say("Answer 15.")])

    def requests():
        return [json.loads(r.content) for r in A.fake_net_seen if r.url.path.endswith("/chat/completions")]
    page.errors.clear()
    try:
        page.goto(f"{server}/#/study")
        page.reload()
        page.click("[data-action=chat-new]")
        page.evaluate("""() => {
            const c = chatState();
            for (let i = 1; i <= 12; i++) {
                c.messages.push({ role: 'user', content: 'Question ' + i }, { role: 'assistant', content: 'Answer ' + i + '.' });
            }
            chatRefresh();
        }""")
        seen = len(requests())

        def ask(text, answer):
            page.fill("#chatInput", text)
            page.keyboard.press("Enter")
            page.wait_for_selector(f".chat-msg.ai >> text={answer}")
            page.wait_for_function("!chatState().streaming")

        # Six messages have left the 20-message window, so a summary is due after the reply. If it fails, the
        # messages it would have covered still go with the next question: nothing is left out
        page.route("**/api/ai/summarise", lambda route: route.fulfill(status=502, json={"detail": "Ollama isn't running."}))
        ask("Question 13", "Answer 13.")
        page.wait_for_function("!chatState().summarising")
        page.unroute("**/api/ai/summarise")
        page.route("**/api/ai/summarise", lambda route: (page.wait_for_timeout(1500), route.continue_()))
        ask("Question 14", "Answer 14.")
        asked = requests()[seen:]
        assert len(asked) == 2 and [m["content"] for m in asked[1]["messages"][1:3]] == ["Question 1", "Answer 1."]
        assert len(asked[1]["messages"]) == 1 + 27 and "Summary of the earlier part" not in asked[1]["messages"][0]["content"]
        # The summary is being made now (slowly): a question asked meanwhile waits for it, then goes with it
        assert page.evaluate("chatState().summarising") is True
        ask("Question 15", "Answer 15.")
        page.unroute("**/api/ai/summarise")
        asked = requests()[seen:]
        assert len(asked) == 4 and asked[2]["messages"][0]["content"].startswith("You keep a running summary")
        folded = asked[2]["messages"][1]["content"]
        assert "Student: Question 1" in folded and "Assistant: Answer 4." in folded and "Question 5" not in folded
        system = asked[3]["messages"][0]["content"]
        assert "Summary of the earlier part of this chat" in system and "The student revised stacks and heaps." in system
        # ...in place of the eight messages it covers: the rest still go as they are
        assert [m["content"] for m in asked[3]["messages"][1:2]] == ["Question 5"] and len(asked[3]["messages"]) == 1 + 21
        page.wait_for_selector(".chat-summary >> text=Earlier messages are summarised for the assistant")
        page.click(".chat-summary > summary")
        page.wait_for_selector(".chat-summary[open] >> text=The student revised stacks and heaps.")
        chat_id = None
        for _ in range(100):                                                    # saved with the chat
            chat_id = page.evaluate("chatState().id")
            if chat_id and page.request.get(f"{server}/api/ai/chats/{chat_id}").json().get("summary"):
                break
            page.wait_for_timeout(100)
        else:
            pytest.fail("The summary wasn't saved")
        saved = page.request.get(f"{server}/api/ai/chats/{chat_id}").json()
        assert sum(1 for m in saved["messages"] if m["meta"].get("summarised")) == 8

        # Keep chats: choosing a limit asks first, then deletes chats not continued for that long
        with A.db() as conn:
            conn.execute("UPDATE conversations SET updated_at=datetime('now', 'localtime', '-60 days') WHERE id=?", (chat_id,))
        page.evaluate("chatReset()")
        page.goto(f"{server}/#/settings")
        page.wait_for_selector("#aiKeepChats")
        page.select_option("#aiKeepChats", label="1 month")
        page.wait_for_selector("#confirm >> text=Delete older chats?")
        page.click("#confirmYes")
        page.wait_for_selector("#toast.show >> text=Deleted 1 older chat")
        assert page.request.get(f"{server}/api/ai/chats/{chat_id}").status == 404
        assert page.request.get(f"{server}/api/ai/state").json()["keep_chats_days"] == 30
        page.select_option("#aiKeepChats", label="Until I delete them")             # longer: nothing to ask
        page.wait_for_selector("#toast.show >> text=Chats are kept until you delete them")

        # Linking a code folder from a subject, then managing it in Settings
        root = tmp_path_factory.mktemp("assignment2")
        (root / "main.py").write_text("print('hi')\n", encoding="utf-8")
        subject = page.request.post(f"{server}/api/subjects", headers=tok, data={"name": "COMP2123 Data Structures"}).json()
        page.evaluate("loadAll()")
        page.wait_for_selector("#nav")
        page.goto(f"{server}/#/subjects")
        card = page.locator(".subject", has_text="COMP2123")
        card.locator("text=Link the folder with your code for this subject").wait_for()
        card.locator("[data-action=code-link-subject]").click()
        page.wait_for_selector("#drawerForm[data-kind=code-folder]")
        assert page.input_value("#drawerForm [name=subject_id]") == str(subject["id"])
        page.fill("#drawerForm [name=path]", str(root))
        page.click("#drawerFoot [type=submit]")
        page.wait_for_selector(".code-tree .tree-row >> text=main.py")
        page.goto(f"{server}/#/subjects")
        page.locator(".subject", has_text="COMP2123").locator(".note-row >> text=assignment2").click()
        page.wait_for_selector(".code-tree .tree-row >> text=main.py")
        page.goto(f"{server}/#/settings")
        row = page.locator(".linked-folder", has_text="assignment2")
        row.wait_for()
        assert "COMP2123 Data Structures" in row.inner_text()
        row.locator("[data-action=code-unlink]").click()
        page.click("#confirmYes")
        row.wait_for(state="detached")
        assert all(f["name"] != "assignment2" for f in page.request.get(f"{server}/api/code/folders").json())
        assert (root / "main.py").exists()                                       # the files themselves stay
        assert [e for e in page.errors if "status of 502" not in e] == []          # only the summary made to fail
        page.errors.clear()
    finally:
        page.evaluate("chatReset()")
        for ch in page.request.get(f"{server}/api/ai/chats").json():
            page.request.delete(f"{server}/api/ai/chats/{ch['id']}", headers=tok)
        for f in page.request.get(f"{server}/api/code/folders").json():
            page.request.delete(f"{server}/api/code/folders/{f['id']}", headers=tok)
        page.request.put(f"{server}/api/ai/settings", headers=tok, data={"keep_chats_days": 0, "code_enabled": False})
        page.request.post(f"{server}/api/ai/terms/withdraw", headers=tok)
        A.fake_net.pop("POST localhost/v1/chat/completions", None)
