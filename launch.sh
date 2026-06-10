#!/bin/bash
# LifePlanner Desktop Launcher
# Starts the server and opens the default browser

APP_DIR="/home/sean/hermes-workspace/student-planner"
cd "$APP_DIR"

# Kill any existing instance
pkill -f "uvicorn.*app:app.*8585" 2>/dev/null
sleep 0.5

# Start server in background
"$APP_DIR/venv/bin/python" "$APP_DIR/app.py" &
SERVER_PID=$!

# Wait for server to be ready
for i in $(seq 1 15); do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:8585/ 2>/dev/null | grep -q 200; then
        break
    fi
    sleep 0.3
done

# Open browser
xdg-open http://localhost:8585/ 2>/dev/null || sensible-browser http://localhost:8585/ 2>/dev/null || echo "Open http://localhost:8585 in your browser"

# Wait for server (keep terminal open if launched from terminal)
wait $SERVER_PID
