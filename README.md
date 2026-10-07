# Trackademic

[![Tests](https://github.com/Mysteryman4k/lifeplanner/actions/workflows/ci.yml/badge.svg)](https://github.com/Mysteryman4k/lifeplanner/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/Mysteryman4k/lifeplanner?label=download)](https://github.com/Mysteryman4k/lifeplanner/releases/latest)

A personal planner for students: assignments and study tasks, job applications and monthly money, all in one place. It runs on your own computer, needs no account and keeps your data offline.

## Features

- **Today**: what's overdue and due this week, your workload for the next 7 days, job follow-ups and how much budget is left
- **Tasks**: grouped by Overdue, Today, Next 7 days and Later; search and filter by subject or priority
- **Plan sessions**: splits a task's estimated hours into study sessions before the due date
- **Calendar**: month view with tasks on each day (weeks start on Monday)
- **Subjects**: your units with their weeks or topics and open task counts
- **Jobs**: a board from Applied to Offer, follow-up reminders and a list of closed applications
- **Money**: your own currency and monthly budget, money in and out by month, and budget bars showing what's left
- **Make it yours**: 6 colour themes (Sunset is the default), 5 text styles, light, dark or system mode, and an animated intro (can be turned off)
- **Backup**: one-click JSON export of everything

## Install (Windows)

1. Go to the [latest release](https://github.com/Mysteryman4k/lifeplanner/releases/latest) and download **Trackademic-Setup-x.y.z.exe**.
2. Run it. It installs for your account only, so no admin password is needed, and adds Start menu and desktop shortcuts.
3. Trackademic checks for new versions when it opens and offers **Update now**. Updates install in about a minute and keep all your data.

Prefer not to install? Download the **portable zip**, unzip it anywhere and run `Trackademic.exe`.

> Windows SmartScreen may say "Windows protected your PC" because the app isn't code-signed yet. Click **More info → Run anyway**.

## Run from source (for development)

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

## Tests

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium     # once, for the browser tests
pytest                                    # everything
pytest -m "not ui"                        # just the fast API tests
ruff check .                              # lint
```

Every push runs the **Tests** workflow on GitHub: API tests on Linux (Python 3.11–3.13) and Windows, a lint check, JavaScript and colour-contrast checks, and a real-browser smoke test of every screen. For `main` and pull requests it also builds the Windows app and **launches it for real**, checking it gets past the intro to the home screen (`tools/smoke_desktop.py`). The Release workflow runs the same start-up test on the exact build it's about to publish.

## Versions and releases

The version lives in the `VERSION` file and follows [Semantic Versioning](https://semver.org/): **major** for big changes, **minor** for new features, **patch** for fixes. `CHANGELOG.md` records what changed in each version.

To publish a new version:

```bash
python tools/bump_version.py minor        # or patch / major / an exact version like 3.4.0
# fill in the new section of CHANGELOG.md
git commit -am "Release v3.3.0"
git tag v3.3.0
git push origin main --tags
```

Pushing the tag runs the **Release** workflow, which:

1. runs all the tests,
2. checks the tag matches `VERSION`,
3. builds the app with PyInstaller, launches it and checks it opens properly, then builds the installer with Inno Setup,
4. publishes a GitHub Release with `Trackademic-Setup-x.y.z.exe`, a portable zip, `SHA256SUMS.txt`, and that version's changelog as the release notes.

Installed copies then see the update. The app only installs an update after checking its SHA-256 checksum against `SHA256SUMS.txt` from the same release, and only downloads from GitHub. Tags with a suffix like `v3.3.0-beta.1` are published as pre-releases, which the update check ignores.

To build locally: `pip install -r requirements-dev.txt`, then `pyinstaller --noconfirm Trackademic.spec` (output in `dist/Trackademic/`). For the installer, install [Inno Setup 6](https://jrsoftware.org/isinfo.php) and run `iscc /DAppVersion=3.2.0 installer\trackademic.iss`.

## Project layout

```
app.py              FastAPI backend + SQLite (all API routes)
desktop.py          Opens the app in a native window (pywebview)
updater.py          Update checks and verified installs from GitHub Releases
VERSION             The app version (single source of truth)
CHANGELOG.md        What changed in each version
installer/          Inno Setup script for the Windows installer
.github/workflows/  Tests on every push; builds and publishes releases on version tags
static/index.html   Page shell
static/splash.html  Desktop start-up screen (filled in by desktop.py, shown before the server is ready)
static/intro.css    Intro animation, shared by the splash and the app's hand-off overlay
static/theme.js     Colour themes, text styles and light/dark (applied before first paint)
static/styles.css   Components and layout, all driven by theme variables
static/app.js       Views, forms and state
static/icons.js     Line icons and the logo
static/fonts/       Outfit, Plus Jakarta Sans, Bricolage Grotesque, DM Sans, Space Grotesk, Fraunces (SIL Open Font License)
tests/              API, update and browser smoke tests
tools/              bump_version.py, release_notes.py, check_contrast.js, smoke_desktop.py (start-up test)
```

## Adding a colour theme or text style

Add an entry to `THEMES` or `FONTS` in `static/theme.js`, then add its key to the `Appearance` model in `app.py`. Font files go in `static/fonts/` with an `@font-face` rule at the top of `styles.css`. Then run `node tools/check_contrast.js`: text needs at least 4.5:1 contrast against its background.

## Renaming the app

Change `APP_NAME` and `APP_SLUG` at the top of `app.py`, add the old slug to `PREVIOUS_SLUGS` so existing data is carried over, and update the logo text in `static/index.html`.

---

© 2026 Mysteryman4k. All rights reserved.
