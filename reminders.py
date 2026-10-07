"""
Daily reminders: one notification a day at the user's chosen time, summarising
what's overdue, what's due today and which job follow-ups are due.

Notifications are shown with the operating system's own notifications:
  Windows -> a toast (via PowerShell + Windows.UI.Notifications, no extra packages)
  Linux   -> notify-send, if installed
The scheduler only runs inside the desktop app (desktop.py starts it).
"""
import base64
import os
import shutil
import subprocess
import sys
import threading
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

# Matches the AppUserModelID the installer gives the Start-menu shortcut, so toasts say "Trackademic"
APP_ID = "Mysteryman4k.Trackademic"
POWERSHELL_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
ACTIVE_JOB_STATUSES = ("applied", "phone_screen", "interviewing", "offer")


def plural(n: int, word: str, many: str = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def build_digest(conn, today: date):
    """What to tell the user today, or None if there's nothing worth a notification."""
    t = today.isoformat()
    overdue = conn.execute("SELECT title FROM tasks WHERE status != 'completed' AND due_date < ? "
                           "ORDER BY due_date", (t,)).fetchall()
    due_today = conn.execute("SELECT title FROM tasks WHERE status != 'completed' AND due_date = ? "
                             "ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END",
                             (t,)).fetchall()
    follow_ups = conn.execute(f"SELECT company FROM job_applications WHERE follow_up_date IS NOT NULL "
                              f"AND follow_up_date <= ? AND status IN ({','.join('?' * len(ACTIVE_JOB_STATUSES))}) "
                              f"ORDER BY follow_up_date", (t, *ACTIVE_JOB_STATUSES)).fetchall()
    if not (overdue or due_today or follow_ups):
        return None

    parts = []
    if due_today:
        parts.append(f"{plural(len(due_today), 'task')} due today")
    if overdue:
        parts.append(f"{len(overdue)} overdue")
    if follow_ups:
        parts.append(plural(len(follow_ups), "follow-up"))
    title = ", ".join(parts)
    title = title[0].upper() + title[1:]

    lines = []
    if due_today:
        names = [r[0] for r in due_today]
        lines.append("Today: " + ", ".join(names[:3]) + (f" +{len(names) - 3} more" if len(names) > 3 else ""))
    if overdue:
        names = [r[0] for r in overdue]
        lines.append("Overdue: " + ", ".join(names[:2]) + (f" +{len(names) - 2} more" if len(names) > 2 else ""))
    if follow_ups:
        names = [r[0] for r in follow_ups]
        lines.append("Follow up with " + ", ".join(names[:3]) + (f" +{len(names) - 3} more" if len(names) > 3 else ""))
    return {"title": title, "body": "\n".join(lines),
            "counts": {"due_today": len(due_today), "overdue": len(overdue), "follow_ups": len(follow_ups)}}


# ── Showing a notification ───────────────────────────────────────────

def _windows_toast(title: str, body: str, app_id: str) -> bool:
    xml = ("<toast><visual><binding template='ToastGeneric'>"
           f"<text>{escape(title)}</text><text>{escape(body)}</text>"
           "</binding></visual></toast>")
    script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@'
{xml}
'@)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app_id}').Show($toast)
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return result.returncode == 0


def _has_start_menu_shortcut() -> bool:
    """Windows only shows notifications for an app id that a Start-menu shortcut carries. The installer
    makes one; the portable zip and running from source don't, so those borrow PowerShell's id."""
    if not getattr(sys, "frozen", False):
        return False
    programs = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return (programs / "Trackademic.lnk").exists() or (programs / "Trackademic" / "Trackademic.lnk").exists()


def notify(title: str, body: str) -> bool:
    """Show a system notification. Returns True if it was handed to the OS."""
    try:
        if os.name == "nt":
            return _windows_toast(title, body, APP_ID if _has_start_menu_shortcut() else POWERSHELL_APP_ID)
        if shutil.which("notify-send"):
            return subprocess.run(["notify-send", "-a", "Trackademic", title, body], timeout=10).returncode == 0
    except Exception as e:
        print(f"Notification failed: {e!r}", flush=True)
    return False


# ── Scheduler (desktop app only) ─────────────────────────────────────

def due_to_send(settings: dict, last_sent: str, now: datetime) -> bool:
    """Send once per day, at or after the chosen time (catches up if the app opens later in the day)."""
    if not settings.get("daily"):
        return False
    if last_sent == now.date().isoformat():
        return False
    hh, mm = (int(x) for x in settings.get("time", "08:30").split(":"))
    return (now.hour, now.minute) >= (hh, mm)


def start_scheduler(get_settings, get_last_sent, set_last_sent, make_digest, interval: float = 30.0,
                    stop: threading.Event = None):
    """Background thread: checks every `interval` seconds whether today's reminder is due."""
    stop = stop or threading.Event()

    def loop():
        while not stop.is_set():
            try:
                now = datetime.now()
                if due_to_send(get_settings(), get_last_sent(), now):
                    digest = make_digest(now.date())
                    if digest:
                        sent = notify(digest["title"], digest["body"])
                        print(f"Daily reminder {'sent' if sent else 'could not be shown'}: {digest['title']}", flush=True)
                    set_last_sent(now.date().isoformat())     # also on quiet days, so it isn't re-checked all day
            except Exception as e:
                print(f"Reminder check failed: {e!r}", flush=True)
            stop.wait(interval)

    thread = threading.Thread(target=loop, name="reminders", daemon=True)
    thread.start()
    return thread
