"""Saved chats (/api/ai/chats): the study assistant's and the code workspace's conversations, kept so they're
there next time and listed under Recent chats. They're the student's data, so they go in backups.

The page saves a chat after each reply (and when a card changes, like Undo): the whole conversation, with its
cards. Gate: the current terms must be agreed. Like every change, saving needs the window's session token.
"""
import json
import shutil
import time
from pathlib import Path
from typing import Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from . import files, terms

MAX_MESSAGES = 400
MAX_META = 200_000                 # characters of a message's cards and the like, as JSON
LIST_LIMIT = 100
MAX_SUMMARY = 8000                 # characters of the summary of a long chat's older messages
KEEP_DAYS = 90                     # suggested code changes and task-change records are kept this long...
KEEP_CHANGES = 200                 # ...and at least the newest this many changes
KEEP_ACTIONS = 500                 # ...and task-change records
KEEP_CHATS = (0, 30, 90, 180, 365)  # the student's choice for saved chats, in days (0: keep them all)


class SavedMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=200_000)
    meta: dict = {}                                           # cards, files sent, an error or "stopped"

    @field_validator("meta")
    @classmethod
    def small_meta(cls, v):
        if len(json.dumps(v)) > MAX_META:
            raise ValueError("too much detail in one message")
        return v


class SavedAttachment(BaseModel):
    """The attached file's text that went with the chat's questions, so it can carry on after reopening."""
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="", max_length=20)
    included: str = Field(default="", max_length=200)
    text: str = Field(min_length=1, max_length=files.CLOUD_CHARS + 20_000)
    chars: int = Field(default=0, ge=0)


class ChatSave(BaseModel):
    title: str = Field(default="", max_length=120)
    kind: Literal["study", "code"] = "study"
    mode: str = Field(default="explain", max_length=20)
    format: str = Field(default="auto", max_length=20)
    task_id: Optional[int] = None
    folder_id: Optional[int] = None
    tokens: int = Field(default=0, ge=0)
    messages: list[SavedMessage] = Field(min_length=1, max_length=MAX_MESSAGES)
    attachment: Optional[SavedAttachment] = None
    summary: str = Field(default="", max_length=MAX_SUMMARY)  # older messages, summarised for the assistant


def register(app, db, load_ai_settings, data_dir: Path):
    """Returns remove_ai_data(), which Remove all AI data calls: chats, linked folders, proposed changes, the
    action log and code backups. Notes stay: they're the student's study notes."""

    def gate():
        if load_ai_settings().terms_version != terms.TERMS_VERSION:
            raise HTTPException(403, "Read and agree to the terms of use first.")

    def exists(conn, table: str, row_id) -> bool:
        return row_id is None or bool(conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (row_id,)).fetchone())

    def title_of(c: ChatSave) -> str:
        if c.title.strip():
            return c.title.strip()[:120]
        first = next((m.content for m in c.messages if m.role == "user" and m.content.strip()), "Chat")
        first = " ".join(first.split())
        return first[:60] + ("…" if len(first) > 60 else "")

    def write(conn, chat_id: int, c: ChatSave):
        # Links to a task or folder that has gone stay empty rather than refuse the save
        task_id = c.task_id if exists(conn, "tasks", c.task_id) else None
        folder_id = c.folder_id if exists(conn, "code_folders", c.folder_id) else None
        attachment = c.attachment.model_dump_json() if c.attachment else ""
        conn.execute("UPDATE conversations SET title=?, kind=?, mode=?, format=?, task_id=?, folder_id=?, tokens=?, "
                     "attachment=?, summary=?, updated_at=datetime('now','localtime') WHERE id=?",
                     (title_of(c), c.kind, c.mode, c.format, task_id, folder_id, c.tokens, attachment, c.summary, chat_id))
        conn.execute("DELETE FROM messages WHERE conversation_id=?", (chat_id,))
        conn.executemany("INSERT INTO messages (conversation_id, position, role, content, meta) VALUES (?, ?, ?, ?, ?)",
                         [(chat_id, i, m.role, m.content, json.dumps(m.meta)) for i, m in enumerate(c.messages)])

    @app.get("/api/ai/chats")
    def list_chats(limit: int = 30):
        """The most recent chats first."""
        gate()
        with db() as conn:
            rows = conn.execute(
                "SELECT c.id, c.title, c.kind, c.mode, c.task_id, c.folder_id, c.updated_at, f.name AS folder_name, "
                "CASE WHEN json_valid(c.attachment) THEN json_extract(c.attachment, '$.name') END AS attachment_name, "
                "(SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS count "
                "FROM conversations c LEFT JOIN code_folders f ON f.id = c.folder_id "
                "ORDER BY c.updated_at DESC, c.id DESC LIMIT ?", (max(1, min(limit, LIST_LIMIT)),)).fetchall()
        return [dict(r) for r in rows]

    @app.get("/api/ai/chats/{chat_id}")
    def get_chat(chat_id: int):
        gate()
        with db() as conn:
            row = conn.execute("SELECT * FROM conversations WHERE id=?", (chat_id,)).fetchone()
            if not row:
                raise HTTPException(404, "That chat has been deleted.")
            messages = [{"role": m["role"], "content": m["content"], "meta": json.loads(m["meta"] or "{}")}
                        for m in conn.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY position",
                                              (chat_id,))]
        try:                                            # a damaged one (from an edited backup) is left off
            attachment = SavedAttachment.model_validate_json(row["attachment"]).model_dump() if row["attachment"] else None
        except ValueError:
            attachment = None
        return {**dict(row), "attachment": attachment, "messages": messages}

    @app.post("/api/ai/chats")
    def create_chat(c: ChatSave):
        gate()
        with db() as conn:
            chat_id = conn.execute("INSERT INTO conversations (title) VALUES ('')").lastrowid
            write(conn, chat_id, c)
        return {"id": chat_id, "title": title_of(c)}

    @app.put("/api/ai/chats/{chat_id}")
    def save_chat(chat_id: int, c: ChatSave):
        gate()
        with db() as conn:
            if not conn.execute("SELECT 1 FROM conversations WHERE id=?", (chat_id,)).fetchone():
                raise HTTPException(404, "That chat has been deleted.")
            write(conn, chat_id, c)
        return {"id": chat_id, "title": title_of(c)}

    @app.delete("/api/ai/chats/{chat_id}")
    def delete_chat(chat_id: int):
        gate()
        with db() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id=?", (chat_id,))
            conn.execute("DELETE FROM conversations WHERE id=?", (chat_id,))
        return {"ok": True}

    def clean_up():
        """Old records that are only useful for a while (run when the app starts, and when Keep chats changes)."""
        return clean_up_records(db, data_dir, load_ai_settings().keep_chats_days)

    def remove_ai_data():
        """For Remove all AI data: chats, linked folders (the folders themselves aren't touched), proposed changes,
        the action log, and the copies kept for Undo."""
        with db() as conn:
            for table in ("messages", "conversations", "file_changes", "ai_actions", "code_folders"):
                conn.execute(f"DELETE FROM {table}")
        target = Path(data_dir) / "code-backups"
        if target.exists():
            try:
                shutil.rmtree(target)
            except OSError as e:                          # say so, rather than report everything removed
                raise HTTPException(500, "Your chats and folder links were removed, but some code backups couldn't be "
                                         f"deleted ({target}). Close any program using them and click Remove again.") from e

    return remove_ai_data, clean_up


