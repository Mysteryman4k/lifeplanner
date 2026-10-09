# Changelog

All notable changes to Trackademic. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/): MAJOR for big changes, MINOR for new features,
PATCH for fixes. Pushing a tag like `v3.2.0` publishes that version's section as the GitHub release notes.

## [Unreleased]

## [3.5.2] - 2026-10-09

### Fixed

- Turning on "Start with Windows" could fail on a fresh Windows account. It now works on every account
- The red Delete button in confirm dialogs was hard to read in dark themes

### Added

- More automatic testing on every change: install and update from the last release on a real Windows machine, Windows-only checks, consistency checks and more browser tests

## [3.5.1] - 2026-10-07

### Fixed

- After an in-app update, the window could keep showing the previous version's screens from its cache, so new features (Reminders, Task types, Restore, Repeats, Money settings) didn't appear. Updates now always load the new screens
- Trackademic keeps its window cache in its own folder (`%APPDATA%\Trackademic\webview`) instead of a folder shared with other apps

## [3.5.0] - 2026-10-07

### Added

- Daily reminders as Windows notifications: what's due today, what's overdue and job follow-ups, at a time you choose. Only sent on days with something to do, and caught up if the app opens later. "Send test" shows one straight away
- Start with Windows (optional): opens Trackademic minimised when you sign in, so reminders arrive without opening it
- Repeating tasks: daily, weekly, every 2 weeks or monthly. Ticking one off adds the next with the same details. Repeating tasks show a "Daily"/"Weekly" tag
- Manage task types in Settings: add your own, rename them and change their colours. Deleting one keeps its tasks
- Restore from a backup file in Settings. It shows what's in the backup before replacing anything, and saves your current data first
- Automatic backups: a copy of your data is saved each day you open the app, keeping the last 10

### Changed

- Opening Trackademic while it's already open brings the open window forward instead of starting a second copy
- The taskbar icon and notifications are grouped under Trackademic

## [3.4.0] - 2026-10-07

### Added

- Choose your currency (any currency, with the right symbol). It's pre-selected from your Windows region
- "Set up your budget": one screen to choose your currency and set a monthly amount per category, with a live total. Add your own categories, and come back any time to change or clear amounts
- Money settings in Settings: currency and budget

### Changed

- New installs start with no budget instead of a made-up $1,500. Today and Money invite you to set one up
- Spending can be logged in any category, even without a budget for it

### Fixed

- Sample budgets from earlier versions are removed if you never changed them and haven't recorded any money. Anything you entered is kept

## [3.3.1] - 2026-10-07

### Fixed

- The app could get stuck on the intro animation on Windows and never open. The start-up no longer waits on the window in a way that can hang
- Safety nets: the start-up screen opens the app by itself if the hand-off is late, and the fade-in overlay can never cover the app for more than a few seconds
- The release build no longer fails when the changelog contains characters like arrows

### Added

- Start-up steps are timestamped in `trackademic.log`, so any slow or stuck start can be diagnosed
- Every release now launches the real packaged app on Windows and checks it reaches the home screen before publishing

## [3.3.0] - 2026-10-06

### Added

- Animated intro when the desktop app opens: the logo builds itself, the tick draws in, and the name slides up over a drifting aurora in your colour theme, then dissolves into the app
- The intro uses your chosen colour theme, text style and light/dark mode
- A loading bar appears if start-up takes longer than the animation
- Option in Settings → Appearance to turn the intro off for a quicker, plain loading screen

### Changed

- The app window appears immediately on launch instead of after the local server has started

## [3.2.0] - 2026-10-06

### Added

- Windows installer: download one file, install without admin rights, Start menu and desktop shortcuts, clean uninstall
- In-app updates: Trackademic checks GitHub for new versions and can download, verify and install them in one click
- Option to turn off automatic update checks
- The packaged app writes a log file (`%APPDATA%\Trackademic\trackademic.log`) to help with bug reports
- Automated tests and release builds on GitHub Actions

### Changed

- The app is packaged as a folder instead of a single `.exe`, so it opens much faster

## [3.1.0] - 2026-10-06

### Added

- New name: Trackademic
- 6 colour themes (Sunset is the default), 5 text styles, and light, dark or system mode, saved in the app
- New logo and app icons

### Changed

- Data saved under the old LifePlanner name is copied across automatically

## [3.0.0] - 2026-10-06

### Added

- Today screen, task groups, calendar, subjects with units, job board, monthly money view
- Study-session planner, one-click backup, keyboard shortcuts

### Fixed

- A failed save no longer freezes the database
- The packaged app no longer loses data when it closes
- Dates are correct in Melbourne mornings; overdue clears when a due date moves
- Input is validated; names can't run as code; the server only listens on this computer
