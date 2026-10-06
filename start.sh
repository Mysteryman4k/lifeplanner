#!/bin/bash
# Trackademic — first run sets everything up, later runs just start the app.
cd "$(dirname "$0")"
if [ ! -d venv ]; then
  echo "Setting up Trackademic for the first time..."
  python3 -m venv venv && venv/bin/pip install -q -r requirements.txt || exit 1
  venv/bin/pip install -q -r requirements-desktop.txt || echo "Native window not available — opening in your browser instead."
fi
if [ "$1" = "--browser" ]; then
  venv/bin/python app.py          # open http://127.0.0.1:8585 in your browser
else
  venv/bin/python desktop.py
fi
