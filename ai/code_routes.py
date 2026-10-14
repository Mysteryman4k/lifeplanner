"""Server routes for the code workspace (/api/code/...): linked folders, the tree, reading a file, and the
files that go with a question. Nothing here writes to the student's folders or runs anything.

Gate: the current terms must be agreed and the Code workspace switch on. Like every change, the routes that
change something need the window's session token (app.py, protect_local_server).
"""
from pathlib import Path
from typing import Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from . import terms
from .code_changes import ChangeStore, CodeTools
from .codebase import CodeError, Folder, language, link_problem

FolderMode = Literal["assignment", "personal"]


class FolderIn(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    mode: FolderMode = "assignment"
    subject_id: Optional[int] = None


class FolderUpdate(BaseModel):
    mode: FolderMode = None
    subject_id: Optional[int] = None
    name: str = Field(default=None, min_length=1, max_length=120)


class ChooseIn(BaseModel):
    question: str = Field(default="", max_length=20000)
    open_file: str = Field(default="", max_length=1000)
    pinned: list[str] = Field(default=[], max_length=20)
    removed: list[str] = Field(default=[], max_length=200)


def register(app, db, load_ai_settings, data_dir: Path, window: dict):
    """load_ai_settings() returns the AISettings (ai/routes.py). window["pick_folder"] is set by the desktop
    app to open the Windows folder picker (it isn't there when the app runs in a browser)."""

    def gate():
        s = load_ai_settings()
        if s.terms_version != terms.TERMS_VERSION:
            raise HTTPException(403, "Read and agree to the terms of use first.")
        if not s.code_enabled:
            raise HTTPException(403, "Turn on the Code workspace in Settings first.")

    def row(folder_id: int) -> dict:
        with db() as conn:
            r = conn.execute("SELECT f.*, s.name AS subject_name FROM code_folders f "
                             "LEFT JOIN subjects s ON s.id = f.subject_id WHERE f.id=?", (folder_id,)).fetchone()
        if not r:
            raise HTTPException(404, "That folder isn't linked any more.")
        return dict(r)

    def open_folder(folder_id: int) -> tuple:
        r = row(folder_id)
        try:
            return r, Folder(r["path"])
        except CodeError as e:
            raise HTTPException(404, str(e)) from None

    def public(r: dict) -> dict:
        return {**r, "exists": Path(r["path"]).is_dir()}

    @app.get("/api/code/folders")
    def list_folders():
        gate()
        with db() as conn:
            rows = conn.execute("SELECT f.*, s.name AS subject_name FROM code_folders f "
                                "LEFT JOIN subjects s ON s.id = f.subject_id ORDER BY lower(f.name)").fetchall()
        return [public(dict(r)) for r in rows]

    @app.post("/api/code/folders")
    def link_folder(f: FolderIn):
        gate()
        problem = link_problem(f.path.strip(), data_dir)
        if problem:
            raise HTTPException(400, problem)
        path = str(Path(f.path.strip()).expanduser().resolve())
        with db() as conn:
            if conn.execute("SELECT 1 FROM code_folders WHERE lower(path)=lower(?)", (path,)).fetchone():
                raise HTTPException(409, "That folder is already linked.")
            if f.subject_id is not None and not conn.execute("SELECT 1 FROM subjects WHERE id=?", (f.subject_id,)).fetchone():
                raise HTTPException(400, "That subject doesn't exist.")
            new_id = conn.execute("INSERT INTO code_folders (subject_id, path, name, mode) VALUES (?, ?, ?, ?)",
                                  (f.subject_id, path, Path(path).name or path, f.mode)).lastrowid
        return public(row(new_id))

    @app.put("/api/code/folders/{folder_id}")
    def update_folder(folder_id: int, f: FolderUpdate):
        gate()
        row(folder_id)
        changes = f.model_dump(exclude_unset=True)
        if "subject_id" in changes and changes["subject_id"] is not None:
            with db() as conn:
                if not conn.execute("SELECT 1 FROM subjects WHERE id=?", (changes["subject_id"],)).fetchone():
                    raise HTTPException(400, "That subject doesn't exist.")
        if changes:
            cols = ", ".join(f"{k}=?" for k in changes)              # keys are FolderUpdate's own fields
            with db() as conn:
                conn.execute(f"UPDATE code_folders SET {cols} WHERE id=?", [*changes.values(), folder_id])
        return public(row(folder_id))

    @app.delete("/api/code/folders/{folder_id}")
    def unlink_folder(folder_id: int):
        """Forget the link. The folder and its files are never touched."""
        gate()
        with db() as conn:
            conn.execute("DELETE FROM code_folders WHERE id=?", (folder_id,))
        return {"ok": True}

    @app.post("/api/code/pick-folder")
    def pick_folder():
        """Open the Windows folder picker (desktop app only). {path: ""} if cancelled."""
        gate()
        picker = window.get("pick_folder")
        if not picker:
            raise HTTPException(501, "The folder picker is only in the desktop app. Type the folder's path instead.")
        return {"path": picker() or ""}

    @app.get("/api/code/folders/{folder_id}/tree")
    def tree(folder_id: int):
        gate()
        _, folder = open_folder(folder_id)
        return folder.tree()

    @app.get("/api/code/folders/{folder_id}/file")
    def read_file(folder_id: int, path: str):
        gate()
        _, folder = open_folder(folder_id)
        try:
            text = folder.read(path)
        except CodeError as e:
            raise HTTPException(400, str(e)) from None
        return {"path": path, "text": text, **language(path)}

    @app.post("/api/code/folders/{folder_id}/choose")
    def choose(folder_id: int, c: ChooseIn):
        """The files that would go with this question, so the student sees (and can change) the list."""
        gate()
        _, folder = open_folder(folder_id)
        return folder.choose(c.question, c.open_file, c.pinned, c.removed)

    def context(folder_id: int, paths: list) -> dict:
        """For the chat: the folder's mode and name, and the files' text with line numbers."""
        gate()
        r, folder = open_folder(folder_id)
        text, sent, left_out = folder.context(paths)
        return {"mode": r["mode"], "name": r["name"], "subject": r.get("subject_name") or "",
                "text": text, "sent": sent, "left_out": left_out,
                "tools": lambda: CodeTools(changes, folder_id, folder, r["mode"])}

    changes = ChangeStore(db, data_dir)
    changes.recover()                     # Apply or Undo cut off when the app last closed

    @app.post("/api/code/changes/{change_id}/apply")
    def apply_change(change_id: int):
        """The student's Apply: back up the file, then write the change."""
        gate()
        return changes.apply(change_id)

    @app.post("/api/code/changes/{change_id}/undo")
    def undo_change(change_id: int):
        """Put the file back exactly as it was before Apply."""
        gate()
        return changes.undo(change_id)

    @app.post("/api/code/changes/{change_id}/dismiss")
    def dismiss_change(change_id: int):
        gate()
        return changes.dismiss(change_id)

    return context
