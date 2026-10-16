# Changelog

All notable changes to Trackademic. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/): MAJOR for big changes, MINOR for new features,
PATCH for fixes. Pushing a tag like `v3.2.0` publishes that version's section as the GitHub release notes.

## [Unreleased]

## [4.0.0-beta.2] - 2026-10-16

### Fixed

- The portable version (the zip) didn't start in 4.0.0-beta.1: Windows marks files unzipped from a download, and the part that draws the window refused to load them. It starts now. If the window still can't open for some other reason, EasyUniTrack opens in your browser instead of closing with an error. The installer wasn't affected

## [4.0.0-beta.1] - 2026-10-15

The first beta of version 4. Installed copies don't update to betas: download it from this page if you'd like to try it. Your data is backed up automatically before version 4 first opens it.

### Added (preview, off by default)

- Settings has a new Study assistant section (preview). Turning it on shows what the AI features can and can't do, then the terms of use, which need three ticks to agree. Until then nothing about AI appears anywhere in the app
- Choose an AI provider: Anthropic, OpenAI, DeepSeek, a custom OpenAI-compatible service, or Ollama for free local models. Test the connection, pick a model, and see what this PC can run. API keys are kept in Windows Credential Manager, never in your data or backups
- Ollama's cloud models are labelled, because they send your messages to ollama.com rather than staying on your PC
- Study assistant (preview): a new Study page appears in the sidebar once the assistant is on. Ask about your units in Explain or Practise mode; replies appear as they're written, with Stop, a token count, Copy and Report this response
- "Help me with this" on any task opens the assistant in a side panel with the task's details attached, and "Open full page" carries the conversation over
- Notes inside subjects: each subject card has a Notes list (shown once the assistant is on, or when the subject has notes). Write your own, save any assistant reply with "Save as note", or have the assistant "Write notes on a topic" for you to check and save. Notes are included in Download backup, and kept (under "Other notes") if their subject is deleted
- The study assistant can add, change and complete tasks when you ask it to. Each change shows a card with Undo, which puts the task back exactly as it was. Deleting a task, or more than 3 changes at once, waits for you to confirm in the chat
- The study assistant shows maths properly (KaTeX), highlights code with a Copy button, and draws diagrams (flowcharts, sequence, state and class diagrams, mind maps). Pick a format for replies (notes, diagram, both, maths or code), or use "Show as…" to see the last answer another way. If a diagram can't be drawn you see its source and Try again. Notes show maths and diagrams too, and everything works offline
- Code workspace (preview, its own switch in Settings): link a code folder to a subject and choose Assignment (hints first) or Personal project (fix freely). Browse the files with highlighting and line numbers; secrets like .env files, anything in .gitignore, dependency and build folders, binary files and files over 200 KB are shown as hidden and never read or sent. Each question shows which files go with it (the open file, what it imports, and files named in an error) and you can take any off. Explain the error marks the lines an error points at, and Debug looks for the bug in the open file. Files the app can't run, like SQL or HTML, are labelled Explain only. Nothing in your folder is changed or run
- Proposed changes in the code workspace: the assistant suggests a fix as a red and green diff, and nothing changes until you click Apply. Apply keeps a backup of the original, and Undo puts the file back exactly as it was. If you've edited the file since the suggestion, Apply refuses rather than overwrite your work. In an Assignment folder, suggestions are a few lines at most and only when you ask for a fix
- Run code from the code workspace: EasyUniTrack finds the compilers and tools on your PC and suggests a command for the open file or the project (npm scripts, Django and Flask, Maven and Gradle, .NET, CMake and Make, Cargo, Go). You can edit the command before clicking Run. Output appears as it's printed, there's a box for keyboard input, servers can keep running with an Open in browser link, and Stop ends the program and anything it started. Runs stop after a time limit you choose, and errors link to the line they point at. The assistant can suggest a command with a Run this? card, but only your click runs it. The first time, a short notice explains that code runs with your permissions, so only run code you trust
- More help with code in the code workspace: Trace (a table of each variable, line by line), Big-O (time and space complexity with the reasoning), Visualise (diagrams of the lists, trees, graphs, stacks and queues your code builds), Write tests (in an Assignment folder, Plan tests suggests cases for you to write), Explain my change (what changed since your last git commit, or since you opened the file) and Practice (a new problem like yours, with hints)
- Chats are saved: they're kept after each reply, listed under Recent chats in the sidebar and in Chats on the Study page, and open again where you left off (code chats in their folder). They're included in Download backup
- Two more study modes: Quiz me (a short quiz, one question at a time, with buttons for multiple-choice answers, marked as you go) and Check my attempt (feedback on your own working without rewriting it)
- A Videos button on replies suggests YouTube searches for the topic
- Attach study material to a chat: click the paperclip, or drop a file on the chat. PDF, PowerPoint (.pptx, with speaker notes), Word (.docx), text and Markdown files are read on your PC, and their text goes with each question. If a file is too long for one question, you choose which pages or slides to send (EasyUniTrack never cuts it short without saying so), and you see roughly how many tokens it adds. Quick buttons: Summarise, Write notes on this, Quiz me on this. With Ollama, EasyUniTrack checks how much your setup can read at once and says how to raise it. Scanned PDFs (pictures of pages) and password-protected files are explained rather than sent empty. While a file is attached, task changes always ask first. The chosen pages are kept with the saved chat
- Long chats keep their thread: once a chat is longer than the last 20 messages that go with each question, the older ones are summarised every few turns and the summary goes instead. "Earlier messages are summarised for the assistant" shows what it remembers. The summary is saved with the chat
- Keep chats (Settings): choose to delete saved chats you haven't continued for a month, 3 months, 6 months or a year. It asks before deleting any. Chats are kept until you delete them unless you choose a limit
- Suggested code changes, the backups Undo uses and the record of changes to your tasks are cleared after 90 days (the newest are always kept), so they don't grow forever
- Link a code folder from a subject: each subject shows its code folders (when the code workspace is on), with a button to link one. Settings lists every linked folder, with Unlink
- Remove all AI data now also removes chats, linked code folders (not the folders themselves) and suggested changes with their backups. Notes stay
- Before a new version changes your data for the first time, EasyUniTrack keeps a copy of it in the backups folder

