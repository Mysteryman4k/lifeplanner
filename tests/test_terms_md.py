"""v4 stage 12: TERMS.md is the in-app terms, word for word, so the published copy can't drift from what students
agree to."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import terms_md  # noqa: E402

from ai import terms  # noqa: E402


def test_terms_md_matches_the_app():
    published = (ROOT / "TERMS.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert published == terms_md.render(), "TERMS.md is out of date: run python tools/terms_md.py"


def test_every_term_and_tick_is_in_it():
    text = terms_md.render()
    assert f"_Version {terms.TERMS_VERSION}_" in text
    for title, body in [*terms.ABOUT, *terms.TERMS]:
        assert title in text and body in text
    assert all(tick in text for tick in terms.TICKS.values())


def test_replies_are_kept_suitable_for_the_store():
    """Microsoft Store Policies 11.16: live generative AI content must follow the Store's content policies (and each
    reply has a Report button, tested in test_ui_smoke)."""
    from ai import prompts
    for system in (prompts.system_prompt("explain"), prompts.system_prompt("quiz", action="videos"),
                   prompts.code_prompt("personal", "proj", "", "")):
        assert "suitable for a general audience of students" in system
        assert "sexual, hateful, harassing or\n  graphic violent content" in system
