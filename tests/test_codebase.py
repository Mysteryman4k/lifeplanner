"""v4 stage 6: linked folders. What's hidden, path safety, the tree, languages and choosing files to send."""
import os
from pathlib import Path

import pytest

from ai.codebase import CodeError, Folder, GitIgnore, language, link_problem


def make(root: Path, files: dict):
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")


@pytest.fixture()
def project(tmp_path):
    make(tmp_path, {
        "main.py": "from helpers import add\nimport utils.maths\n\nprint(add(1, 2))\n",
        "helpers.py": "def add(a, b):\n    return a + b\n",
        "utils/__init__.py": "",
        "utils/maths.py": "PI = 3.14\n",
        ".env": "API_KEY=secret\n",
        "config/prod.env": "X=1\n",
        "server.pem": "-----BEGIN-----\n",
        "id_rsa": "key\n",
        "secrets.json": "{}\n",
        "node_modules/lib/index.js": "x\n",
        "venv/lib/site.py": "x\n",
        "logo.png": b"\x89PNG\x00\x00binary",
        "big.txt": "x" * (200 * 1024 + 1),
        ".gitignore": "*.log\n/output/\ndata/**/*.csv\n!data/keep.csv\nnotes/\n",
        "run.log": "log\n",
        "output/result.txt": "r\n",
        "src/output/real.py": "ok = 1\n",
        "data/a/b.csv": "1,2\n",
        "data/keep.csv": "k\n",
        "notes/todo.md": "t\n",
        "lib/.gitignore": "generated.py\n",
        "lib/generated.py": "g = 1\n",
        "lib/kept.py": "k = 1\n",
        "web/app.js": "import { f } from './util'\nconst g = require('../shared/g.js')\n",
        "web/util.js": "export const f = 1\n",
        "shared/g.js": "module.exports = 1\n",
        "c/main.c": '#include "list.h"\n#include <stdio.h>\nint main() { return 0; }\n',
        "c/list.h": "int len(void);\n",
        "Queries.sql": "SELECT 1;\n",
    })
    return Folder(str(tmp_path))


def flat(tree):
    out = {}

    def walk(nodes):
        for n in nodes:
            out[n["path"]] = n
            walk(n.get("children") or [])
    walk(tree["children"])
    return out


def test_secrets_dependencies_binary_big_and_gitignored_files_are_hidden(project):
    t = flat(project.tree())
    hidden = {p: n["hidden"] for p, n in t.items() if n["hidden"]}
    assert hidden[".env"] == hidden["config/prod.env"] == hidden["server.pem"] == "may contain secrets"
    assert hidden["id_rsa"] == hidden["secrets.json"] == "may contain secrets"
    assert hidden["node_modules"] == hidden["venv"] == "build or dependency folder"
    assert "node_modules/lib/index.js" not in t                          # hidden folders aren't opened
    assert hidden["big.txt"] == "over 200 KB"
    for p in ("run.log", "output", "data/a/b.csv", "notes", "lib/generated.py"):
        assert hidden[p] == "in .gitignore", p
    for p in ("main.py", "src/output/real.py", "data/keep.csv", "lib/kept.py", "Queries.sql"):
        assert not t[p]["hidden"], p                                      # anchored /output/, '!' and nested rules
    with pytest.raises(CodeError, match="binary"):
        project.read("logo.png")
    for p in (".env", "server.pem", "node_modules/lib/index.js", "output/result.txt", "notes/todo.md",
              "lib/generated.py", "big.txt", "data/a/b.csv"):
        with pytest.raises(CodeError, match="hidden"):
            project.read(p)


