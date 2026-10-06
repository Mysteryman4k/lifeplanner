# Changelog

All notable changes to Trackademic. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/): MAJOR for big changes, MINOR for new features,
PATCH for fixes. Pushing a tag like `v3.2.0` publishes that version's section as the GitHub release notes.

## [Unreleased]

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
