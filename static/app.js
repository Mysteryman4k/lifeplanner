/* ═══════════════════════════════════════════════════════════════
   EasyUniTrack — frontend
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
// Money is shown in the user's chosen currency (Settings → Money)
let MONEY_FMT, MONEY_FMT_WHOLE;
function setCurrency(code) {
  const make = (extra) => new Intl.NumberFormat(undefined, { style: 'currency', currency: code, currencyDisplay: 'narrowSymbol', ...extra });
  try { MONEY_FMT = make({}); MONEY_FMT_WHOLE = make({ minimumFractionDigits: 0, maximumFractionDigits: 0 }); }
  catch (_) { code = 'USD'; MONEY_FMT = make({}); MONEY_FMT_WHOLE = make({ minimumFractionDigits: 0, maximumFractionDigits: 0 }); }
  state.currency = code;
}
const money = (n, whole = false) => (whole ? MONEY_FMT_WHOLE : MONEY_FMT).format(n || 0);
const currencySymbol = () => MONEY_FMT.formatToParts(0).find(p => p.type === 'currency')?.value || state.currency;
const currencyName = code => { try { return new Intl.DisplayNames(undefined, { type: 'currency' }).of(code); } catch (_) { return code; } };
const POPULAR_CURRENCIES = ['AUD', 'USD', 'EUR', 'GBP', 'NZD', 'CAD', 'ZAR', 'INR', 'SGD', 'JPY', 'CNY', 'HKD', 'MYR', 'NGN', 'KES', 'PHP'];
function currencyOptions(selected) {
  let all = [];
  try { all = Intl.supportedValuesOf('currency'); } catch (_) { all = POPULAR_CURRENCIES; }
  const popular = [...new Set([selected, ...POPULAR_CURRENCIES])].filter(c => all.includes(c) || c === selected);
  const label = c => `${c} — ${currencyName(c)}`;
  return `<optgroup label="Common">${popular.map(c => opt(c, label(c), selected)).join('')}</optgroup>
    <optgroup label="All currencies">${all.filter(c => !popular.includes(c)).map(c => opt(c, label(c), selected)).join('')}</optgroup>`;
}
// Categories offered when setting up a budget or logging spending
const SPENDING_CATEGORIES = ['Rent', 'Groceries', 'Eating out', 'Transport', 'Bills & Utilities', 'Phone & Internet',
  'Education', 'Health', 'Entertainment', 'Shopping', 'Other'];
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
  startup: { intro: true },
  currency: 'USD', currencyChosen: false,
  reminders: { daily: true, time: '08:30' }, autostart: { supported: false, enabled: false }, backups: null,
};

const REPEATS = { '': "Doesn't repeat", daily: 'Every day', weekly: 'Every week', fortnightly: 'Every 2 weeks', monthly: 'Every month' };
const REPEAT_SHORT = { daily: 'Daily', weekly: 'Weekly', fortnightly: 'Fortnightly', monthly: 'Monthly' };

setCurrency('USD');   // replaced by the saved/suggested currency once settings load

// ── API ───────────────────────────────────────────────────────────
// Written into the page by the app; the local server refuses changes without it (see app.py)
const APP_TOKEN = document.querySelector('meta[name="app-token"]')?.content || '';

async function api(path, { method = 'GET', body, raw } = {}) {
  const headers = { 'X-EasyUniTrack-Token': APP_TOKEN };
  if (body) headers['Content-Type'] = 'application/json';
  if (raw) headers['Content-Type'] = 'application/octet-stream';        // a file, sent as it is
  const res = await fetch(path, {
    method,
    headers,
    body: raw || (body ? JSON.stringify(body) : undefined),
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
  const [tasks, categories, subjects, jobs, info, appearance, ai, notes] = await Promise.all([
    api('/api/tasks'), api('/api/categories'), api('/api/subjects'), api('/api/jobs'), api('/api/info'),
    api('/api/settings/appearance').catch(() => null), api('/api/ai/state').catch(() => null),
    api('/api/notes').catch(() => []),
  ]);
  state.notes = notes;
  if (ai) state.ai = ai;
  if (ai?.terms?.agreed) loadChats();
  api('/api/settings/startup').then(st => { state.startup = st; }).catch(() => {});
  api('/api/settings/reminders').then(r => { state.reminders = r; }).catch(() => {});
  api('/api/settings/autostart').then(a => { state.autostart = a; }).catch(() => {});
  api('/api/backups').then(b => { state.backups = b; }).catch(() => {});
  // The database copy is the source of truth (localStorage only avoids a flash on start-up)
  if (appearance && JSON.stringify(appearance) !== JSON.stringify(window.__appearance)) {
    saveAppearanceLocal(applyAppearance(appearance));
    $('.brand-mark').innerHTML = BRAND_MARK;
  }
  Object.assign(state, { tasks, categories, subjects, jobs, info });
  document.title = info.name || 'EasyUniTrack';
  const moneySettings = await api('/api/settings/money').catch(() => ({ currency: 'USD', chosen: false }));
  setCurrency(moneySettings.currency);
  state.currencyChosen = moneySettings.chosen;
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
    t.recurrence_pattern ? `<span class="repeats" title="${esc(REPEATS[t.recurrence_pattern])}">${icon('repeat', 13)}${esc(REPEAT_SHORT[t.recurrence_pattern])}</span>` : '',
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
  study: { label: 'Study assistant', icon: 'spark' },
  code: { label: 'Code workspace', icon: 'code' },
  settings: { label: 'Settings', icon: 'settings' },
  more: { label: 'More', icon: 'more' },
};
const aiOn = () => !!state.ai?.assistant_enabled;
const codeOn = () => !!state.ai?.code_enabled;
/** The Android and iPhone app (mobile/): the same screens, with a More tab and the phone's own ways to save and remind. */
const onPhone = () => !!state.info.mobile;
const route = () => {
  const r = location.hash.replace(/^#\/?/, '').split('?')[0];
  if ((r === 'study' && !aiOn()) || (r === 'code' && !codeOn()) || (r === 'more' && !onPhone())) return 'today';   // AI features are invisible while off
  return ROUTES[r] ? r : 'today';
};
/** The phone's tabs: the fourth is the study assistant when it's on, otherwise Money. Everything else is under More. */
const phoneTabs = () => ['today', 'tasks', 'calendar', aiOn() ? 'study' : 'money', 'more'];
/** Where this copy keeps AI keys, and what to call the device, in the words of each platform. */
const keyStore = () => onPhone() ? "this phone's secure storage" : 'Windows Credential Manager';
const thisDevice = () => onPhone() ? 'this phone' : 'this PC';

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
    ${aiOn() || codeOn() ? `<div class="nav-label">Study <span class="preview-badge sm">Preview</span></div>${aiOn() ? item('study') : ''}${codeOn() ? item('code') : ''}${recentChats()}` : ''}
    <div class="nav-label">Track</div>${['jobs', 'money'].map(item).join('')}`;
  $('#navFoot').innerHTML = item('settings');
  const tabs = onPhone() ? phoneTabs() : ['today', 'tasks', 'calendar', 'jobs', 'money'];
  const current = tabs.includes(r) ? r : onPhone() ? 'more' : r;          // a screen under More lights up More
  $('#tabbar').innerHTML = tabs.map(k =>
    `<a class="tab ${current === k ? 'active' : ''}" href="#/${k}" ${current === k ? 'aria-current="page"' : ''}>${icon(ROUTES[k].icon, 22)}<span>${k === 'study' ? 'Study' : ROUTES[k].label}</span>${counts[k] && onPhone() ? `<span class="tab-count">${counts[k].n}</span>` : ''}</a>`).join('');
}

function setHeader(title, eyebrow = '', actions = '') {
  $('#pageTitle').textContent = title;
  $('#eyebrow').textContent = eyebrow;
  const gear = route() !== 'settings' && !onPhone()          // on the phone, Settings is under More
    ? `<a class="icon-btn mobile-only" href="#/settings" aria-label="Settings">${icon('settings', 20)}</a>` : '';
  $('#headerActions').innerHTML = actions + gear;
}

const btn = (action, label, iconName, cls = 'btn-primary', extra = '') =>
  `<button class="btn ${cls}" data-action="${action}" ${extra}>${iconName ? icon(iconName, 17) : ''}<span class="btn-label">${label}</span></button>`;

function render() {
  renderNav();
  const r = route();
  document.documentElement.dataset.route = r;
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
          ${budgetTotal ? `<a class="card tile" href="#/money">
            <div class="tile-left">
              <div class="tile-top">Left to spend</div>
              <div class="tile-note">${isThisMonth ? `of ${money(budgetTotal, true)} · ${plural(daysLeft, 'day')} left` : ''}</div>
            </div>
            <div class="tile-value ${left < 0 ? 'bad' : ''}">${left < 0 ? '−' : ''}${money(Math.abs(left), true)}</div>
          </a>` : `<button class="card tile tile-cta" data-action="budget-plan">
            <div class="tile-left">
              <div class="tile-top">Monthly budget</div>
              <div class="tile-note">Not set up yet</div>
            </div>
            <div class="tile-value tile-value-cta">Set up ${icon('arrowRight', 20)}</div>
          </button>`}
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
        ${notesBlock(s.id)}
        ${subjectCodeBlock(s.id)}
      </article>`;
    }).join('')}${notesBlock(null)}</div>`;
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
    setHeader('Money', `Amounts in ${state.currency} · ${currencyName(state.currency)}`,
      btn('budget-plan', state.budgets.length ? 'Edit budgets' : 'Set up budget', 'money', 'btn-ghost') + btn('new-tx', 'Add transaction', 'plus'));
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
        ${!state.budgets.length ? `
        <section class="card onboard">
          <div class="onboard-icon">${icon('money', 26)}</div>
          <div class="onboard-text">
            <h2>Set up your monthly budget</h2>
            <p>Pick your currency and how much you want to spend on things like rent, groceries and transport each month. EasyUniTrack then shows what's left as you go.</p>
          </div>
          ${btn('budget-plan', 'Set up budget', 'arrowRight', 'btn-primary keep-label')}
        </section>` : ''}
        <div class="tiles">
          <div class="card tile"><div class="tile-left"><div class="tile-top">Money in</div><div class="tile-note">${plural(state.transactions.filter(x => x.type === 'income').length, 'payment')}</div></div>
            <div class="tile-value">${money(income, true)}</div></div>
          <div class="card tile"><div class="tile-left"><div class="tile-top">Money out</div><div class="tile-note">${income ? `${Math.round(spent / income * 100)}% of what came in` : plural(state.transactions.filter(x => x.type === 'expense').length, 'purchase')}</div></div>
            <div class="tile-value">${money(spent, true)}</div></div>
          ${budgetTotal ? `<div class="card tile"><div class="tile-left"><div class="tile-top">Budget left</div><div class="tile-note">of ${money(budgetTotal, true)}</div></div>
            <div class="tile-value ${budgetTotal - budgetSpent < 0 ? 'bad' : ''}">${budgetTotal - budgetSpent < 0 ? '−' : ''}${money(Math.abs(budgetTotal - budgetSpent), true)}</div></div>`
          : `<button class="card tile tile-cta" data-action="budget-plan"><div class="tile-left"><div class="tile-top">Budget left</div><div class="tile-note">No budget yet</div></div>
            <div class="tile-value tile-value-cta">Set up ${icon('arrowRight', 20)}</div></button>`}
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
            <div class="section-head"><h2>Budgets</h2>${state.budgets.length ? `<button class="link" data-action="budget-plan">Edit all</button>` : ''}</div>
            <div class="budget-list">${state.budgets.map(budgetRow).join('') || `<p class="small muted">No budgets yet. ${''}<button class="link" data-action="budget-plan">Set one up</button></p>`}</div>
          </section>
        </div>
      </div>`;
  },


  study() {
    if (chatState().code) chatReset();             // coming from the code workspace: a fresh study chat
    setHeader('Study assistant', 'Preview · your AI tutor', btn('chats-all', 'Chats', 'inbox', 'btn-ghost') + btn('chat-new', 'New chat', 'plus', 'btn-ghost'));
    $('#content').innerHTML = `<div class="study">${chatShell(false)}</div>`;
    chatAfterRender();
  },

  code() {
    const k = codeState();
    if (!k.folders) {
      setHeader('Code workspace', 'Preview');
      $('#content').innerHTML = `<div class="card muted">Loading your folders…</div>`;
      codeLoad();
      return;
    }
    const f = codeFolder();
    if (!f && k.folders.length) {                   // listed from Settings or a subject, none open yet
      k.folderId = k.folders[0].id;
      codeLoadTree();
      return;
    }
    if (!f) {
      setHeader('Code workspace', 'Preview · help with your code');
      $('#content').innerHTML = `<div class="card">${emptyState('folder', 'Link a code folder',
        'Pick a folder with your code. The assistant reads only that folder, skips secrets like .env files and anything in .gitignore, and never changes or runs anything by itself.',
        btn('code-link', 'Link a folder', 'plus'))}</div>`;
      return;
    }
    if (chatState().code !== f.id) chatReset(null, f.id);
    const modeBtn = (m, label) => `<button class="${f.mode === m ? 'on' : ''}" data-action="code-mode" data-mode="${m}">${label}</button>`;
    setHeader(f.name, `Code workspace · Preview${f.subject_name ? ' · ' + f.subject_name : ''}`,
      `<div class="segmented code-modes" role="group" aria-label="How the assistant helps">${modeBtn('assignment', 'Assignment · hints first')}${modeBtn('personal', 'Personal · fix freely')}</div>` +
      btn('chat-new', 'New chat', 'plus', 'btn-ghost') + btn('code-link', 'Link a folder', 'folder', 'btn-ghost'));
    const others = k.folders.length > 1 ? `<select class="select select-sm" id="codeFolder" aria-label="Linked folder">
      ${k.folders.map(x => opt(x.id, x.name, f.id)).join('')}</select>` : `<b class="code-folder-name">${icon('folder', 15)}${esc(f.name)}</b>`;
    const treePane = `<aside class="card code-tree">
        <div class="code-pane-head">${others}<span class="spacer"></span>
          <button class="icon-btn" data-action="code-refresh" aria-label="Refresh the file list" title="Refresh">${icon('refresh', 16)}</button>
          <button class="icon-btn" data-action="code-unlink" aria-label="Unlink this folder" title="Unlink (your files aren't touched)">${icon('x', 16)}</button></div>
        <div class="code-tree-list" id="codeTree">${k.treeError ? '' : k.tree ? codeTreeNodes(k.tree.children) +
          (k.tree.truncated ? '<p class="muted small">Only the first 3,000 items are shown.</p>' : '') : '<p class="muted small">Loading…</p>'}</div></aside>`;
    const main = k.treeError
      ? `<section class="card code-main">${emptyState('alert', "This folder can't be found", esc(k.treeError),
          btn('code-unlink', 'Unlink it', 'x', 'btn-ghost'))}</section>`
      : `<section class="card code-main" id="codeMain">${codeViewer()}</section>`;
    $('#content').innerHTML = `<div class="code-ws ${k.filesOpen ? 'files-open' : ''}">${treePane}${main}<section class="code-chat">${chatShell(false)}</section></div>`;
    codeScrollToMark();
    chatAfterRender();
    if (k.run?.status === 'running') codePoll();
  },

  more() {
    setHeader('More');
    const follow = state.jobs.filter(j => ACTIVE_JOB.has(j.status) && j.follow_up_date && j.follow_up_date <= todayStr()).length;
    const active = state.jobs.filter(j => ACTIVE_JOB.has(j.status)).length;
    const budgetLeft = state.budgets.reduce((t, b) => t + b.monthly_limit - b.spent, 0);
    const tabs = phoneTabs();
    const row = (key, note = '') => tabs.includes(key) ? '' : `<a class="more-row" href="#/${key}">${icon(ROUTES[key].icon, 20)}<span>${ROUTES[key].label}</span>${note ? `<span class="more-note">${note}</span>` : ''}${icon('chevronRight', 16)}</a>`;
    const group = (title, rows) => rows.join('') ? `<section class="more-group"><h2>${title}</h2><div class="card">${rows.join('')}</div></section>` : '';
    $('#content').innerHTML = `<div class="more-list">
      ${group('Plan', [row('subjects', plural(state.subjects.length, 'subject'))])}
      ${group('Track', [row('jobs', follow ? plural(follow, 'follow-up') + ' due' : plural(active, 'active application')),
        row('money', state.budgets.length ? `${budgetLeft < 0 ? '−' : ''}${money(Math.abs(budgetLeft), true)} left` : '')])}
      ${aiOn() || codeOn() ? group('Study <span class="preview-badge sm">Preview</span>', [aiOn() ? row('study') : '', codeOn() ? row('code') : '']) : ''}
      ${group('App', [row('settings', esc(state.info.version || ''))])}
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
            <div class="appearance-head"><div><div class="setting-title">Light or dark</div><div class="setting-desc">System follows your ${onPhone() ? 'phone' : 'computer'}'s setting.</div></div>
              <div class="segmented">${mode('system', 'System', 'monitor')}${mode('light', 'Light', 'sun')}${mode('dark', 'Dark', 'moon')}</div></div>
            ${onPhone() ? '' : `<div class="appearance-head"><div><div class="setting-title">Intro animation</div><div class="setting-desc">Plays when the desktop app opens. Turn off for a quicker, plain loading screen.</div></div>
              <button class="switch ${state.startup.intro ? 'on' : ''}" role="switch" aria-checked="${state.startup.intro}" data-action="toggle-intro" aria-label="Intro animation"><i></i></button></div>`}
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
        <h2>Reminders</h2>
        <div class="card">${remindersCard()}</div>
        <h2>Study assistant <span class="preview-badge">Preview</span></h2>
        <div class="card" id="aiCard">${aiCard()}</div>
        <h2>Task types</h2>
        <div class="card">${taskTypesCard()}</div>
        <h2>Your data</h2>
        <div class="card">
          <div class="setting"><div><div class="setting-title">Saved on this ${onPhone() ? 'phone' : 'computer'}</div><div class="setting-desc ${onPhone() ? '' : 'path'}">${esc(state.info.data_file || '')}</div></div>${icon('database', 20)}</div>
          <div class="setting"><div><div class="setting-title">Back up</div><div class="setting-desc">${plural(state.tasks.length, 'task')}, ${plural(state.jobs.length, 'application')}, ${state.subjects.length} subjects${state.backups?.latest ? '. A copy is also saved automatically each day you open the app (the last 10 are kept).' : ''}${onPhone() ? ' Save the file to Drive or Files, or send it to your computer.' : ''}</div></div>
            ${onPhone() ? btn('export', 'Save backup', 'share', 'btn-ghost btn-sm keep-label') : btn('export', 'Download backup', 'download', 'btn-ghost btn-sm keep-label')}</div>
          <div class="setting"><div><div class="setting-title">Restore from a backup</div><div class="setting-desc">Replaces everything with a backup file${onPhone() ? ', from this phone or the desktop app' : ''}. Your current data is saved first, just in case.</div></div>
            ${btn('import', 'Restore…', 'upload', 'btn-ghost btn-sm keep-label')}<input type="file" id="importFile" accept=".json,application/json" hidden></div>
        </div>
        <h2>Money</h2>
        <div class="card">
          <div class="setting"><div><div class="setting-title">Currency</div><div class="setting-desc">Used for every amount in the app. Changing it relabels your amounts; it doesn't convert them.</div></div>
            <select class="select" id="settingsCurrency" style="width:auto;max-width:280px" aria-label="Currency">${currencyOptions(state.currency)}</select></div>
          <div class="setting"><div><div class="setting-title">Monthly budget</div><div class="setting-desc">${state.budgets.length ? `${plural(state.budgets.length, 'category', 'categories')}, ${money(state.budgets.reduce((t, b) => t + b.monthly_limit, 0), true)} a month` : 'Not set up yet'}</div></div>
            ${btn('budget-plan', state.budgets.length ? 'Edit budgets' : 'Set up budget', 'money', 'btn-ghost btn-sm keep-label')}</div>
        </div>
        ${onPhone() ? '' : `<h2>Updates</h2>
        <div class="card">${updatesCard()}</div>`}
        <h2>About</h2>
        <div class="card">
          <div class="setting"><div><div class="setting-title">${esc(state.info.name || 'EasyUniTrack')} ${esc(state.info.version || '')}</div><div class="setting-desc">Student planner, job tracker and money manager${onPhone() ? `. Updates come from ${state.info.platform === 'ios' ? 'the App Store' : 'Google Play'}.` : ''}</div></div></div>
          <div class="setting"><div><div class="setting-title">Made by Mysteryman4k</div><div class="setting-desc">© 2026 Mysteryman4k. All rights reserved.</div></div>
            <a class="link" href="https://github.com/Mysteryman4k/lifeplanner" target="_blank" rel="noopener">GitHub ${icon('external', 14)}</a></div>
        </div>
      </div>`;
  },
};

