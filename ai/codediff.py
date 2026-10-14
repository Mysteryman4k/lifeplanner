"""What changed in a file: since the last git commit, or since the student opened it in this session.

For "Explain my change". Git is used only to read the committed copy (`git cat-file`), never `git diff`:
a project downloaded from the internet can set up filters, diff drivers or a file-system monitor in its own
git config, and `git diff` would run those programs. Reading a blob runs none of them, and the comparison is
made here.
"""
import difflib
import os
import shutil
import subprocess

from .codebase import MAX_FILE, CodeError, Folder

MAX_DIFF = 20_000                  # characters of diff sent with a question


def _git(root, *args, binary: bool = False):
    """Run git in the folder, with nothing from the repo's config that could start another program."""
    from .runner import clean_env
    git = shutil.which("git")
    if not git:
        return None
    env = {**clean_env(), "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
    try:
        r = subprocess.run([git, "-C", str(root), "-c", "core.fsmonitor=false", "-c", "core.hooksPath=",
                            "--no-pager", *args], capture_output=True, timeout=10, env=env,
                           creationflags=0x08000000 if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r if binary else (r.returncode, r.stdout.decode("utf-8", errors="replace").strip())


def committed(folder: Folder, rel: str):
    """The file as it was in the last commit: (text, "") / (None, "new") if it's not in the last commit /
    (None, "") if this isn't a git repository (or git isn't installed)."""
    r = _git(folder.root, "rev-parse", "--is-inside-work-tree")
    if not r or r[0] != 0 or r[1] != "true":
        return None, ""
    spec = f"HEAD:./{rel}"
    exists = _git(folder.root, "cat-file", "-e", spec)
    if not exists or exists[0] != 0:
        return None, "new"
    blob = _git(folder.root, "cat-file", "blob", spec, binary=True)
    if blob is None or blob.returncode != 0 or len(blob.stdout) > MAX_FILE or b"\x00" in blob.stdout[:8192]:
        return None, ""
    return blob.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n"), ""


def changes(folder: Folder, rel: str, baseline: str = None) -> dict:
    """{"source": "git" | "opened" | "none", "diff": unified diff text, "truncated": bool}. The file must be one
    that can be read and sent (hidden files are refused)."""
    now = folder.read(rel)                                # refuses hidden, binary, outside paths
    old, state = committed(folder, rel)
    if old is not None or state == "new":
        source, before, label = "git", old or "", "last commit"
    elif baseline is not None:
        source, before, label = "opened", baseline.replace("\r\n", "\n"), "when opened"
    else:
        return {"source": "none", "diff": "", "truncated": False}
    diff = "\n".join(difflib.unified_diff(before.split("\n"), now.split("\n"), f"{rel} ({label})", f"{rel} (now)",
                                          lineterm="", n=3))
    return {"source": source, "diff": diff[:MAX_DIFF], "truncated": len(diff) > MAX_DIFF,
            "new_file": state == "new"}


__all__ = ["changes", "committed", "CodeError"]
