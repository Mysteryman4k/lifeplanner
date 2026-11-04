# EasyUniTrack for Android (and later iPhone)

The phone app runs the desktop app's own screens (`static/`) in a [Capacitor](https://capacitorjs.com) app. The
desktop's server (`app.py`, `ai/`) can't run on a phone, so this folder has a TypeScript version of it that runs
on the phone: the screens call `fetch('/api/…')` as usual, and `src/main.ts` answers those calls from the
phone's own SQLite database.

```
src/main.ts           Starts the app: opens the database, answers /api/… calls, reminders, the back button
src/http.ts           A small router with FastAPI's status codes and error bodies
src/validate.ts       The desktop's Pydantic rules and messages
src/api/              app.py's routes: tasks, subjects, notes, jobs, money, settings, backup
src/ai/               ai/'s routes: terms, providers (Anthropic, OpenAI-compatible), task tools, chats, attachments
src/db/               SQLite: the same tables as the desktop (native on the phone, sql.js in tests and the preview)
src/reminders.ts      The daily reminder, handed to the system two weeks ahead so it comes while the app is closed
src/platform/         Notifications, files, sharing, the key store and streamed requests on the phone
web/mobile.css        The phone's touches on top of styles.css (the More screen, tab counts)
android/              The Android project (StreamFetchPlugin.java streams the assistant's replies)
tests/                Vitest: the API, parity with the desktop server, the phone's extras, and the app in a browser
```

## What's the same, and what's different

Everything in the planner works as on the desktop, and a backup from either restores on the other. On the phone:

- **Tabs:** Today, Tasks, Calendar, Money and More (Subjects, Jobs, Settings). Once the assistant is on, Study
  takes Money's place in the tab bar and Money moves to More
- **Reminders** arrive even while the app is closed, at the time you choose: the next two weeks are scheduled
  each time the app opens
- **Backups** go to the share sheet (Drive, Files, email…); restore picks a file from the phone
- **The study assistant** works with Anthropic, OpenAI, DeepSeek or another OpenAI-compatible service. Keys are
  kept in the phone's secure storage (Android Keystore). Code files can be attached to a chat
- **Not on the phone:** the code workspace (it links project folders and runs programs on a computer), Ollama
  (it runs models on a computer), Start with Windows, and self-updates (Google Play updates the app)

## Working on it

```bash
cd mobile
npm ci
npm run build          # www/: the screens, the phone's backend (mobile.js) and pdf.js
npm run preview        # the app in your browser at http://localhost:8686 (use the browser's phone view)
npm test               # API and phone tests
npx tsc --noEmit       # type check
```

More tests, as CI runs them:

```bash
EUT_PYTHON=../venv/bin/python npx vitest run   # also compare every response with the real desktop server
EUT_UI=1 npx vitest run                         # also the app at phone size in Chromium (npx playwright install chromium)
```

The parity tests (`tests/parity.test.ts`) run each scenario on the phone's API and on a fresh `app.py`, and
compare every response. **When you change a route in `app.py`, change it in `src/api/` too**; the parity tests
and the route check fail until both agree. The prompts are checked word for word against `ai/prompts.py`.

## Android

Needs Android Studio (or the Android SDK) and Java 21.

```bash
npm run android                   # build, copy into android/ and open Android Studio
cd android && ./gradlew assembleDebug   # or build the APK from the command line
```

The version comes from the repository's `VERSION` file. CI builds the debug app on every push (download it
from the run's artifacts) and checks the release build. To sign a release build, set `EUT_KEYSTORE`,
`EUT_KEYSTORE_PASSWORD`, `EUT_KEY_ALIAS` and `EUT_KEY_PASSWORD`. After changing `static/icon.svg`, redraw the
launcher icons with `node scripts/android-assets.mjs`.