function remindersCard() {
  const r = state.reminders, a = state.autostart;
  return `
    <div class="setting"><div><div class="setting-title">Daily reminder</div><div class="setting-desc">A notification with what's due today, what's overdue and job follow-ups. Only sent on days with something to do${onPhone() ? ', even when the app is closed' : ', while EasyUniTrack is open (it can be minimised)'}.</div></div>
      <button class="switch ${r.daily ? 'on' : ''}" role="switch" aria-checked="${r.daily}" data-action="toggle-reminders" aria-label="Daily reminder"><i></i></button></div>
    ${r.daily ? `<div class="setting"><div><div class="setting-title">Time</div><div class="setting-desc">${onPhone() ? 'Each day at this time.' : 'If the app opens after this time, you get it then.'}</div></div>
      <div class="row-gap"><input class="input" type="time" id="reminderTime" value="${esc(r.time)}" aria-label="Reminder time">
      ${btn('test-reminder', 'Send test', 'bell', 'btn-ghost btn-sm keep-label')}</div></div>` : ''}
    ${onPhone() ? '' : `<div class="setting"><div><div class="setting-title">Start with Windows</div><div class="setting-desc">${a.supported
      ? 'Opens EasyUniTrack minimised when you sign in, so reminders arrive without you opening it.'
      : 'Available in the installed Windows app.'}</div></div>
      <button class="switch ${a.enabled ? 'on' : ''}" role="switch" aria-checked="${a.enabled}" data-action="toggle-autostart" aria-label="Start with Windows" ${a.supported ? '' : 'disabled'}><i></i></button></div>`}`;
}

function taskTypesCard() {
  const used = id => state.tasks.filter(t => t.category_id === id).length;
  return `
    <div class="setting-desc type-intro">The "Type" you can give a task. Rename them, change their colour or add your own.</div>
    <div class="type-list">${state.categories.map(c => `
      <div class="type-row">
        <i class="dot" style="--c:${esc(c.color)}"></i>
        <span class="type-name">${esc(c.name)}</span>
        <span class="muted small">${plural(used(c.id), 'task')}</span>
        <button class="icon-btn sm" data-action="edit-type" data-id="${c.id}" aria-label="Edit ${esc(c.name)}" title="Edit">${icon('pencil', 15)}</button>
      </div>`).join('')}</div>
    <div class="type-add">${btn('new-type', 'Add a type', 'plus', 'btn-ghost btn-sm keep-label')}</div>`;
}

function openType(id) {
  const c = id ? state.categories.find(x => x.id === id) : { name: '', color: SUBJECT_COLORS[1] };
  if (!c) return;
  const body = `
    <form id="drawerForm" class="form-stack" data-kind="type" data-id="${id || ''}" autocomplete="off">
      <input class="title-input" name="name" placeholder="e.g. Lab report" value="${esc(c.name)}" required maxlength="120" autofocus aria-label="Name">
      ${field('Colour', swatchPicker(c.color))}
    </form>`;
  openDrawer(id ? 'Edit task type' : 'New task type', body, footer(id ? 'delete-type' : ''), 'type');
}

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
    <span><strong>EasyUniTrack ${esc(u.latest)}</strong> is available <span class="muted">· you have ${esc(u.current)}</span></span>
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
  if (state.info.store) {
    return `<div class="setting"><div><div class="setting-title">Version ${esc(current)}</div>
      <div class="setting-desc">EasyUniTrack updates itself through the Microsoft Store. Open the Store and check Downloads to update by hand.</div></div></div>`;
  }
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


// ── AI study assistant (preview): settings, About and Terms ───────
// Everything AI stays hidden until the student agrees to the terms here. See ai/ on the server.
function aiCard() {
  const a = state.ai;
  if (!a) return `<div class="setting"><div class="setting-desc">Loading…</div></div>`;
  if (!a.terms.agreed) {
    const desc = a.terms.needs_reagreement
      ? 'The terms of use have been updated. Read and agree to the new version to keep using the AI features.'
      : onPhone() ? 'An AI tutor for your units, using your own AI provider. Off until you turn it on.'
      : 'An AI tutor for your units and a coding helper, using your own AI provider or a free model on this PC. Off until you turn it on.';
    return `<div class="setting"><div><div class="setting-title">AI study assistant and code workspace</div><div class="setting-desc">${desc}</div></div>
      ${btn('ai-start', a.terms.needs_reagreement ? 'Read new terms' : 'Learn more', 'spark', 'btn-primary btn-sm keep-label')}</div>`;
  }
  const p = a.provider, preset = a.providers[p] || null;
  const pill = (k, v) => `<button class="${p === k ? 'on' : ''}" data-action="ai-provider" data-id="${k}">${esc(v.name)}</button>`;
  const links = preset ? [
    preset.key_url ? `<a class="link" href="${esc(preset.key_url)}" target="_blank" rel="noopener">${p === 'ollama' ? 'Download Ollama' : 'Get an API key'} ${icon('external', 13)}</a>` : '',
    preset.limit_url ? `<a class="link" href="${esc(preset.limit_url)}" target="_blank" rel="noopener">Set a spending limit (recommended) ${icon('external', 13)}</a>` : '',
  ].filter(Boolean).join(' · ') : '';
  const needsKey = preset && (preset.needs_key || p === 'custom');
  const models = [...new Set([...(state.aiModels || []), a.model].filter(Boolean))];
  const t = state.aiTest;
  const sys = state.aiSystem;
  return `
    <div class="setting"><div><div class="setting-title">Study assistant</div><div class="setting-desc">Explain, practise and quiz yourself on your units with an AI tutor.</div></div>
      <button class="switch ${a.assistant_enabled ? 'on' : ''}" role="switch" aria-checked="${a.assistant_enabled}" data-action="toggle-ai-assistant" aria-label="Study assistant"><i></i></button></div>
    ${onPhone() ? '' : `<div class="setting"><div><div class="setting-title">Code workspace</div><div class="setting-desc">Help with code in folders you link. Code only runs when you click Run.</div></div>
      <button class="switch ${a.code_enabled ? 'on' : ''}" role="switch" aria-checked="${a.code_enabled}" data-action="toggle-ai-code" aria-label="Code workspace"><i></i></button></div>`}
    ${a.code_enabled ? codeFoldersSetting() : ''}
    <div class="setting"><div><div class="setting-title">Keep chats</div><div class="setting-desc">Saved chats you haven't continued for this long are deleted. Suggested code changes, their backups and the record of changes to your tasks are cleared after 90 days.</div></div>
      <select class="select" id="aiKeepChats" style="max-width:220px" aria-label="Keep chats">${KEEP_CHATS.map(([v, l]) => opt(v, l, a.keep_chats_days || 0)).join('')}</select></div>
    <div class="setting ai-provider"><div style="flex:1;min-width:0"><div class="setting-title">AI provider</div>
      <div class="segmented ai-pills" role="group" aria-label="AI provider">${Object.entries(a.providers).map(([k, v]) => pill(k, v)).join('')}</div>
      ${preset ? `<div class="setting-desc ai-about-provider">${esc(preset.about)}</div>${links ? `<div class="small ai-links">${links}</div>` : ''}` : `<div class="setting-desc">Choose where the AI runs. You can change this any time.</div>`}
    </div></div>
    ${p === 'custom' ? `<div class="setting"><div><div class="setting-title">Base URL</div><div class="setting-desc">The service's OpenAI-compatible address, for example https://openrouter.ai/api/v1</div></div>
      <input class="input" id="aiBaseUrl" type="url" value="${esc(a.base_url)}" placeholder="https://" style="max-width:300px" aria-label="Base URL"></div>` : ''}
    ${needsKey ? `<div class="setting"><div><div class="setting-title">API key</div><div class="setting-desc">${a.key ? `Saved in ${keyStore()} (${esc(a.key)}). Paste a new key to replace it.` : `Stored in ${keyStore()}${onPhone() ? '' : ' on this PC'}, never in your backups.`}</div></div>
      <div class="row-gap"><input class="input" id="aiKey" type="password" autocomplete="off" spellcheck="false" placeholder="${a.key ? 'Paste a new key' : 'Paste your API key'}" style="width:220px" aria-label="API key">
      ${btn('ai-save-key', 'Save', 'check', 'btn-ghost btn-sm keep-label')}${a.key ? btn('ai-remove-key', 'Remove', 'trash', 'btn-danger-ghost btn-sm keep-label') : ''}</div></div>` : ''}
    ${preset ? `<div class="setting"><div style="min-width:0"><div class="setting-title">Model</div>
      <div class="setting-desc ${t ? (t.ok ? 'ai-ok' : 'ai-bad') : ''}" id="aiTestResult">${t ? esc(t.message) : 'Test the connection to load the models available to you.'}</div></div>
      <div class="row-gap">${models.length ? `<select class="select" id="aiModel" style="max-width:260px" aria-label="Model">${models.map(m => opt(m, (state.aiCloud || []).includes(m) ? `${m} (Ollama cloud: data leaves this PC)` : m, a.model)).join('')}</select>` : ''}
      ${btn('ai-test', state.aiTesting ? 'Testing…' : 'Test connection', 'refresh', 'btn-ghost btn-sm keep-label', state.aiTesting ? 'disabled' : '')}</div></div>` : ''}
    ${p === 'ollama' ? `<div class="setting"><div><div class="setting-title">This PC</div><div class="setting-desc">${sys ? `${esc(sys.advice)} ${sys.ollama.running ? `Ollama ${esc(sys.ollama.version)} is running.` : 'Ollama isn\'t running.'}` : 'Checking…'}</div></div>${icon('monitor', 20)}</div>` : ''}
    <div class="setting"><div><div class="setting-title">Terms of use</div><div class="setting-desc">Agreed to version ${esc(a.terms.agreed_version)} on ${esc(fmt(a.terms.agreed_at.slice(0, 10), { day: 'numeric', month: 'short', year: 'numeric' }))}. Saved only on ${thisDevice()}.</div></div>
      <div class="row-gap">${btn('ai-view-terms', 'View', 'shield', 'btn-ghost btn-sm keep-label')}${btn('ai-withdraw', 'Turn off', 'power', 'btn-ghost btn-sm keep-label')}</div></div>
    <div class="setting"><div><div class="setting-title">Remove all AI data</div><div class="setting-desc">${onPhone() ? 'Deletes your saved API keys, chats, and your AI settings and agreement.' : 'Deletes your saved API keys, chats, linked code folders (not the folders themselves), suggested changes and their backups, and your AI settings and agreement.'} Your notes and planner data aren't touched.</div></div>
      ${btn('ai-remove-all', 'Remove', 'trash', 'btn-danger-ghost btn-sm keep-label')}</div>`;
}

async function aiTerms() {
  if (!state.aiTerms) state.aiTerms = await api('/api/ai/terms');
  return state.aiTerms;
}

async function openAiAbout() {
  const t = await aiTerms();
  const body = `
    <div class="ai-about">
      <p class="muted small">AI features are a <b>beta</b>. Here's what to know before you turn them on.</p>
      <ul>${t.about.map(x => `<li><b>${esc(x.title)}.</b> ${esc(x.text)}</li>`).join('')}</ul>
      <p class="small muted">Next you'll read the terms of use. Nothing is set up until you agree.</p>
    </div>`;
  const foot = `<span class="spacer"></span><button class="btn btn-ghost" type="button" data-action="close-drawer">Not now</button>
    <button class="btn btn-primary" type="button" data-action="ai-terms-next">Next: terms</button>`;
  openDrawer('Before you turn this on', body, foot, 'ai-about');
}

async function openAiTerms(readOnly) {
  const t = await aiTerms();
  const body = `
    <div class="ai-terms">
      <p class="small muted">EasyUniTrack AI features · terms of use (beta) · version ${esc(t.version)}</p>
      <div class="terms-box" tabindex="0" aria-label="Terms of use">${t.terms.map(x => `<h4>${esc(x.title)}</h4><p>${esc(x.text)}</p>`).join('')}</div>
      ${readOnly ? '' : `<div class="ai-ticks">${Object.entries(t.ticks).map(([k, text]) => `
        <label class="tick-row"><input type="checkbox" class="ai-tick" data-k="${k}"><span>${esc(text)}</span></label>`).join('')}</div>`}
    </div>`;
  const foot = readOnly
    ? `<span class="spacer"></span><button class="btn btn-ghost" type="button" data-action="close-drawer">Close</button>`
    : `<span class="spacer"></span><button class="btn btn-ghost" type="button" data-action="close-drawer">Not now</button>
       <button class="btn btn-primary" type="button" id="aiAgree" data-action="ai-agree" disabled>Agree and continue</button>`;
  openDrawer('Terms of use', body, foot, 'ai-terms');
}

const KEEP_CHATS = [[0, 'Until I delete them'], [365, '1 year'], [180, '6 months'], [90, '3 months'], [30, '1 month']];

async function aiSettings(body) {
  state.ai = await api('/api/ai/settings', { method: 'PUT', body });
  return state.ai;
}

async function aiLoadSystem() {
  try { state.aiSystem = await api('/api/ai/system'); } catch (_) { /* shown as "Checking…" */ }
  if (route() === 'settings') stillRender();
}

// ── Study assistant chat (preview) ────────────────────────────────
// Replies stream from /api/ai/chat. They're rendered by chatMarkdown(), which escapes everything first,
// so model output can never add HTML or scripts to the page. Only YouTube search links become links.
const CHAT_MODES = { explain: 'Explain', practise: 'Practise', quiz: 'Quiz me', check: 'Check my attempt' };
const CHAT_MODE_HELP = {
  explain: 'Explain gives clear explanations and checks you understood.',
  practise: 'Practise gives you questions like the ones you\'ll face, one at a time.',
  quiz: 'Quiz me asks a few questions on a topic, one at a time, marks each answer and tells you what to revise.',
  check: 'Check my attempt gives feedback on your own working, without rewriting it for you.',
};
const CHAT_FORMATS = { auto: 'Any format', notes: 'Notes', diagram: 'Diagram', both: 'Notes and diagram', maths: 'Maths', code: 'Code' };
const FORMAT_ASK = { notes: 'as notes', diagram: 'as a diagram', both: 'as notes with a diagram', maths: 'with the maths written out', code: 'as code' };
const CHAT_IDEAS = ['Explain recursion with a simple example', 'Give me a practice question on Big-O',
  'What is the difference between a stack and a queue?', 'Help me plan revision for a mid-semester exam'];

function chatState() {
  if (!state.chat) state.chat = { mode: 'explain', format: 'auto', session: {}, messages: [], tokens: 0, streaming: false, taskId: null, controller: null, file: null, attaching: null, summary: '' };
  return state.chat;
}

// Safe rendering, in this order: code and maths are taken out of the raw text first (they need it unescaped),
// everything else is escaped and then turned into Markdown, and the result goes through DOMPurify as a second
// line of defence. Diagrams are drawn after the reply is on screen (enhanceRich).
const PURIFY = { ALLOW_DATA_ATTR: false, ADD_ATTR: ['target'], FORBID_TAGS: ['style', 'form', 'input', 'button', 'textarea', 'select'] };

function chatMarkdown(src) {
  const blocks = [], spans = [];
  const keep = (list, html, mark) => { list.push(html); return `${mark}${list.length - 1}${mark}`; };
  let text = String(src).replace(/[\u0000\u0001]/g, '')
    .replace(/```([^\n`]*)\n([\s\S]*?)(```|$)/g, (_, lang, code) => keep(blocks, codeBlock(lang.trim(), code.replace(/\n$/, '')), '\u0000'))
    .replace(/`([^`\n]+)`/g, (_, code) => keep(spans, `<code>${esc(code)}</code>`, '\u0001'))
    .replace(/\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]/g, (_, a, b) => keep(spans, maths(a ?? b, true), '\u0001'))
    .replace(/\\\((.+?)\\\)|\$(?=[^\s$])([^$\n]*?[^\s$\\])\$(?!\d)/g, (_, a, b) => keep(spans, maths(a ?? b, false), '\u0001'));
  // Some models (gpt-oss) write a few HTML tags: <br> in table cells, <u>, <sup>, <sub>. Only those exact tags,
  // with no attributes, become formatting again after escaping; any other tag stays as text
  text = esc(text).replace(/&lt;br\s*\/?&gt;/gi, '<br>').replace(/&lt;(\/?)(u|sup|sub)&gt;/gi, (_, end, tag) => `<${end}${tag.toLowerCase()}>`);
  const inline = s => s
    .replace(/\*\*(?=\S)(.+?)\*\*/g, '<strong>$1</strong>')            // may hold *italics* of its own
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]\n]+)\]\((https:\/\/www\.youtube\.com\/results\?search_query=[^\s)"<>]+)\)/g,
      `<a class="link" href="$2" target="_blank" rel="noopener noreferrer">${icon('external', 13)}$1</a>`)
    .replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, '$1 ($2)');                 // any other link stays plain text
  const html = markdownLines(text.split('\n'), inline, blocks)
    .replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[+i]).replace(/\u0001(\d+)\u0001/g, (_, i) => spans[+i]);
  return window.DOMPurify ? DOMPurify.sanitize(html, PURIFY) : html;
}

/** chatMarkdown's block level, on escaped lines: tables, quotes (their lines are rendered the same way inside),
 *  headings, rules and lists. Lists nest by indentation, a numbered list split by a paragraph or code goes on
 *  from its number, and a code block indented under a list item stays in it. */
