"""Proposed changes to files in a linked folder (design section 6.3).

- The assistant never writes to disk itself. It calls propose_change, and the student sees a red/green diff
  card with Apply and Dismiss.
- Apply backs up the original into code-backups/ in EasyUniTrack's data folder, writes the change and records
  it. Undo puts the backup back, byte for byte (or removes a file the change created).
- If the file changed on disk since the proposal, Apply refuses and asks for a fresh proposal. If it changed
  after Apply, Undo refuses rather than overwrite the student's later edits.
- Writes stay inside the linked folder, never to hidden files (Folder.check_writable).
- In an Assignment folder a change is a few lines at most, never a rewrite (hints first).
"""
import difflib
import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path

from fastapi import HTTPException

from .codebase import MAX_FILE, CodeError, Folder

ASSIGNMENT_MAX_LINES = 12          # changed lines in one proposal in an Assignment folder
MAX_DIFF_LINES = 400               # diff lines shown on a card

TOOL = {
    "name": "propose_change",
    "description": "Propose a change to one file in the student's folder. The student sees it as a diff and decides "
                   "whether to apply it; nothing is written until they do. To edit, give `find` (text copied exactly "
                   "from the file, without the line numbers) and `replace`. To create a new file, leave out `find` "
                   "and give the whole file as `replace`. To replace a whole existing file, also set whole_file.",
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "File path inside the folder, as shown in the files"},
        "find": {"type": "string", "description": "Exact text to replace, copied from the file"},
        "replace": {"type": "string", "description": "The new text"},
        "summary": {"type": "string", "description": "One short line saying what the change does"},
        "whole_file": {"type": "boolean", "description": "true only to replace an existing file completely"}},
        "required": ["path", "replace", "summary"]},
}

PROMPT = {
    "assignment": "You can propose a change with the propose_change tool, but in this Assignment folder only when the "
                  "student asks for a fix, and only a few lines (the app refuses bigger ones). Never rewrite a file. "
                  "The student applies changes themselves, so never say a change is applied.",
    "personal": "When a fix or new code would help, propose it with the propose_change tool (one call per file, "
                "several calls are fine). The student applies changes themselves, so never say a change is applied.",
}

_NUMBERED = re.compile(r"^\s*\d+\| ?")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strip_line_numbers(text: str) -> str:
    """Models sometimes copy the "12| " prefixes from the context; take them off if every line has one."""
    lines = text.split("\n")
    if lines and all(_NUMBERED.match(x) for x in lines if x.strip()):
        return "\n".join(_NUMBERED.sub("", x, count=1) for x in lines)
    return text


def match_indent(current: str, find: str, replace: str) -> str:
    """Models often leave the indentation off: find "return x" inside "    return x", with replacement lines
    written from column 0. If the match starts after only spaces on its line and the replacement doesn't start
    with its own indentation, give its following lines the same indentation as that line."""
    at = current.find(find)
    prefix = current[current.rfind("\n", 0, at) + 1:at]
    if not prefix or prefix.strip() or replace[:1] in (" ", "\t") or "\n" not in replace:
        return replace
    return "\n".join([line if i == 0 or not line.strip() else prefix + line
                      for i, line in enumerate(replace.split("\n"))])


def diff_lines(old: str, new: str) -> list:
    """[{t: ' ' | '+' | '-' | '@', s: text}] for the card."""
    out = []
    for line in difflib.unified_diff(old.split("\n"), new.split("\n"), lineterm="", n=3):
        if line.startswith(("---", "+++")):
            continue
        out.append({"t": line[0] if line[:1] in "+-@" else " ", "s": line[1:] if line[:1] in "+- " else line})
        if len(out) >= MAX_DIFF_LINES:
            out.append({"t": "@", "s": "… (the rest of the change isn't shown here)"})
            break
    return out


def changed_count(old: str, new: str) -> int:
    return sum(1 for d in diff_lines(old, new) if d["t"] in "+-")