def test_paths_outside_the_folder_are_refused(project, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.py").write_text("x = 1\n")
    for bad in ("../secret.py", "utils/../../secret.py", str(outside / "secret.py"), "C:/Windows/win.ini",
                "/etc/passwd", ""):
        with pytest.raises(CodeError):
            project.read(bad)
    assert project.read("utils/../helpers.py".replace("utils/../", "")).startswith("def add")


def test_a_link_out_of_the_folder_is_refused(project, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere")
    (outside / "x.py").write_text("x = 1\n")
    try:
        os.symlink(outside, project.root / "linked", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("can't make symlinks here")
    with pytest.raises(CodeError, match="outside"):
        project.read("linked/x.py")
    assert flat(project.tree())["linked"]["hidden"] == "links outside the folder"


def test_languages_and_tiers():
    assert language("Main.java") == {"language": "Java", "tier": 1, "highlight": "java"}
    assert language("main.go")["tier"] == 2 and language("q.sql")["tier"] == 3
    assert language("Makefile")["language"] == "Makefile" and language("weird.xyz")["tier"] == 3


def test_choosing_files_open_file_imports_and_errors(project):
    chosen = project.choose("", "main.py")
    assert [f["path"] for f in chosen["files"]] == ["main.py", "helpers.py", "utils/maths.py"]
    assert chosen["files"][1]["why"] == "used by main.py"
    tb = 'Traceback (most recent call last):\n  File "C:\\Users\\me\\proj\\helpers.py", line 2, in add\nTypeError'
    chosen = project.choose(tb, "lib/kept.py")
    assert [f["path"] for f in chosen["files"]][:2] == ["lib/kept.py", "helpers.py"]
    assert chosen["files"][1]["why"] == "named in your message"
    js = [f["path"] for f in project.choose("", "web/app.js")["files"]]
    assert js == ["web/app.js", "web/util.js", "shared/g.js"]
    assert [f["path"] for f in project.choose("", "c/main.c")["files"]] == ["c/main.c", "c/list.h"]
    # The student's changes win: removed files stay out, pinned ones go first, hidden ones never go
    chosen = project.choose("see .env and server.pem", "main.py", pinned=["Queries.sql", ".env"], removed=["helpers.py"])
    assert [f["path"] for f in chosen["files"]] == ["Queries.sql", "main.py", "utils/maths.py"]
    assert any(x["path"] == ".env" and "hidden" in x["why"] for x in chosen["left_out"])


def test_the_size_budget(project, monkeypatch):
    import ai.codebase as cb
    monkeypatch.setattr(cb, "SEND_BUDGET", 70)
    chosen = project.choose("", "main.py")
    assert [f["path"] for f in chosen["files"]] == ["main.py"]
    assert {x["path"] for x in chosen["left_out"]} == {"helpers.py", "utils/maths.py"}


def test_the_context_has_line_numbers(project):
    text, sent, left_out = project.context(["helpers.py", "logo.png", ".env"])
    assert [x["path"] for x in left_out] == ["logo.png", ".env"] and "binary" in left_out[0]["why"]
    assert sent == ["helpers.py"] and "--- helpers.py (Python) ---" in text and "   2|     return a + b" in text


def test_the_file_count_limit_is_reported_as_such(project, monkeypatch):
    import ai.codebase as cb
    monkeypatch.setattr(cb, "MAX_SEND_FILES", 1)
    _, sent, left_out = project.context(["helpers.py", "main.py"])
    assert sent == ["helpers.py"] and left_out == [{"path": "main.py", "why": "only 1 files go with one message"}]


def test_names_in_a_long_error_walk_the_folder_once(project, monkeypatch):
    calls = []
    real = os.walk
    monkeypatch.setattr(os, "walk", lambda *a, **k: calls.append(1) or real(*a, **k))
    log = "".join(f'  File "x{i}.py", line 1\n' for i in range(300)) + 'File "helpers.py", line 2'
    assert project.referenced(log) == ["helpers.py"] and len(calls) == 1


def test_names_in_errors_match_whole_path_segments(tmp_path):
    make(tmp_path, {"ab/x.py": "a = 1\n", "src/b/x.py": "b = 1\n", "app/main.py": "m = 1\n"})
    f = Folder(str(tmp_path))
    assert f._find("b/x.py") == "src/b/x.py"                  # not ab/x.py, which only ends with the same text
    assert f._find("other/x.py") is None
    assert f._find("lab3/app/main.py") == "app/main.py"       # a longer path from somewhere else still matches


def test_gitignore_rules():
    g = GitIgnore()
    g.add_file("", "build\n*.o\n/top.txt\ndocs/**/draft*\n!docs/keep/draft1.md\n# comment\n")
    assert g.ignored("build", True) and g.ignored("src/build", True) and g.ignored("a/b.o", False)
    assert g.ignored("top.txt", False) and not g.ignored("src/top.txt", False)
    assert g.ignored("docs/x/y/draft2.md", False) and not g.ignored("docs/keep/draft1.md", False)


def test_which_folders_can_be_linked(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (tmp_path / "proj").mkdir()
    assert link_problem(str(tmp_path / "proj"), data) == ""
    assert "can't be found" in link_problem(str(tmp_path / "nope"), data)
    assert "full folder path" in link_problem("proj", data)
    assert "whole drive" in link_problem(Path(tmp_path.anchor).as_posix(), data)
    assert "user folder" in link_problem(str(Path.home()), data)
    assert "own data" in link_problem(str(data), data) and "own data" in link_problem(str(tmp_path), data)
