# Trackademic

A personal planner for students: assignments and study tasks, job applications and monthly money, all in one place. It runs on your own computer, needs no account and keeps your data offline.

## Features

- **Today**: what's overdue and due this week, your workload for the next 7 days, job follow-ups and how much budget is left
- **Tasks**: grouped by Overdue, Today, Next 7 days and Later; search and filter by subject or priority
- **Plan sessions**: splits a task's estimated hours into study sessions before the due date
- **Calendar**: month view with tasks on each day (weeks start on Monday)
- **Subjects**: your units with their weeks or topics and open task counts
- **Jobs**: a board from Applied to Offer, follow-up reminders and a list of closed applications
- **Money**: money in and out by month, budgets with progress bars and remaining amounts
- **Make it yours**: 6 colour themes (Sunset is the default), 5 text styles, and light, dark or system mode
- **Backup**: one-click JSON export of everything

## Run it

**Windows:** double-click `start.bat`. The first run creates a virtual environment and installs the dependencies, which takes about a minute.

**macOS / Linux:**

```bash
./start.sh            # desktop window
./start.sh --browser  # or serve on http://127.0.0.1:8585
```

**Manually:**

```bash
python -m venv venv
venv\Scripts\activate        # Windows  (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt -r requirements-desktop.txt
python desktop.py            # or: python app.py  then open http://127.0.0.1:8585
```

On Windows the desktop window uses Microsoft Edge WebView2, which is built into Windows 10 and 11. If the native window (`pywebview`) can't be installed on your Python version, `desktop.py` opens the app in your default browser instead.

## Where your data lives

| System  | Location |
|---------|----------|
| Windows | `%APPDATA%\Trackademic\planner.db` |
| macOS   | `~/Library/Application Support/Trackademic/planner.db` |
| Linux   | `~/.local/share/Trackademic/planner.db` |

Set `TRACKADEMIC_DATA_DIR` to use a different folder. Data from earlier versions, saved under the old LifePlanner name or next to `app.py`, is copied across automatically the first time you run this version.

## Build a standalone app

```bash
pip install -r requirements-dev.txt
pyinstaller Trackademic.spec          # output: dist/Trackademic(.exe)
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Project layout

```
app.py              FastAPI backend + SQLite (all API routes)
desktop.py          Opens the app in a native window (pywebview)
static/index.html   Page shell
static/theme.js     Colour themes, text styles and light/dark (applied before first paint)
static/styles.css   Components and layout, all driven by theme variables
static/app.js       Views, forms and state
static/icons.js     Line icons and the logo
static/fonts/       Outfit, Plus Jakarta Sans, Bricolage Grotesque, DM Sans, Space Grotesk, Fraunces (SIL Open Font License)
tests/              API tests
```

## Adding a colour theme or text style

Add an entry to `THEMES` or `FONTS` in `static/theme.js`, then add its key to the `Appearance` model in `app.py`. Font files go in `static/fonts/` with an `@font-face` rule at the top of `styles.css`. Then run `node tools/check_contrast.js`: text needs at least 4.5:1 contrast against its background.

## Renaming the app

Change `APP_NAME` and `APP_SLUG` at the top of `app.py`, add the old slug to `PREVIOUS_SLUGS` so existing data is carried over, and update the logo text in `static/index.html`.

---

© 2026 Mysteryman4k. All rights reserved.
