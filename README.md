# 📚 Student Planner

A beautiful, professional daily planner for students — track assignments, projects, and deadlines with smart auto-planning. Runs locally with zero login required.

## ✨ Features

- **📊 Dashboard** — Stats overview: total tasks, completion rate, upcoming deadlines, category breakdown
- **✅ Task Management** — Create, edit, complete, and delete tasks with full details
- **🎯 Smart Auto-Plan** — Enter a due date + estimated hours, and the planner generates a spaced study schedule
- **📅 Calendar View** — Monthly calendar with color-coded task dots
- **🔍 Search & Filter** — Search by title, filter by priority, status, or category
- **🏷 Categories** — 6 default categories with colored badges (Assignment, Exam, Project, Reading, Personal, Other)
- **⚡ Priority Levels** — Low, Medium, High, Urgent with visual badges
- **📈 Progress Tracking** — 0-100% progress bar for each task
- **🎉 Completion Celebration** — Confetti animation when you mark a task done
- **🌙 Dark/Light Theme** — Toggle between dark and light modes, saved across sessions
- **⌨️ Keyboard Shortcuts** — Ctrl+N for new task, Esc to close modals
- **🔔 Smart Status** — Tasks automatically marked overdue when past their due date

## 🚀 Quick Start

```bash
cd /home/sean/hermes-workspace/student-planner
./start.sh
```

Then open **http://localhost:8585** in your browser.

## 🛠 Tech Stack

- **Backend:** Python 3.12 + FastAPI + SQLite
- **Frontend:** Vanilla HTML/CSS/JS (no framework, no build step)
- **Design:** Custom design system with CSS variables for theming
- **Database:** SQLite (zero configuration, stored locally)

## 📁 Project Structure

```
student-planner/
├── app.py              # FastAPI backend + API endpoints
├── planner.db          # SQLite database (auto-created)
├── start.sh            # Launch script
├── venv/               # Python virtual environment
└── static/
    └── index.html      # Complete frontend SPA
```

## 🔌 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/tasks` | List tasks (filter by status, category, priority, search) |
| POST | `/api/tasks` | Create task |
| GET | `/api/tasks/{id}` | Get single task |
| PUT | `/api/tasks/{id}` | Update task |
| DELETE | `/api/tasks/{id}` | Delete task |
| POST | `/api/tasks/{id}/auto-plan` | Generate smart completion plan |
| GET | `/api/categories` | List categories |
| POST | `/api/categories` | Create category |
| DELETE | `/api/categories/{id}` | Delete category |
| GET | `/api/stats` | Get dashboard statistics |
