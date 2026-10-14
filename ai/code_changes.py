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


class Conflict(Exception):
    """The file changed between the check and the write; nothing was overwritten."""


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
        tmp = ChangeStore._temp(target, data, stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644)
        try:
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    @staticmethod
    def _temp(target: Path, data: bytes, mode: int) -> str:
        """The new bytes in a temporary file next to the target. mkstemp makes it owner-only, so it gets the
        original's permissions (a script stays executable), or the usual ones for a new file."""
        fd, tmp = tempfile.mkstemp(prefix=".eut-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.chmod(tmp, mode)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return tmp

    @staticmethod
    def _put(src: Path, target: Path):
        """Move src to target only if nothing is at target: a hard link fails if the name is taken, so nothing
        that appears there can be overwritten. Raises Conflict if the name is taken."""
        try:
            os.link(src, target)
        except FileExistsError:
            raise Conflict() from None
        except OSError:                                    # no hard links here (FAT drives, some network shares):
            data, mode = src.read_bytes(), stat.S_IMODE(src.stat().st_mode)   # create it exclusively instead,
            try:                                                               # which also fails if it exists
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), mode)
            except FileExistsError:
                raise Conflict() from None
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
            except BaseException:
                target.unlink(missing_ok=True)                                 # ours, half-written
                raise
        os.unlink(src)

    @staticmethod
    def hold_path(target: Path, tag: str) -> Path:
        """Where swap moves the file aside: named after the change, so recover() can find it after a crash."""
        return target.with_name(f".eut-hold-{tag}-{target.name}")

    @classmethod
    def swap(cls, target: Path, data, expected, tag: str = ""):
        """Replace target with data (or remove it, if data is None), but only if it still is the file with hash
        `expected` (None: there must be no file). An edit saved at any moment is never overwritten: the file is
        moved aside in one step, the moved copy is checked, and the new one is put in place only if nothing has
        appeared there. Otherwise everything is put back and Conflict is raised."""
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644
        tmp = cls._temp(target, data, mode) if data is not None else None
        hold = None
        try:
            if expected is None:
                if target.exists():
                    raise Conflict()
            else:
                hold = cls.hold_path(target, tag or str(os.getpid()))
                try:
                    os.replace(target, hold)               # one step: from here, edits to target can't touch it
                except FileNotFoundError:
                    hold = None
                    raise Conflict() from None
                if sha(hold.read_bytes()) != expected:     # edited after the check, before the move
                    raise Conflict()
            if tmp is not None:
                cls._put(Path(tmp), target)
                tmp = None
            if hold is not None:
                hold.unlink()
                hold = None
        finally:
            if tmp is not None:
                Path(tmp).unlink(missing_ok=True)
            if hold is not None and hold.exists():         # something went wrong: put the student's file back
                try:
                    cls._put(hold, target)
                except Conflict:
                    pass                                   # a new file took the name: keep both (hold stays)

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
        stale = HTTPException(409, f"{c['path']} has changed since this was proposed, so it wasn't applied. "
                                   "Ask the assistant for a fresh change.")
        current = target.read_bytes() if target.exists() else None
        if (sha(current) if current is not None else None) != c["base_hash"]:
            self.claim(change_id, "proposed", "stale")
            raise stale
        if not self.claim(change_id, "proposed", "applying"):
            raise HTTPException(409, "That change was already applied or dismissed.")
        new = c["new_content"].replace("\n", "\r\n" if c["eol"] == "CRLF" else "\n").encode("utf-8")
        try:
            backup = ""
            if current is not None:
                self.backups.mkdir(parents=True, exist_ok=True)
                backup = str(self.backups / f"{change_id}-{target.name}")
                self.write(Path(backup), current)
            # Recorded before the file is touched, so a change cut off part-way can be sorted out (recover)
            self.set(change_id, backup=backup, applied_hash=sha(new))
            self.swap(target, new, c["base_hash"], str(change_id))
        except Conflict:
            self.set(change_id, status="stale")
            raise stale from None
        except OSError as e:
            self.set(change_id, status="proposed")
            raise HTTPException(500, f"The change couldn't be written: {e.strerror or e}") from None
        self.set(change_id, status="applied")
        return {"status": "applied", "path": c["path"], "created": current is None}

    def undo(self, change_id: int) -> dict:
        c = self.get(change_id)
        if c["status"] != "applied":
            raise HTTPException(409, "Only an applied change can be undone.")
        try:
            target = Folder(c["folder_path"]).resolve(c["path"])
        except CodeError as e:
            raise HTTPException(400, str(e)) from None
        changed = HTTPException(409, f"{c['path']} has changed since this was applied, so Undo would lose those "
                                     "edits. Undo later changes first, or change it back yourself.")
        current = target.read_bytes() if target.exists() else None
        if current is None or sha(current) != c["applied_hash"]:
            raise changed
        if not self.claim(change_id, "applied", "undoing"):
            raise HTTPException(409, "That change was already undone.")
        try:
            original = Path(c["backup"]).read_bytes() if c["backup"] else None   # None: the change made the file
            self.swap(target, original, c["applied_hash"], str(change_id))
        except Conflict:
            self.set(change_id, status="applied")
            raise changed from None
        except OSError as e:
            self.set(change_id, status="applied")
            raise HTTPException(500, f"Undo couldn't restore the file: {e.strerror or e}") from None
        self.set(change_id, status="undone")
        return {"status": "undone", "path": c["path"], "removed": not c["backup"]}

    def dismiss(self, change_id: int) -> dict:
        if not self.claim(change_id, "proposed", "dismissed"):
            raise HTTPException(409, "That change was already applied or dismissed.")
        return {"status": "dismissed"}

    def _tidy_hold(self, c: dict, target: Path, hold: Path):
        """Both the file and the moved-aside copy exist after a crash. If the file is a cut-off start of what was
        being written (only possible where there are no hard links), it's ours: remove it, so the copy goes back.
        If the write finished, the copy is the one we checked: remove it once its hash confirms that."""
        if c["status"] == "applying":
            intended = c["new_content"].replace("\n", "\r\n" if c["eol"] == "CRLF" else "\n").encode("utf-8")
            held = c["base_hash"]
        elif c["backup"]:
            intended, held = Path(c["backup"]).read_bytes(), c["applied_hash"]
        else:
            return
        now = target.read_bytes()
        if len(now) < len(intended) and intended.startswith(now):
            target.unlink()                                # half-written by us: the original goes back next
        elif now == intended and held and sha(hold.read_bytes()) == held:
            hold.unlink()                                  # finished; the copy is the file as it was checked

    def recover(self):
        """At start-up, sort out changes cut off part-way (the app closed during Apply or Undo) from what the
        file actually holds now."""
        try:
            with self.db() as conn:
                rows = [dict(r) for r in conn.execute(
                    "SELECT c.*, f.path AS folder_path FROM file_changes c JOIN code_folders f ON f.id = c.folder_id "
                    "WHERE c.status IN ('applying', 'undoing')")]
        except Exception:                                  # an older database without the table: nothing to do
            return
        for c in rows:
            try:
                target = Folder(c["folder_path"]).resolve(c["path"])
                hold = self.hold_path(target, str(c["id"]))
                if hold.is_file() and target.exists():
                    self._tidy_hold(c, target, hold)
                if hold.is_file() and not target.exists():   # the crash came while the file was moved aside
                    if (c["status"] == "undoing" and not c["backup"] and c["applied_hash"]
                            and sha(hold.read_bytes()) == c["applied_hash"]):
                        hold.unlink()                        # Undo of a file the change made, unedited: it goes
                    else:
                        try:
                            self._put(hold, target)          # put the file back as it was before the click
                        except Conflict:
                            pass
                now = sha(target.read_bytes()) if target.exists() else None
            except (CodeError, OSError):
                now = "unknown"
            backup_ok = not c["base_hash"] or bool(c["backup"] and Path(c["backup"]).is_file()
                                                   and sha(Path(c["backup"]).read_bytes()) == c["base_hash"])
            if c["applied_hash"] and now == c["applied_hash"] and backup_ok:
                status = "applied"                         # the change is in the file, and Undo has its backup
            elif now == c["base_hash"]:
                status = "proposed" if c["status"] == "applying" else "undone"
            else:
                status = "stale" if c["status"] == "applying" else "applied"
            self.set(c["id"], status=status)


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
