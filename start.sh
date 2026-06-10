#!/bin/bash
# Student Planner — Launch Script
cd "$(dirname "$0")"
echo "📚 Starting Student Planner..."
echo "   http://localhost:8585"
echo ""
venv/bin/python app.py
