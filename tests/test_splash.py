"""The desktop start-up screen: it must build for every look, and match the app's hand-off overlay."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
sys.path.insert(0, str(ROOT))
from desktop import STYLE_FONTS, build_splash_html  # noqa: E402

THEMES = ["sunset", "midnight", "cobalt", "ocean", "berry", "graphite"]


def intro_markup(html: str) -> str:
    m = re.search(r"<!-- intro:start -->(.*?)<!-- intro:end -->", html, re.S)
    assert m, "intro markers missing"
    return m.group(1)


def test_splash_and_app_overlay_use_identical_markup():
    """If these drift apart, the hand-off from splash to app visibly jumps."""
    splash = (STATIC / "splash.html").read_text(encoding="utf-8")
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert intro_markup(splash) == intro_markup(index)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("font", list(STYLE_FONTS))
def test_splash_builds_for_every_look(theme, font):
    html = build_splash_html(STATIC, {"theme": theme, "font": font, "mode": "dark"}, True, "9.9.9")
    assert "{{" not in html, "a placeholder was left unfilled"
    assert STYLE_FONTS[font][0] in html and "Version 9.9.9" in html
    assert 'class="intro play"' in html


def test_quick_splash_when_intro_is_off():
    html = build_splash_html(STATIC, {"theme": "sunset", "font": "rounded", "mode": "light"}, False, "1.0.0")
    assert 'class="intro quick"' in html


def test_text_style_fonts_match_theme_js():
    theme_js = (STATIC / "theme.js").read_text(encoding="utf-8")
    for key, (family, file) in STYLE_FONTS.items():
        assert re.search(rf"{key}:\s*\{{[^}}]*display:\s*'{re.escape(family)}'", theme_js), key
        assert (STATIC / "fonts" / file).exists(), file