function markdownLines(lines, inline, blocks) {
  const out = [], lists = [];                      // the open lists, innermost last: { tag, indent }
  const closeLists = (indent = -1) => { while (lists.length && lists[lists.length - 1].indent > indent) out.push(`</li></${lists.pop().tag}>`); };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let m;
    if (line.includes('|') && (lines[i + 1] || '').includes('|') && TABLE_RULE.test(lines[i + 1])) {   // not a --- rule
      closeLists();
      const head = tableCells(line), aligns = tableCells(lines[i + 1]).map(c => /^:-+:$/.test(c) ? 'center' : /-:$/.test(c) ? 'right' : '');
      const al = j => aligns[j] ? ` class="al-${aligns[j]}"` : '';
      const rows = [];
      for (i += 2; i < lines.length && lines[i].includes('|') && lines[i].trim(); i++) rows.push(tableCells(lines[i]));
      i--;
      out.push(`<div class="chat-table-wrap"><table class="chat-table"><thead><tr>${head.map((c, j) => `<th${al(j)}>${inline(c)}</th>`).join('')}</tr></thead>` +
        `<tbody>${rows.map(r => `<tr>${head.map((_, j) => `<td${al(j)}>${inline(r[j] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
      continue;
    }
    if (/^\s*&gt;/.test(line)) {                   // a quote (> is escaped by now): its lines without the >
      const indent = line.match(/^\s*/)[0].replace(/\t/g, '    ').length;
      closeLists(lists.length && indent > lists[0].indent ? indent - 1 : -1);   // indented under an item: stays in it
      const inner = [], prose = s => s.trim() && !/^\s*([-*+]|\d+[.)])\s|^#{1,6}\s|^\s*&gt;|\u0000|\||^\s*([-*_])(\s*\2){2,}\s*$/.test(s);
      for (; i < lines.length && /^\s*&gt;/.test(lines[i]); i++) {
        const text = lines[i].replace(/^\s*&gt;\s?/, ''), prev = inner[inner.length - 1];
        if (prose(text) && prev !== undefined && prose(prev)) inner[inner.length - 1] = `${prev}<br>${text.trim()}`;  // one paragraph
        else inner.push(text);
      }
      i--;
      out.push(`<blockquote>${markdownLines(inner, inline, blocks)}</blockquote>`);
      continue;
    }
    if ((m = line.match(/^(\s*)\u0000(\d+)\u0000\s*$/))) {
      if (!lists.length || m[1].length <= lists[0].indent) closeLists();
      out.push(blocks[+m[2]]);                     // indented under a list item: it stays in the item
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { closeLists(); out.push('<hr>'); continue; }
    if ((m = line.match(/^(\s*)(?:([-*+])|(\d+)[.)])\s+(.*)$/))) {
      const indent = m[1].replace(/\t/g, '    ').length, tag = m[2] ? 'ul' : 'ol';
      closeLists(indent);
      const top = lists[lists.length - 1];
      if (top && top.indent === indent && top.tag === tag) { out.push(`</li><li>${inline(m[4])}`); continue; }
      if (top && top.indent === indent) out.push(`</li></${lists.pop().tag}>`);
      const start = tag === 'ol' && +m[3] > 1 ? ` start="${+m[3]}"` : '';
      out.push(`<${tag}${start}><li>${inline(m[4])}`);
      lists.push({ tag, indent });
      continue;
    }
    if (!line.trim()) continue;                    // a blank line keeps a list open: "1." … blank … "2." is one list
    const indent = line.match(/^\s*/)[0].replace(/\t/g, '    ').length;
    if (lists.length && indent > lists[0].indent) {   // text indented under an item: it belongs to that item
      closeLists(indent - 1);
      out.push(`<p>${inline(line.trim())}</p>`);
      continue;
    }
    closeLists();
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) { const h = Math.min(m[1].length + 2, 6); out.push(`<h${h}>${inline(m[2])}</h${h}>`); }
    else out.push(`<p>${inline(line)}</p>`);
  }
  closeLists();
  return out.join('');
}

const TABLE_RULE = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;      // a table's --- row (any number of dashes)
const tableCells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());

function maths(tex, display) {
  if (!window.katex) return `<code>${esc(tex)}</code>`;
  try {
    return katex.renderToString(tex, { displayMode: display, throwOnError: false, trust: false, strict: 'ignore', maxSize: 20, maxExpand: 300 });
  } catch (_) { return `<code>${esc(tex)}</code>`; }
}

function codeBlock(lang, code) {
  const l = lang.toLowerCase().replace(/[^a-z0-9+#-]/g, '');
  if (l === 'mermaid') return `<div class="chat-diagram"><pre class="chat-code"><code>${esc(code)}</code></pre></div>`;
  let html = esc(code);
  if (window.hljs && l && hljs.getLanguage(l)) {
    try { html = hljs.highlight(code, { language: l, ignoreIllegals: true }).value; } catch (_) { /* stays plain */ }
  }
  return `<pre class="chat-code"><code class="hljs${l ? ` language-${l}` : ''}">${html}</code></pre>`;
}

// ── After a reply is on screen: Copy on code blocks, and diagrams drawn with mermaid ──
const DIAGRAMS = new Map();          // theme + source -> { svg } or { error }, so redraws are instant
let mermaidLoading = null, diagramCount = 0;

function loadMermaid() {
  return mermaidLoading ||= new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = `/static/vendor/mermaid.min.js?v=${encodeURIComponent(state.info?.version || '')}`;
    s.onload = () => resolve(window.mermaid);
    s.onerror = () => { mermaidLoading = null; s.remove(); reject(new Error("The diagram library couldn't load.")); };
    document.head.append(s);
  });
}

function cleanSvg(svg) {
  // Mermaid's own sanitising (securityLevel strict) runs first; this is the second line of defence.
  // Its <style> is kept for the colours, without anything that could fetch from elsewhere.
  const frag = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true }, ADD_TAGS: ['style'],
    FORBID_TAGS: ['foreignObject', 'a', 'image', 'use'], RETURN_DOM_FRAGMENT: true });
  for (const style of frag.querySelectorAll('style')) style.textContent = safeCss(style.textContent);
  for (const node of frag.querySelectorAll('*')) {
    for (const { name, value } of [...node.attributes]) {
      if (name === 'style') node.setAttribute('style', safeCss(value));
      else if (/url\s*\(|\\/i.test(value) && !/^\s*url\(\s*['"]?#[\w-]+['"]?\s*\)\s*$/.test(value)) node.removeAttribute(name);
    }
  }
  const box = document.createElement('div');
  box.append(frag);
  return box.innerHTML;
}

/** CSS with nothing that can load from elsewhere: escapes are decoded first (so u\72l( can't hide a url),
 *  then @import, @font-face and every image function except a link to something inside the diagram go. */
function safeCss(css) {
  return css
    .replace(/\\([0-9a-f]{1,6})[ \t\r\n\f]?/gi, (_, h) => { const cp = parseInt(h, 16); return cp && cp <= 0x10ffff ? String.fromCodePoint(cp) : '�'; })
    .replace(/\\([\s\S])/g, '$1')
    .replace(/@import[^;]*;?/gi, '')
    .replace(/@font-face\s*\{[^}]*\}/gi, '')
    .replace(/(?:-webkit-)?(?:url|image-set|image|cross-fade|element)\(\s*(?!['"]?#[\w-]+['"]?\s*\))[^)]*\)/gi, 'none');
}

/** Flowcharts only: put each node's label in double quotes, so brackets and colons inside it are read as text.
 *  Used only after a diagram has failed to draw, so it can't break one that works. */
function quoteLabels(src) {
  const lines = src.split('\n');
  if (!/^\s*(flowchart|graph)\b/.test(lines[0] || '')) return null;
  const OPEN = '[({', CLOSE = '])}';
  return lines.map((line, n) => {
    if (!n || /^\s*(classDef|class|style|linkStyle|click|%%)/.test(line)) return line;
    let out = '', i = 0;
    while (i < line.length) {
      const ch = line[i];
      if (ch === '|') {                                    // text on an arrow: leave it alone
        const j = line.indexOf('|', i + 1);
        if (j < 0) return out + line.slice(i);
        out += line.slice(i, j + 1); i = j + 1; continue;
      }
      if (!OPEN.includes(ch) || !/[\w-]$/.test(out)) { out += ch; i++; continue; }
      let depth = 0, j = i;                                // the matching close, counting every kind of bracket
      for (; j < line.length; j++) {
        if (OPEN.includes(line[j])) depth++;
        else if (CLOSE.includes(line[j]) && --depth === 0) break;
      }
      if (j >= line.length) return out + line.slice(i);
      let k = 0;                                           // [[ (( ([ shapes open with more than one bracket
      while (k < 3 && OPEN.includes(line[i + k]) && CLOSE.includes(line[j - k])) k++;
      const inner = line.slice(i + k, j - k + 1).trim();
      const label = /^".*"$/.test(inner) ? inner : `"${inner.replace(/"/g, '#quot;')}"`;
      out += line.slice(i, i + k) + label + line.slice(j - k + 1, j + 1);
      i = j + 1;
    }
    return out;
  }).join('\n');
}

/** Sequence diagrams: a ; inside a message or note ends the line there ("SYN-ACK; open" breaks the diagram).
 *  Write each as #59;, which draws as ;, and drop one that only ends a line. Used only after a diagram has failed
 *  to draw, like quoteLabels. */
function escapeSemicolons(src) {
  const lines = src.split('\n');
  if (!/^\s*sequenceDiagram\b/.test(lines[0] || '')) return null;
  return lines.map((line, n) => {
    const at = line.indexOf(':');
    if (!n || at < 0) return line;
    const text = line.slice(at + 1).replace(/(#\w+;)|;(\s*)$|;/g, (m, entity, end) => entity || (end === undefined ? '#59;' : ''));
    return line.slice(0, at + 1) + text;
  }).join('\n');
}

async function drawDiagram(el) {
  const code = $('code', el);
  if (!code) return;
  const src = code.textContent, dark = document.documentElement.dataset.mode === 'dark';
  const key = `${dark}\n${src}`;
  el.dataset.drawn = '1';
  let result = DIAGRAMS.get(key);
  if (!result) {
    el.classList.add('drawing');
    const render = async text => {
      const id = `diagram${++diagramCount}`;
      let mermaid;
      try { mermaid = await loadMermaid(); }
      catch (e) { return { error: e.message, transient: true }; }   // not the diagram's fault: don't remember it
      try {
        mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: dark ? 'dark' : 'neutral',
          htmlLabels: false, flowchart: { htmlLabels: false }, maxTextSize: 20000, maxEdges: 300,
          fontFamily: getComputedStyle(document.body).fontFamily });
        return { svg: cleanSvg((await mermaid.render(id, text)).svg) };
      } catch (e) {
        // Mermaid's message: "Parse error on line 2:", the line, a pointer, then "Expecting …": keep the first and last
        const lines = String(e?.message || e || 'unknown problem').split('\n').map(x => x.trim()).filter(Boolean);
        return { error: [...new Set([lines[0], lines[lines.length - 1]])].join(' ').slice(0, 240) };
      } finally {
        document.getElementById(id)?.remove();           // mermaid can leave its working copy behind
        document.getElementById('d' + id)?.remove();
      }
    };
    result = await render(src);
    // Small models often leave brackets unquoted inside labels (A[Stack: [5]]), or put a ; in a sequence diagram's
    // message: try again with that tidied
    const repairs = [[quoteLabels, 'labels put in quotes'], [escapeSemicolons, 'semicolons in its text escaped']];
    for (const [repair, note] of result.error ? repairs : []) {
      const fixed = repair(src);
      if (!fixed || fixed === src) continue;
      const second = await render(fixed);
      if (second.svg) { result = { ...second, source: fixed, note }; break; }
    }
    if (!result.transient) DIAGRAMS.set(key, result);
  }
  if (!el.isConnected) return;
  el.classList.remove('drawing');
  const source = `<details class="diagram-src"><summary>Diagram source${result.source ? ` (${result.note} so it could be drawn)` : ''}</summary>
    <pre class="chat-code"><code>${esc(result.source || src)}</code></pre></details>`;
  if (result.svg) {
    el.innerHTML = `<div class="diagram-svg">${result.svg}</div>${source}`;
    $('svg', el)?.setAttribute('role', 'img');
  } else {
    const inChat = el.closest('.chat-msg.ai');
    el.innerHTML = `<div class="chat-error">${icon('alert', 15)}<span>This diagram couldn't be drawn: ${esc(result.error)}</span>
      ${result.transient ? `<button class="btn btn-ghost btn-sm" data-action="diagram-redraw">${icon('repeat', 14)}Try again</button>`
        : inChat ? `<button class="btn btn-ghost btn-sm" data-action="diagram-retry">${icon('repeat', 14)}Try again</button>` : ''}</div>
      <pre class="chat-code"><code>${esc(src)}</code></pre>`;
    el.dataset.error = result.error;
  }
}