class ChangeStore:
    """The file_changes table, and writing and restoring files."""

    def __init__(self, db, data_dir: Path):
        self.db, self.backups = db, Path(data_dir) / "code-backups"

    def get(self, change_id: int) -> dict:
        with self.db() as conn:
            r = conn.execute("SELECT c.*, f.path AS folder_path, f.mode AS folder_mode FROM file_changes c "
                             "JOIN code_folders f ON f.id = c.folder_id WHERE c.id=?", (change_id,)).fetchone()
        if not r:
            raise HTTPException(404, "That change isn't known any more.")
        return dict(r)

    def add(self, folder_id: int, path: str, summary: str, base_hash, new_content: str, eol: str) -> int:
        with self.db() as conn:
            return conn.execute("INSERT INTO file_changes (folder_id, path, summary, base_hash, new_content, eol, status) "
                                "VALUES (?, ?, ?, ?, ?, ?, 'proposed')",
                                (folder_id, path, summary, base_hash, new_content, eol)).lastrowid

    def update(self, change_id: int, summary: str, new_content: str):
        with self.db() as conn:
            conn.execute("UPDATE file_changes SET summary=?, new_content=? WHERE id=?", (summary, new_content, change_id))

    def claim(self, change_id: int, from_status: str, to_status: str) -> bool:
        """Move the change on in one step, so a double-click can't apply or undo it twice."""
        with self.db() as conn:
            return conn.execute("UPDATE file_changes SET status=? WHERE id=? AND status=?",
                                (to_status, change_id, from_status)).rowcount == 1

    def set(self, change_id: int, **fields):
        cols = ", ".join(f"{k}=?" for k in fields)        # keys are this module's own names
        with self.db() as conn:
            conn.execute(f"UPDATE file_changes SET {cols} WHERE id=?", [*fields.values(), change_id])

    @staticmethod
    def write(target: Path, data: bytes):
        """Write through a temporary file in the same folder, so a crash can't leave half a file."""
        target.parent.mkdir(parents=True, exist_ok=True)
        # mkstemp makes the file owner-only: keep the original's permissions (a script stays executable),
        # and give a new file the usual ones
        mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644
        fd, tmp = tempfile.mkstemp(prefix=".eut-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.chmod(tmp, mode)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ── the student's buttons ──
    def apply(self, change_id: int) -> dict:
        c = self.get(change_id)
        if c["status"] != "proposed":
            raise HTTPException(409, "That change was already applied or dismissed.")
        try:
            folder = Folder(c["folder_path"])
            target = folder.check_writable(c["path"])
        except CodeError as e:
            raise HTTPException(400, str(e)) from None
        current = target.read_bytes() if target.exists() else None
        if (sha(current) if current is not None else None) != c["base_hash"]:
            self.claim(change_id, "proposed", "stale")
            raise HTTPException(409, f"{c['path']} has changed since this was proposed, so it wasn't applied. "
                                     "Ask the assistant for a fresh change.")
        if not self.claim(change_id, "proposed", "applying"):
            raise HTTPException(409, "That change was already applied or dismissed.")
        try:
            backup = ""
            if current is not None:
                self.backups.mkdir(parents=True, exist_ok=True)
                backup = str(self.backups / f"{change_id}-{target.name}")
                self.write(Path(backup), current)
            new = c["new_content"].replace("\n", "\r\n" if c["eol"] == "CRLF" else "\n").encode("utf-8")
            self.write(target, new)
        except OSError as e:
            self.set(change_id, status="proposed")
            raise HTTPException(500, f"The change couldn't be written: {e.strerror or e}") from None
        self.set(change_id, status="applied", backup=backup, applied_hash=sha(new))
        return {"status": "applied", "path": c["path"], "created": current is None}

    def undo(self, change_id: int) -> dict:
        c = self.get(change_id)
        if c["status"] != "applied":
            raise HTTPException(409, "Only an applied change can be undone.")
        try:
            target = Folder(c["folder_path"]).resolve(c["path"])
        except CodeError as e:
            raise HTTPException(400, str(e)) from None
        current = target.read_bytes() if target.exists() else None
        if current is None or sha(current) != c["applied_hash"]:
            raise HTTPException(409, f"{c['path']} has changed since this was applied, so Undo would lose those "
                                     "edits. Undo later changes first, or change it back yourself.")
        if not self.claim(change_id, "applied", "undoing"):
            raise HTTPException(409, "That change was already undone.")
        try:
            if c["backup"]:
                self.write(target, Path(c["backup"]).read_bytes())
            else:
                target.unlink()                                # the change created this file
        except OSError as e:
            self.set(change_id, status="applied")
            raise HTTPException(500, f"Undo couldn't restore the file: {e.strerror or e}") from None
        self.set(change_id, status="undone")
        return {"status": "undone", "path": c["path"], "removed": not c["backup"]}

    def dismiss(self, change_id: int) -> dict:
        if not self.claim(change_id, "proposed", "dismissed"):
            raise HTTPException(409, "That change was already applied or dismissed.")
        return {"status": "dismissed"}


class CodeTools:
    """propose_change for one reply in one folder. Same interface as TaskTools (ai/tools.py)."""

    schema = [TOOL]

    def __init__(self, store: ChangeStore, folder_id: int, folder: Folder, mode: str):
        self.store, self.folder_id, self.folder, self.mode = store, folder_id, folder, mode
        self.pending = {}                                  # path -> (change_id, base text): one card per file per reply

    def addendum(self) -> str:
        return PROMPT.get(self.mode, PROMPT["assignment"])

    def run_round(self, calls: list, state: dict) -> tuple:
        results, events = [], []
        for call in calls:
            try:
                if call["name"] != "propose_change":
                    raise CodeError(f"There's no tool called {call['name']}.")
                ev = self.propose(call.get("args") or {})
                events.append(ev)
                results.append((call, f"Shown to the student as a proposed change to {ev['path']}. They decide whether "
                                      "to apply it; don't say it's applied."))
            except CodeError as e:
                results.append((call, f"Couldn't propose that: {e}"))
        return results, events

    def propose(self, a: dict) -> dict:
        path = re.sub(r"^(\./)+", "", str(a.get("path") or "").strip().replace("\\", "/"))
        if not path:
            raise CodeError("Say which file to change (path).")
        replace = strip_line_numbers(str(a.get("replace") or ""))
        find = strip_line_numbers(str(a.get("find") or ""))
        summary = " ".join(str(a.get("summary") or "").split())[:200] or f"Change {path}"
        self.folder.check_writable(path)
        exists = self.folder.resolve(path).exists()
        if path in self.pending:                            # a second edit to the same file joins its card
            change_id, before = self.pending[path]
            current = self.store.get(change_id)["new_content"]
            base_hash = None
        else:
            change_id = None
            if exists:
                current, raw = self.folder.read_exact(path)
                base_hash, eol = sha(raw), ("CRLF" if b"\r\n" in raw else "LF")
            else:
                current, base_hash, eol = "", None, "LF"
            before = current
        if find:
            if not exists and change_id is None:
                raise CodeError(f"{path} doesn't exist. To create it, leave out find.")
            count = current.count(find)
            if count == 0:
                raise CodeError(f"The find text isn't in {path}. Copy it exactly from the file, without line numbers.")
            if count > 1:
                raise CodeError(f"The find text appears {count} times in {path}. Include more lines so it's unique.")
            replace = match_indent(current, find, replace)
            new = current.replace(find, replace, 1)
        else:
            if exists or change_id is not None:
                if self.mode == "assignment":
                    raise CodeError("In an Assignment folder, change only a few lines using find and replace.")
                if a.get("whole_file") is not True:          # a forgotten find mustn't wipe the rest of the file
                    raise CodeError(f"{path} already exists. Give find (the exact text to replace), or set "
                                    "whole_file to replace the whole file.")
            new = replace if replace.endswith("\n") or not replace else replace + "\n"
        if new == current:
            raise CodeError("That change doesn't change anything.")
        if len(new.encode("utf-8")) > MAX_FILE:
            raise CodeError("That would make the file over 200 KB.")
        if self.mode == "assignment" and changed_count(before, new) > ASSIGNMENT_MAX_LINES:
            raise CodeError(f"In an Assignment folder a change can be at most {ASSIGNMENT_MAX_LINES} changed lines. "
                            "Explain the rest instead, so the student writes it.")
        if change_id is None:
            change_id = self.store.add(self.folder_id, path, summary, base_hash, new, eol)
            self.pending[path] = (change_id, before)
        else:
            self.store.update(change_id, summary, new)
        return {"type": "change", "change_id": change_id, "path": path, "summary": summary,
                "new_file": not exists, "diff": diff_lines(before, new)}
