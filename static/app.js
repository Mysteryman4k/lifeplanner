/* ═══════════════════════════════════════════════════════════════
   Trackademic — frontend
   Plain JavaScript, no build step. One state object, render on change.
   ═══════════════════════════════════════════════════════════════ */
'use strict';

// ── Small helpers ─────────────────────────────────────────────────
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const pad = n => String(n).padStart(2, '0');
/** Local calendar date as YYYY-MM-DD (never UTC — toISOString() gave yesterday's date before 11am in Melbourne). */
const ymd = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const todayStr = () => ymd(new Date());
const parseDate = s => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
const addDays = (s, n) => { const d = parseDate(s); d.setDate(d.getDate() + n); return ymd(d); };
const daysBetween = (a, b) => Math.round((parseDate(b) - parseDate(a)) / 86400000);
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ESC[c]);
const AUD = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD' });
const AUD0 = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD', maximumFractionDigits: 0 });
const money = (n, whole = false) => (whole ? AUD0 : AUD).format(n || 0);
const fmt = (s, opts) => parseDate(s).toLocaleDateString('en-AU', opts);
const shortDate = s => fmt(s, { day: 'numeric', month: 'short' });
const longDate = s => fmt(s, { weekday: 'long', day: 'numeric', month: 'long' });
const monthLabel = ym => parseDate(ym + '-01').toLocaleDateString('en-AU', { month: 'long', year: 'numeric' });
const plural = (n, word, many = word + 's') => `${n} ${n === 1 ? word : many}`;

const PRIORITY_RANK = { urgent: 0, high: 1, medium: 2, low: 3 };
const SUBJECT_COLORS = ['#2F5D50', '#3B6EA8', '#7B4FA3', '#B4532A', '#A67C00', '#B23A5B', '#4F7A28', '#5B6170'];
const GRADES = ['', 'HD', 'D', 'C', 'P'];
const JOB_STAGES = [
  { key: 'applied', label: 'Applied' },
  { key: 'phone_screen', label: 'Screening' },
  { key: 'interviewing', label: 'Interviewing' },
  { key: 'offer', label: 'Offer' },
];
const JOB_CLOSED = { accepted: 'Accepted', rejected: 'Rejected', withdrawn: 'Withdrawn' };
const JOB_LABEL = { ...Object.fromEntries(JOB_STAGES.map(s => [s.key, s.label])), ...JOB_CLOSED };
const ACTIVE_JOB = new Set(JOB_STAGES.map(s => s.key));
const INCOME_CATEGORIES = ['Wages', 'Allowance', 'Gift', 'Other income'];

// ── State ─────────────────────────────────────────────────────────
const state = {
  tasks: [], categories: [], subjects: [], jobs: [], budgets: [], transactions: [], info: {},
  month: todayStr().slice(0, 7),
  taskFilter: 'open', taskSearch: '', taskSubject: '', taskPriority: '',
  calMonth: todayStr().slice(0, 7), calSel: todayStr(),
  drawer: null,
  update: null, updateSettings: { auto_check: true }, updateDismissed: false, checkingUpdate: false,
};

// ── API ───────────────────────────────────────────────────────────
async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = 'Something went wrong';
    try {
      const e = await res.json();
      if (typeof e.detail === 'string') msg = e.detail;
      else if (Array.isArray(e.detail) && e.detail[0]) {
        const d = e.detail[0];
        const field = (d.loc || []).slice(-1)[0];
        msg = `${field ? field.replace(/_/g, ' ') + ': ' : ''}${d.msg.replace(/^Value error, /, '')}`;
      }
    } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
}

async function loadAll() {
  const [tasks, categories, subjects, jobs, info, appearance] = await Promise.all([
    api('/api/tasks'), api('/api/categories'), api('/api/subjects'), api('/api/jobs'), api('/api/info'),
    api('/api/settings/appearance').catch(() => null),
  ]);
  // The database copy is the source of truth (localStorage only avoids a flash on start-up)
  if (appearance && JSON.stringify(appearance) !== JSON.stringify(window.__appearance)) {
    saveAppearanceLocal(applyAppearance(appearance));
    $('.brand-mark').innerHTML = BRAND_MARK;
  }
  Object.assign(state, { tasks, categories, subjects, jobs, info });
  document.title = info.name || 'Trackademic';
  await loadMoney();
}

async function loadMoney() {
  const [budgets, transactions] = await Promise.all([
    api('/api/budgets?month=' + state.month), api('/api/transactions?month=' + state.month),
  ]);
  Object.assign(state, { budgets, transactions });
}

// ── Task logic ────────────────────────────────────────────────────
const isDone = t => t.status === 'completed';
const isLate = t => !isDone(t) && t.due_date && t.due_date < todayStr();

function dueInfo(t) {
  if (!t.due_date) return { text: '', cls: '' };
  const diff = daysBetween(todayStr(), t.due_date);
  if (isDone(t)) return { text: shortDate(t.due_date), cls: '' };
  if (diff < 0) return { text: diff === -1 ? 'Yesterday' : `${-diff} days late`, cls: 'late' };
  if (diff === 0) return { text: 'Today', cls: 'today' };
  if (diff === 1) return { text: 'Tomorrow', cls: '' };
  if (diff < 7) return { text: fmt(t.due_date, { weekday: 'short' }), cls: '' };
  return { text: shortDate(t.due_date), cls: '' };
}

function bucketOf(t) {
  if (isDone(t)) return 'done';
  if (!t.due_date) return 'none';
  const diff = daysBetween(todayStr(), t.due_date);
  if (diff < 0) return 'late';
  if (diff === 0) return 'today';
  if (diff <= 7) return 'week';
  return 'later';
}
const BUCKETS = [
  ['late', 'Overdue'], ['today', 'Today'], ['week', 'Next 7 days'], ['later', 'Later'], ['none', 'No due date'], ['done', 'Done'],
];

const byDueThenPriority = (a, b) =>
  (a.due_date || '9999').localeCompare(b.due_date || '9999') || PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority];

function subjectById(id) { return state.subjects.find(s => s.id === id); }

function taskRow(t) {
  const due = dueInfo(t);
  const subj = subjectById(t.subject_id);
  const meta = [
    subj ? `<span><i class="dot" style="--c:${esc(subj.color)}"></i>${esc(subj.name)}</span>` : '',
    t.unit_name ? `<span>${esc(t.unit_name)}</span>` : '',
    t.category_name ? `<span>${esc(t.category_name)}</span>` : '',
    t.estimated_hours ? `<span>${icon('clock', 13)}${esc(t.estimated_hours)}h</span>` : '',
    t.target_grade ? `<span>Aiming for ${esc(t.target_grade)}</span>` : '',
  ].filter(Boolean).join('');
  const prio = (t.priority === 'urgent' || t.priority === 'high') && !isDone(t)
    ? `<span class="prio ${t.priority}" title="${t.priority} priority">${icon('flag', 13)}<span class="prio-label">${t.priority}</span></span>` : '';
  const progress = t.progress > 0 && !isDone(t)
    ? `<span class="mini-progress" title="${t.progress}% done"><i style="width:${t.progress}%"></i></span>` : '';
  return `
    <div class="task ${isDone(t) ? 'done' : ''}" data-action="open-task" data-id="${t.id}">
      <button class="check ${isDone(t) ? 'done' : ''}" data-action="toggle-task" data-id="${t.id}"
        aria-label="${isDone(t) ? 'Mark as not done' : 'Mark as done'}: ${esc(t.title)}">${icon('check', 14)}</button>
      <div class="task-main">
        <div class="task-title">${esc(t.title)}</div>
        ${meta ? `<div class="task-meta">${meta}</div>` : ''}
      </div>
      <div class="task-side">${progress}${prio}<span class="due ${due.cls}">${esc(due.text)}</span></div>
    </div>`;
}

function taskGroups(list, { showDone = false } = {}) {
  const groups = {};
  list.forEach(t => (groups[bucketOf(t)] ||= []).push(t));
  return BUCKETS.filter(([k]) => groups[k] && (k !== 'done' || showDone)).map(([k, label]) => {
    const items = groups[k].sort(k === 'done' ? (a, b) => (b.updated_at || '').localeCompare(a.updated_at || '') : byDueThenPriority);
    return `<section class="task-group">
      <h3 class="group-label ${k === 'late' ? 'danger' : ''}">${label} <span class="num">${items.length}</span></h3>
      <div class="task-list">${items.map(taskRow).join('')}</div>
    </section>`;
  }).join('');
}

function emptyState(iconName, title, text, action = '') {
  return `<div class="empty">${icon(iconName, 40)}<h3>${title}</h3><p>${text}</p>${action}</div>`;
}