function enhanceRich(root = document) {
  for (const pre of $$('.chat-text pre.chat-code', root)) {
    if (pre.parentElement.classList.contains('code-wrap') || pre.closest('.chat-diagram')) continue;
    const lang = ($('code', pre)?.className.match(/language-([\w+#-]+)/) || [])[1] || '';
    const wrap = document.createElement('div');
    wrap.className = 'code-wrap';
    wrap.innerHTML = `<div class="code-head"><span>${esc(lang)}</span><button class="btn btn-ghost btn-sm keep-label" type="button" data-action="code-copy">${icon('copy', 13)}Copy</button></div>`;
    pre.replaceWith(wrap);
    wrap.append(pre);
  }
  // Diagrams wait until the reply has finished arriving (half a diagram can't be drawn)
  for (const el of $$('.chat-diagram:not([data-drawn])', root)) {
    if (!el.closest('.live')) drawDiagram(el);
  }
}

// Replies and notes appear through several paths (chat, panel, notes, the topic preview): catch them all here
new MutationObserver(() => {
  if (enhanceRich.queued) return;
  enhanceRich.queued = requestAnimationFrame(() => { enhanceRich.queued = 0; enhanceRich(); });
}).observe(document.body, { childList: true, subtree: true });

/** A new GitHub issue for reporting a reply. Nothing from the chat goes in the address (GitHub would receive it as
 *  the page opens): clicking Report copies the reply, for the student to paste in if they choose (see the click
 *  listener below). Only the model, mode and version are filled in. */
function chatReportUrl() {
  const c = chatState();
  const body = `**What was wrong with this response?**\n\n(describe it here)\n\n**The response**\n\n` +
    `(Report copied it for you: paste it here if you'd like to include it, and remove anything private.)\n\n---\n` +
    `Model: ${state.ai?.model || '?'} (${state.ai?.provider || '?'}), mode: ${c.code ? 'code' : c.mode}, EasyUniTrack ${state.info.version || ''}`;
  return `https://github.com/Mysteryman4k/lifeplanner/issues/new?labels=ai-response&title=${encodeURIComponent('Report an AI response')}&body=${encodeURIComponent(body)}`;
}

function chatMessage(m, i) {
  if (m.role === 'user') {
    const sent = m.files ? `<div class="chat-sent">${m.files.length ? `Sent with this: ${m.files.map(p =>
        `<button class="link-btn" data-action="code-open" data-path="${esc(p)}">${esc(p)}</button>`).join(', ')}` : 'No files were sent with this.'}
      ${(m.leftOut || []).map(x => `<span class="muted" title="${esc(x.why)}">· not sent: ${esc(x.path)}</span>`).join(' ')}</div>` : '';
    // Plain text keeps its spacing, so a pasted traceback or code keeps its indentation
    const body = m.content.includes('```') ? `<div class="chat-text">${chatMarkdown(m.content)}</div>` : `<span class="chat-plain">${esc(m.content)}</span>`;
    return `<div class="chat-msg me">${body}</div>${sent}`;
  }
  const c = chatState();
  const live = c.streaming && i === c.messages.length - 1;
  const last = !live && i === c.messages.length - 1 && !c.streaming;
  return `<div class="chat-msg ai ${live ? 'live' : ''} ${last ? 'last' : ''}" data-i="${i}">
    <div class="chat-text">${m.content ? chatMarkdown(m.content) : (live ? `<span class="chat-typing" aria-label="Thinking"><i></i><i></i><i></i></span>${c.file ? '<span class="muted small"> Reading the file…</span>'
      : m.think ? '<span class="muted small"> Thinking first…</span>' : ''}` : '')}</div>
    ${(m.cards || []).map((card, n) => chatCard(card, i, n)).join('')}
    ${m.error ? `<div class="chat-error">${icon('alert', 15)}${esc(m.error)}</div>` : ''}
    ${m.stopped ? '<div class="small muted">Stopped.</div>' : ''}
    ${last && c.mode === 'quiz' && !c.code ? quizChoices(m.content) : ''}
    ${!live && m.content ? `<div class="chat-tools">
      <button class="icon-btn sm" data-action="chat-copy" data-i="${i}" aria-label="Copy" title="Copy">${icon('copy', 15)}</button>
      <button class="icon-btn sm" data-action="chat-save-note" data-i="${i}" aria-label="Save as note" title="Save as note">${icon('subjects', 15)}</button>
      ${c.code ? '' : `<button class="icon-btn sm" data-action="chat-videos" data-i="${i}" aria-label="Videos" title="Videos: YouTube searches for this topic">${icon('play', 15)}</button>`}
      <a class="icon-btn sm chat-report" data-i="${i}" href="${esc(chatReportUrl())}" target="_blank" rel="noopener" aria-label="Report" title="Report this reply on GitHub (the reply is copied for you to paste in)">${icon('flag', 15)}</a>
      ${last ? `<select class="select select-sm chat-reformat" aria-label="Show this again in another format"><option value="">Show as…</option>
        ${Object.entries(FORMAT_ASK).map(([k]) => `<option value="${k}">${CHAT_FORMATS[k]}</option>`).join('')}</select>` : ''}</div>` : ''}
  </div>`;
}

function chatShell(inPanel) {
  const c = chatState(), a = state.ai || {};
  const ready = a.provider && a.model;
  const task = c.taskId && state.tasks.find(t => t.id === c.taskId);
  const folder = c.code && codeFolder();
  const modes = folder
    ? `<div class="chat-quick" role="group" aria-label="Quick actions">
        <button class="chip" data-action="code-explain-error" ${c.streaming ? 'disabled' : ''}>${icon('alert', 13)}Explain the error</button>
        <button class="chip" data-action="code-debug" ${c.streaming ? 'disabled' : ''}>${icon('search', 13)}Debug</button>
        ${CODE_ACTIONS.map(([kind, label, ic, title]) => `<button class="chip" data-action="code-action" data-kind="${kind}" title="${esc(title)}" ${c.streaming ? 'disabled' : ''}>${icon(ic, 13)}${kind === 'tests' && folder.mode === 'assignment' ? 'Plan tests' : label}</button>`).join('')}</div>`
    : `<div class="segmented" role="group" aria-label="Study mode">${Object.entries(CHAT_MODES).map(([k, v]) =>
        `<button class="${c.mode === k ? 'on' : ''}" data-action="chat-mode" data-mode="${k}" ${c.streaming ? 'disabled' : ''}>${v}</button>`).join('')}</div>`;
  const intro = !c.messages.length ? (folder ? `<div class="chat-empty">
      <h3>Ask about your code</h3>
      <p class="muted small">${folder.mode === 'personal'
        ? 'Personal project: the assistant explains problems and shows fixes straight away.'
        : 'Assignment: the assistant points at the problem and asks guiding questions, so the work stays yours.'}
        Paste an error and click Explain the error, or ask anything about the open file.</p></div>` : `<div class="chat-empty">
      <h3>${task ? 'What would you like help with?' : 'Ask about anything in your units'}</h3>
      <p class="muted small">${CHAT_MODE_HELP[c.mode] || CHAT_MODE_HELP.explain}</p>
      ${task ? '' : `<div class="chat-ideas">${CHAT_IDEAS.map(x => `<button class="chat-idea" data-action="chat-idea">${esc(x)}</button>`).join('')}</div>`}
    </div>`) : '';
  const cloud = folder && a.provider && a.provider !== 'ollama'
    ? `<div class="code-cloud-note">${icon('shield', 14)}<span>Code you send goes to ${esc(a.providers?.[a.provider]?.name || a.provider)}. To keep it on this PC, use Ollama in Settings.</span></div>` : '';
  if (!ready) return `<div class="card chat-setup">${emptyState('spark', 'Choose an AI provider first',
    'Pick a provider and model in Settings, then come back here.', '<a class="btn btn-primary" href="#/settings">Open Settings</a>')}</div>`;
  return `
    <div class="chat ${inPanel ? 'in-panel' : ''}">
      <div class="chat-bar">
        ${modes}
        <select class="select select-sm" id="chatFormat" aria-label="Format of replies" ${c.streaming ? 'disabled' : ''}>
          ${Object.entries(CHAT_FORMATS).map(([k, v]) => opt(k, v, c.format)).join('')}</select>
        <span class="spacer"></span>
        <span class="chat-meta" title="Tokens used in this chat (billed by cloud providers)">${esc(a.model)} · <span id="chatTokens">${c.tokens.toLocaleString()}</span> tokens</span>
      </div>
      ${task ? `<div class="chat-attached">${icon('tasks', 15)}<div><b>${esc(task.title)}</b><span class="muted small">${[task.subject_name, task.due_date ? 'due ' + fmt(task.due_date, { weekday: 'short', day: 'numeric', month: 'short' }) : ''].filter(Boolean).map(esc).join(' · ')}</span></div></div>` : ''}
      <div class="chat-log" id="chatLog" aria-live="polite">${intro}${c.summary && chatConversation().some(m => m.summarised) ? `<details class="chat-summary">
          <summary>${icon('chevronRight', 14, 'chat-summary-mark')}Earlier messages are summarised for the assistant</summary><div class="chat-text">${chatMarkdown(c.summary)}</div></details>` : ''}${c.messages.map(chatMessage).join('')}</div>
      ${folder ? codeSendList() + cloud : ''}
      ${chatFileChip()}
      <form class="composer" id="chatForm">
        <div class="composer-row">${folder ? '<span class="composer-prompt" aria-hidden="true">&gt;</span>' : ''}
          <textarea class="composer-input" id="chatInput" rows="1" maxlength="20000" placeholder="${folder ? 'Ask about this code, or paste an error message' : task ? 'Ask about this task' : c.file ? 'Ask about the attached file' : 'Ask a question, or paste something to work through'}" aria-label="Message" ${c.streaming ? 'disabled' : ''}></textarea></div>
        <div class="composer-bar">
          <button class="icon-btn sm chat-attach" type="button" data-action="chat-attach" aria-label="Attach a file" title="Attach a PDF, PowerPoint (.pptx), Word (.docx) or text file. You can also drop one here." ${c.streaming || c.attaching ? 'disabled' : ''}>${icon('paperclip', 16)}</button>
          <input type="file" id="chatFile" accept="${onPhone() ? `${FILE_TYPES},${PHONE_CODE_TYPES}` : FILE_TYPES}" hidden>
          ${a.can_think ? `<button class="think-toggle ${a.think ? 'on' : ''}" type="button" data-action="chat-think" aria-pressed="${a.think ? 'true' : 'false'}"
            title="${a.think ? 'Think first is on: the model thinks before it answers. Slower, and can help with hard maths and debugging. Click for quick replies.'
              : 'Quick replies. Click to let the model think before it answers: slower, and can help with hard maths and debugging.'}" ${c.streaming || state.thinkSaving ? 'disabled' : ''}>${icon('bulb', 14)}Think</button>` : ''}
          <span class="composer-hint">Enter to send · Shift+Enter for a new line</span>
          ${c.streaming
            ? `<button class="send-btn stop" type="button" data-action="chat-stop" aria-label="Stop" title="Stop">${icon('stop', 15)}</button>`
            : `<button class="send-btn" type="submit" aria-label="Send" title="Send" ${chatFileBlocked() ? 'disabled' : ''}>${icon('up', 16)}</button>`}
        </div>
      </form>
      <div class="chat-foot">Preview. The assistant can be wrong: check important answers against your unit material.</div>
    </div>`;
}

function chatRoot() { return $('#drawer:not([hidden]) .chat') || $('#content .chat'); }

function chatAfterRender() {
  const log = $('#chatLog', chatRoot() || document);
  if (log) log.scrollTop = log.scrollHeight;
  if (!chatState().streaming) setTimeout(() => $('#chatInput', chatRoot() || document)?.focus(), 30);
}

function chatRefresh({ keepDraft = false } = {}) {
  const root = chatRoot();
  if (!root) return;
  const draft = keepDraft ? $('#chatInput', root)?.value : '';      // attaching a file keeps what was typed
  root.outerHTML = chatShell(root.classList.contains('in-panel'));
  const box = draft && $('#chatInput', chatRoot());
  if (box && !box.disabled) box.value = draft;
  chatAfterRender();
}

function chatUpdateLast() {
  const c = chatState(), i = c.messages.length - 1, root = chatRoot();
  const el = root && $(`.chat-msg.ai[data-i="${i}"]`, root);
  if (!el) return;
  el.outerHTML = chatMessage(c.messages[i], i);
  const log = $('#chatLog', root);
  if (log && log.scrollHeight - log.scrollTop - log.clientHeight < 160) log.scrollTop = log.scrollHeight;
  const tok = $('#chatTokens', root);
  if (tok) tok.textContent = c.tokens.toLocaleString();
}


/** POST to /api/ai/chat and call onEvent for each event ({type: text|usage|error|done}).
 *  onEvent returning false stops reading. Throws with a readable message if the request is refused. */
async function streamChat(payload, signal, onEvent) {
  const res = await fetch('/api/ai/chat', {
    method: 'POST', signal,
    headers: { 'Content-Type': 'application/json', 'X-EasyUniTrack-Token': APP_TOKEN },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let msg = `Something went wrong (${res.status})`;
    try {
      const e = await res.json();
      if (typeof e.detail === 'string') msg = e.detail;
      else if (Array.isArray(e.detail) && e.detail[0]) msg = `${(e.detail[0].loc || []).slice(-1)[0] || 'request'}: ${e.detail[0].msg}`;
    } catch (_) { /* keep default */ }
    throw new Error(msg);
  }
  const reader = res.body.getReader(), dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buf += dec.decode(value, { stream: true });
    let cut;
    while ((cut = buf.indexOf('\n\n')) >= 0) {
      const line = buf.slice(0, cut).trim();
      buf = buf.slice(cut + 2);
      if (line.startsWith('data:') && onEvent(JSON.parse(line.slice(5))) === false) { reader.cancel(); return; }
    }
  }
}

async function chatSend(text, extra = {}) {
  const c = chatState();
  text = text.trim();
  if (!text || c.streaming || c.attaching) return;
  if (chatFileBlocked()) { toast('Choose fewer pages or slides of the attached file first.', 'error'); return; }
  const folderId = c.code;
  const run = {};                              // this send; a reset (New chat, another folder or task) replaces it
  const current = () => c.run === run;
  if (folderId) {
    if (c.preparing) return;
    c.preparing = true;
    c.run = run;
    try { await codeChoose(text); }            // add files named in the message (an error's traceback, say)
    finally { c.preparing = false; }
    if (c.streaming || c.code !== folderId || !current()) return;
    codeMarkErrors(text);
  }
  const think = !!(state.ai?.can_think && state.ai?.think);        // the Think toggle; quick replies otherwise
  c.messages.push({ role: 'user', content: text }, { role: 'assistant', content: '', ...(think ? { think } : {}) });
  const asked = c.messages[c.messages.length - 2];
  c.streaming = true;
  c.controller = new AbortController();
  c.run = run;                                 // a newer chat (New chat, another task) takes over the state
  chatRefresh();
  const reply = c.messages[c.messages.length - 1];
  let tasksChanged = false;
  if (c.summaryRun) {                          // older messages being summarised: wait, so this question has it
    await c.summaryRun;
    if (!current()) return;
  }
  // Everything the summary doesn't cover goes with the question: the last CHAT_WINDOW messages, and any older
  // ones not summarised yet (the next summary is due, or the last one failed), up to CHAT_MAX
  const convo = chatConversation();              // not the reply being written (it's empty)
  let history = convo.filter(m => !m.summarised).map(m => ({ role: m.role, content: m.content })).slice(-CHAT_MAX);
  while (history.length && history[0].role !== 'user') history = history.slice(1);   // same window as the server
  try {
    const file = c.file ? { attachment: { name: c.file.name, included: chatFileIncluded(c.file), text: chatFileText(c.file) } } : {};
    if (c.summary && convo.some(m => m.summarised)) file.summary = c.summary;   // in place of the summarised ones
    const payload = folderId
      ? { mode: 'code', format: c.format || 'auto', messages: history, think, ...file,
          code: { folder_id: folderId, files: (codeState().files || []).map(f => f.path), ...extra } }
      : { mode: extra.mode || c.mode, format: c.format || 'auto', messages: history, think, ...file, ...(c.taskId ? { task_id: c.taskId } : {}), ...(extra.action ? { action: extra.action } : {}) };
    await streamChat(payload, c.controller.signal, ev => {
      if (!current()) return false;
      if (ev.type === 'files') { asked.files = ev.files; asked.leftOut = ev.left_out; chatRefresh(); return true; }
      if (ev.type === 'text') reply.content += ev.text;
      else if (ev.type === 'usage') c.tokens += (ev.input || 0) + (ev.output || 0);
      else if (ev.type === 'error') reply.error = ev.message;
      else if (ev.type === 'action') { (reply.cards ||= []).push({ kind: 'action', id: ev.action_id, summary: ev.summary, status: 'done' }); tasksChanged = true; }
      else if (ev.type === 'run_suggestion') (reply.cards ||= []).push({ kind: 'run', command: ev.command, why: ev.why, status: 'pending' });
      else if (ev.type === 'change') {           // a proposed file change (a second edit to the same file updates its card)
        const cards = reply.cards ||= [], card = { kind: 'change', id: ev.change_id, path: ev.path, summary: ev.summary, newFile: ev.new_file, diff: ev.diff, status: 'proposed' };
        const same = cards.find(x => x.kind === 'change' && x.id === ev.change_id);
        if (same) Object.assign(same, card); else cards.push(card);
      }
      else if (ev.type === 'confirm') (reply.cards ||= []).push({ kind: 'confirm', id: ev.action_id, items: ev.items, danger: ev.danger, status: 'pending' });
      chatUpdateLast();
      return true;
    });
  } catch (e) {
    if (!current()) return;                    // replaced by a newer chat: leave its state alone
    if (e.name === 'AbortError') reply.stopped = true;
    else reply.error = e.message;
  }
  if (!current()) return;
  c.streaming = false;
  c.controller = null;
  c.run = null;
  if (tasksChanged) await reloadTasks();
  chatRefresh();
  chatSave();
  chatSummarise();
}

// ── Long chats: messages older than the last CHAT_WINDOW are folded into a running summary (every few turns,
// after a reply), and the summary goes with each question in their place ──
const CHAT_WINDOW = 20;                          // always sent as they are
const CHAT_MAX = 40;                             // MAX_HISTORY in ai/routes.py: the window and any not yet summarised
const SUMMARY_EVERY = 6;                         // messages left out of the window before the summary is updated
const SUMMARY_BATCH = 60;                        // messages folded in at a time (the server takes up to 200)

/** The messages that count as the conversation (not empty replies or errors), as the server sees them. */
function chatConversation() { return chatState().messages.filter(m => m.content && !m.error); }

function chatSummarise() {
  const c = chatState();
  if (c.summarising || c.streaming) return;
  const run = chatSummariseNow(c);                 // never rejects: a failed summary is tried again later
  c.summaryRun = run;                              // a question asked meanwhile waits for it (chatSend)
  run.finally(() => { if (c.summaryRun === run) c.summaryRun = null; });
}

async function chatSummariseNow(c) {
  const session = c.session;
  c.summarising = true;
  try {
    for (;;) {                                    // a long chat from before summaries goes in batches, oldest first
      const fresh = chatConversation().slice(0, -CHAT_WINDOW).filter(m => !m.summarised);
      if (fresh.length < SUMMARY_EVERY) break;
      const batch = fresh.slice(0, SUMMARY_BATCH);
      const r = await api('/api/ai/summarise', { method: 'POST', body: { kind: c.code ? 'code' : 'study', previous: c.summary || '',
        messages: batch.map(m => ({ role: m.role, content: m.content.slice(0, 20000) })) } });
      if (c.session !== session) return;          // another chat since
      c.summary = r.summary;
      batch.forEach(m => { m.summarised = true; });
      c.tokens += r.tokens || 0;
      if (!c.streaming) chatRefresh({ keepDraft: true });    // shows the summary note (a reply streaming redraws anyway)
      chatSave();
    }
  } catch (_) {
    // Tried again after the next reply; meanwhile the messages it would have covered go with each question
  } finally {
    if (c.session === session) c.summarising = false;
  }
}

async function reloadTasks() {
  try {
    state.tasks = await api('/api/tasks');
    // Redraw the page under the side panel; the Study page has no task list (and redrawing it would clear the input)
    if (route() === 'study') renderNav(); else stillRender();
    return true;
  } catch (_) {
    toast("The change was made, but the task list couldn't refresh. Reload the page to see it.", 'error');
    return false;
  }
}

function changeCard(card, ref) {
  const sign = { '+': 'add', '-': 'del', '@': 'hunk' };
  const diff = `<div class="diff" role="group" aria-label="Changes to ${esc(card.path)}">${card.diff.map(d =>
    `<div class="diff-line ${sign[d.t] || ''}"><span class="diff-sign" aria-hidden="true">${d.t === '@' ? '' : esc(d.t)}</span><span>${esc(d.s) || ' '}</span></div>`).join('')}</div>`;
  const busy = card.busy ? 'disabled' : '';
  const state = {
    proposed: `<div class="chat-card-btns"><button class="btn btn-ghost btn-sm" data-action="code-change-dismiss" ${ref} ${busy}>Dismiss</button>
        <button class="btn btn-primary btn-sm" data-action="code-change-apply" ${ref} ${busy}>${icon('check', 14)}Apply</button></div>`,
    applied: `<div class="change-status ok">${icon('check', 14)}<span>Applied. The original is backed up.</span>
        <button class="btn btn-ghost btn-sm keep-label" data-action="code-change-undo" ${ref} ${busy}>${icon('repeat', 14)}Undo</button></div>`,
    undone: `<div class="change-status">${icon('repeat', 14)}<span>Undone. ${card.newFile ? 'The new file was removed.' : 'The file is back exactly as it was.'}</span></div>`,
    dismissed: `<div class="change-status">${icon('x', 14)}<span>Dismissed. Nothing was changed.</span></div>`,
    stale: `<div class="change-status warn">${icon('alert', 14)}<span>The file changed after this was proposed, so it wasn't applied. Ask for a fresh change.</span></div>`,
  }[card.status] || '';
  const open = card.status === 'proposed' || card.status === 'applied';
  return `<div class="chat-card change-card ${card.status}">
      <div class="change-head">${icon('file', 15)}<button class="link-btn" data-action="code-open" data-path="${esc(card.path)}">${esc(card.path)}</button>
        ${card.newFile ? '<span class="pill">New file</span>' : ''}<span class="muted small change-summary">${esc(card.summary)}</span></div>
      ${open ? diff : `<details class="change-more"><summary>Show the change</summary>${diff}</details>`}
      ${state}</div>`;
}

function chatCard(card, i, n) {
  const ref = `data-i="${i}" data-c="${n}"`;
  if (card.kind === 'change') return changeCard(card, ref);
  if (card.kind === 'run') {
    return `<div class="chat-card run-card ${card.status}">${icon('code', 15)}<div class="chat-card-text">
        <b>${card.status === 'ran' ? 'Ran' : card.status === 'cancelled' ? 'Not run' : 'Run this?'}</b>${card.why ? ` <span class="muted small">${esc(card.why)}</span>` : ''}
        <pre class="chat-code run-suggestion"><code>${esc(card.command)}</code></pre>
        ${card.status === 'pending' ? '<span class="muted small">It runs only if you click Run.</span>' : ''}</div>
      ${card.status === 'pending' ? `<div class="chat-card-btns"><button class="btn btn-ghost btn-sm" data-action="run-suggest-cancel" ${ref} ${card.busy ? 'disabled' : ''}>Cancel</button>
        <button class="btn btn-primary btn-sm" data-action="run-suggest-run" ${ref} ${card.busy ? 'disabled' : ''}>${icon('up', 14)}${card.busy ? 'Starting…' : 'Run'}</button></div>` : ''}</div>`;
  }
  if (card.kind === 'action' || card.status === 'approved' || card.status === 'undone') {
    const undone = card.status === 'undone';
    const title = card.kind === 'action' ? esc(card.summary) : `Done: ${card.items.map(esc).join('; ')}`;
    return `<div class="chat-card ${undone ? 'muted-card' : 'ok'}">${icon(undone ? 'x' : 'check', 15)}
      <span class="chat-card-text">${undone ? `Undone · <s>${title}</s>` : title}</span>
      ${undone ? '' : `<button class="btn btn-ghost btn-sm keep-label" data-action="chat-undo" ${ref} ${card.busy ? 'disabled' : ''}>${icon('repeat', 14)}Undo</button>`}</div>`;
  }
  if (card.status === 'rejected') {
    return `<div class="chat-card muted-card">${icon('x', 15)}<span class="chat-card-text">Left as it was · <s>${card.items.map(esc).join('; ')}</s></span></div>`;
  }
  const busy = card.busy ? 'disabled' : '';
  return `<div class="chat-card ${card.danger ? 'danger' : 'warn'}">
      ${icon('alert', 15)}<div class="chat-card-text"><b>${card.danger ? 'Delete this?' : 'Make these changes?'}</b>
      <ul>${card.items.map(x => `<li>${esc(x)}</li>`).join('')}</ul>
      <span class="muted small">The assistant asked for ${card.items.length > 1 ? 'these changes' : 'this'}. Nothing happens unless you say so.</span></div>
      <div class="chat-card-btns">
        <button class="btn btn-ghost btn-sm" data-action="chat-confirm" data-approve="0" ${ref} ${busy}>${card.danger ? 'Keep' : 'Not now'}</button>
        <button class="btn btn-sm ${card.danger ? 'btn-danger' : 'btn-primary'}" data-action="chat-confirm" data-approve="1" ${ref} ${busy}>${card.danger ? 'Delete' : 'Do it'}</button>
      </div></div>`;
}

let chatOpening = 0;                             // the latest chat asked for: a slower, older one is ignored

/** A fresh chat. Any chat still being opened is cancelled (New chat, another task, Remove all AI data),
 *  except when chatOpen itself resets on the way to showing the chat it opened (fromOpen). */
function chatReset(taskId = null, code = null, fromOpen = false) {
  if (!fromOpen) chatOpening++;
  const c = chatState();
  c.controller?.abort();                       // stop any reply still streaming for the old chat
  // A new session: saves still queued for the chat that was showing can't touch this one (chatSave)
  Object.assign(c, { id: null, session: {}, messages: [], tokens: 0, taskId, code, streaming: false, controller: null, run: null, file: null, attaching: null,
    summary: '', summarising: false, summaryRun: null });
}

// ── Saved chats: kept after each reply, listed under Recent chats, and opened again ──
async function loadChats() {
  try { state.chats = await api('/api/ai/chats?limit=30'); } catch (_) { state.chats = state.chats || []; }
  renderNav();
}

function recentChats() {
  const chats = (state.chats || []).filter(ch => ch.kind === 'code' ? codeOn() : aiOn()).slice(0, 5);
  if (!chats.length) return '';
  const open = chatState().id;
  return `<div class="nav-chats" aria-label="Recent chats">${chats.map(ch =>
    `<button class="nav-chat ${ch.id === open ? 'on' : ''}" data-action="chat-open" data-id="${ch.id}" title="${esc(ch.title)}">${icon(ch.kind === 'code' ? 'code' : 'spark', 13)}<span>${esc(ch.title || 'Chat')}</span></button>`).join('')}
    <button class="nav-chat more" data-action="chats-all">All chats…</button></div>`;
}

/** Save the chat as it is now (after a reply, or when a card changes). One save at a time, newest wins. */
const CHAT_SAVE_MAX = 400;                       // MAX_MESSAGES in ai/chats.py

function chatSave() {
  if (chatSave.blocked) return Promise.resolve();  // Remove all AI data is running
  const c = chatState();
  // The newest 400 (the server's limit): a very long chat keeps saving, without its oldest messages
  const messages = c.messages.filter(m => m.content || m.cards?.length || m.error).slice(-CHAT_SAVE_MAX).map(m => ({
    role: m.role, content: m.content || '',
    meta: Object.fromEntries(Object.entries({ cards: m.cards?.map(({ busy, ...card }) => card), files: m.files,
      leftOut: m.leftOut, error: m.error, stopped: m.stopped, summarised: m.summarised }).filter(([, v]) => v !== undefined && v !== null && v !== false)),
  }));
  if (!messages.some(m => m.role === 'user')) return Promise.resolve();
  const fileText = c.file ? chatFileText(c.file) : '';
  const body = { kind: c.code ? 'code' : 'study', mode: c.code ? 'code' : c.mode, format: c.format || 'auto',
    task_id: c.taskId || null, folder_id: c.code || null, tokens: c.tokens || 0, messages, summary: c.summary || '',
    attachment: fileText ? { name: c.file.name, kind: c.file.kind || '', included: chatFileIncluded(c.file), text: fileText, chars: fileText.length } : null };
  const chat = c, session = c.session;
  chatSave.queue = (chatSave.queue || Promise.resolve()).then(async () => {
    if (chat.session !== session) return;                // reset, or another chat opened, since this was asked for
    try {
      const saved = chat.id ? await api(`/api/ai/chats/${chat.id}`, { method: 'PUT', body })
        : await api('/api/ai/chats', { method: 'POST', body });
      if (!chat.id && chat.session === session) chat.id = saved.id;
      loadChats();
    } catch (e) {
      // Deleted meanwhile (elsewhere, or by Keep chats): kept as a new chat straight away, so the reply isn't
      // lost if the app closes first. Only for this session: another chat may be open now
      if (/deleted/.test(e.message) && chat.session === session && chat.id) {
        chat.id = null;
        try {
          const saved = await api('/api/ai/chats', { method: 'POST', body });
          // If another chat was opened meanwhile, this conversation is still kept, as its own chat under Recent
          // chats: it's the student's, with the reply this save is for. It just isn't the one on screen any more
          if (chat.session === session) chat.id = saved.id;
          loadChats();
        } catch (_) { /* the next save tries again */ }
      }
    }
  });
  return chatSave.queue;
}

async function chatOpen(id) {
  const asked = ++chatOpening, stale = () => asked !== chatOpening;
  let ch;
  try { ch = await api(`/api/ai/chats/${id}`); } catch (e) { if (!stale()) { toast(e.message, 'error'); loadChats(); } return; }
  if (stale()) return;
  if (ch.kind === 'code') {
    const k = codeState();
    if (!k.folders) await codeLoad();
    if (stale()) return;
    if (!ch.folder_id || !k.folders.some(f => f.id === ch.folder_id)) { toast('That chat\'s folder isn\'t linked any more.', 'error'); return; }
    if (k.folderId !== ch.folder_id) codeSelectFolder(ch.folder_id, true);
    chatReset(null, ch.folder_id, true);
  } else {
    chatReset(ch.task_id, null, true);
  }
  const c = chatState();
  Object.assign(c, { id: ch.id, tokens: ch.tokens, format: ch.format || 'auto',
    mode: ch.kind === 'study' && CHAT_MODES[ch.mode] ? ch.mode : c.mode,
    // The file's text that went with its questions carries on (its other pages aren't kept: attach it again for those)
    file: ch.attachment ? { name: ch.attachment.name, kind: ch.attachment.kind, included: ch.attachment.included, text: ch.attachment.text } : null,
    summary: ch.summary || '',
    messages: ch.messages.map(m => ({ role: m.role, content: m.content, ...m.meta })) });
  closeDrawer();
  const target = ch.kind === 'code' ? '#/code' : '#/study';
  if (location.hash !== target) location.hash = target; else render();
}

function chatList() {
  const chats = state.chats || [];
  const when = s => fmt(s.slice(0, 10), { day: 'numeric', month: 'short' });
  const body = chats.length ? `<div class="chat-list">${chats.map(ch => `<div class="chat-list-row">
      <button class="chat-list-open" data-action="chat-open" data-id="${ch.id}">${icon(ch.kind === 'code' ? 'code' : 'spark', 15)}
        <span><b>${esc(ch.title || 'Chat')}</b><span class="muted small">${esc([ch.kind === 'code' ? ch.folder_name || 'Code workspace' : CHAT_MODES[ch.mode] || 'Study', when(ch.updated_at), `${ch.count} messages`, ch.attachment_name].filter(Boolean).join(' · '))}</span></span></button>
      <button class="icon-btn" data-action="chat-delete" data-id="${ch.id}" aria-label="Delete ${esc(ch.title)}" title="Delete">${icon('trash', 16)}</button></div>`).join('')}</div>`
    : emptyState('spark', 'No saved chats yet', 'Chats are kept here after each reply.');
  openDrawer('Chats', body, '<span class="spacer"></span><button class="btn btn-ghost" type="button" data-action="close-drawer">Close</button>', 'chats');
}

/** A quiz's multiple-choice options (A) … D) on their own lines) as answer buttons. */
function quizChoices(text) {
  const letters = [...new Set([...text.matchAll(/^\s*\**\(?([A-D])[).]\**\s+\S/gm)].map(m => m[1]))];
  if (letters.length < 2) return '';
  return `<div class="quiz-choices" role="group" aria-label="Answer">${letters.map(l =>
    `<button class="btn btn-ghost btn-sm" data-action="chat-answer" data-v="${l}">${l}</button>`).join('')}</div>`;
}

// ── Attached files: a PDF, PowerPoint, Word or text file is read on this PC (ai/files.py), and the text of the
// pages, slides or sections chosen goes with each question ──
const FILE_TYPES = '.pdf,.pptx,.docx,.txt,.md,.markdown';
// On the phone, code files go into a study chat too (the desktop's code workspace links whole folders instead)
const PHONE_CODE_TYPES = '.py,.java,.c,.h,.cpp,.hpp,.cc,.cs,.js,.ts,.jsx,.tsx,.go,.rs,.kt,.swift,.rb,.php,.sql,.html,.css,.json,.xml,.yaml,.yml,.sh,.r,.m,.scala,.dart';
const FILE_MAX = 30 * 1024 * 1024;               // MAX_UPLOAD in ai/files.py
const CHARS_PER_TOKEN = 3.7;                     // for the estimate shown (English prose)
const FILE_ASKS = {
  summary: 'Summarise the attached file: the main ideas in order, with the page, slide or section for each.',
  notes: 'Write study notes on the attached file.',
  quiz: 'Quiz me on the attached file.',
};

/** The text that goes with each question: the chosen parts, each under its label ([Page 3] ...). A reopened
 *  chat has only the text that was chosen then. */
function chatFileText(f) {
  if (!f.parts) return f.text || '';
  return f.parts.slice(f.from, f.to + 1).map(p => `[${p.label}]\n${p.text}`).join('\n\n');
}

/** Which parts are included, in words: "the whole file", "Page 4" or "Pages 4–12". */
function chatFileIncluded(f) {
  if (!f.parts) return f.included || '';
  if (f.to < f.from) return '';
  if (f.from === 0 && f.to === f.parts.length - 1) return 'the whole file';
  const [word, a] = f.parts[f.from].label.split(' '), b = f.parts[f.to].label.split(' ')[1];
  return f.from === f.to ? `${word} ${a}` : `${word}s ${a}–${b}`;
}

/** The last part that fits the provider's budget, going on from part `from` (from - 1 if not even that one fits). */
function chatFileFit(f, from = 0) {
  let to = from - 1, size = -2;
  for (let i = from; i < f.parts.length; i++) {
    size += f.parts[i].label.length + 3 + f.parts[i].text.length + 2;
    if (size > f.budget.chars) break;
    to = i;
  }
  return to;
}

/** True when the chosen parts can't be sent: none fit, or more than the provider reads with one question. */
function chatFileBlocked() {
  const f = chatState().file;
  if (!f) return false;
  const n = chatFileText(f).length;
  return !n || (f.budget && n > f.budget.chars);
}

async function chatAttach(file) {
  const c = chatState(), session = c.session;
  if (!file || c.streaming || c.attaching) return;
  if (file.size > FILE_MAX) { toast('That file is over 30 MB. Attach a smaller file, or just the part you need.', 'error'); return; }
  c.attaching = file.name;
  chatRefresh({ keepDraft: true });
  try {
    const doc = await api(`/api/ai/attach?name=${encodeURIComponent(file.name)}`, { method: 'POST', raw: file });
    if (c.session !== session) return;            // a new chat was started meanwhile
    const f = { ...doc, from: 0, to: doc.parts.length - 1 };
    f.to = Math.min(f.to, chatFileFit(f));        // too long for one question: start with the parts that fit, and say so
    f.trimmed = f.to < doc.parts.length - 1;
    c.file = f;
  } catch (e) {
    if (c.session === session) toast(e.message, 'error');
  } finally {
    if (c.session === session) { c.attaching = null; chatRefresh({ keepDraft: true }); }
  }
}

function chatFileChip() {
  const c = chatState(), f = c.file, a = state.ai || {};
  if (c.attaching) return `<div class="chat-file">${icon('paperclip', 15)}<span class="muted small">Reading ${esc(c.attaching)}…</span></div>`;
  if (!f) return '';
  const text = chatFileText(f), n = text.length, b = f.budget;
  const local = a.provider === 'ollama', who = local ? 'Ollama' : a.provider === 'custom' ? 'this provider' : a.providers?.[a.provider]?.name || 'the assistant';
  const unit = { PDF: 'pages', PowerPoint: 'slides' }[f.kind] || 'sections';
  const notes = [];
  const raise = local && b?.context ? ` To read more at once, raise Context length in Ollama's settings (it's ${b.context.toLocaleString()} tokens now), then attach the file again.` : '';
  if (!n && f.parts) notes.push(['warn', `Even ${f.parts[f.from].label} is more than ${who} can read with one question.${raise}`]);
  else if (b && n > b.chars) notes.push(['warn', `That's more than ${who} can read with one question (about ${b.chars.toLocaleString()} characters). Choose fewer ${unit}.${raise}`]);
  else if (f.trimmed && f.parts && !(f.from === 0 && f.to === f.parts.length - 1)) notes.push(['info', `The whole file is too long for one question, so ${chatFileIncluded(f)} go with it. Choose other ${unit} to ask about the rest.${raise}`]);
  if (local && b?.slow_over && n > b.slow_over && n <= b.chars) notes.push(['info', 'A local model takes a while to read this much: the reply can take a few minutes to start on a PC without a graphics card.']);
  const range = f.parts && f.parts.length > 1 ? `<span class="chat-file-range">
      <select class="select select-sm" data-file-range="from" aria-label="First of the ${unit} to send">${f.parts.map((p, i) => opt(i, p.label, f.from)).join('')}</select>
      <span class="muted small">to</span>
      <select class="select select-sm" data-file-range="to" aria-label="Last of the ${unit} to send">${f.parts.map((p, i) => opt(i, p.label, f.to)).join('')}</select></span>` : '';
  const tokens = Math.max(100, Math.round(n / CHARS_PER_TOKEN / 100) * 100);
  const sendable = n && !(b && n > b.chars);
  return `<div class="chat-file ${sendable ? '' : 'over'}">
      <div class="chat-file-head">${icon('paperclip', 15)}<b title="${esc(f.name)}">${esc(f.name)}</b>
        <span class="muted small">${esc([f.kind, chatFileIncluded(f), n ? `about ${tokens.toLocaleString()} tokens with each question` : ''].filter(Boolean).join(' · '))}</span>
        ${range}
        <button class="icon-btn" type="button" data-action="chat-file-remove" aria-label="Remove the attached file" title="Remove" ${c.streaming ? 'disabled' : ''}>${icon('x', 15)}</button></div>
      ${notes.map(([kind, t]) => `<div class="chat-file-note ${kind}">${icon(kind === 'warn' ? 'alert' : 'clock', 13)}<span>${esc(t)}</span></div>`).join('')}
      ${!c.code && sendable ? `<div class="chat-quick" role="group" aria-label="Use the file">
        <button class="chip" data-action="chat-file-ask" data-kind="summary" ${c.streaming ? 'disabled' : ''}>Summarise</button>
        <button class="chip" data-action="chat-file-ask" data-kind="notes" ${c.streaming ? 'disabled' : ''}>Write notes on this</button>
        <button class="chip" data-action="chat-file-ask" data-kind="quiz" ${c.streaming ? 'disabled' : ''}>Quiz me on this</button></div>` : ''}
    </div>`;
}

// ── Linked folders outside the workspace: on each subject, and in Settings ──
/** Just the list of linked folders (the workspace loads the open folder's files itself). */
async function codeLoadFolders() {
  const k = codeState();
  if (k.loadingFolders || k.folders) return;
  k.loadingFolders = true;
  try { k.folders = await api('/api/code/folders'); } catch (_) { k.folders = []; }
  finally { k.loadingFolders = false; }
  if (route() === 'settings' || route() === 'subjects') stillRender();
}

function subjectCodeBlock(subjectId) {
  if (!codeOn()) return '';
  const k = codeState();
  if (!k.folders) { codeLoadFolders(); return ''; }
  const list = k.folders.filter(f => f.subject_id === subjectId);
  return `<div class="subject-notes subject-code">
      <div class="subject-notes-head"><span>Code folders</span>${list.length ? `<span class="muted small">${list.length}</span>` : ''}<span class="spacer"></span>
        <button class="icon-btn sm" data-action="code-link-subject" data-subject="${subjectId}" title="Link a code folder" aria-label="Link a code folder">${icon('plus', 15)}</button></div>
      ${list.length ? `<div class="note-list">${list.map(f => `<button class="note-row" data-action="code-go" data-id="${f.id}">${icon('folder', 14)}<span class="note-title">${esc(f.name)}</span>
          <span class="muted small">${f.mode === 'personal' ? 'Personal' : 'Assignment'}</span></button>`).join('')}</div>`
        : '<p class="small muted notes-empty">Link the folder with your code for this subject, to get help with it in the code workspace.</p>'}
    </div>`;
}

function codeFoldersSetting() {
  const k = codeState();
  if (!k.folders) codeLoadFolders();
  const list = k.folders || [];
  return `<div class="setting"><div style="flex:1;min-width:0"><div class="setting-title">Linked code folders</div>
      ${list.length ? `<div class="linked-folders">${list.map(f => `<div class="linked-folder">${icon('folder', 15)}
          <button class="link-btn" data-action="code-go" data-id="${f.id}">${esc(f.name)}</button>
          <span class="muted small">${esc([f.subject_name, f.mode === 'personal' ? 'Personal project' : 'Assignment'].filter(Boolean).join(' · '))}</span>
          <button class="icon-btn sm" data-action="code-unlink" data-id="${f.id}" aria-label="Unlink ${esc(f.name)}" title="Unlink (your files aren't touched)">${icon('x', 14)}</button></div>`).join('')}</div>`
        : `<div class="setting-desc">${k.folders ? 'None yet. The assistant only reads folders you link.' : 'Loading…'}</div>`}</div>
    ${btn('code-link', 'Link a folder', 'folder', 'btn-ghost btn-sm keep-label')}</div>`;
}

// ── Code workspace: a linked folder's tree, a file viewer, and the files sent with each question ──
function codeLinkForm(subjectId = null) {
  const radio = (value, title, text, on) => `<label class="radio-card"><input type="radio" name="mode" value="${value}" ${on ? 'checked' : ''}>
      <span><b>${title}</b><span class="muted small">${text}</span></span></label>`;
  const body = `
    <form id="drawerForm" class="form-stack" data-kind="code-folder" autocomplete="off">
      ${field('Folder', `<div class="input-row"><input class="input" name="path" required maxlength="1000" placeholder="C:\\Users\\you\\Documents\\project" autofocus>
        <button class="btn btn-ghost" type="button" data-action="code-browse">${icon('folder', 16)}Browse…</button></div>`)}
      ${field('Subject', `<select class="select" name="subject_id">${noteSubjectOptions(subjectId)}</select>`)}
      <fieldset class="field"><span>How should the assistant help?</span>
        ${radio('assignment', 'Assignment · hints first', 'Points at problems and asks guiding questions. Fixes only when you ask, and small.', true)}
        ${radio('personal', 'Personal project · fix freely', 'Explains problems and shows fixes straight away.', false)}
        <span class="muted small">You can change this later.</span></fieldset>
      <p class="muted small">The assistant only reads this folder. It skips secrets (.env, keys), anything in .gitignore, dependency and build folders, binary files and files over 200 KB. It never changes or runs anything by itself.</p>
    </form>`;
  openDrawer('Link a code folder', body, footer(''), 'code-folder');
}

function codeRender() { $('#content').classList.add('still'); VIEWS.code(); }   // redraw without the page fade

function codeState() {
  return state.code ||= { folders: null, folderId: null, tree: null, treeError: '', expanded: new Set(), open: null,
    files: [], pinned: [], removed: [], marks: {}, baselines: {}, commands: null, cmd: '', keep: false, limit: 30, runs: {},
    // Each folder keeps its own run, so switching folders doesn't lose one that's still going
    get run() { return this.runs[this.folderId] || null; },
    set run(v) { this.runs[this.folderId] = v; } };
}
function codeFolder() { const k = codeState(); return (k.folders || []).find(f => f.id === k.folderId) || null; }

async function codeLoad() {
  const k = codeState();
  try { k.folders = await api('/api/code/folders'); }
  catch (e) { k.folders = []; toast(e.message, 'error'); }
  if (!codeFolder()) k.folderId = k.folders[0]?.id ?? null;
  if (k.folderId) await codeLoadTree(); else if (route() === 'code') codeRender();
}

async function codeLoadTree() {
  const k = codeState(), id = k.folderId;
  k.tree = null; k.treeError = '';
  if (route() === 'code') codeRender();
  try { const tree = await api(`/api/code/folders/${id}/tree`); if (k.folderId === id) k.tree = tree; }
  catch (e) { if (k.folderId === id) k.treeError = e.message; }
  if (k.folderId === id && route() === 'code') codeRender();
  if (k.folderId === id && !k.open) {                                     // the project's own commands, after
    await codeLoadCommands();
    if (k.folderId === id && route() === 'code') codeRunRefresh();
  }
}

function codeSelectFolder(id, fromOpen = false) {
  const k = codeState();
  Object.assign(k, { folderId: id, tree: null, treeError: '', expanded: new Set(), open: null, files: [], pinned: [], removed: [], marks: {},
    commands: null, cmd: '', cmdEdited: false, customRun: false });
  chatReset(null, id, fromOpen);
  codeLoadTree();
}

function codeFiles(nodes = codeState().tree?.children || [], out = []) {
  for (const n of nodes) { if (n.type === 'file' && !n.hidden) out.push(n.path); if (n.children) codeFiles(n.children, out); }
  return out;
}

function codeTreeNodes(nodes, depth = 0) {
  const k = codeState(), sending = new Set(k.files.map(f => f.path));
  return nodes.map(n => {
    const pad = `style="--depth:${depth}"`;
    if (n.hidden) {
      return `<div class="tree-row hidden-row" ${pad} title="Hidden (${esc(n.hidden)}): never read or sent">${icon(n.type === 'dir' ? 'folder' : 'file', 14)}<span class="tree-name">${esc(n.name)}</span><span class="small">(hidden)</span></div>`;
    }
    if (n.type === 'dir') {
      const open = k.expanded.has(n.path);
      return `<button class="tree-row" ${pad} data-action="code-dir" data-path="${esc(n.path)}" aria-expanded="${open}">${icon(open ? 'chevron' : 'right', 13)}${icon('folder', 14)}<span class="tree-name">${esc(n.name)}</span></button>` +
        (open ? codeTreeNodes(n.children || [], depth + 1) : '');
    }
    return `<button class="tree-row ${k.open?.path === n.path ? 'on' : ''}" ${pad} data-action="code-open" data-path="${esc(n.path)}" title="${esc(n.language)}">${icon('file', 14)}<span class="tree-name">${esc(n.name)}</span>${sending.has(n.path) ? '<span class="tree-sending" title="Sent with your next message"></span>' : ''}</button>`;
  }).join('');
}

function codeViewer() {
  const k = codeState(), f = k.open;
  if (!f) return `<div class="code-file-head">${codeFilesToggle()}<span class="muted small">No file open</span></div>` +
    emptyState('file', 'Choose a file', 'Pick a file in the list to read it here. Hidden files stay hidden and are never sent.') + codeRunPanel();
  const lines = f.text.split('\n');
  let html = esc(f.text);
  if (f.highlight && window.hljs?.getLanguage(f.highlight)) {
    try { html = hljs.highlight(f.text, { language: f.highlight, ignoreIllegals: true }).value; } catch (_) { /* stays plain */ }
  }
  const marks = k.marks[f.path] || [];
  const sending = k.files.some(x => x.path === f.path);
  return `<div class="code-file-head">${codeFilesToggle()}<span class="code-tab">${icon('file', 14)}<b class="code-path">${esc(f.path)}</b><span class="pill">${esc(f.language)}</span></span>
      <span class="spacer"></span>
      <button class="btn btn-ghost btn-sm keep-label" data-action="${sending ? 'code-unsend' : 'code-send-open'}" data-path="${esc(f.path)}">${icon(sending ? 'check' : 'plus', 14)}${sending ? 'Sending' : 'Send with question'}</button></div>
    <div class="code-view" id="codeView"><div class="code-lines">
      ${marks.map(n => `<div class="code-mark" style="top:${(n - 1) * 20 + 10}px" title="Line ${n} is in the error"></div>`).join('')}
      <div class="code-gutter" aria-hidden="true">${lines.map((_, i) => `<span class="${marks.includes(i + 1) ? 'marked' : ''}">${i + 1}</span>`).join('')}</div>
      <pre class="code-text"><code class="hljs">${html}</code></pre></div></div>${codeRunPanel()}`;
}

/** Narrow windows hide the file list beside the code: this shows it over the code instead. */
function codeFilesToggle() {
  return `<button class="icon-btn sm files-toggle" data-action="code-files" aria-label="Show files" title="Files">${icon('folder', 15)}</button>`;
}

// ── Running code: the student's click only, in the linked folder, with a time limit and Stop ──
const RUN_LIMITS = [[30, '30 s'], [60, '1 min'], [120, '2 min'], [300, '5 min']];
const ANSI = new RegExp(String.fromCharCode(27) + '\\[[0-9;?]*[A-Za-z]', 'g');

function codeRunPanel() {
  const k = codeState(), run = k.run, cmds = k.commands?.commands || [];
  const running = run?.status === 'running';
  if (!cmds.length && !run && !k.customRun) {
    if (!k.commands) return '<div class="code-run"></div>';             // filled in when the commands arrive
    if (k.commands.kind === 'none' && !k.open) {                        // nothing to go on yet: not a limitation
      return `<div class="code-run"><div class="run-bar explain-bar neutral">${icon('terminal', 15)}
        <span>Open a file to see how to run it.</span>
        <button class="btn btn-ghost btn-sm" data-action="code-run-custom">Type a command</button></div></div>`;
    }
    return `<div class="code-run"><div class="run-bar explain-bar">${icon('alert', 15)}
      <span><b>Explain only.</b> ${esc(k.commands.explain_only || '')}</span>
      <button class="btn btn-ghost btn-sm" data-action="code-run-custom">Run a command anyway</button></div></div>`;
  }
  const chosen = cmds.find(c => c.command === k.cmd);
  const missing = chosen?.missing?.length ? `<span class="run-note">${icon('alert', 13)}${esc(chosen.missing.join(', '))} wasn't found on this PC.</span>` : '';
  const why = chosen?.why ? `<span class="run-note">${esc(chosen.why)}</span>` : '';
  return `<div class="code-run">
    <div class="run-bar">
      <span class="run-prompt" aria-hidden="true">$</span>
      <input class="input run-command" id="runCommand" list="runCommands" value="${esc(k.cmd || '')}" aria-label="Command to run" spellcheck="false" ${running ? 'disabled' : ''}>
      <datalist id="runCommands">${cmds.map(c => `<option value="${esc(c.command)}">${esc(c.label)}</option>`).join('')}</datalist>
      <label class="run-keep" title="For servers and apps: no time limit, Stop when you're done"><input type="checkbox" id="runKeep" ${k.keep ? 'checked' : ''} ${running ? 'disabled' : ''}>Keep running</label>
      ${k.keep ? '' : `<select class="select select-sm" id="runLimit" aria-label="Time limit" ${running ? 'disabled' : ''}>${RUN_LIMITS.map(([v, l]) => opt(v, l, k.limit || 30)).join('')}</select>`}
      ${running ? `<button class="btn btn-ghost btn-sm" data-action="code-run-stop">${icon('x', 15)}Stop</button>`
        : `<button class="btn btn-primary btn-sm" data-action="code-run">${icon('up', 15)}Run</button>`}
    </div>
    ${missing || why ? `<div class="run-notes">${missing}${why}</div>` : ''}
    ${run ? codeRunOutput() : ''}
  </div>`;
}

function codeRunOutput() {
  const run = codeState().run;
  const state = { running: `${icon('clock', 13)}Running… <span id="runElapsed">${run.elapsed}</span> s`,
    finished: run.exit_code === 0 ? `${icon('check', 13)}Finished in ${run.elapsed} s` : `${icon('alert', 13)}Ended with exit code ${run.exit_code} after ${run.elapsed} s`,
    timed_out: `${icon('alert', 13)}${esc(run.reason)}`, stopped: `${icon('x', 13)}Stopped after ${run.elapsed} s` }[run.status] || '';
  const lines = run.status !== 'running' ? codeErrorTargets(run.text) : [];
  return `<div class="run-out">
    <div class="run-status ${run.status} ${run.exit_code ? 'failed' : ''}" id="runStatus">${state}
      <span class="spacer"></span><button class="icon-btn" data-action="code-run-clear" aria-label="Clear the output" title="Clear">${icon('trash', 14)}</button></div>
    <div class="run-links" id="runLinks">${codeRunLinks(run)}${lines.map(t => `<button class="link-btn" data-action="code-goto" data-path="${esc(t.path)}" data-line="${t.line}">${esc(t.path)} line ${t.line}</button>`).join(' ')}</div>
    <pre class="run-text" id="runText" aria-live="polite">${esc(run.text.replace(ANSI, ''))}${run.truncated ? '\n… (the rest of the output isn\'t shown: it\'s over 200 KB)' : ''}</pre>
    ${run.status === 'running' ? `<form class="run-input" id="runInput"><input class="input" name="line" placeholder="Type input for the program and press Enter" autocomplete="off" aria-label="Input for the program">
      <button class="btn btn-ghost btn-sm" type="submit">Send</button></form>` : ''}
  </div>`;
}

function codeRunLinks(run) {
  return (run.links || []).map(u => `<a class="btn btn-ghost btn-sm keep-label" href="${esc(u.replace('0.0.0.0', 'localhost'))}" target="_blank" rel="noopener">${icon('external', 13)}Open ${esc(u.replace(/^https?:\/\//, ''))} in browser</a>`).join('');
}

/** Files and lines an error in the output points at (only files in this folder). */
function codeErrorTargets(text) {
  const files = codeFiles(), out = [];
  for (const { name, line } of errorLines((text || '').replace(ANSI, ''))) {
    const path = files.find(p => p === name || name.endsWith('/' + p))
      || (files.filter(p => p.split('/').pop() === name.split('/').pop()).length === 1 && files.find(p => p.split('/').pop() === name.split('/').pop()));
    if (path && !out.some(t => t.path === path && t.line === line)) out.push({ path, line });
  }
  return out.slice(-4);
}

async function codeLoadCommands() {
  const k = codeState(), id = k.folderId, open = k.open?.path || '';
  try {
    const r = await api(`/api/code/folders/${id}/commands?open_file=${encodeURIComponent(open)}`);
    if (k.folderId !== id) return;
    k.commands = r;
    const mine = r.commands.find(c => c.label === `Run ${open.split('/').pop()}`);
    if (!k.cmdEdited || !k.cmd) {
      const pick = mine || r.commands[0];
      k.cmd = pick?.command || '';
      k.keep = !!pick?.keep_running;
    }
  } catch (_) { if (k.folderId === id) k.commands = { commands: [], explain_only: '' }; }
}

const codeStarting = new Set();                 // folders with a run being started (a double-click starts one)

async function codeStartRun(command) {
  const f = codeFolder();
  if (!f || !command.trim()) { toast('Type a command to run first.', 'error'); return false; }
  if (codeStarting.has(f.id)) return false;
  codeStarting.add(f.id);
  try { return await codeStartRunIn(f, command); } finally { codeStarting.delete(f.id); }
}

async function codeStartRunIn(f, command) {
  const k = codeState();
  if (!state.ai?.run_notice) {
    const ok = await confirmDialog('Before you run code',
      'Code runs on this PC with your permissions, so it can read and change your files, and read the AI key saved in EasyUniTrack. Only run code you trust. ' +
      'Nothing runs unless you click Run, and EasyUniTrack stops a run at its time limit or when you click Stop.', 'I understand', 'primary');
    if (!ok) return false;
    try { await api('/api/ai/run-notice', { method: 'POST' }); state.ai.run_notice = true; } catch (e) { toast(e.message, 'error'); return false; }
  }
  try {
    const r = await api(`/api/code/folders/${f.id}/run`, { method: 'POST',
      body: { command: command.trim(), keep_running: !!k.keep, timeout: Number(k.limit) || 30 } });
    const run = { ...r, text: r.output };
    k.runs[f.id] = run;                          // the folder that started it, even if another is shown now
    if (k.folderId === f.id) codeRunRefresh();
    codePoll(run);
  } catch (e) { toast(e.message, 'error'); return false; }
  return true;
}

function codePoll(run = codeState().run) {
  const k = codeState();
  if (!run || run.status !== 'running') return;
  clearTimeout(run.timer);                                 // one poller per run, whichever folder is shown
  run.timer = setTimeout(async () => {
    if (k.runs[run.folder_id] !== run) return;           // cleared or replaced
    try {
      const v = await api(`/api/code/runs/${run.id}?since=${run.next}`);
      if (k.runs[run.folder_id] !== run) return;
      const shown = k.folderId === run.folder_id && route() === 'code';
      const grew = !!v.output, done = v.status !== 'running';
      Object.assign(run, { ...v, text: run.text + v.output });
      if (done) {
        if (shown) {
          codeRunRefresh();
          if (run.exit_code) codeMarkErrors(run.text.replace(ANSI, ''));
        }
        return;
      }
      if (grew && shown) {                                        // add to the output without redrawing the input box
        const pre = $('#runText');
        if (pre) {
          const atEnd = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
          pre.textContent = run.text.replace(ANSI, '');
          if (atEnd) pre.scrollTop = pre.scrollHeight;
        }
        const links = $('#runLinks');
        if (links && run.links?.length) links.innerHTML = codeRunLinks(run);
      }
      const el = shown && $('#runElapsed');
      if (el) el.textContent = run.elapsed;
    } catch (_) { /* try again on the next tick */ }
    codePoll(run);
  }, 300);
}

function codeRunRefresh() {
  const panel = $('.code-run');
  const html = codeRunPanel();
  if (panel) panel.outerHTML = html || '<div class="code-run"></div>';
  const pre = $('#runText');
  if (pre) pre.scrollTop = pre.scrollHeight;
  $('#runInput input')?.focus();
}

// ── The computer science quick actions (Trace, Big-O, Visualise, tests, Explain my change, practice) ──
const CODE_ACTIONS = [
  ['trace', 'Trace', 'layers', 'A table of each variable, line by line'],
  ['big_o', 'Big-O', 'clock', 'Time and space complexity, with the reasoning'],
  ['visualise', 'Visualise', 'spark', 'Diagrams of the data structures the code builds'],
  ['tests', 'Write tests', 'check', 'Normal, edge and error cases'],
  ['explain_change', 'Explain my change', 'repeat', 'What changed since the last commit, or since you opened the file'],
  ['practice', 'Practice', 'flag', 'A new problem like this one, with hints'],
];

async function codeAction(kind) {
  const k = codeState(), f = codeFolder(), open = k.open?.path;
  if (!f) return;
  const box = $('#chatInput'), extra = box?.value.trim() || '';
  if (!open && kind !== 'practice') { toast('Open a file first.'); return; }
  if (kind === 'explain_change') {
    // Another file or folder opened while waiting: this answer is for something that isn't shown any more
    const moved = () => route() !== 'code' || chatState().code !== f.id || k.folderId !== f.id || k.open?.path !== open;
    let r;
    try {
      r = await api(`/api/code/folders/${f.id}/diff`, { method: 'POST', body: { path: open, baseline: k.baselines[`${f.id}:${open}`] ?? null } });
    } catch (e) { if (!moved()) toast(e.message, 'error'); return; }
    if (moved()) return;
    if (!r.diff) {
      toast(r.source === 'git' ? `${open} hasn't changed since the last commit.` : `${open} hasn't changed since you opened it.`);
      return;
    }
    try {                                           // show the file as it is now, since that's what's explained
      const now = await api(`/api/code/folders/${f.id}/file?path=${encodeURIComponent(open)}`);
      if (!moved()) { k.open = { ...k.open, ...now }; const main = $('#codeMain'); if (main) main.innerHTML = codeViewer(); }
    } catch (_) { /* the viewer keeps what it had */ }
    if (moved()) return;
    const since = r.source === 'git' ? (r.new_file ? 'a new file since the last commit' : 'since the last commit') : 'since I opened it';
    const cut = r.truncated ? '\n\nThe change is long, so only its first part is included: say what you can\'t see.' : '';
    if (r.truncated) toast('The change is long, so only its first part goes with your question.');
    await chatSend(`Explain my change to ${open} (${since}).${cut}${extra ? `\n\n${extra}` : ''}`, { action: 'explain_change', diff: r.diff });
    return;
  }
  const text = {
    trace: `Trace ${open} step by step${extra ? `, with: ${extra}` : '.'}`,
    big_o: `What's the Big-O of ${open}?${extra ? ` ${extra}` : ''}`,
    visualise: `Visualise the data structures in ${open}.${extra ? ` ${extra}` : ''}`,
    tests: `${f?.mode === 'assignment' ? 'Help me plan tests for' : 'Write tests for'} ${open}.${extra ? ` ${extra}` : ''}`,
    practice: `Give me a practice problem like ${open || 'this'}${extra ? `, about ${extra}` : ''}.`,
  }[kind];
  if (text) await chatSend(text, { action: kind });
}

/** The last run's output, when it failed, for Explain the error and Debug. */
function codeFailedOutput() {
  const run = codeState().run;
  if (!run || run.status === 'running' || (run.exit_code === 0 && run.status === 'finished')) return '';
  return run.text.replace(ANSI, '').slice(-4000);
}

function codeScrollToMark() {
  const k = codeState(), first = k.open && (k.marks[k.open.path] || [])[0];
  const view = $('#codeView');
  if (view && first) view.scrollTop = Math.max(0, (first - 4) * 20);
}

async function codeOpen(path) {
  const k = codeState(), id = k.folderId;
  try {
    const f = await api(`/api/code/folders/${id}/file?path=${encodeURIComponent(path)}`);
    if (k.folderId !== id) return;
    k.open = { ...f, name: path.split('/').pop() };
    k.baselines[`${id}:${path}`] ??= f.text;       // as first opened (per folder), for Explain my change without git
    k.removed = [];
    for (let p = path.split('/').slice(0, -1), i = 1; i <= p.length; i++) k.expanded.add(p.slice(0, i).join('/'));
  } catch (e) { toast(e.message, 'error'); return; }
  await Promise.all([codeChoose(''), codeLoadCommands()]);
  if (route() === 'code') codeRender();
}

function codeSendList() {
  const k = codeState(), files = k.files || [];
  return `<div class="code-send" id="codeSend"><span class="muted small">${files.length ? 'Sent with your message:' : 'No files will be sent. Open one, or name it in your message.'}</span>
    ${files.map(f => `<span class="chip file-chip" title="${esc(f.why)}">${icon('file', 12)}${esc(f.path)}<button type="button" class="chip-x" data-action="code-unsend" data-path="${esc(f.path)}" aria-label="Don't send ${esc(f.path)}">${icon('x', 11)}</button></span>`).join('')}</div>`;
}

/** Ask the server which files go with this question (the open file, files named in it, what the open file
 *  imports, and the student's own picks), then show the list. */
async function codeChoose(question) {
  const k = codeState(), id = k.folderId;
  if (!id) return;
  try {
    const r = await api(`/api/code/folders/${id}/choose`, { method: 'POST',
      body: { question, open_file: k.open?.path || '', pinned: k.pinned, removed: k.removed } });
    if (k.folderId !== id) return;
    k.files = r.files;
  } catch (_) { return; }
  const box = $('#codeSend');
  if (box) box.outerHTML = codeSendList();
  const tree = $('#codeTree');
  if (tree && k.tree) tree.innerHTML = codeTreeNodes(k.tree.children);
}

/** Apply, Undo or Dismiss on a proposed change, then show the file as it is now. */
async function codeChangeAction(el, what) {
  const card = chatState().messages[Number(el.dataset.i)]?.cards?.[Number(el.dataset.c)];
  if (!card || card.busy) return;
  card.busy = true; chatRefresh();
  try {
    const r = what === 'apply' ? await api(`/api/code/changes/${card.id}/apply`, { method: 'POST' })
      : what === 'undo' ? await api(`/api/code/changes/${card.id}/undo`, { method: 'POST' })
      : await api(`/api/code/changes/${card.id}/dismiss`, { method: 'POST' });
    card.status = r.status;
    toast({ applied: `Applied to ${card.path}`, undone: `Undone: ${card.path} is back as it was`, dismissed: 'Dismissed' }[r.status] || 'Done');
    const k = codeState();
    if (r.created || r.removed) await codeLoadTree();                       // a file appeared or went away
    else if (k.open?.path === card.path) await codeOpen(card.path);        // show the file as it is now
  } catch (e) {
    if (/changed since this was proposed/.test(e.message)) card.status = 'stale';
    toast(e.message, 'error');
  }
  card.busy = false;
  chatRefresh();
  chatSave();
}

/** Line numbers an error points at, per file: Python, Java, gcc/clang, node, C# and the like. */
function errorLines(text) {
  const out = [];
  const add = (name, line) => { if (name && line) out.push({ name: name.replace(/\\/g, '/'), line: Number(line) }); };
  for (const m of text.matchAll(/File "([^"]+)", line (\d+)/g)) add(m[1], m[2]);
  for (const m of text.matchAll(/\(([\w$.-]+\.(?:java|kt|scala)):(\d+)\)/g)) add(m[1], m[2]);
  for (const m of text.matchAll(/([\w./\\:-]+\.[A-Za-z]{1,6})(?::(\d+)(?::\d+)?|\((\d+),\d+\))/g)) add(m[1], m[2] || m[3]);
  return out;
}

function codeMarkErrors(text) {
  const k = codeState(), files = codeFiles(), marks = {};
  for (const { name, line } of errorLines(text)) {
    const path = files.find(p => p === name || name.endsWith('/' + p))
      || (files.filter(p => p.split('/').pop() === name.split('/').pop()).length === 1 && files.find(p => p.split('/').pop() === name.split('/').pop()));
    if (path) (marks[path] ||= []).includes(line) || marks[path].push(line);
  }
  if (!Object.keys(marks).length) return;
  k.marks = marks;
  const open = k.open && marks[k.open.path] ? null : Object.keys(marks)[0];
  if (open && k.open) toast(`The error points at ${open}. Open it from the list to see the line.`);
  const main = $('#codeMain');
  if (main && k.open) { main.innerHTML = codeViewer(); codeScrollToMark(); }
}

function openChatPanel(taskId) {
  const c = chatState();
  if (c.taskId !== taskId) chatReset(taskId);
  const foot = `<span class="spacer"></span><a class="btn btn-ghost" href="#/study" data-action="chat-full">${icon('external', 15)}Open full page</a>`;
  openDrawer('Help with this task', chatShell(true), foot, 'chat');
  chatAfterRender();
}

// ── Notes (inside subjects) ───────────────────────────────────────
// Shown on a subject when the study assistant is on or the subject already has notes, so the app looks
// the same as before for anyone not using the new features.
const notesFor = subjectId => (state.notes || []).filter(n => (n.subject_id ?? null) === subjectId);

function notesBlock(subjectId) {
  const list = notesFor(subjectId);
  if (subjectId === null) {                    // notes whose subject was deleted, or saved without one
    if (!list.length) return '';
    return `<article class="card subject other-notes"><div class="subject-head"><h3 class="subject-name">Other notes</h3></div>
      <p class="subject-stats">Notes without a subject</p>${notesList(list, null)}</article>`;
  }
  if (!list.length && !aiOn()) return '';
  return `<div class="subject-notes">
      <div class="subject-notes-head"><span>Notes</span>${list.length ? `<span class="muted small">${list.length}</span>` : ''}<span class="spacer"></span>
        ${aiOn() ? `<button class="icon-btn sm" data-action="note-topic" data-subject="${subjectId}" title="Write notes on a topic" aria-label="Write notes on a topic">${icon('spark', 15)}</button>` : ''}
        <button class="icon-btn sm" data-action="new-note" data-subject="${subjectId}" title="New note" aria-label="New note">${icon('plus', 15)}</button></div>
      ${list.length ? notesList(list, subjectId) : `<p class="small muted notes-empty">Save replies from the study assistant here, or write your own.</p>`}
    </div>`;
}

function notesList(list, subjectId) {
  const key = String(subjectId);
  const open = state.notesOpen?.[key];
  const shown = open ? list : list.slice(0, 4);
  return `<div class="note-list">${shown.map(n => `
      <button class="note-row" data-action="open-note" data-id="${n.id}">
        ${icon(n.source === 'manual' ? 'pencil' : 'spark', 14)}<span class="note-title">${esc(n.title)}</span>
        <span class="muted small">${esc(fmt(n.updated_at.slice(0, 10), { day: 'numeric', month: 'short' }))}</span></button>`).join('')}
    ${list.length > 4 ? `<button class="link small note-more" data-action="notes-more" data-subject="${key}">${open ? 'Show fewer' : `Show all ${list.length}`}</button>` : ''}</div>`;
}

function noteSubjectOptions(selected) {
  return opt('', 'No subject', selected ?? '') + state.subjects.map(s => opt(s.id, s.name, selected)).join('');
}

function openNote(id) {
  const n = state.notes.find(x => x.id === id);
  if (!n) return;
  const subj = n.subject_id && subjectById(n.subject_id);
  const from = { chat: 'Saved from the study assistant', topic: 'Written by the study assistant', manual: 'Your note' }[n.source] || '';
  const body = `<div class="note-view">
      <p class="small muted">${esc([subj?.name, from, 'updated ' + fmt(n.updated_at.slice(0, 10), { day: 'numeric', month: 'short', year: 'numeric' })].filter(Boolean).join(' · '))}</p>
      <div class="chat-text note-body">${n.body ? chatMarkdown(n.body) : '<p class="muted">This note is empty.</p>'}</div></div>`;
  const foot = `<button class="btn btn-danger-ghost btn-sm" type="button" data-action="delete-note" data-id="${id}">${icon('trash', 16)}Delete</button>
    <span class="spacer"></span><button class="btn btn-ghost" type="button" data-action="close-drawer">Close</button>
    <button class="btn btn-primary" type="button" data-action="edit-note" data-id="${id}">${icon('pencil', 16)}Edit</button>`;
  openDrawer(n.title, body, foot, 'note-view');
}

function editNote(id, defaults = {}) {
  const n = id ? state.notes.find(x => x.id === id) : { title: '', body: '', subject_id: null, source: 'manual', ...defaults };
  if (!n) return;
  const body = `
    <form id="drawerForm" class="form-stack" data-kind="note" data-id="${id || ''}" data-source="${esc(n.source || 'manual')}" data-task="${n.task_id || ''}" autocomplete="off">
      <input class="title-input" name="title" placeholder="Note title" value="${esc(n.title)}" required maxlength="200" ${id ? '' : 'autofocus'} aria-label="Title">
      ${field('Subject', `<select class="select" name="subject_id">${noteSubjectOptions(n.subject_id)}</select>`)}
      ${field('Note', `<textarea class="textarea note-editor" name="body" rows="16" maxlength="200000" placeholder="Write with Markdown: # headings, - lists, **bold**, \`code\`">${esc(n.body)}</textarea>`)}
    </form>`;
  openDrawer(id ? 'Edit note' : 'New note', body, footer(''), 'note');
}

function openNoteTopic(subjectId) {
  const s = subjectById(subjectId);
  state.noteTopic?.controller?.abort();          // a previous topic still being written stops (and stops costing)
  state.noteTopic = { subjectId, text: '', streaming: false, controller: null, error: '' };
  const body = `<div class="form-stack note-topic">
      <p class="small muted">The study assistant writes structured notes (overview, key points, a worked example and a summary)${s ? ` for ${esc(s.name)}` : ''}. You can edit them before saving.</p>
      ${field('Topic', `<input class="input" id="noteTopicInput" maxlength="300" placeholder="e.g. Hash tables and collision handling" autofocus>`)}
      <div class="chat-text note-preview" id="noteTopicPreview" aria-live="polite"></div>
    </div>`;
  const foot = `<span class="spacer"></span><button class="btn btn-ghost" type="button" data-action="close-drawer">Cancel</button>
    <button class="btn btn-ghost" type="button" data-action="note-topic-stop" hidden id="noteTopicStop">${icon('x', 16)}Stop</button>
    <button class="btn btn-primary" type="button" data-action="note-topic-go" id="noteTopicGo">${icon('spark', 16)}Write notes</button>
    <button class="btn btn-primary" type="button" data-action="note-topic-save" hidden id="noteTopicSave">${icon('check', 16)}Save note</button>`;
  openDrawer('Write notes on a topic', body, foot, 'note-topic');
}

async function noteTopicWrite() {
  const t = state.noteTopic, topic = $('#noteTopicInput').value.trim();
  if (!t || !topic || t.streaming) { if (!topic) toast('Enter a topic first.', 'error'); return; }
  const s = subjectById(t.subjectId);
  Object.assign(t, { topic, text: '', error: '', streaming: true, controller: new AbortController() });
  const show = () => {
    const box = $('#noteTopicPreview');
    if (!box || state.noteTopic !== t) return;
    box.classList.toggle('live', t.streaming);
    box.innerHTML = (t.text ? chatMarkdown(t.text) : '<span class="chat-typing" aria-label="Writing"><i></i><i></i><i></i></span>') +
      (t.error ? `<div class="chat-error">${icon('alert', 15)}${esc(t.error)}</div>` : '');
    $('#noteTopicStop').hidden = !t.streaming;
    $('#noteTopicGo').hidden = t.streaming || !!t.text;
    $('#noteTopicSave').hidden = t.streaming || !t.text;
  };
  show();
  try {
    await streamChat({ mode: 'notes', messages: [{ role: 'user', content: `Write study notes on: ${topic}${s ? `\nUnit: ${s.name}` : ''}` }] },
      t.controller.signal, ev => {
        if (state.noteTopic !== t) return false;
        if (ev.type === 'text') t.text += ev.text;
        else if (ev.type === 'error') t.error = ev.message;
        show();
        return true;
      });
  } catch (e) {
    if (e.name !== 'AbortError') t.error = e.message;
  }
  t.streaming = false;
  show();
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
  // Focus the first field, unless the user (or a test) is already in one
  setTimeout(() => { if (!$('#drawer').contains(document.activeElement)) $('#drawer [autofocus]')?.focus(); }, 30);
}
function closeDrawer() {
  if ($('#drawer').hidden) return;
  if (state.drawer === 'note-topic') { state.noteTopic?.controller?.abort(); state.noteTopic = null; }
  if (state.drawer === 'budget-plan' && state.savedCurrency) setCurrency(state.savedCurrency);
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
      ${id && aiOn() ? `<button class="ai-help" type="button" data-action="chat-help" data-id="${id}">${icon('spark', 16)}<span><b>Help me with this</b><span class="muted small">Ask the study assistant about this task</span></span>${icon('external', 14)}</button>` : ''}
      <div id="planSlot"></div>
      <div class="form-grid">
        ${field('Due date', `<input class="input" type="date" name="due_date" value="${esc(t.due_date || '')}">`)}
        ${field('Repeats', `<select class="select" name="recurrence_pattern">${Object.entries(REPEATS).map(([k, v]) => opt(k, v, t.recurrence_pattern || '')).join('')}</select>`)}
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
  const budgeted = state.budgets.map(b => b.category);
  const cats = type === 'income' ? INCOME_CATEGORIES : [...budgeted, ...SPENDING_CATEGORIES.filter(c => !budgeted.includes(c))];
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
        ${field(type === 'income' ? 'Source' : 'Category', `<select class="select" name="category" required>${cats.map(c => opt(c, c)).join('')}</select>`, 'span-2')}
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

function planRow(category, amount) {
  return `<label class="plan-cat" data-category="${esc(category)}">
    <span class="plan-cat-name">${esc(category)}</span>
    <span class="money-input"><span class="money-sym" data-sym>${esc(currencySymbol())}</span>
      <input class="input" type="number" min="0" step="1" inputmode="decimal" value="${amount === '' ? '' : esc(amount)}" placeholder="No budget" aria-label="Monthly budget for ${esc(category)}"></span>
  </label>`;
}

/** One screen to choose a currency and set (or clear) a monthly amount for every category. */
function openBudgetPlan() {
  const existing = Object.fromEntries(state.budgets.map(b => [b.category, b.monthly_limit]));
  const names = [...state.budgets.map(b => b.category), ...SPENDING_CATEGORIES.filter(c => !(c in existing))];
  const body = `
    <form id="drawerForm" class="form-stack" data-kind="budget-plan" autocomplete="off">
      <p class="muted" style="margin-top:-4px">Enter how much you want to spend per month. Leave a category empty to skip it. You can change this any time.</p>
      ${field('Currency', `<select class="select" name="currency" id="planCurrency">${currencyOptions(state.currency)}</select>`)}
      <div class="plan-list" id="planRows">${names.map(n => planRow(n, n in existing ? existing[n] : '')).join('')}</div>
      <div class="plan-add">
        <input class="input" id="planNewName" placeholder="Add your own category" maxlength="60" aria-label="New category name">
        <button class="btn btn-ghost btn-sm" type="button" data-action="plan-add-row">${icon('plus', 15)}Add</button>
      </div>
    </form>`;
  state.savedCurrency = state.currency;
  openDrawer(state.budgets.length ? 'Your monthly budget' : 'Set up your budget', body,
    `<div class="plan-total"><span class="muted small">Total per month</span><strong id="planTotal"></strong></div>
     <span class="spacer"></span>
     <button class="btn btn-ghost" type="button" data-action="close-drawer">Cancel</button>
     <button class="btn btn-primary" type="submit" form="drawerForm">Save budget</button>`, 'budget-plan');
  const update = () => {
    const code = $('#planCurrency').value;
    setCurrency(code);
    $$('#planRows [data-sym]').forEach(el => (el.textContent = currencySymbol()));
    const total = $$('#planRows input').reduce((t, i) => t + (Number(i.value) || 0), 0);
    $('#planTotal').textContent = money(total, true);
  };
  $('#drawerForm').addEventListener('input', update);
  $('#planCurrency').addEventListener('change', update);
  $('#planNewName').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); ACTIONS['plan-add-row'](); } });
  update();
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
        recurrence_pattern: d.recurrence_pattern || '',
      };
      const prev = id && state.tasks.find(x => x.id === id);
      if (prev && prev.status !== 'completed' && body.status === 'completed' && body.progress < 100) body.progress = 100;
      const saved = await api(id ? `/api/tasks/${id}` : '/api/tasks', { method: id ? 'PUT' : 'POST', body });
      upsert(state.tasks, saved);
      if (saved.next_task) { upsert(state.tasks, saved.next_task); toast(`Done. Next one added for ${fmt(saved.next_task.due_date, { weekday: 'short', day: 'numeric', month: 'short' })}`); }
      else toast(id ? 'Task updated' : 'Task added');
    } else if (kind === 'type') {
      const saved = await api(id ? `/api/categories/${id}` : '/api/categories', { method: id ? 'PUT' : 'POST', body: { name: d.name, color: d.color } });
      upsert(state.categories, saved);
      // Task rows show the type's name, so refresh them
      if (id) state.tasks.forEach(t => { if (t.category_id === id) { t.category_name = saved.name; t.category_color = saved.color; } });
      toast(id ? 'Task type updated' : 'Task type added');
    } else if (kind === 'job') {
      const body = { ...d, applied_date: d.applied_date || null, follow_up_date: d.follow_up_date || null };
      upsert(state.jobs, await api(id ? `/api/jobs/${id}` : '/api/jobs', { method: id ? 'PUT' : 'POST', body }));
      toast(id ? 'Application updated' : 'Application added');
    } else if (kind === 'tx') {
      await api('/api/transactions', { method: 'POST', body: { ...d, amount: Number(d.amount) } });
      state.month = d.date.slice(0, 7);
      await loadMoney();
      toast('Transaction added');
    } else if (kind === 'budget-plan') {
      const items = $$('#planRows [data-category]').map(r => {
        const v = r.querySelector('input').value.trim();
        return { category: r.dataset.category, monthly_limit: v === '' ? null : Number(v) };
      });
      const money_ = await api('/api/settings/money', { method: 'PUT', body: { currency: d.currency } });
      setCurrency(money_.currency); state.currencyChosen = true; state.savedCurrency = money_.currency;
      await api('/api/budget-plan', { method: 'PUT', body: { items } });
      await loadMoney();
      toast('Budget saved');
    } else if (kind === 'budget') {
      await api(id ? `/api/budgets/${id}` : '/api/budgets', { method: id ? 'PUT' : 'POST', body: { category: d.category, monthly_limit: Number(d.monthly_limit), color: b_color(id) } });
      await loadMoney();
      toast('Budget saved');
    } else if (kind === 'code-folder') {
      const saved = await api('/api/code/folders', { method: 'POST',
        body: { path: d.path.trim(), mode: d.mode || 'assignment', subject_id: numOrNull(d.subject_id) } });
      const k = codeState();
      k.folders = [...(k.folders || []), saved].sort((a, b) => a.name.localeCompare(b.name));
      codeSelectFolder(saved.id);
      toast(`Linked ${saved.name}`);
      closeDrawer();
      location.hash = '#/code';
      render();
      return;
    } else if (kind === 'note') {
      const body = { title: d.title, body: d.body, subject_id: numOrNull(d.subject_id) };
      if (!id) Object.assign(body, { source: form.dataset.source || 'manual', task_id: numOrNull(form.dataset.task) });
      const saved = await api(id ? `/api/notes/${id}` : '/api/notes', { method: id ? 'PUT' : 'POST', body });
      upsert(state.notes, saved);
      state.notes.sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || '') || b.id - a.id);
      toast(id ? 'Note saved' : `Note saved${saved.subject_id ? ` in ${subjectById(saved.subject_id)?.name || 'its subject'}` : ''}`);
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
  async 'chat-undo'(el) {
    const card = chatState().messages[Number(el.dataset.i)]?.cards?.[Number(el.dataset.c)];
    if (!card || card.busy) return;
    card.busy = true; chatRefresh();
    try {
      await api('/api/ai/undo', { method: 'POST', body: { action_id: card.id } });
      card.status = 'undone';
      if (await reloadTasks()) toast('Undone');
    } catch (e) { toast(e.message, 'error'); }
    card.busy = false;
    chatRefresh();
    chatSave();
  },
  async 'chat-confirm'(el) {
    const card = chatState().messages[Number(el.dataset.i)]?.cards?.[Number(el.dataset.c)];
    if (!card || card.busy) return;
    const approve = el.dataset.approve === '1';
    card.busy = true; chatRefresh();
    try {
      const r = await api('/api/ai/confirm', { method: 'POST', body: { action_id: card.id, approve } });
      card.status = approve ? 'approved' : 'rejected';
      if (approve) {
        if (await reloadTasks()) toast(r.failed?.length ? `Done, but ${r.failed.length} couldn't be made: ${r.failed[0]}` : 'Done', r.failed?.length ? 'error' : '');
      }
    } catch (e) { toast(e.message, 'error'); }
    card.busy = false;
    chatRefresh();
    chatSave();
  },
  'open-note'(el) { openNote(Number(el.dataset.id)); },
  'edit-note'(el) { editNote(Number(el.dataset.id)); },
  'new-note'(el) { editNote(null, { subject_id: Number(el.dataset.subject) || null }); },
  async 'delete-note'(el) {
    const id = Number(el.dataset.id);
    if (!(await confirmDialog('Delete this note?', "It's removed from EasyUniTrack. This can't be undone.", 'Delete'))) return;
    try {
      await api(`/api/notes/${id}`, { method: 'DELETE' });
      state.notes = state.notes.filter(n => n.id !== id);
      closeDrawer(); render(); toast('Note deleted');
    } catch (e) { toast(e.message, 'error'); }
  },
  'notes-more'(el) { state.notesOpen = { ...(state.notesOpen || {}), [el.dataset.subject]: !state.notesOpen?.[el.dataset.subject] }; stillRender(); },
  'chat-save-note'(el) {
    const c = chatState(), m = c.messages[Number(el.dataset.i)];
    const task = c.taskId && state.tasks.find(t => t.id === c.taskId);
    const heading = (m.content.match(/^#{1,3}\s+(.+)$/m) || [])[1];
    const question = [...c.messages.slice(0, Number(el.dataset.i))].reverse().find(x => x.role === 'user')?.content || '';
    const title = (heading || question || 'Study assistant note').replace(/[*`#]/g, '').trim().slice(0, 120);
    editNote(null, { title, body: m.content, subject_id: task?.subject_id ?? null, task_id: task?.id ?? null, source: 'chat' });
  },
  'note-topic'(el) { openNoteTopic(Number(el.dataset.subject)); },
  'note-topic-go'() { noteTopicWrite(); },
  'note-topic-stop'() { state.noteTopic?.controller?.abort(); },
  'note-topic-save'() {
    const t = state.noteTopic;
    if (!t?.text) return;
    editNote(null, { title: t.topic.slice(0, 200), body: t.text, subject_id: t.subjectId, source: 'topic' });
  },
  'chat-open'(el) { chatOpen(Number(el.dataset.id)); },
  'chats-all'() { loadChats().then(chatList); },
  async 'chat-delete'(el) {
    const id = Number(el.dataset.id), ch = (state.chats || []).find(x => x.id === id);
    if (!(await confirmDialog('Delete this chat?', `“${ch?.title || 'Chat'}” is removed from EasyUniTrack. This can't be undone.`, 'Delete'))) return;
    try { await api(`/api/ai/chats/${id}`, { method: 'DELETE' }); } catch (e) { toast(e.message, 'error'); return; }
    if (chatState().id === id) chatState().id = null;     // the open chat carries on, saved as a new one
    await loadChats();
    if (state.drawer === 'chats') chatList();
    toast('Chat deleted');
  },
  'chat-answer'(el) { chatSend(el.dataset.v); },
  'chat-videos'() { chatSend('Find videos on this.', { action: 'videos' }); },
  'chat-new'() {
    chatReset(null, route() === 'code' ? codeState().folderId : null);   // a new chat stays in the same folder
    chatRefresh();
    renderNav();                                    // Recent chats no longer marks the old one as open
  },
  'chat-mode'(el) { if (!chatState().streaming) { chatState().mode = el.dataset.mode; chatRefresh(); } },
  async 'chat-think'() {                          // kept as a setting, so the next chat starts the same way
    if (chatState().streaming || !state.ai || state.thinkSaving) return;
    const on = !state.ai.think;
    state.ai = { ...state.ai, think: on };
    state.thinkSaving = true;                     // one save at a time, so the last click is what's kept
    chatRefresh({ keepDraft: true });
    try { await aiSettings({ think: on }); }
    catch (e) { state.ai = { ...state.ai, think: !on }; toast(e.message, 'error'); }
    finally { state.thinkSaving = false; chatRefresh({ keepDraft: true }); }
  },
  'chat-attach'() {
    const input = $('#chatFile', chatRoot() || document);
    if (input) { input.value = ''; input.click(); }
  },
  'chat-file-remove'() {
    const c = chatState();
    if (c.streaming) return;
    c.file = null;
    chatRefresh({ keepDraft: true });
    chatSave();                                   // the saved chat no longer carries it either
  },
  'chat-file-ask'(el) {
    const c = chatState(), kind = el.dataset.kind;
    if (c.streaming) return;
    if (kind === 'quiz') c.mode = 'quiz';         // Quiz me carries on as a quiz; notes are written once
    chatSend(FILE_ASKS[kind], kind === 'notes' ? { mode: 'notes' } : {});
  },
  'chat-idea'(el) { chatSend(el.textContent); },
  'code-link'() { codeLinkForm(); },
  async 'code-change-apply'(el) { await codeChangeAction(el, 'apply'); },
  async 'code-change-undo'(el) { await codeChangeAction(el, 'undo'); },
  async 'code-change-dismiss'(el) { await codeChangeAction(el, 'dismiss'); },
  async 'code-browse'() {
    try {
      const r = await api('/api/code/pick-folder', { method: 'POST' });
      if (r.path) $('#drawerForm [name=path]').value = r.path;
    } catch (e) { toast(e.message, 'error'); $('#drawerForm [name=path]')?.focus(); }
  },
  'code-dir'(el) {
    const k = codeState(), p = el.dataset.path;
    if (k.expanded.has(p)) k.expanded.delete(p); else k.expanded.add(p);
    $('#codeTree').innerHTML = codeTreeNodes(k.tree.children);
  },
  'code-open'(el) { codeState().filesOpen = false; codeOpen(el.dataset.path); },
  'code-files'() {                                          // narrow windows: the file list over the code
    const k = codeState();
    k.filesOpen = !k.filesOpen;
    $('.code-ws')?.classList.toggle('files-open', k.filesOpen);
  },
  'code-refresh'() { codeLoadTree(); },
  async 'code-mode'(el) {
    const f = codeFolder();
    if (!f || f.mode === el.dataset.mode) return;
    try { Object.assign(f, await api(`/api/code/folders/${f.id}`, { method: 'PUT', body: { mode: el.dataset.mode } })); }
    catch (e) { toast(e.message, 'error'); return; }
    toast(f.mode === 'personal' ? 'Personal project: fixes come straight away' : 'Assignment: hints first');
    codeRender();
  },
  async 'code-unlink'(el) {
    const k = codeState(), id = el?.dataset?.id ? Number(el.dataset.id) : k.folderId;   // from Settings, or the open one
    const f = (k.folders || []).find(x => x.id === id);
    if (!f || !(await confirmDialog(`Unlink ${f.name}?`, "EasyUniTrack stops reading it. Your files aren't changed or deleted.", 'Unlink'))) return;
    try { await api(`/api/code/folders/${f.id}`, { method: 'DELETE' }); } catch (e) { toast(e.message, 'error'); return; }
    k.folders = k.folders.filter(x => x.id !== f.id);
    if (k.folderId === f.id) {
      const next = k.folders[0]?.id ?? null;
      if (next) codeSelectFolder(next);
      else { k.folderId = null; if (chatState().code === f.id) chatReset(); }
    }
    if (route() === 'code') codeRender(); else stillRender();
  },
  'code-link-subject'(el) { codeLinkForm(Number(el.dataset.subject)); },
  'code-go'(el) {
    const id = Number(el.dataset.id), k = codeState();
    if (k.folderId !== id) codeSelectFolder(id);
    location.hash = '#/code';
  },
  'code-unsend'(el) {
    const k = codeState(), p = el.dataset.path;
    k.pinned = k.pinned.filter(x => x !== p);
    if (!k.removed.includes(p)) k.removed.push(p);
    codeChoose('').then(() => { const main = $('#codeMain'); if (k.open?.path === p && main) main.innerHTML = codeViewer(); });
  },
  'code-send-open'(el) {
    const k = codeState(), p = el.dataset.path;
    k.removed = k.removed.filter(x => x !== p);
    if (!k.pinned.includes(p)) k.pinned.push(p);
    codeChoose('').then(() => { const main = $('#codeMain'); if (k.open?.path === p && main) main.innerHTML = codeViewer(); });
  },
  'code-explain-error'() {
    const box = $('#chatInput'), typed = box?.value.trim(), ran = codeFailedOutput();
    const text = typed || ran;
    if (!text) { toast('Run the program, or paste the error message into the box, then click Explain the error.'); box?.focus(); return; }
    const from = !typed && ran ? ` from running \`${codeState().run.command}\`` : '';
    chatSend(`Explain this error${from}:\n\n\`\`\`\n${text}\n\`\`\``, { action: 'explain_error' });
  },
  'code-debug'() {
    const k = codeState(), text = $('#chatInput')?.value.trim() || '', ran = codeFailedOutput();
    if (!text && !k.open && !ran) { toast('Open the file with the problem, or describe it in the box first.'); return; }
    chatSend(`Help me find the bug${k.open ? ` in ${k.open.path}` : ''}.${text ? `\n\n${text}` : ''}` +
      (ran ? `\n\nWhen I ran \`${k.run.command}\` it printed:\n\`\`\`\n${ran}\n\`\`\`` : ''), { action: 'debug' });
  },
  async 'code-action'(el) { await codeAction(el.dataset.kind); },
  'code-run'() { const k = codeState(); k.cmd = $('#runCommand')?.value ?? k.cmd; codeStartRun(k.cmd); },
  async 'code-run-stop'() {
    const run = codeState().run;
    if (run) { try { await api(`/api/code/runs/${run.id}/stop`, { method: 'POST' }); } catch (e) { toast(e.message, 'error'); } }
  },
  'code-run-clear'() { const k = codeState(); if (k.run?.status !== 'running') { k.run = null; codeRunRefresh(); } },
  'code-run-custom'() { const k = codeState(); k.customRun = true; k.cmd = ''; codeRunRefresh(); $('#runCommand')?.focus(); },
  'code-goto'(el) {
    const k = codeState(), path = el.dataset.path, line = Number(el.dataset.line);
    k.marks = { [path]: [line] };
    if (k.open?.path === path) { $('#codeMain').innerHTML = codeViewer(); codeScrollToMark(); } else codeOpen(path).then(codeScrollToMark);
  },
  'run-suggest-run'(el) {
    const card = chatState().messages[Number(el.dataset.i)]?.cards?.[Number(el.dataset.c)];
    if (!card || card.busy) return;
    const k = codeState();
    k.cmd = card.command; k.cmdEdited = true;
    card.busy = true; chatRefresh();                         // one click starts one run
    codeRunRefresh();
    codeStartRun(card.command).then(started => {             // "Ran" only once it really started
      card.busy = false;
      if (started) card.status = 'ran';
      chatRefresh();
      chatSave();
    });
  },
  'run-suggest-cancel'(el) {
    const card = chatState().messages[Number(el.dataset.i)]?.cards?.[Number(el.dataset.c)];
    if (card) { card.status = 'cancelled'; chatRefresh(); chatSave(); }
  },
  async 'code-copy'(el) {
    try { await navigator.clipboard.writeText($('code', el.closest('.code-wrap')).textContent); toast('Copied'); }
    catch (_) { toast("Couldn't copy. Select the code and press Ctrl+C.", 'error'); }
  },
  'diagram-redraw'(el) { drawDiagram(el.closest('.chat-diagram')); },     // the library didn't load: draw it again here
  'diagram-retry'(el) {
    const box = el.closest('.chat-diagram');
    if (chatState().streaming) return;
    chatSend(`The diagram didn't draw (${box?.dataset.error || 'it has a mistake'}). Please send the corrected diagram in a \`\`\`mermaid block, with every label in double quotes.`);
  },
  'chat-stop'() { chatState().controller?.abort(); },
  async 'chat-copy'(el) {
    try { await navigator.clipboard.writeText(chatState().messages[Number(el.dataset.i)].content); toast('Copied'); }
    catch (_) { toast("Couldn't copy. Select the text and copy it instead.", 'error'); }
  },
  'chat-help'(el) { openChatPanel(Number(el.dataset.id)); },
  'chat-full'() { closeDrawer(); location.hash = '#/study'; },
  async 'ai-start'() {
    try { await openAiAbout(); } catch (e) { toast(e.message, 'error'); }
  },
  'ai-terms-next': () => openAiTerms(false),
  'ai-view-terms': () => openAiTerms(true),
  async 'ai-agree'(el) {
    const ticks = Object.fromEntries($$('.ai-tick').map(c => [c.dataset.k, c.checked]));
    el.disabled = true;
    try {
      state.ai = await api('/api/ai/terms/agree', { method: 'POST', body: { version: state.aiTerms.version, ticks } });
      closeDrawer();
      toast('AI features are on (preview). Choose a provider to finish setting up.');
      stillRender();
    } catch (e) { el.disabled = false; toast(e.message, 'error'); }
  },
  async 'toggle-ai-assistant'() {
    try { await aiSettings({ assistant_enabled: !state.ai.assistant_enabled }); stillRender(); } catch (e) { toast(e.message, 'error'); }
  },
  async 'toggle-ai-code'() {
    try { await aiSettings({ code_enabled: !state.ai.code_enabled }); stillRender(); } catch (e) { toast(e.message, 'error'); }
  },
  async 'ai-provider'(el) {
    if (el.dataset.id === state.ai.provider) return;
    try {
      await aiSettings({ provider: el.dataset.id, model: '' });
      state.aiTest = null; state.aiModels = [];
      stillRender();
      if (el.dataset.id === 'ollama') aiLoadSystem();
    } catch (e) { toast(e.message, 'error'); }
  },
  async 'ai-save-key'() {
    const key = $('#aiKey').value.trim();
    if (key.length < 8) { toast("That doesn't look like a full API key.", 'error'); return; }
    try {
      state.ai = await api('/api/ai/key', { method: 'PUT', body: { provider: state.ai.provider, key } });
      state.aiTest = null;
      toast(`Key saved in ${keyStore()}`);
      stillRender();
    } catch (e) { toast(e.message, 'error'); }
  },
  async 'ai-remove-key'() {
    if (!(await confirmDialog('Remove this API key?', `It's deleted from ${keyStore()}. You can add it again any time.`, 'Remove'))) return;
    try { state.ai = await api(`/api/ai/key/${state.ai.provider}`, { method: 'DELETE' }); state.aiTest = null; stillRender(); }
    catch (e) { toast(e.message, 'error'); }
  },
  async 'ai-test'() {
    const a = state.ai;
    state.aiTesting = true; stillRender();
    try {
      const r = await api('/api/ai/test', { method: 'POST', body: { provider: a.provider, model: a.model, base_url: a.provider === 'custom' ? a.base_url : '' } });
      state.aiTest = r; state.aiModels = r.models; state.aiCloud = r.cloud_models || [];
      if (r.ok && r.suggested && !r.models.includes(a.model)) await aiSettings({ model: r.suggested });
    } catch (e) { state.aiTest = { ok: false, message: e.message }; }
    state.aiTesting = false;
    stillRender();
  },
  async 'ai-withdraw'() {
    if (!(await confirmDialog('Turn off AI features?', 'This withdraws your agreement to the terms. Your saved API keys stay until you remove them.', 'Turn off'))) return;
    try { state.ai = await api('/api/ai/terms/withdraw', { method: 'POST' }); toast('AI features are off'); stillRender(); }
    catch (e) { toast(e.message, 'error'); }
  },
  async 'ai-remove-all'() {
    if (!(await confirmDialog('Remove all AI data?', 'Deletes your saved API keys, chats, linked code folders (the folders themselves aren\'t touched), suggested changes and their backups, and your AI settings and agreement. Your notes and planner data stay.', 'Remove'))) return;
    chatSave.blocked = true;                      // no save may land after the chats are removed
    try {
      await chatSave.queue;
      state.ai = await api('/api/ai/all', { method: 'DELETE' });
      state.aiTest = null; state.aiModels = []; state.aiSystem = null;
      state.chats = []; state.code = null; chatReset();                    // chats and folder links are gone too
      toast('AI data removed');
      stillRender();
    } catch (e) { toast(e.message, 'error'); } finally { chatSave.blocked = false; }
  },
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
      if (saved.next_task) upsert(state.tasks, saved.next_task);
      setTimeout(render, done ? 350 : 0);
      if (saved.next_task) toast(`Done. Next one added for ${fmt(saved.next_task.due_date, { weekday: 'short', day: 'numeric', month: 'short' })}`);
      else if (done) toast('Nice — task done');
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
  'budget-plan': () => openBudgetPlan(),
  'plan-add-row'() {
    const input = $('#planNewName');
    const name = input.value.trim();
    if (!name) return input.focus();
    if ($$('#planRows [data-category]').some(r => r.dataset.category.toLowerCase() === name.toLowerCase())) { toast('That category is already in the list', 'error'); return; }
    $('#planRows').insertAdjacentHTML('beforeend', planRow(name, ''));
    input.value = '';
    $(`#planRows [data-category="${CSS.escape(name)}"] input`).focus();
  },
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
      if (onPhone()) {                     // the share sheet: save to Files or Drive, or send it to your computer
        const name = `${(state.info.name || 'easyunitrack').toLowerCase()}-backup-${todayStr()}.json`;
        if (await window.EUT_NATIVE.saveFile(name, JSON.stringify(data, null, 2))) toast('Backup saved');
        return;
      }
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${(state.info.name || 'easyunitrack').toLowerCase()}-backup-${todayStr()}.json`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      toast('Backup downloaded');
    } catch (e) { toast(e.message, 'error'); }
  },
  async 'toggle-intro'() {
    try {
      state.startup = await api('/api/settings/startup', { method: 'PUT', body: { intro: !state.startup.intro } });
      $('#content').classList.add('still'); VIEWS.settings();
      toast(state.startup.intro ? 'Intro animation on' : 'Intro animation off');
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
    if (!(await confirmDialog(`Update to ${u.latest}?`, 'EasyUniTrack will close, install the update and open again. It takes about a minute.', 'Update now', 'primary'))) return;
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

  'new-type': () => openType(null),
  'edit-type': el => openType(Number(el.dataset.id)),
  async 'delete-type'() {
    const id = Number($('#drawerForm').dataset.id);
    const c = state.categories.find(x => x.id === id);
    const n = state.tasks.filter(t => t.category_id === id).length;
    if (!(await confirmDialog(`Delete "${c.name}"?`, n ? `${plural(n, 'task')} will keep their details but have no type.` : 'No tasks use it.'))) return;
    try {
      await api(`/api/categories/${id}`, { method: 'DELETE' });
      state.categories = state.categories.filter(x => x.id !== id);
      state.tasks.forEach(t => { if (t.category_id === id) { t.category_id = null; t.category_name = null; } });
      closeDrawer(); stillRender(); toast('Task type deleted');
    } catch (e) { toast(e.message, 'error'); }
  },

  async 'toggle-reminders'() {
    try {
      state.reminders = await api('/api/settings/reminders', { method: 'PUT', body: { ...state.reminders, daily: !state.reminders.daily } });
      stillRender(); toast(state.reminders.daily ? `Daily reminder at ${state.reminders.time}` : 'Daily reminder off');
    } catch (e) { toast(e.message, 'error'); }
  },
  async 'test-reminder'() {
    try {
      const r = await api('/api/reminders/test', { method: 'POST' });
      toast(r.shown ? 'Test notification sent' : `The notification couldn't be shown. Check that notifications are on in ${onPhone() ? "your phone's settings for EasyUniTrack" : 'Windows Settings'}.`, r.shown ? '' : 'error');
    } catch (e) { toast(e.message, 'error'); }
  },
  async 'toggle-autostart'() {
    try {
      state.autostart = await api('/api/settings/autostart', { method: 'PUT', body: { enabled: !state.autostart.enabled } });
      stillRender(); toast(state.autostart.enabled ? 'EasyUniTrack will start with Windows' : "EasyUniTrack won't start with Windows");
    } catch (e) { toast(e.message, 'error'); }
  },

  import: () => { const f = $('#importFile'); f.value = ''; f.click(); },
};

/** Re-render the current screen without the entry animation, keeping the scroll position. */
function stillRender() {
  const scroll = $('#content').scrollTop;
  $('#content').classList.add('still');
  render();
  $('#content').scrollTop = scroll;
}

async function restoreFromFile(file) {
  let data;
  try { data = JSON.parse(await file.text()); }
  catch (_) { toast("That file isn't an EasyUniTrack backup.", 'error'); return; }
  try {
    const p = await api('/api/import/preview', { method: 'POST', body: data });
    const c = p.counts;
    const when = p.exported_at ? ` from ${p.exported_at}` : '';
    const ok = await confirmDialog(`Restore the backup${when}?`,
      `It has ${plural(c.tasks, 'task')}, ${plural(c.job_applications, 'job application')}, ${plural(c.transactions, 'transaction')} and ${plural(c.subjects, 'subject')}. ` +
      'Everything in the app now will be replaced. A copy of your current data is saved first.', 'Restore', 'primary');
    if (!ok) return;
    await api('/api/import', { method: 'POST', body: data });
    await loadAll();
    stillRender();
    toast('Backup restored');
  } catch (e) { toast(e.message, 'error'); }
}

document.addEventListener('click', e => {
  const el = e.target.closest('[data-action]');
  if (!el || !ACTIONS[el.dataset.action]) return;
  e.preventDefault();
  ACTIONS[el.dataset.action](el, e);
});

// Report: the GitHub page opens as a normal link, and the reply is copied for the student to paste in
document.addEventListener('click', e => {
  const a = e.target.closest('a.chat-report');
  const m = a && chatState().messages[Number(a.dataset.i)];
  if (!m) return;
  navigator.clipboard.writeText(m.content)
    .then(() => toast('The reply is copied: paste it into the report if you like, and remove anything private'))
    .catch(() => toast('Copy the reply into the report yourself if you like (Copy under the reply).'));
});

document.addEventListener('keydown', e => {
  if (e.target.id === 'noteTopicInput' && e.key === 'Enter') { e.preventDefault(); noteTopicWrite(); return; }
  if (e.target.id === 'runCommand' && e.key === 'Enter' && !e.isComposing) { e.preventDefault(); ACTIONS['code-run'](); return; }
  // On a phone the keyboard's return key starts a new line; the send button sends
  if (e.target.id === 'chatInput' && e.key === 'Enter' && !e.shiftKey && !e.isComposing && !onPhone()) {
    e.preventDefault(); chatSend(e.target.value);
  }
});

// A file dropped on the chat is attached (anywhere else, dropping does nothing rather than open the file)
document.addEventListener('dragover', e => {
  if (e.dataTransfer?.types?.includes('Files')) { e.preventDefault(); e.dataTransfer.dropEffect = e.target.closest?.('.chat') ? 'copy' : 'none'; }
});
document.addEventListener('drop', e => {
  if (!e.dataTransfer?.files?.length) return;
  e.preventDefault();
  if (e.target.closest?.('.chat')) chatAttach(e.dataTransfer.files[0]);
});

// In the code workspace, files named in the message (an error you paste, say) join the list as you type
let codeTyping = 0;
document.addEventListener('input', e => {
  if (e.target.id === 'chatInput') {                        // the message box grows with the message, up to a limit
    e.target.style.height = 'auto';
    e.target.style.height = `${Math.min(e.target.scrollHeight, 220)}px`;
  }
  if (e.target.id !== 'chatInput' || !chatState().code) return;
  clearTimeout(codeTyping);
  codeTyping = setTimeout(() => codeChoose(e.target.value), 500);
});

document.addEventListener('change', async e => {
  if (e.target.id === 'chatFormat') { chatState().format = e.target.value; return; }
  if (e.target.id === 'chatFile') { if (e.target.files[0]) chatAttach(e.target.files[0]); return; }
  if (e.target.id === 'aiKeepChats') {
    const days = Number(e.target.value), before = state.ai?.keep_chats_days || 0;
    const label = (KEEP_CHATS.find(([v]) => v === days) || [])[1] || '';
    if (days && (!before || days < before) && !(await confirmDialog('Delete older chats?',
      `Saved chats you haven't continued for ${label.toLowerCase()} are deleted now, and from now on. This can't be undone.`, 'Delete them'))) {
      e.target.value = String(before);
      return;
    }
    try {
      const r = await aiSettings({ keep_chats_days: days });
      toast(r.clean_up_failed ? "Saved. Older chats couldn't be deleted just now, so they'll be deleted when EasyUniTrack next starts."
        : r.removed_chats ? `Deleted ${plural(r.removed_chats, 'older chat')}` : days ? `Chats are kept for ${label.toLowerCase()}` : 'Chats are kept until you delete them');
      loadChats();
    } catch (err) { toast(err.message, 'error'); e.target.value = String(before); }
    return;
  }
  if (e.target.dataset.fileRange) {                        // the pages, slides or sections to send
    const f = chatState().file, i = Number(e.target.value);
    if (!f?.parts) return;
    if (e.target.dataset.fileRange === 'from') { f.from = i; f.to = Math.max(i, chatFileFit(f, i)); }   // as many as fit from there
    else { f.to = i; f.from = Math.min(f.from, i); }
    chatRefresh({ keepDraft: true });
    return;
  }
  if (e.target.id === 'codeFolder') { codeSelectFolder(Number(e.target.value)); return; }
  if (e.target.id === 'runKeep') { codeState().keep = e.target.checked; codeRunRefresh(); return; }
  if (e.target.id === 'runLimit') { codeState().limit = Number(e.target.value); return; }
  if (e.target.id === 'runCommand') {                      // picked from the list, or typed
    const k = codeState(), pick = (k.commands?.commands || []).find(c => c.command === e.target.value);
    k.cmd = e.target.value; k.cmdEdited = true;
    if (pick) { k.keep = !!pick.keep_running; codeRunRefresh(); }
    return;
  }
  if (e.target.classList.contains('chat-reformat') && e.target.value) {
    const c = chatState(), f = e.target.value;
    c.format = f;
    chatSend(`Show that again ${FORMAT_ASK[f]}.`);
    return;
  }
  if (e.target.id === 'importFile' && e.target.files[0]) { restoreFromFile(e.target.files[0]); return; }
  if (e.target.classList.contains('ai-tick')) { $('#aiAgree').disabled = $$('.ai-tick').some(c => !c.checked); return; }
  if (e.target.id === 'aiModel' || e.target.id === 'aiBaseUrl') {
    try { await aiSettings(e.target.id === 'aiModel' ? { model: e.target.value } : { base_url: e.target.value.trim() }); state.aiTest = null; stillRender(); }
    catch (err) { toast(err.message, 'error'); }
    return;
  }
  if (e.target.id === 'reminderTime') {
    if (!e.target.value) return;
    try {
      state.reminders = await api('/api/settings/reminders', { method: 'PUT', body: { ...state.reminders, time: e.target.value } });
      toast(`Daily reminder at ${state.reminders.time}`);
    } catch (err) { toast(err.message, 'error'); }
    return;
  }
  if (e.target.id !== 'settingsCurrency') return;
  try {
    const m = await api('/api/settings/money', { method: 'PUT', body: { currency: e.target.value } });
    setCurrency(m.currency); state.currencyChosen = true;
    $('#content').classList.add('still'); VIEWS.settings();
    toast(`Currency set to ${m.currency}`);
  } catch (err) { toast(err.message, 'error'); }
});

document.addEventListener('submit', e => {
  const form = e.target;
  if (form.id === 'chatForm') { e.preventDefault(); const t = $('#chatInput', form); chatSend(t.value); return; }
  if (form.id === 'runInput') {                            // a line of keyboard input for the running program
    e.preventDefault();
    const run = codeState().run, box = form.line, line = box.value;
    if (!run || run.status !== 'running') return;
    box.value = '';
    api(`/api/code/runs/${run.id}/input`, { method: 'POST', body: { text: line } })
      .then(() => {                                          // show what was typed, as a terminal would
        run.text += line + '\n';
        const pre = $('#runText');
        if (pre) { pre.textContent = run.text.replace(ANSI, ''); pre.scrollTop = pre.scrollHeight; }
      })
      .catch(err => toast(err.message, 'error'));
    return;
  }
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
/** Fade out the start-up overlay that continues the desktop splash animation. */
function finishIntro() {
  const el = $('#intro');
  if (!el || el.hidden) return;
  requestAnimationFrame(() => el.classList.add('leaving'));
  setTimeout(() => { el.hidden = true; el.classList.remove('leaving'); }, 650);
  history.replaceState(null, '', location.pathname + location.hash);   // drop ?from=splash&ap=…
}

(async function init() {
  $('.brand-mark').innerHTML = BRAND_MARK;
  // Make rows reachable by keyboard
  new MutationObserver(() => $$('.task, .job, .closed-row').forEach(r => { if (!r.hasAttribute('tabindex')) r.tabIndex = 0; }))
    .observe($('#content'), { childList: true, subtree: true });
  try {
    await loadAll();
  } catch (e) {
    $('#content').innerHTML = `<div class="card">${emptyState('alert', "Couldn't load your data", esc(e.message))}</div>`;
    finishIntro();
    return;
  }
  render();
  finishIntro();
  api('/api/diag/client-ready', { method: 'POST' }).catch(() => {});   // recorded in the log, checked by CI
  if (!onPhone()) checkForUpdates(false);                              // the phone's app store updates it
})();
