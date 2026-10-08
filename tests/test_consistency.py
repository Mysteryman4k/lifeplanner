"""Static checks that catch the mistakes that are easy to make while adding features:
a button whose action has no handler, a call to a server route that doesn't exist, an icon that
isn't drawn, or a page file that isn't versioned (and so could be served stale after an update)."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
STATIC = ROOT / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def actions_used():
    used = set(re.findall(r'data-action="([a-z][a-z0-9-]*)"', APP_JS + INDEX))
    used |= set(re.findall(r"\bbtn\('([a-z][a-z0-9-]*)'", APP_JS))          # btn('export', ...)
    used |= set(re.findall(r"\bfooter\('([a-z][a-z0-9-]*)'", APP_JS))       # footer('delete-task')
    used |= set(re.findall(r"\? '(delete-[a-z0-9-]+)' : ''", APP_JS))       # footer(id ? 'delete-x' : '')
    return used


def actions_handled():
    block = APP_JS[APP_JS.index("const ACTIONS = {"):]
    block = block[:block.index("\n};")]
    keys = set(re.findall(r"^\s{2}(?:async\s+)?'([a-z0-9-]+)'\s*[:(]", block, re.M))
    keys |= set(re.findall(r"^\s{2}(?:async\s+)?([a-zA-Z]+)\s*[:(]", block, re.M))
    return keys


def test_every_button_action_has_a_handler():
    missing = actions_used() - actions_handled()
    assert not missing, f"data-action with no handler in ACTIONS: {sorted(missing)}"


def test_every_api_call_matches_a_server_route():
    import app
    routes = [(r.path, getattr(r, "methods", set())) for r in app.app.routes if r.path.startswith("/api/")]
    patterns = [(re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", p) + "$"), m) for p, m in routes]
    calls = re.findall(r"api\(\s*[`'](/api/[^`'?]*)[^`']*[`'](?:\s*\+[^,)]*)?\s*(?:,\s*\{\s*method:\s*'([A-Z]+)')?", APP_JS)
    assert len(calls) > 20, "the API call pattern stopped matching app.js"
    bad = []
    for path, method in calls:
        concrete = re.sub(r"\$\{[^}]+\}", "1", path)
        method = method or "GET"
        if not any(rx.match(concrete) and method in m for rx, m in patterns):
            bad.append(f"{method} {path}")
    assert not bad, f"app.js calls routes the server doesn't have: {bad}"


def test_every_icon_used_is_drawn():
    icons_js = (STATIC / "icons.js").read_text(encoding="utf-8")
    drawn = set(re.findall(r"^\s{2}([a-z0-9]+):", icons_js, re.M))
    used = set(re.findall(r"icon\('([a-z0-9]+)'", APP_JS)) | set(re.findall(r"btn\('[^']+', '[^']*', '([a-z0-9]+)'", APP_JS))
    missing = used - drawn
    assert not missing, f"icons used but not in icons.js: {sorted(missing)}"


def test_every_script_and_stylesheet_in_the_page_exists_and_gets_versioned():
    import app
    from fastapi.testclient import TestClient
    page = TestClient(app.app).get("/").text
    for ref in re.findall(r'(?:src|href)="(/static/[^"]+\.(?:js|css))', INDEX):
        assert (ROOT / ref.lstrip("/")).exists(), ref
        assert f'{ref}?v={app.APP_VERSION}"' in page, f"{ref} isn't versioned, so it could be served stale after an update"