// ── Navigation ────────────────────────────────────────────────────
const ROUTES = {
  today: { label: 'Today', icon: 'today' },
  tasks: { label: 'Tasks', icon: 'tasks' },
  calendar: { label: 'Calendar', icon: 'calendar' },
  subjects: { label: 'Subjects', icon: 'subjects' },
  jobs: { label: 'Jobs', icon: 'jobs' },
  money: { label: 'Money', icon: 'money' },
  settings: { label: 'Settings', icon: 'settings' },
};
const route = () => { const r = location.hash.replace(/^#\/?/, '').split('?')[0]; return ROUTES[r] ? r : 'today'; };

function renderNav() {
  const r = route();
  const late = state.tasks.filter(isLate).length;
  const follow = state.jobs.filter(j => ACTIVE_JOB.has(j.status) && j.follow_up_date && j.follow_up_date <= todayStr()).length;
  const counts = { tasks: late ? { n: late, alert: true } : null, jobs: follow ? { n: follow, alert: true } : null };
  const item = key => {
    const c = counts[key];
    return `<a class="nav-item ${r === key ? 'active' : ''}" href="#/${key}" ${r === key ? 'aria-current="page"' : ''}>
      ${icon(ROUTES[key].icon)}<span>${ROUTES[key].label}</span>
      ${c ? `<span class="nav-count ${c.alert ? 'alert' : ''}" title="${key === 'tasks' ? 'Overdue' : 'Follow-ups due'}">${c.n}</span>` : ''}</a>`;
  };
  $('#nav').innerHTML = `
    <div class="nav-label">Plan</div>${['today', 'tasks', 'calendar', 'subjects'].map(item).join('')}
    <div class="nav-label">Track</div>${['jobs', 'money'].map(item).join('')}`;
  $('#navFoot').innerHTML = item('settings');
  $('#tabbar').innerHTML = ['today', 'tasks', 'calendar', 'jobs', 'money'].map(k =>
    `<a class="tab ${r === k ? 'active' : ''}" href="#/${k}">${icon(ROUTES[k].icon, 22)}<span>${ROUTES[k].label}</span></a>`).join('');
}

function setHeader(title, eyebrow = '', actions = '') {
  $('#pageTitle').textContent = title;
  $('#eyebrow').textContent = eyebrow;
  const gear = route() !== 'settings'
    ? `<a class="icon-btn mobile-only" href="#/settings" aria-label="Settings">${icon('settings', 20)}</a>` : '';
  $('#headerActions').innerHTML = actions + gear;
}

const btn = (action, label, iconName, cls = 'btn-primary', extra = '') =>
  `<button class="btn ${cls}" data-action="${action}" ${extra}>${iconName ? icon(iconName, 17) : ''}<span class="btn-label">${label}</span></button>`;

function render() {
  renderNav();
  const r = route();
  VIEWS[r]();
  $('.brand-mark').innerHTML = BRAND_MARK;
}

// ── Views ─────────────────────────────────────────────────────────
const VIEWS = {
  today() {
    const t = todayStr();
    const hour = new Date().getHours();
    const greet = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
    setHeader(greet, longDate(t), btn('new-task', 'New task', 'plus'));

    const open = state.tasks.filter(x => !isDone(x));
    const late = open.filter(isLate);
    const weekEnd = addDays(t, 7);
    const dueWeek = open.filter(x => x.due_date && x.due_date >= t && x.due_date <= weekEnd);
    const activeJobs = state.jobs.filter(j => ACTIVE_JOB.has(j.status));
    const followDue = activeJobs.filter(j => j.follow_up_date && j.follow_up_date <= t);
    const isThisMonth = state.month === t.slice(0, 7);
    const budgetTotal = state.budgets.reduce((s, b) => s + b.monthly_limit, 0);
    const spent = state.budgets.reduce((s, b) => s + b.spent, 0);
    const left = budgetTotal - spent;
    const lastDay = new Date(+t.slice(0, 4), +t.slice(5, 7), 0).getDate();
    const daysLeft = lastDay - +t.slice(8) + 1;

    const focus = open.filter(x => x.due_date && x.due_date <= weekEnd).sort(byDueThenPriority);
    const focusShown = focus.slice(0, 8);

    // Workload: estimated hours (or 1h if not set) of open tasks due on each of the next 7 days
    const days = [...Array(7)].map((_, i) => addDays(t, i));
    const load = days.map(d => open.filter(x => x.due_date === d).reduce((s, x) => s + (x.estimated_hours || 1), 0));
    const max = Math.max(4, ...load);

    const followSoon = activeJobs.filter(j => j.follow_up_date && j.follow_up_date <= addDays(t, 3))
      .sort((a, b) => a.follow_up_date.localeCompare(b.follow_up_date)).slice(0, 5);

    $('#content').innerHTML = `
      <div class="stack">
        <div class="tiles">
          <a class="card tile" href="#/tasks">
            <div class="tile-left">
              <div class="tile-top">Due this week</div>
              <div class="tile-note">${late.length ? `<span class="bad">${late.length} overdue</span>` : 'Nothing overdue'}</div>
            </div>
            <div class="tile-value">${dueWeek.length}<small>${dueWeek.length === 1 ? 'task' : 'tasks'}</small></div>
          </a>
          <a class="card tile" href="#/jobs">
            <div class="tile-left">
              <div class="tile-top">Active applications</div>
              <div class="tile-note">${followDue.length ? `<span class="warn">${plural(followDue.length, 'follow-up')} due</span>` : 'No follow-ups due'}</div>
            </div>
            <div class="tile-value">${activeJobs.length}</div>
          </a>
          <a class="card tile" href="#/money">
            <div class="tile-left">
              <div class="tile-top">Left to spend</div>
              <div class="tile-note">${isThisMonth ? `of ${money(budgetTotal, true)} · ${plural(daysLeft, 'day')} left` : ''}</div>
            </div>
            <div class="tile-value ${left < 0 ? 'bad' : ''}">${left < 0 ? '−' : ''}${money(Math.abs(left), true)}</div>
          </a>
        </div>

        <div class="grid-2">
          <section>
            <div class="section-head"><h2>Focus</h2><a class="link" href="#/tasks">All tasks ${icon('arrowRight', 14)}</a></div>
            ${focusShown.length
              ? `<div class="task-list">${focusShown.map(taskRow).join('')}</div>
                 ${focus.length > focusShown.length ? `<p class="small muted" style="margin:10px 4px 0">+${focus.length - focusShown.length} more this week</p>` : ''}`
              : `<div class="card">${emptyState('check', 'Clear for the week', 'Nothing is due in the next 7 days.', btn('new-task', 'Add a task', 'plus', 'btn-ghost btn-sm'))}</div>`}
          </section>

          <aside class="stack">
            <section class="card card-pad">
              <div class="section-head"><h2>Workload</h2><span class="small muted">Hours due · next 7 days</span></div>
              <div class="week" role="img" aria-label="Hours of work due each day this week: ${days.map((d, i) => `${fmt(d, { weekday: 'short' })} ${load[i]}`).join(', ')}">
                ${days.map((d, i) => `
                  <div class="week-col ${i === 0 ? 'is-today' : ''}" data-tip title="${esc(longDate(d))}: ${load[i]}h due">
                    <span class="week-val">${load[i] ? load[i] + 'h' : ''}</span>
                    <div class="week-bar-wrap"><div class="week-bar ${load[i] ? '' : 'zero'}" style="height:${load[i] ? Math.max(6, load[i] / max * 100) : 3}%"></div></div>
                    <span class="week-day">${i === 0 ? 'Today' : fmt(d, { weekday: 'short' })}</span>
                  </div>`).join('')}
              </div>
            </section>

            <section class="card card-pad">
              <div class="section-head"><h2>Follow up</h2><a class="link" href="#/jobs">Jobs ${icon('arrowRight', 14)}</a></div>
              ${followSoon.length ? followSoon.map(j => {
                const d = daysBetween(t, j.follow_up_date);
                const pill = d < 0 ? `<span class="pill danger">${-d}d overdue</span>` : d === 0 ? '<span class="pill warn">Today</span>' : `<span class="pill">${esc(fmt(j.follow_up_date, { weekday: 'short' }))}</span>`;
                return `<div class="closed-row" style="padding:10px 4px" data-action="open-job" data-id="${j.id}">
                  <div><div style="font-weight:750">${esc(j.company)}</div><div class="small muted">${esc(j.role)}</div></div>
                  <span class="small muted">${esc(JOB_LABEL[j.status])}</span>${pill}</div>`;
              }).join('') : '<p class="small muted">No follow-ups in the next few days.</p>'}
            </section>
          </aside>
        </div>
      </div>`;
  },

  tasks() {
    setHeader('Tasks', `${plural(state.tasks.filter(x => !isDone(x)).length, 'open task')}`, btn('new-task', 'New task', 'plus'));
    const q = state.taskSearch.toLowerCase();
    const base = state.tasks.filter(t =>
      (!q || t.title.toLowerCase().includes(q) || (t.description || '').toLowerCase().includes(q)) &&
      (!state.taskSubject || String(t.subject_id) === state.taskSubject) &&
      (!state.taskPriority || t.priority === state.taskPriority));
    const counts = { open: base.filter(t => !isDone(t)).length, late: base.filter(isLate).length, done: base.filter(isDone).length, all: base.length };
    const f = state.taskFilter;
    const list = base.filter(t => f === 'all' || (f === 'open' && !isDone(t)) || (f === 'late' && isLate(t)) || (f === 'done' && isDone(t)));
    const seg = (k, label) => `<button class="${f === k ? 'on' : ''}" data-action="task-filter" data-value="${k}">${label} <span class="count">${counts[k]}</span></button>`;

    $('#content').innerHTML = `
      <div>
        <div class="toolbar">
          <label class="input-icon">${icon('search', 16)}<span class="sr-only">Search tasks</span>
            <input class="input" id="taskSearch" type="search" placeholder="Search tasks" value="${esc(state.taskSearch)}"></label>
          <div class="segmented" role="group" aria-label="Show">${seg('open', 'Open')}${seg('late', 'Overdue')}${seg('done', 'Done')}${seg('all', 'All')}</div>
          <span class="spacer"></span>
          <select class="select" id="taskSubject" style="width:auto" aria-label="Subject">
            <option value="">All subjects</option>
            ${state.subjects.map(s => `<option value="${s.id}" ${String(s.id) === state.taskSubject ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}
          </select>
          <select class="select" id="taskPriority" style="width:auto" aria-label="Priority">
            <option value="">Any priority</option>
            ${['urgent', 'high', 'medium', 'low'].map(p => `<option value="${p}" ${p === state.taskPriority ? 'selected' : ''}>${p[0].toUpperCase() + p.slice(1)}</option>`).join('')}
          </select>
          <a class="btn btn-ghost btn-sm mobile-only" href="#/subjects">${icon('subjects', 16)}Subjects</a>
        </div>
        ${list.length ? taskGroups(list, { showDone: f === 'done' || f === 'all' })
          : state.tasks.length
            ? `<div class="card">${emptyState('search', 'Nothing here', f === 'late' ? "You're not behind on anything." : 'No tasks match these filters.')}</div>`
            : `<div class="card">${emptyState('tasks', 'No tasks yet', 'Add assignments, readings and exams with a due date to plan your week.', btn('new-task', 'Add your first task', 'plus', 'btn-primary keep-label'))}</div>`}
      </div>`;
    const search = $('#taskSearch');
    search.addEventListener('input', e => {
      state.taskSearch = e.target.value;
      const pos = e.target.selectionStart;
      VIEWS.tasks();
      const s = $('#taskSearch'); s.focus(); s.setSelectionRange(pos, pos);
    });
    $('#taskSubject').addEventListener('change', e => { state.taskSubject = e.target.value; VIEWS.tasks(); });
    $('#taskPriority').addEventListener('change', e => { state.taskPriority = e.target.value; VIEWS.tasks(); });
  },

  calendar() {
    setHeader('Calendar', '', btn('new-task', 'New task', 'plus'));
    const [y, m] = state.calMonth.split('-').map(Number);
    const first = new Date(y, m - 1, 1);
    const startOffset = (first.getDay() + 6) % 7;            // weeks start on Monday
    const start = ymd(new Date(y, m - 1, 1 - startOffset));
    const daysInMonth = new Date(y, m, 0).getDate();
    const cells = Math.ceil((startOffset + daysInMonth) / 7) * 7;
    const byDay = {};
    state.tasks.forEach(t => t.due_date && (byDay[t.due_date] ||= []).push(t));
    const t = todayStr();
    const dow = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

    let grid = dow.map(d => `<div class="cal-dow">${d}</div>`).join('');
    for (let i = 0; i < cells; i++) {
      const d = addDays(start, i);
      const items = (byDay[d] || []).sort((a, b) => isDone(a) - isDone(b) || PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority]);
      const out = d.slice(0, 7) !== state.calMonth;
      grid += `<button class="cal-day ${out ? 'out' : ''} ${d === t ? 'today' : ''} ${d === state.calSel ? 'sel' : ''}"
          data-action="cal-select" data-date="${d}" aria-label="${esc(longDate(d))}, ${plural(items.length, 'task')}">
        <span class="cal-num">${+d.slice(8)}</span>
        ${items.slice(0, 3).map(x => `<span class="cal-chip ${isDone(x) ? 'done' : isLate(x) ? 'late' : ''}">${subjectById(x.subject_id) ? `<i class="dot" style="--c:${esc(subjectById(x.subject_id).color)}"></i>` : ''}<span class="cal-chip-t">${esc(x.title)}</span></span>`).join('')}
        ${items.length > 3 ? `<span class="cal-more">+${items.length - 3} more</span>` : ''}
        <span class="cal-dots">${items.slice(0, 4).map(x => `<i class="dot" style="--c:${isLate(x) ? 'var(--danger)' : isDone(x) ? 'var(--line-strong)' : 'var(--accent)'}"></i>`).join('')}</span>
      </button>`;
    }
    const sel = (byDay[state.calSel] || []).sort(byDueThenPriority);
    $('#content').innerHTML = `
      <div class="cal-layout">
        <div>
          <div class="cal-head">
            <h2>${esc(monthLabel(state.calMonth))}</h2>
            <button class="icon-btn" data-action="cal-shift" data-value="-1" aria-label="Previous month">${icon('chevronLeft')}</button>
            <button class="icon-btn" data-action="cal-shift" data-value="1" aria-label="Next month">${icon('chevronRight')}</button>
            <button class="btn btn-ghost btn-sm" data-action="cal-today">Today</button>
          </div>
          <div class="cal">${grid}</div>
        </div>
        <aside class="card card-pad day-panel">
          <p class="eyebrow">${state.calSel === t ? 'Today' : esc(fmt(state.calSel, { year: 'numeric' }))}</p>
          <h3>${esc(longDate(state.calSel))}</h3>
          <p class="small muted" style="margin-bottom:14px">${plural(sel.length, 'task')} due</p>
          ${sel.length ? `<div class="task-list">${sel.map(taskRow).join('')}</div>` : ''}
          <button class="btn btn-ghost btn-sm" style="margin-top:14px" data-action="new-task" data-due="${state.calSel}">${icon('plus', 16)}Add task on this day</button>
        </aside>
      </div>`;
  },

  subjects() {
    setHeader('Subjects', 'Units and the tasks that belong to them', btn('new-subject', 'New subject', 'plus'));
    if (!state.subjects.length) {
      $('#content').innerHTML = `<div class="card">${emptyState('subjects', 'No subjects yet', 'Add the units you are studying this trimester, e.g. SIT313 Full Stack Development.', btn('new-subject', 'Add a subject', 'plus', 'btn-primary keep-label'))}</div>`;
      return;
    }
    $('#content').innerHTML = `<div class="subjects">${state.subjects.map(s => {
      const tasks = state.tasks.filter(t => t.subject_id === s.id);
      const open = tasks.filter(t => !isDone(t));
      const next = open.filter(t => t.due_date).sort(byDueThenPriority)[0];
      return `<article class="card subject" style="--c:${esc(s.color)}">
        <div class="subject-head">
          <h3 class="subject-name">${esc(s.name)}</h3>
          <button class="icon-btn sm" data-action="edit-subject" data-id="${s.id}" aria-label="Edit ${esc(s.name)}">${icon('pencil', 15)}</button>
        </div>
        <p class="subject-stats">${plural(open.length, 'open task')}${tasks.length - open.length ? ` · ${tasks.length - open.length} done` : ''}${next ? ` · next due ${esc(dueInfo(next).text.toLowerCase())}` : ''}</p>
        <div class="units">${s.units.map(u => `
          <div class="unit"><span>${esc(u.name)}</span>
            <button class="icon-btn sm danger" data-action="delete-unit" data-id="${u.id}" data-subject="${s.id}" aria-label="Remove ${esc(u.name)}">${icon('x', 14)}</button></div>`).join('')
          || '<p class="small muted" style="padding:0 8px">No units yet — add weeks or topics below.</p>'}</div>
        <form class="unit-add" data-subject="${s.id}">
          <input class="input" name="name" placeholder="Add a unit or week" aria-label="New unit for ${esc(s.name)}" maxlength="120" required>
          <button class="btn btn-ghost btn-sm" type="submit">Add</button>
        </form>
      </article>`;
    }).join('')}</div>`;
  },

  jobs() {
    const active = state.jobs.filter(j => ACTIVE_JOB.has(j.status));
    setHeader('Job applications', `${plural(active.length, 'active application')}`, btn('new-job', 'Add application', 'plus'));
    if (!state.jobs.length) {
      $('#content').innerHTML = `<div class="card">${emptyState('jobs', 'No applications yet', 'Track where you have applied, when to follow up and how far each one has got.', btn('new-job', 'Add an application', 'plus', 'btn-primary keep-label'))}</div>`;
      return;
    }
    const t = todayStr();
    const card = j => {
      let pill = '';
      if (j.follow_up_date) {
        const d = daysBetween(t, j.follow_up_date);
        pill = d < 0 ? `<span class="pill danger">${icon('bell', 12)}Follow up</span>` : d === 0 ? `<span class="pill warn">${icon('bell', 12)}Follow up today</span>` : d <= 3 ? `<span class="pill">${icon('bell', 12)}${esc(fmt(j.follow_up_date, { weekday: 'short' }))}</span>` : '';
      }
      return `<div class="job" data-action="open-job" data-id="${j.id}">
        <button class="icon-btn sm job-advance" data-action="advance-job" data-id="${j.id}" title="Move to ${esc(JOB_LABEL[nextStage(j.status)])}" aria-label="Move ${esc(j.company)} to ${esc(JOB_LABEL[nextStage(j.status)])}">${icon('arrowRight', 15)}</button>
        <div class="job-co">${esc(j.company)}</div>
        <div class="job-role">${esc(j.role)}</div>
        <div class="job-foot">
          <span class="small muted">${j.applied_date ? 'Applied ' + esc(shortDate(j.applied_date)) : ''}</span>
          ${pill}
        </div></div>`;
    };
    const closed = state.jobs.filter(j => !ACTIVE_JOB.has(j.status));
    $('#content').innerHTML = `
      <div>
        <div class="board">${JOB_STAGES.map(s => {
          const items = active.filter(j => j.status === s.key);
          return `<section class="col"><div class="col-head">${s.label}<span class="num">${items.length}</span></div>
            ${items.map(card).join('') || '<div class="col-empty">None</div>'}</section>`;
        }).join('')}</div>
        ${closed.length ? `<section class="closed-list">
          <div class="section-head"><h2>Closed</h2><span class="small muted">${plural(closed.length, 'application')}</span></div>
          <div class="task-list">${closed.map(j => `
            <div class="closed-row" data-action="open-job" data-id="${j.id}">
              <div style="min-width:0"><span style="font-weight:750">${esc(j.company)}</span> <span class="muted">· ${esc(j.role)}</span></div>
              <span class="small muted">${j.applied_date ? esc(shortDate(j.applied_date)) : ''}</span>
              <span class="pill ${j.status === 'accepted' ? 'ok' : ''}">${esc(JOB_CLOSED[j.status])}</span>
            </div>`).join('')}</div></section>` : ''}
      </div>`;
  },

  money() {
    setHeader('Money', '', btn('new-budget', 'Budget', 'money', 'btn-ghost') + btn('new-tx', 'Add transaction', 'plus'));
    const income = state.transactions.filter(x => x.type === 'income').reduce((s, x) => s + x.amount, 0);
    const spent = state.transactions.filter(x => x.type === 'expense').reduce((s, x) => s + x.amount, 0);
    const budgetTotal = state.budgets.reduce((s, b) => s + b.monthly_limit, 0);
    const budgetSpent = state.budgets.reduce((s, b) => s + b.spent, 0);
    const byDay = {};
    state.transactions.forEach(x => (byDay[x.date] ||= []).push(x));
    const days = Object.keys(byDay).sort().reverse();

    $('#content').innerHTML = `
      <div class="stack">
        <div class="toolbar" style="margin:0">
          <div class="month-switch">
            <button class="icon-btn sm" data-action="month-shift" data-value="-1" aria-label="Previous month">${icon('chevronLeft', 16)}</button>
            <strong>${esc(monthLabel(state.month))}</strong>
            <button class="icon-btn sm" data-action="month-shift" data-value="1" aria-label="Next month">${icon('chevronRight', 16)}</button>
          </div>
        </div>
        <div class="tiles">
          <div class="card tile"><div class="tile-left"><div class="tile-top">Money in</div><div class="tile-note">${plural(state.transactions.filter(x => x.type === 'income').length, 'payment')}</div></div>
            <div class="tile-value">${money(income, true)}</div></div>
          <div class="card tile"><div class="tile-left"><div class="tile-top">Money out</div><div class="tile-note">${income ? `${Math.round(spent / income * 100)}% of what came in` : plural(state.transactions.filter(x => x.type === 'expense').length, 'purchase')}</div></div>
            <div class="tile-value">${money(spent, true)}</div></div>
          <div class="card tile"><div class="tile-left"><div class="tile-top">Budget left</div><div class="tile-note">${budgetTotal ? `of ${money(budgetTotal, true)}` : 'No budgets set'}</div></div>
            <div class="tile-value ${budgetTotal - budgetSpent < 0 ? 'bad' : ''}">${budgetTotal - budgetSpent < 0 ? '−' : ''}${money(Math.abs(budgetTotal - budgetSpent), true)}</div></div>
        </div>
        <div class="grid-2">
          <section class="card card-pad">
            <div class="section-head"><h2>Transactions</h2></div>
            ${days.length ? days.map(d => `
              <div class="tx-day">${d === todayStr() ? 'Today' : esc(fmt(d, { weekday: 'long', day: 'numeric', month: 'short' }))}</div>
              ${byDay[d].map(x => `
                <div class="tx">
                  <span class="tx-icon ${x.type === 'income' ? 'in' : ''}">${icon(x.type === 'income' ? 'down' : 'up', 16)}</span>
                  <div style="min-width:0"><div class="tx-desc">${esc(x.description || x.category)}</div><div class="tx-cat">${esc(x.category)}</div></div>
                  <span class="tx-amt ${x.type === 'income' ? 'in' : ''}">${x.type === 'income' ? '+' : '−'}${money(x.amount)}</span>
                  <button class="icon-btn sm danger" data-action="delete-tx" data-id="${x.id}" aria-label="Delete ${esc(x.description || x.category)}">${icon('trash', 15)}</button>
                </div>`).join('')}`).join('')
              : emptyState('inbox', 'Nothing this month', 'Add your pay and spending to see where your money goes.', btn('new-tx', 'Add transaction', 'plus', 'btn-ghost btn-sm keep-label'))}
          </section>
          <section class="card card-pad">
            <div class="section-head"><h2>Budgets</h2><span class="small muted">${esc(monthLabel(state.month))}</span></div>
            <div class="budget-list">${state.budgets.map(budgetRow).join('') || '<p class="small muted">No budgets yet.</p>'}</div>
          </section>
        </div>
      </div>`;
  },

  settings() {
    setHeader('Settings', 'Make it yours');
    const ap = window.__appearance || DEFAULT_APPEARANCE;
    const dark = document.documentElement.dataset.mode === 'dark';
    const mode = (k, label, ic) => `<button class="${ap.mode === k ? 'on' : ''}" data-action="set-appearance" data-key="mode" data-value="${k}">${icon(ic, 15)}${label}</button>`;
    $('#content').innerHTML = `
      <div class="settings">
        <h2>Appearance</h2>
        <div class="card">
          <div class="appearance">
            <div class="preview-strip">
              <span class="preview-title">Your week at a glance</span>
              <span class="pill accent">3 due today</span>
              <button class="btn btn-primary btn-sm" type="button" tabindex="-1">${icon('plus', 15)}New task</button>
            </div>
            <div class="appearance-head"><div><div class="setting-title">Light or dark</div><div class="setting-desc">System follows your computer's setting.</div></div>
              <div class="segmented">${mode('system', 'System', 'monitor')}${mode('light', 'Light', 'sun')}${mode('dark', 'Dark', 'moon')}</div></div>
          </div>
          <div class="appearance">
            <div class="appearance-head"><div class="setting-title">Colour theme</div><span class="small muted">${esc(THEMES[ap.theme]?.name || '')}</span></div>
            <div class="picker" role="radiogroup" aria-label="Colour theme">${Object.entries(THEMES).map(([k, t]) => {
              const c = dark ? t.dark : t.light;
              return `<button class="pick ${ap.theme === k ? 'on' : ''}" role="radio" aria-checked="${ap.theme === k}" data-action="set-appearance" data-key="theme" data-value="${k}"
                  style="--pa:${c.a};--pb:${c.b};--pbg:${dark ? `hsl(${t.hue} ${t.sat * 0.5}% 10%)` : '#fff'}">
                <span class="pick-swatch"><i></i><i style="opacity:.7"></i></span>
                <div class="pick-name">${esc(t.name)}${k === DEFAULT_APPEARANCE.theme ? ' <span class="muted small">· default</span>' : ''}</div>
              </button>`;
            }).join('')}</div>
          </div>
          <div class="appearance">
            <div class="appearance-head"><div class="setting-title">Text style</div><span class="small muted">${esc(FONTS[ap.font]?.name || '')}</span></div>
            <div class="picker fonts" role="radiogroup" aria-label="Text style">${Object.entries(FONTS).map(([k, f]) => `
              <button class="pick ${ap.font === k ? 'on' : ''}" role="radio" aria-checked="${ap.font === k}" data-action="set-appearance" data-key="font" data-value="${k}">
                <span class="pick-aa" style="font-family:'${f.display}';font-weight:${f.weight};letter-spacing:${f.track}">Aa</span>
                <div class="pick-name" style="font-family:'${f.body}'">${esc(f.name)}${k === DEFAULT_APPEARANCE.font ? ' <span class="muted small">· default</span>' : ''}</div>
                <div class="pick-sub">${esc(f.sample)}</div>
              </button>`).join('')}</div>
          </div>
        </div>
        <h2>Your data</h2>
        <div class="card">
          <div class="setting"><div><div class="setting-title">Saved on this computer</div><div class="setting-desc path">${esc(state.info.data_file || '')}</div></div>${icon('database', 20)}</div>
          <div class="setting"><div><div class="setting-title">Back up</div><div class="setting-desc">${plural(state.tasks.length, 'task')}, ${plural(state.jobs.length, 'application')}, ${state.subjects.length} subjects</div></div>
            ${btn('export', 'Download backup', 'download', 'btn-ghost btn-sm keep-label')}</div>
        </div>
        <h2>Updates</h2>
        <div class="card">${updatesCard()}</div>
        <h2>About</h2>
        <div class="card">
          <div class="setting"><div><div class="setting-title">${esc(state.info.name || 'Trackademic')} ${esc(state.info.version || '')}</div><div class="setting-desc">Student planner, job tracker and money manager</div></div></div>
          <div class="setting"><div><div class="setting-title">Made by Mysteryman4k</div><div class="setting-desc">© 2026 Mysteryman4k. All rights reserved.</div></div>
            <a class="link" href="https://github.com/Mysteryman4k/lifeplanner" target="_blank" rel="noopener">GitHub ${icon('external', 14)}</a></div>
        </div>
      </div>`;
  },
};

function budgetRow(b) {
  const pct = b.monthly_limit ? b.spent / b.monthly_limit : 0;
  const cls = pct > 1 ? 'over' : pct >= 0.85 ? 'warn' : '';
  const remaining = b.monthly_limit - b.spent;
  return `<div class="budget">
    <div class="budget-name"><span>${esc(b.category)}</span>
      <span class="budget-actions">
        <button class="icon-btn sm" data-action="edit-budget" data-id="${b.id}" aria-label="Edit ${esc(b.category)} budget">${icon('pencil', 14)}</button>
      </span></div>
    <div class="budget-amt">${money(b.spent, true)} <span class="of">/ ${money(b.monthly_limit, true)}</span></div>
    <div class="bar ${cls}" role="progressbar" aria-valuenow="${Math.round(pct * 100)}" aria-valuemin="0" aria-valuemax="100" aria-label="${esc(b.category)}"><i style="width:${Math.min(100, pct * 100)}%"></i></div>
    <div class="budget-note ${pct > 1 ? 'over' : ''}">${pct > 1 ? `${money(-remaining)} over budget` : `${money(remaining)} left`}</div>
  </div>`;
}

function nextStage(status) {
  const order = ['applied', 'phone_screen', 'interviewing', 'offer', 'accepted'];
  const i = order.indexOf(status);
  return order[Math.min(i + 1, order.length - 1)];
}

// ── Updates ───────────────────────────────────────────────────────
async function checkForUpdates(force) {
  state.checkingUpdate = force;
  if (force && route() === 'settings') VIEWS.settings();
  try {
    const [settings, update] = await Promise.all([
      api('/api/settings/updates'), api('/api/update/check' + (force ? '?force=true' : '')),
    ]);
    state.updateSettings = settings;
    state.update = update;
    if (force && !update.available) toast(update.error || `You're on the latest version (${update.current})`, update.error ? 'error' : '');
  } catch (e) {
    if (force) toast(e.message, 'error');
  } finally {
    state.checkingUpdate = false;
  }
  renderUpdateBanner();
  if (route() === 'settings') { $('#content').classList.add('still'); VIEWS.settings(); }
}

function renderUpdateBanner() {
  const u = state.update;
  const el = $('#updateBanner');
  if (!u || !u.available || state.updateDismissed) { el.hidden = true; return; }
  el.hidden = false;
  el.innerHTML = `
    <span class="update-dot" aria-hidden="true"></span>
    <span><strong>Trackademic ${esc(u.latest)}</strong> is available <span class="muted">· you have ${esc(u.current)}</span></span>
    <span class="spacer"></span>
    <a class="link" href="#/settings">What's new</a>
    ${u.can_install ? `<button class="btn btn-primary btn-sm keep-label" data-action="install-update">${icon('download', 15)}Update now</button>`
      : `<a class="btn btn-primary btn-sm keep-label" href="${esc(u.url)}" target="_blank" rel="noopener">${icon('download', 15)}Download</a>`}
    <button class="icon-btn sm" data-action="dismiss-update" aria-label="Hide until next launch">${icon('x', 15)}</button>`;
}

function releaseNotesHtml(md) {
  // Release notes come from CHANGELOG.md: render headings and bullet points as plain, escaped text
  const lines = (md || '').split('\n').map(l => l.trimEnd()).filter(Boolean).slice(0, 40);
  let html = '', inList = false;
  for (const l of lines) {
    const bullet = l.match(/^[-*]\s+(.*)/);
    const heading = l.match(/^#{1,6}\s+(.*)/);
    if (bullet) { if (!inList) { html += '<ul>'; inList = true; } html += `<li>${esc(bullet[1].replace(/`/g, ''))}</li>`; continue; }
    if (inList) { html += '</ul>'; inList = false; }
    html += heading ? `<h4>${esc(heading[1])}</h4>` : `<p>${esc(l)}</p>`;
  }
  return html + (inList ? '</ul>' : '');
}

function updatesCard() {
  const u = state.update || {};
  const current = state.info.version || '';
  const status = state.checkingUpdate ? 'Checking…'
    : u.available ? (u.can_install ? `Version ${esc(u.latest)} is ready to install` : `Version ${esc(u.latest)} is available`)
    : u.error ? esc(u.error)
    : u.latest ? `You're up to date`
    : 'Not checked yet';
  return `
    <div class="setting"><div><div class="setting-title">Version ${esc(current)}</div><div class="setting-desc">${status}</div></div>
      ${btn('check-updates', state.checkingUpdate ? 'Checking…' : 'Check now', 'refresh', 'btn-ghost btn-sm keep-label', state.checkingUpdate ? 'disabled' : '')}</div>
    ${u.available ? `
      <div class="setting release-notes-wrap"><div style="flex:1">
        <div class="setting-title">What's new in ${esc(u.latest)}</div>
        <div class="release-notes">${releaseNotesHtml(u.notes)}</div>
        <div class="toolbar" style="margin:14px 0 0">
          ${u.can_install ? btn('install-update', 'Update now', 'download', 'btn-primary btn-sm keep-label')
            : `<a class="btn btn-primary btn-sm keep-label" href="${esc(u.url)}" target="_blank" rel="noopener">${icon('download', 15)}Download from GitHub</a>
               <span class="small muted">${state.info.installed ? '' : 'Automatic install works in the installed Windows app.'}</span>`}
        </div></div></div>` : ''}
    <div class="setting"><div><div class="setting-title">Check for updates automatically</div>
      <div class="setting-desc">Looks for new versions on GitHub when the app opens. Nothing about you or your data is sent.</div></div>
      <button class="switch ${state.updateSettings.auto_check ? 'on' : ''}" role="switch" aria-checked="${state.updateSettings.auto_check}"
        data-action="toggle-auto-update" aria-label="Check for updates automatically"><i></i></button></div>`;
}

// ── Drawer (forms) ────────────────────────────────────────────────
let lastFocus = null;
function openDrawer(title, bodyHtml, footHtml, kind) {
  lastFocus = document.activeElement;
  state.drawer = kind;
  $('#drawerTitle').textContent = title;
  $('#drawerBody').innerHTML = bodyHtml;
  $('#drawerFoot').innerHTML = footHtml;
  $('[data-action="close-drawer"]').innerHTML = icon('x', 20);
  $('#scrim').hidden = false;
  $('#drawer').hidden = false;
  setTimeout(() => $('#drawer [autofocus]')?.focus(), 30);
}
function closeDrawer() {
  if ($('#drawer').hidden) return;
  $('#drawer').hidden = true;
  $('#scrim').hidden = true;
  state.drawer = null;
  lastFocus?.focus?.();
}

const opt = (value, label, selected) => `<option value="${esc(value)}" ${String(value) === String(selected ?? '') ? 'selected' : ''}>${esc(label)}</option>`;
const field = (label, control, cls = '') => `<label class="field ${cls}"><span>${label}</span>${control}</label>`;
const footer = (deleteAction, extra = '') => `
  ${deleteAction ? `<button class="btn btn-danger-ghost btn-sm" type="button" data-action="${deleteAction}">${icon('trash', 16)}Delete</button>` : ''}
  <span class="spacer"></span>${extra}
  <button class="btn btn-ghost" type="button" data-action="close-drawer">Cancel</button>
  <button class="btn btn-primary" type="submit" form="drawerForm">Save</button>`;

function unitOptions(subjectId, selected) {
  const s = subjectById(Number(subjectId));
  return opt('', s?.units.length ? 'None' : 'No units') + (s ? s.units.map(u => opt(u.id, u.name, selected)).join('') : '');
}

function openTask(id, defaults = {}) {
  const t = id ? state.tasks.find(x => x.id === id) : { priority: 'medium', status: 'not_started', progress: 0, ...defaults };
  if (!t) return;
  const body = `
    <form id="drawerForm" class="form-stack" data-kind="task" data-id="${id || ''}" autocomplete="off">
      <input class="title-input" name="title" placeholder="What needs doing?" value="${esc(t.title)}" required maxlength="120" ${id ? '' : 'autofocus'} aria-label="Title">
      <div id="planSlot"></div>
      <div class="form-grid">
        ${field('Due date', `<input class="input" type="date" name="due_date" value="${esc(t.due_date || '')}">`)}
        ${field('Priority', `<select class="select" name="priority">${['low', 'medium', 'high', 'urgent'].map(p => opt(p, p[0].toUpperCase() + p.slice(1), t.priority)).join('')}</select>`)}
        ${field('Subject', `<select class="select" name="subject_id" id="fSubject">${opt('', 'None')}${state.subjects.map(s => opt(s.id, s.name, t.subject_id)).join('')}</select>`)}
        ${field('Unit', `<select class="select" name="unit_id" id="fUnit">${unitOptions(t.subject_id, t.unit_id)}</select>`)}
        ${field('Type', `<select class="select" name="category_id">${opt('', 'None')}${state.categories.map(c => opt(c.id, c.name, t.category_id)).join('')}</select>`)}
        ${field('Status', `<select class="select" name="status">${opt('not_started', 'Not started', t.status)}${opt('in_progress', 'In progress', t.status)}${opt('completed', 'Done', t.status)}</select>`)}
        ${field('Estimated hours', `<input class="input" type="number" name="estimated_hours" min="0" max="1000" step="0.5" value="${esc(t.estimated_hours ?? '')}" placeholder="e.g. 6">`)}
        ${field('Aiming for', `<select class="select" name="target_grade">${GRADES.map(g => opt(g, g || 'No target', t.target_grade)).join('')}</select>`)}
        ${field('Progress', `<div class="range-row"><input type="range" name="progress" min="0" max="100" step="5" value="${t.progress || 0}" id="fProgress"><output id="fProgressOut">${t.progress || 0}%</output></div>`, 'span-2')}
        ${field('Details', `<textarea class="textarea" name="description" placeholder="Brief, links, marking criteria…">${esc(t.description || '')}</textarea>`, 'span-2')}
        ${field('Notes', `<textarea class="textarea" name="notes" placeholder="Anything to remember">${esc(t.notes || '')}</textarea>`, 'span-2')}
      </div>
    </form>`;
  const planBtn = id ? `<button class="btn btn-ghost btn-sm" type="button" data-action="auto-plan" title="Split the estimated hours into study sessions before the due date">${icon('wand', 16)}<span class="btn-label">Plan sessions</span></button>` : '';
  openDrawer(id ? 'Edit task' : 'New task', body, footer(id ? 'delete-task' : '', planBtn), 'task');
  $('#fSubject').addEventListener('change', e => { $('#fUnit').innerHTML = unitOptions(e.target.value); });
  $('#fProgress').addEventListener('input', e => { $('#fProgressOut').textContent = e.target.value + '%'; });
}

function openJob(id) {
  const j = id ? state.jobs.find(x => x.id === id) : { status: 'applied', priority: 'medium', applied_date: todayStr() };
  if (!j) return;
  const body = `
    <form id="drawerForm" class="form-stack" data-kind="job" data-id="${id || ''}" autocomplete="off">
      <div class="form-grid">
        ${field('Company', `<input class="input" name="company" value="${esc(j.company)}" required maxlength="120" ${id ? '' : 'autofocus'}>`)}
        ${field('Role', `<input class="input" name="role" value="${esc(j.role)}" required maxlength="120">`)}
        ${field('Stage', `<select class="select" name="status">${Object.entries(JOB_LABEL).map(([k, v]) => opt(k, v, j.status)).join('')}</select>`)}
        ${field('Priority', `<select class="select" name="priority">${['low', 'medium', 'high'].map(p => opt(p, p[0].toUpperCase() + p.slice(1), j.priority)).join('')}</select>`)}
        ${field('Applied on', `<input class="input" type="date" name="applied_date" value="${esc(j.applied_date || '')}">`)}
        ${field('Follow up on', `<input class="input" type="date" name="follow_up_date" value="${esc(j.follow_up_date || '')}">`)}
        ${field('Job ad link', `<input class="input" type="url" name="url" value="${esc(j.url)}" placeholder="https://" maxlength="500">`, 'span-2')}
        ${field('Pay', `<input class="input" name="salary_range" value="${esc(j.salary_range)}" placeholder="e.g. $30/hr" maxlength="60">`)}
        ${field('Contact', `<input class="input" name="contact_name" value="${esc(j.contact_name)}" maxlength="120">`)}
        ${field('Contact email', `<input class="input" type="email" name="contact_email" value="${esc(j.contact_email)}" maxlength="200">`, 'span-2')}
        ${field('Notes', `<textarea class="textarea" name="notes" placeholder="Interview prep, questions to ask…">${esc(j.notes || '')}</textarea>`, 'span-2')}
      </div>
      ${j.url && /^https?:\/\//i.test(j.url) ? `<a class="link" href="${esc(j.url)}" target="_blank" rel="noopener">Open job ad ${icon('external', 14)}</a>` : ''}
    </form>`;
  openDrawer(id ? j.company : 'New application', body, footer(id ? 'delete-job' : ''), 'job');
}

function openTx(type = 'expense') {
  const cats = type === 'income' ? INCOME_CATEGORIES : state.budgets.map(b => b.category);
  const date = state.month === todayStr().slice(0, 7) ? todayStr() : state.month + '-01';
  const body = `
    <form id="drawerForm" class="form-stack" data-kind="tx" autocomplete="off">
      <div class="segmented" role="group" aria-label="Type" style="align-self:flex-start">
        <button type="button" class="${type === 'expense' ? 'on' : ''}" data-action="tx-type" data-value="expense">Money out</button>
        <button type="button" class="${type === 'income' ? 'on' : ''}" data-action="tx-type" data-value="income">Money in</button>
      </div>
      <input type="hidden" name="type" value="${type}">
      <div class="form-grid">
        ${field('Amount', `<input class="input" type="number" name="amount" min="0.01" step="0.01" required placeholder="0.00" autofocus inputmode="decimal">`)}
        ${field('Date', `<input class="input" type="date" name="date" value="${date}" required>`)}
        ${field(type === 'income' ? 'Source' : 'Budget', `<select class="select" name="category" required>${cats.map(c => opt(c, c)).join('')}</select>`, 'span-2')}
        ${field('Description', `<input class="input" name="description" placeholder="${type === 'income' ? 'e.g. Weekly pay' : 'e.g. Groceries'}" maxlength="200">`, 'span-2')}
      </div>
    </form>`;
  openDrawer(type === 'income' ? 'Money in' : 'Money out', body, footer(''), 'tx');
}

function swatchPicker(current) {
  const c = current || SUBJECT_COLORS[0];
  return `<input type="hidden" name="color" value="${esc(c)}"><div class="swatches" role="radiogroup" aria-label="Colour">${SUBJECT_COLORS.map(col =>
    `<button type="button" class="swatch ${col.toLowerCase() === c.toLowerCase() ? 'on' : ''}" style="--c:${col}" data-action="pick-color" data-value="${col}" role="radio" aria-checked="${col.toLowerCase() === c.toLowerCase()}" aria-label="Colour ${col}"></button>`).join('')}</div>`;
}

function openBudget(id) {
  const b = id ? state.budgets.find(x => x.id === id) : {};
  if (!b) return;
  const body = `
    <form id="drawerForm" class="form-stack" data-kind="budget" data-id="${id || ''}" autocomplete="off">
      ${field('Name', `<input class="input" name="category" value="${esc(b.category)}" required maxlength="120" placeholder="e.g. Groceries" ${id ? '' : 'autofocus'}>`)}
      ${field('Monthly limit', `<input class="input" type="number" name="monthly_limit" min="1" step="1" value="${esc(b.monthly_limit ?? '')}" required inputmode="decimal">`)}
      ${id ? '<p class="small muted">Renaming keeps this budget\'s past transactions.</p>' : ''}
    </form>`;
  openDrawer(id ? 'Edit budget' : 'New budget', body, footer(id ? 'delete-budget' : ''), 'budget');
}

function openSubject(id) {
  const s = id ? subjectById(id) : { color: SUBJECT_COLORS[state.subjects.length % SUBJECT_COLORS.length] };
  if (!s) return;
  const body = `
    <form id="drawerForm" class="form-stack" data-kind="subject" data-id="${id || ''}" autocomplete="off">
      ${field('Name', `<input class="input" name="name" value="${esc(s.name)}" required maxlength="120" placeholder="e.g. SIT313 Full Stack Development" autofocus>`)}
      <div class="field"><span class="field-label">Colour</span>${swatchPicker(s.color)}</div>
    </form>`;
  openDrawer(id ? 'Edit subject' : 'New subject', body, footer(id ? 'delete-subject' : ''), 'subject');
}

function formData(form) {
  const out = {};
  new FormData(form).forEach((v, k) => { out[k] = typeof v === 'string' ? v.trim() : v; });
  return out;
}
const numOrNull = v => (v === '' || v == null ? null : Number(v));

async function submitDrawer(form) {
  const kind = form.dataset.kind;
  const id = Number(form.dataset.id) || null;
  const d = formData(form);
  const save = form.closest('.drawer').querySelector('[type="submit"]') || $('#drawerFoot [type="submit"]');
  if (save) save.disabled = true;
  try {
    if (kind === 'task') {
      const body = {
        title: d.title, description: d.description, notes: d.notes, priority: d.priority, status: d.status,
        due_date: d.due_date || null, subject_id: numOrNull(d.subject_id), unit_id: numOrNull(d.unit_id),
        category_id: numOrNull(d.category_id), estimated_hours: numOrNull(d.estimated_hours),
        target_grade: d.target_grade, progress: Number(d.progress) || 0,
      };
      const prev = id && state.tasks.find(x => x.id === id);
      if (prev && prev.status !== 'completed' && body.status === 'completed' && body.progress < 100) body.progress = 100;
      const saved = await api(id ? `/api/tasks/${id}` : '/api/tasks', { method: id ? 'PUT' : 'POST', body });
      upsert(state.tasks, saved);
      toast(id ? 'Task updated' : 'Task added');
    } else if (kind === 'job') {
      const body = { ...d, applied_date: d.applied_date || null, follow_up_date: d.follow_up_date || null };
      upsert(state.jobs, await api(id ? `/api/jobs/${id}` : '/api/jobs', { method: id ? 'PUT' : 'POST', body }));
      toast(id ? 'Application updated' : 'Application added');
    } else if (kind === 'tx') {
      await api('/api/transactions', { method: 'POST', body: { ...d, amount: Number(d.amount) } });
      state.month = d.date.slice(0, 7);
      await loadMoney();
      toast('Transaction added');
    } else if (kind === 'budget') {
      await api(id ? `/api/budgets/${id}` : '/api/budgets', { method: id ? 'PUT' : 'POST', body: { category: d.category, monthly_limit: Number(d.monthly_limit), color: b_color(id) } });
      await loadMoney();
      toast('Budget saved');
    } else if (kind === 'subject') {
      const saved = await api(id ? `/api/subjects/${id}` : '/api/subjects', { method: id ? 'PUT' : 'POST', body: d });
      if (id) Object.assign(subjectById(id), d); else state.subjects.push(saved);
      state.subjects.sort((a, b) => a.name.localeCompare(b.name));
      if (id) state.tasks.forEach(t => { if (t.subject_id === id) { t.subject_name = d.name; t.subject_color = d.color; } });
      toast(id ? 'Subject updated' : 'Subject added');
    }
    closeDrawer();
    render();
  } catch (e) {
    toast(e.message, 'error');
  } finally {
    if (save) save.disabled = false;
  }
}

const b_color = id => (id && state.budgets.find(x => x.id === id)?.color) || '#2f5d50';

function upsert(list, item) {
  const i = list.findIndex(x => x.id === item.id);
  if (i >= 0) list[i] = item; else list.push(item);
}

// ── Confirm, toast, celebrate ─────────────────────────────────────
function confirmDialog(title, text, yes = 'Delete', style = 'danger') {
  return new Promise(resolve => {
    const wrap = $('#confirm');
    $('#confirmTitle').textContent = title;
    $('#confirmText').textContent = text;
    $('#confirmYes').textContent = yes;
    $('#confirmYes').className = `btn ${style === 'danger' ? 'btn-danger' : 'btn-primary'}`;
    wrap.hidden = false;
    $('#confirmNo').focus();
    const done = v => { wrap.hidden = true; wrap.onclick = null; document.removeEventListener('keydown', onKey, true); resolve(v); };
    const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); done(false); } };
    document.addEventListener('keydown', onKey, true);
    wrap.onclick = e => { if (e.target === wrap || e.target.id === 'confirmNo') done(false); else if (e.target.id === 'confirmYes') done(true); };
  });
}