### Changed

- A calmer, plainer look. The new default theme, Plain, uses neutral greys and one quiet accent colour, with your computer's own font. There are no gradients or glows, and cards, buttons and headings are flatter and smaller. The colourful themes are still in Settings, also calmer than before. If you changed the look before, you keep yours
- The chat has one message box with attach and send inside it, and the tools under replies are small icons
- The code workspace looks like a code editor: dark colours with familiar syntax highlighting, the open file as a tab, and run output like a terminal. In a narrow window the code and chat stay in view, with a Files button for the file list
- Tables in the assistant's replies (like Trace's step-by-step table) are shown as tables
- The privacy policy now covers the optional AI features: what's stored on your PC, what's sent to the AI provider you choose and when, and how to remove it. The AI terms of use are also published as TERMS.md
- Messages you send in a chat keep their spacing, so a pasted error or code keeps its indentation

### Security

- EasyUniTrack's built-in server now only answers EasyUniTrack itself. Websites open in your browser can no longer read or change your planner data, even with tricks that point a web address at your own computer

## [3.6.1] - 2026-10-13

### Fixed

- In the calendar's day panel, task names are no longer cut short and their details are easier to read

### Added

- A privacy policy, linked from the README: EasyUniTrack has no accounts, ads or tracking, and your data stays on your computer

## [3.6.0] - 2026-10-13

### Changed

- Trackademic is now called EasyUniTrack. Updating keeps everything: your data is copied to the new `%APPDATA%\EasyUniTrack` folder (the old folder is left in place), "Start with Windows" stays on if you had it on, and backups made under the old name still restore

### Added

- EasyUniTrack can be packaged for the Microsoft Store, where the Store handles updates

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
