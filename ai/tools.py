"""Task tools the study assistant can call, and the rules for when it may act on its own.

Rules (from the design):
- list_tasks runs straight away (read-only).
- add_task, update_task and complete_task run straight away and show a card with Undo.
- delete_task always asks first (a Keep / Delete card).
- More than 3 changes in one reply: the 4th onwards ask first, together on one card.
- While a file or folder is attached (stage 11), every change asks first.
Every change is recorded in ai_actions with what the task looked like before, so Undo restores it exactly.

The app passes in a TaskStore (see app.py) so these tools use the same code paths as the app itself:
validation, status rules and repeating tasks all behave the same.
"""
import json
from datetime import date

MAX_DIRECT_CHANGES = 3
CHANGE_TOOLS = {"add_task", "update_task", "complete_task", "delete_task"}

_TASK_FIELDS = {
    "title": {"type": "string", "description": "Short task title"},
    "due_date": {"type": "string", "description": "Due date as YYYY-MM-DD"},
    "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
    "subject": {"type": "string", "description": "Name of one of the student's subjects"},
    "estimated_hours": {"type": "number", "description": "Hours the task should take"},
    "description": {"type": "string", "description": "Details for the task"},
}

TOOLS = [
    {"name": "list_tasks",
     "description": "List the student's tasks. Use this to find a task's id before changing it.",
     "parameters": {"type": "object", "properties": {
         "status": {"type": "string", "enum": ["open", "done", "all"], "description": "Default open"},
         "search": {"type": "string", "description": "Only tasks whose title contains this"}}}},
    {"name": "add_task",
     "description": "Add a task to the student's planner. Only when the student asks for tasks to be added.",
     "parameters": {"type": "object", "properties": _TASK_FIELDS, "required": ["title"]}},
    {"name": "update_task",
     "description": "Change a task's title, due date, priority, subject, hours or details.",
     "parameters": {"type": "object", "properties": {"id": {"type": "integer"}, **_TASK_FIELDS}, "required": ["id"]}},
    {"name": "complete_task",
     "description": "Mark a task as done.",
     "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
    {"name": "delete_task",
     "description": "Delete a task. The student is always asked to confirm in the app first.",
     "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
]

PROMPT = """You can manage the student's tasks with tools: list_tasks, add_task, update_task, complete_task and
delete_task. You don't know their tasks until you call list_tasks: call it before you mention, list or change
any task, and never make tasks up. Only change tasks when the student asks you to. Use dates as YYYY-MM-DD
(today is {today}). Changes appear in the app as cards the student can undo; deleting a task, or more than 3
changes at once, waits for the student to confirm in the app, so say that and don't claim it's done."""


def system_addendum() -> str:
    today = date.today()
    return PROMPT.format(today=f"{today:%A} {today.isoformat()}")      # the weekday helps with "next Friday"


DASHES = {c: "-" for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212)}     # hyphens, dashes, minus


class ToolError(Exception):
    """A problem to report back to the model in plain words (it can then fix its call)."""


class TaskTools:
    schema = TOOLS

    def __init__(self, store, log):
        """store: the app's TaskStore. log: ActionLog for recording and undoing changes."""
        self.store, self.log = store, log

    def addendum(self) -> str:
        """The tool instructions, with the student's subjects, so a task gets a subject's real name."""
        names = self.store.subject_names()
        return system_addendum() + (f"\nThe student's subjects: {'; '.join(names)}." if names else "")

    # ── helpers ──
    def _fields(self, args: dict) -> dict:
        out = {}
        for key in ("title", "due_date", "priority", "estimated_hours", "description"):
            if args.get(key) not in (None, ""):
                out[key] = args[key]
        if isinstance(out.get("due_date"), str):        # gpt-oss writes 2026‑11‑03 with non-breaking hyphens
            out["due_date"] = out["due_date"].translate(DASHES).strip()
        if args.get("subject"):
            sid = self.store.subject_id(args["subject"])
            if sid is None:
                raise ToolError(f"{args['subject']!r} isn't one of the student's subjects. Leave it out or use one of: "
                                + ", ".join(self.store.subject_names()) + ".")
            out["subject_id"] = sid
        return out

    def _task(self, task_id) -> dict:
        try:
            row = self.store.get(int(task_id))
        except (TypeError, ValueError):
            row = None
        if not row:
            raise ToolError(f"There's no task with id {task_id}. Use list_tasks to find it.")
        return row

    def describe(self, call: dict) -> str:
        """One plain line for a card: what this change does."""
        name, a = call["name"], call.get("args") or {}
        if name == "add_task":
            return f"Add “{a.get('title', 'task')}”" + (f" (due {a['due_date']})" if a.get("due_date") else "")
        title = (self.store.get(int(a["id"])) or {}).get("title", f"task {a.get('id')}") if a.get("id") else "task"
        return {"update_task": f"Change “{title}”", "complete_task": f"Mark “{title}” done",
                "delete_task": f"Delete “{title}”"}.get(name, name)

    # ── the turn ──
    def run_round(self, calls: list, state: dict) -> tuple:
        """Run one round of tool calls. state carries 'changes' (done so far this reply) and 'ask_first'.
        Returns (results for the model, events for the app)."""
        results, events, waiting = [], [], []
        for call in calls:
            name = call["name"]
            try:
                if name == "list_tasks":
                    results.append((call, json.dumps(self.store.list(**(call.get("args") or {})))))
                    continue
                if name not in CHANGE_TOOLS:
                    raise ToolError(f"There's no tool called {name}.")
                if name == "delete_task":
                    self._task((call.get("args") or {}).get("id"))      # check it exists before asking
                if name == "delete_task" or state.get("ask_first") or state["changes"] >= MAX_DIRECT_CHANGES:
                    self._prepare(call)                                 # validate now, run after a yes
                    waiting.append(call)
                    results.append((call, "Waiting for the student to confirm this in the app. Tell them; don't "
                                          "say it's done."))
                    continue
                summary = self.describe(call)
                action_id = self.log.start(summary)
                try:
                    ops = [self._apply(call, lambda op, aid=action_id: self.log.progress(aid, [op]))]
                except ToolError:
                    self.log.set_status(action_id, "rejected")             # nothing was changed
                    raise
                except BaseException:
                    self.log.set_status(action_id, "done")                 # undo whatever was saved
                    raise
                self.log.complete_pending(action_id, ops)
                state["changes"] += 1
                events.append({"type": "action", "action_id": action_id, "summary": summary})
                results.append((call, f"Done: {summary}."))
            except ToolError as e:
                results.append((call, f"Couldn't do that: {e}"))
        if waiting:
            summaries = [self.describe(c) for c in waiting]
            action_id = self.log.pending(waiting, summaries)
            danger = any(c["name"] == "delete_task" for c in waiting)
            events.append({"type": "confirm", "action_id": action_id, "items": summaries, "danger": danger})
        return results, events

    def _prepare(self, call):
        a = call.get("args") or {}
        if call["name"] == "add_task":
            if not str(a.get("title", "")).strip():
                raise ToolError("A task needs a title.")
            self._fields(a)
        elif call["name"] in ("update_task", "complete_task", "delete_task"):
            self._task(a.get("id"))
            if call["name"] == "update_task":
                self._fields(a)

    def _apply(self, call, save=lambda op: None) -> dict:
        """Make one change and return what's needed to undo it. save(op) stores the undo step before the task
        is touched, so a change cut off part-way (the app closed) can still be undone."""
        name, a = call["name"], call.get("args") or {}
        if name == "add_task":
            if not str(a.get("title", "")).strip():
                raise ToolError("A task needs a title.")
            row = self.store.create(self._fields(a))
            op = {"op": "add", "task_id": row["id"]}
            save(op)
            return op
        before = self._task(a.get("id"))
        if name == "update_task":
            fields = self._fields(a)
            if not fields:
                raise ToolError("Say what to change.")
            op = {"op": "update", "task_id": before["id"], "before": before}
            save(op)
            self.store.update(before["id"], fields)
            return op
        if name == "complete_task":
            op = {"op": "complete", "task_id": before["id"], "before": before, "spawned": None}
            save(op)
            after = self.store.update(before["id"], {"status": "completed"})
            op["spawned"] = (after.get("next_task") or {}).get("id")
            if op["spawned"]:
                save(op)
            return op
        if name == "delete_task":
            op = {"op": "delete", "task_id": before["id"], "before": before, "notes": self.store.note_ids(before["id"])}
            save(op)
            self.store.delete(before["id"])
            return op
        raise ToolError(f"There's no tool called {name}.")

    # ── after the reply: the student's buttons ──
    def confirm(self, action_id: int, approve: bool) -> dict:
        calls = self.log.take_pending(action_id)
        if not approve:
            self.log.set_status(action_id, "rejected")
            return {"status": "rejected"}
        ops, failed = [], []
        try:
            for call in calls:
                try:
                    ops.append(self._apply(call, lambda op: self.log.progress(action_id, ops + [op])))
                except ToolError as e:
                    failed.append(str(e))
        except BaseException:
            self.log.set_status(action_id, "done")          # the undo steps saved so far can still be used
            raise
        self.log.complete_pending(action_id, ops)
        return {"status": "done", "done": len(ops), "failed": failed}

    def undo(self, action_id: int) -> dict:
        ops = self.log.take_done(action_id)
        try:
            self._reverse(ops)
        except Exception:
            self.log.set_status(action_id, "done")          # not undone: let the student try again
            raise
        self.log.set_status(action_id, "undone")
        return {"status": "undone"}

    def _reverse(self, ops: list):
        for op in reversed(ops):
            if op["op"] == "add":
                self.store.delete(op["task_id"])
            elif op["op"] in ("update", "complete"):
                if op.get("spawned"):
                    self.store.delete(op["spawned"])
                self.store.restore(op["before"])
            elif op["op"] == "delete":
                self.store.restore(op["before"])
                self.store.relink_notes(op["task_id"], op.get("notes") or [])
