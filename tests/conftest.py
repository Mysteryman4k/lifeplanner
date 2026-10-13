"""Shared test setup: no test may ever read or write the real user data folder."""
import os
import tempfile

# Set before any test imports app.py, which picks its data folder (and copies old data across) on import.
# Tests that need their own folder still override this with monkeypatch.
os.environ["TRACKADEMIC_DATA_DIR"] = tempfile.mkdtemp(prefix="easyunitrack-tests-")
