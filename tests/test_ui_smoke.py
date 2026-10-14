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

    # 150 earlier messages: the request carries only the last 20, starting with the student's
    page.evaluate("""() => { chatReset(); const c = chatState();
        for (let i = 0; i < 150; i++) c.messages.push({ role: i % 2 ? 'assistant' : 'user', content: 'm' + i }); }""")
    page.evaluate("chatSend('latest question')")
    page.wait_for_function("!chatState().streaming")
    body = json.loads([r for r in A.fake_net_seen if r.url.path.endswith("/chat/completions")][-1].content)
    sent = body["messages"][1:]                                    # after the system prompt
    assert len(sent) <= 20 and sent[0]["role"] == "user" and sent[-1]["content"] == "latest question"
    assert not any(e for e in page.errors if "422" in e)

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