let toastTimer;
function toast(msg, type = '') {
  const el = $('#toast');
  el.innerHTML = (type === 'error' ? icon('alert', 16) : icon('check', 16)) + `<span>${esc(msg)}</span>`;
  el.className = `toast show ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), type === 'error' ? 4500 : 2400);
}

function celebrate(from) {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches || !from) return;
  const r = from.getBoundingClientRect();
  const colors = ['var(--accent)', 'var(--warn)', 'var(--ok)', 'var(--ink-2)'];
  for (let i = 0; i < 14; i++) {
    const s = document.createElement('i');
    s.className = 'spark';
    const a = (Math.PI * 2 * i) / 14;
    s.style.cssText = `left:${r.left + r.width / 2}px;top:${r.top + r.height / 2}px;background:${colors[i % 4]};--dx:${Math.cos(a) * (30 + Math.random() * 30)}px;--dy:${Math.sin(a) * (30 + Math.random() * 30)}px`;
    document.body.appendChild(s);
    setTimeout(() => s.remove(), 1000);
  }
}

// ── Actions (event delegation) ────────────────────────────────────
const ACTIONS = {
  'new-task': el => openTask(null, el.dataset.due ? { due_date: el.dataset.due } : {}),
  'open-task': el => openTask(Number(el.dataset.id)),
  async 'toggle-task'(el) {
    const t = state.tasks.find(x => x.id === Number(el.dataset.id));
    const done = !isDone(t);
    el.classList.toggle('done', done);
    if (done) { el.classList.add('pop'); celebrate(el); }
    try {
      const saved = await api(`/api/tasks/${t.id}`, { method: 'PUT', body: done ? { status: 'completed' } : { status: t.progress > 0 && t.progress < 100 ? 'in_progress' : 'not_started', progress: t.progress === 100 ? 0 : t.progress } });
      upsert(state.tasks, saved);
      setTimeout(render, done ? 350 : 0);
      if (done) toast('Nice — task done');
    } catch (e) { toast(e.message, 'error'); render(); }
  },
  async 'delete-task'() {
    const id = Number($('#drawerForm').dataset.id);
    if (!(await confirmDialog('Delete this task?', 'This cannot be undone.'))) return;
    try { await api(`/api/tasks/${id}`, { method: 'DELETE' }); state.tasks = state.tasks.filter(x => x.id !== id); closeDrawer(); render(); toast('Task deleted'); }
    catch (e) { toast(e.message, 'error'); }
  },
  async 'auto-plan'() {
    const form = $('#drawerForm');
    const id = Number(form.dataset.id);
    const f = formData(form);
    try {
      // Save the current due date / hours first so the plan uses what's on screen
      upsert(state.tasks, await api(`/api/tasks/${id}`, { method: 'PUT', body: { due_date: f.due_date || null, estimated_hours: numOrNull(f.estimated_hours) } }));
      const r = await api(`/api/tasks/${id}/auto-plan`, { method: 'POST' });
      $('#planSlot').innerHTML = r.plan.length ? `
        <div class="plan"><div class="plan-head"><span>Study plan</span><span>${esc(r.message)}</span></div>
        ${r.plan.map(p => `<div class="plan-row"><span>${esc(fmt(p.date, { weekday: 'short', day: 'numeric', month: 'short' }))}</span><span>${esc(p.label)}</span><span class="muted">${p.hours}h · ${p.target}%</span></div>`).join('')}</div>`
        : `<p class="pill warn" style="height:auto;padding:8px 12px">${esc(r.message)}</p>`;
      upsert(state.tasks, await api(`/api/tasks/${id}`));
    } catch (e) { toast(e.message, 'error'); }
  },
  'task-filter': el => { state.taskFilter = el.dataset.value; VIEWS.tasks(); },
  'cal-select': el => { state.calSel = el.dataset.date; if (el.dataset.date.slice(0, 7) !== state.calMonth) state.calMonth = el.dataset.date.slice(0, 7); VIEWS.calendar(); },
  'cal-shift': el => { const d = parseDate(state.calMonth + '-01'); d.setMonth(d.getMonth() + Number(el.dataset.value)); state.calMonth = ymd(d).slice(0, 7); VIEWS.calendar(); },
  'cal-today': () => { state.calMonth = todayStr().slice(0, 7); state.calSel = todayStr(); VIEWS.calendar(); },

  'new-subject': () => openSubject(null),
  'edit-subject': el => openSubject(Number(el.dataset.id)),
  async 'delete-subject'() {
    const id = Number($('#drawerForm').dataset.id);
    if (!(await confirmDialog('Delete this subject?', 'Its units are removed too. Tasks stay, just without a subject.'))) return;
    try {
      await api(`/api/subjects/${id}`, { method: 'DELETE' });
      state.subjects = state.subjects.filter(s => s.id !== id);
      state.tasks.forEach(t => { if (t.subject_id === id) Object.assign(t, { subject_id: null, unit_id: null, subject_name: null, unit_name: null }); });
      closeDrawer(); render(); toast('Subject deleted');
    } catch (e) { toast(e.message, 'error'); }
  },
  async 'delete-unit'(el) {
    const id = Number(el.dataset.id), sid = Number(el.dataset.subject);
    try {
      await api(`/api/units/${id}`, { method: 'DELETE' });
      const s = subjectById(sid); s.units = s.units.filter(u => u.id !== id);
      state.tasks.forEach(t => { if (t.unit_id === id) Object.assign(t, { unit_id: null, unit_name: null }); });
      render();
    } catch (e) { toast(e.message, 'error'); }
  },

  'new-job': () => openJob(null),
  'open-job': el => openJob(Number(el.dataset.id)),
  async 'advance-job'(el) {
    const j = state.jobs.find(x => x.id === Number(el.dataset.id));
    try { upsert(state.jobs, await api(`/api/jobs/${j.id}`, { method: 'PUT', body: { status: nextStage(j.status) } })); render(); toast(`${j.company} moved to ${JOB_LABEL[nextStage(j.status)]}`); }
    catch (e) { toast(e.message, 'error'); }
  },
  async 'delete-job'() {
    const id = Number($('#drawerForm').dataset.id);
    if (!(await confirmDialog('Delete this application?', 'This cannot be undone.'))) return;
    try { await api(`/api/jobs/${id}`, { method: 'DELETE' }); state.jobs = state.jobs.filter(x => x.id !== id); closeDrawer(); render(); toast('Application deleted'); }
    catch (e) { toast(e.message, 'error'); }
  },

  'new-tx': () => openTx('expense'),
  'tx-type': el => openTx(el.dataset.value),
  async 'delete-tx'(el) {
    if (!(await confirmDialog('Delete this transaction?', 'It will be removed from this month\'s totals.'))) return;
    try { await api(`/api/transactions/${el.dataset.id}`, { method: 'DELETE' }); await loadMoney(); render(); toast('Transaction deleted'); }
    catch (e) { toast(e.message, 'error'); }
  },
  'new-budget': () => openBudget(null),
  'edit-budget': el => openBudget(Number(el.dataset.id)),
  async 'delete-budget'() {
    const id = Number($('#drawerForm').dataset.id);
    if (!(await confirmDialog('Delete this budget?', 'Past transactions are kept.'))) return;
    try { await api(`/api/budgets/${id}`, { method: 'DELETE' }); await loadMoney(); closeDrawer(); render(); toast('Budget deleted'); }
    catch (e) { toast(e.message, 'error'); }
  },
  async 'month-shift'(el) {
    const d = parseDate(state.month + '-01'); d.setMonth(d.getMonth() + Number(el.dataset.value));
    state.month = ymd(d).slice(0, 7);
    try { await loadMoney(); } catch (e) { toast(e.message, 'error'); }
    VIEWS.money();
  },
  'pick-color'(el) {
    const form = el.closest('form');
    form.querySelector('[name="color"]').value = el.dataset.value;
    $$('.swatch', form).forEach(s => { const on = s === el; s.classList.toggle('on', on); s.setAttribute('aria-checked', on); });
  },

  async 'set-appearance'(el) {
    const next = applyAppearance({ ...window.__appearance, [el.dataset.key]: el.dataset.value });
    saveAppearanceLocal(next);
    $('.brand-mark').innerHTML = BRAND_MARK;
    const scroll = $('#content').scrollTop;
    $('#content').classList.add('still');
    VIEWS.settings();
    $('#content').scrollTop = scroll;
    try { await api('/api/settings/appearance', { method: 'PUT', body: next }); }
    catch (e) { toast("Couldn't save your look: " + e.message, 'error'); }
  },
  async export() {
    try {
      const data = await api('/api/export');
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${(state.info.name || 'trackademic').toLowerCase()}-backup-${todayStr()}.json`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      toast('Backup downloaded');
    } catch (e) { toast(e.message, 'error'); }
  },
  'check-updates': () => checkForUpdates(true),
  'dismiss-update': () => { state.updateDismissed = true; renderUpdateBanner(); },
  async 'toggle-auto-update'() {
    const next = { auto_check: !state.updateSettings.auto_check };
    try {
      state.updateSettings = await api('/api/settings/updates', { method: 'PUT', body: next });
      $('#content').classList.add('still'); VIEWS.settings();
    } catch (e) { toast(e.message, 'error'); }
  },
  async 'install-update'() {
    const u = state.update;
    if (!(await confirmDialog(`Update to ${u.latest}?`, 'Trackademic will close, install the update and open again. It takes about a minute.', 'Update now', 'primary'))) return;
    $('#updateOverlay').hidden = false;
    try {
      await api('/api/update/install', { method: 'POST' });
      // The app closes itself once the installer starts
    } catch (e) {
      $('#updateOverlay').hidden = true;
      toast(e.message, 'error');
    }
  },
  'close-drawer': closeDrawer,
};