def clean_up_records(db, data_dir: Path, keep_chats_days: int = 0) -> dict:
    """Keep what only matters for a while from growing forever:
    - suggested code changes (and the backups Undo uses) older than KEEP_DAYS, beyond the newest KEEP_CHANGES;
    - the record of task changes (Undo for those) on the same terms, beyond the newest KEEP_ACTIONS;
    - code backups nothing refers to any more (a removed link, or a crash), once they're an hour old;
    - saved chats not opened or changed for keep_chats_days, only if the student chose a limit (0: kept).
    Nothing that's part-way through (being applied or undone, or waiting for a yes) is touched."""
    age = f"-{KEEP_DAYS} days"
    removed = {}
    with db() as conn:
        removed["changes"] = conn.execute(
            "DELETE FROM file_changes WHERE status NOT IN ('applying', 'undoing') AND created_at < "
            "datetime('now', 'localtime', ?) AND id NOT IN (SELECT id FROM file_changes ORDER BY id DESC LIMIT ?)",
            (age, KEEP_CHANGES)).rowcount
        removed["actions"] = conn.execute(
            "DELETE FROM ai_actions WHERE status NOT IN ('pending', 'applying', 'undoing') AND created_at < "
            "datetime('now', 'localtime', ?) AND id NOT IN (SELECT id FROM ai_actions ORDER BY id DESC LIMIT ?)",
            (age, KEEP_ACTIONS)).rowcount
        removed["chats"] = 0
        if keep_chats_days:
            old = [r[0] for r in conn.execute("SELECT id FROM conversations WHERE updated_at < datetime('now', 'localtime', ?)",
                                              (f"-{int(keep_chats_days)} days",))]
            for i in range(0, len(old), 500):
                part = old[i:i + 500]
                marks = ",".join("?" * len(part))
                conn.execute(f"DELETE FROM messages WHERE conversation_id IN ({marks})", part)
                conn.execute(f"DELETE FROM conversations WHERE id IN ({marks})", part)
            removed["chats"] = len(old)
        in_use = {Path(r[0]).name for r in conn.execute("SELECT backup FROM file_changes WHERE backup != ''")}
    removed["backups"] = 0
    folder = Path(data_dir) / "code-backups"
    if folder.is_dir():
        settled = time.time() - 3600                      # one being written right now isn't recorded yet
        for f in folder.iterdir():
            try:
                if f.is_file() and f.name not in in_use and f.stat().st_mtime < settled:
                    f.unlink()
                    removed["backups"] += 1
            except OSError:                               # in use: tried again next time
                pass
    return removed
