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
import threading

from .codebase import MAX_FILE, CodeError, Folder

MAX_DIFF = 20_000                  # characters of diff sent with a question
BLOB_TIMEOUT = 10                  # seconds to read the committed copy


def _git_call(root, args: list):
    """The git command line and environment: nothing from the repo's config that could start another program,
    and none of git's own variables (GIT_DIR, GIT_WORK_TREE, GIT_CONFIG_* and the like, set when EasyUniTrack is
    started from a git hook or a developer's shell), which would point it at another repository or settings."""
    from .runner import clean_env
    git = shutil.which("git")
    if not git:
        return None, None
    env = {k: v for k, v in clean_env().items() if not k.upper().startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    return [git, "-C", str(root), "-c", "core.fsmonitor=false", "-c", "core.hooksPath=", "--no-pager", *args], env


def _git(root, *args):
    """(exit code, output text), or None if git isn't there or didn't answer."""
    cmd, env = _git_call(root, list(args))
    if not cmd:
        return None
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=10, env=env,
                           creationflags=0x08000000 if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.returncode, r.stdout.decode("utf-8", errors="replace").strip()


def _git_blob(root, spec: str, limit: int):
    """A committed file's bytes, reading at most limit + 1 bytes (None if it's bigger, or can't be read)."""
    cmd, env = _git_call(root, ["cat-file", "blob", spec])
    if not cmd:
        return None
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
                             creationflags=0x08000000 if os.name == "nt" else 0)
    except OSError:
        return None
    got = {}
    reader = threading.Thread(target=lambda: got.update(data=p.stdout.read(limit + 1)), daemon=True)
    reader.start()
    reader.join(BLOB_TIMEOUT)                             # git stuck: give up rather than wait forever
    stuck = reader.is_alive()
    p.kill()                                              # also ends a read still waiting on the pipe
    p.wait()
    reader.join(2)
    data = got.get("data")
    return None if stuck or data is None or len(data) > limit else data


def committed(folder: Folder, rel: str):
    """The file as it was in the last commit: (text, "") / (None, "new") if it's not in the last commit /
    (None, "") if this isn't a git repository, git isn't installed, or the committed copy is too big."""
    r = _git(folder.root, "rev-parse", "--is-inside-work-tree")
    if not r or r[0] != 0 or r[1] != "true":
        return None, ""
    spec = f"HEAD:./{rel}"
    size = _git(folder.root, "cat-file", "-s", spec)
    if not size or size[0] != 0:
        return None, "new"
    if not size[1].isdigit() or int(size[1]) > MAX_FILE:  # checked first, so a huge file is never read
        return None, ""
    blob = _git_blob(folder.root, spec, MAX_FILE)         # and capped, in case it changes in between
    if blob is None or b"\x00" in blob[:8192]:
        return None, ""
    return blob.decode("utf-8", errors="replace").replace("\r\n", "\n"), ""


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
