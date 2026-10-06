@echo off
REM LifePlanner - first run sets everything up, later runs just start the app.
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
  echo Setting up LifePlanner for the first time...
  python -m venv venv || (echo Python was not found. Install it from python.org or run this from the Anaconda Prompt. & pause & exit /b 1)
  venv\Scripts\python -m pip install --upgrade pip >nul
  venv\Scripts\python -m pip install -r requirements.txt || (pause & exit /b 1)
  venv\Scripts\python -m pip install -r requirements-desktop.txt || echo Native window not available - LifePlanner will open in your browser instead.
)
venv\Scripts\python -c "import webview" 2>nul && (start "" venv\Scripts\pythonw.exe desktop.py) || (venv\Scripts\python.exe desktop.py)
