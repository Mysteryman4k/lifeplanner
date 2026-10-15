#!/usr/bin/env python3
"""Write TERMS.md from the in-app terms (ai/terms.py), so the published copy always matches what students
agree to in the app. A test (tests/test_terms_md.py) fails if TERMS.md is out of date.

  python tools/terms_md.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def render() -> str:
    from ai import terms
    lines = [
        "# EasyUniTrack AI features: terms of use",
        "",
        f"_Version {terms.TERMS_VERSION}_",
        "",
        "These are the terms you agree to in EasyUniTrack before using the AI features: the study assistant and the "
        "code workspace. The app shows the same text (Settings > AI study assistant and code workspace). They're off "
        "until you agree, and the rest of EasyUniTrack doesn't need them.",
        "",
        "This file is generated from `ai/terms.py` by `tools/terms_md.py`. Don't edit it by hand.",
        "",
        "## Before you start",
        "",
        *[f"- **{title}.** {text}" for title, text in terms.ABOUT],
        "",
        "## Terms",
        "",
    ]
    for title, text in terms.TERMS:
        lines += [f"### {title}", "", text, ""]
    lines += ["## Agreeing", "", "To agree, you tick all three:", "",
              *[f"- {text}" for text in terms.TICKS.values()], "",
              "The agreement is saved only on your PC and isn't included in backups. If these terms change, "
              "EasyUniTrack asks you to agree again.", ""]
    return "\n".join(lines)


def main():
    (ROOT / "TERMS.md").write_text(render(), encoding="utf-8", newline="\n")
    print("wrote TERMS.md")


if __name__ == "__main__":
    main()