document.addEventListener('click', e => {
  const el = e.target.closest('[data-action]');
  if (!el || !ACTIONS[el.dataset.action]) return;
  e.preventDefault();
  ACTIONS[el.dataset.action](el, e);
});

document.addEventListener('submit', e => {
  const form = e.target;
  e.preventDefault();
  if (form.id === 'drawerForm') return submitDrawer(form);
  if (form.classList.contains('unit-add')) {
    const sid = Number(form.dataset.subject);
    const name = form.name.value.trim();
    if (!name) return;
    api(`/api/subjects/${sid}/units`, { method: 'POST', body: { name } })
      .then(u => { const s = subjectById(sid); s.units.push(u); s.units.sort((a, b) => a.name.localeCompare(b.name)); VIEWS.subjects(); $(`.unit-add[data-subject="${sid}"] input`)?.focus(); })
      .catch(err => toast(err.message, 'error'));
  }
});

document.addEventListener('keydown', e => {
  // Enter / Space on clickable rows
  if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.task, .job, .closed-row')) { e.preventDefault(); e.target.click(); }
  if (e.key === 'Escape') closeDrawer();
  const typing = e.target.matches('input, textarea, select, [contenteditable]');
  if (!typing && !e.ctrlKey && !e.metaKey && !e.altKey && e.key === 'n' && $('#drawer').hidden) { e.preventDefault(); openTask(null); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') { e.preventDefault(); openTask(null); }
});

$('#scrim').addEventListener('click', closeDrawer);
window.addEventListener('hashchange', () => { $('#content').classList.remove('still'); closeDrawer(); render(); $('#content').scrollTop = 0; });

// Re-render when the date changes (app left open overnight) or the tab comes back
let lastDay = todayStr();
document.addEventListener('visibilitychange', () => { if (!document.hidden && todayStr() !== lastDay) { lastDay = todayStr(); render(); } });
setInterval(() => { if (todayStr() !== lastDay) { lastDay = todayStr(); render(); } }, 60000);

// ── Start ─────────────────────────────────────────────────────────
(async function init() {
  $('.brand-mark').innerHTML = BRAND_MARK;
  // Make rows reachable by keyboard
  new MutationObserver(() => $$('.task, .job, .closed-row').forEach(r => { if (!r.hasAttribute('tabindex')) r.tabIndex = 0; }))
    .observe($('#content'), { childList: true, subtree: true });
  try {
    await loadAll();
  } catch (e) {
    $('#content').innerHTML = `<div class="card">${emptyState('alert', "Couldn't load your data", esc(e.message))}</div>`;
    return;
  }
  render();
  checkForUpdates(false);
})();
