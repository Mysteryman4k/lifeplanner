/* The AI routes (/api/ai/…) on the phone: the desktop's ai/routes.py and ai/chats.py.
   Gate: apart from reading the state and the terms, nothing works until the current terms are agreed.
   These routes open their own short transactions: a reply streams for a while, and the network is never
   waited on while the database is held. */
import type { Row } from '../db/db';
import { HttpError, body, intParam, queryInt, queryStr, type Handler, type Req } from '../http';
import { bool, int, lit, optInt, parse, str, ValueError, type Model, type Rule } from '../validate';
import { dumpJson, getSetting, putSetting, type Ctx } from '../api/context';
import * as files from './files';
import * as prompts from './prompts';
import { PRESETS, ProviderError, getProvider, suggestModel, type StreamEvent } from './providers';
import { termsDict, TERMS_VERSION, TICKS } from './terms';
import { ActionLog, TaskStore, TaskTools } from './tools';

const SETTING_KEY = 'ai';
const MAX_HISTORY = 40;
const MAX_TOOL_ROUNDS = 5;
const PROVIDERS = ['anthropic', 'openai', 'deepseek', 'custom'] as const;
const KEEP_CHATS = [0, 30, 90, 180, 365];
const MAX_MESSAGES = 400, MAX_META = 200_000, LIST_LIMIT = 100, MAX_SUMMARY = 8000;
const KEEP_DAYS = 90, KEEP_ACTIONS = 500, KEEP_CHANGES = 200;

const AISettings: Model = {
  assistant_enabled: bool({ default: false }),
  code_enabled: bool({ default: false }),
  provider: lit(['', ...PROVIDERS], { default: '' }),
  model: str({ maxLen: 200 }),
  base_url: str({ maxLen: 500 }),
  terms_version: str(),
  terms_agreed_at: str(),
  run_notice: bool({ default: false }),
  keep_chats_days: lit(KEEP_CHATS, { default: 0 }),
  think: bool({ default: false }),
};
const AISettingsUpdate: Model = Object.fromEntries(
  ['assistant_enabled', 'code_enabled', 'provider', 'model', 'base_url', 'keep_chats_days', 'think'].map(k => [k, { ...AISettings[k], default: null }]));

const ChatMessage: Rule = { kind: 'model', model: { role: lit(['user', 'assistant'], { required: true }), content: str({ required: true, minLen: 1, maxLen: 20000 }) } };
const Attachment: Model = {
  name: str({ required: true, minLen: 1, maxLen: 200 }),
  included: str({ maxLen: 200 }),
  text: str({ required: true, minLen: 1, maxLen: files.CLOUD_CHARS + 20_000 }),
};
const ChatIn: Model = {
  mode: lit(['explain', 'practise', 'quiz', 'check', 'notes', 'code'], { default: 'explain' }),
  format: lit(['auto', 'notes', 'diagram', 'both', 'maths', 'code'], { default: 'auto' }),
  messages: { kind: 'list', required: true, minItems: 1, maxItems: 200, item: ChatMessage },
  task_id: optInt(),
  code: { kind: 'dict', nullable: true, default: null },
  action: lit(['videos'], { nullable: true, default: null }),
  attachment: { kind: 'model', nullable: true, default: null, model: Attachment },
  summary: str({ maxLen: 8000 }),
  think: bool({ nullable: true, default: null }),
};
const SummariseIn: Model = {
  kind: lit(['study', 'code'], { default: 'study' }),
  previous: str({ maxLen: 8000 }),
  messages: { kind: 'list', required: true, minItems: 1, maxItems: 200, item: ChatMessage },
};
const Agreement: Model = { version: str({ required: true }), ticks: { kind: 'dict', required: true } };
const KeyIn: Model = { provider: lit(PROVIDERS, { required: true }), key: str({ required: true, minLen: 8, maxLen: 500 }) };
const TestIn: Model = { provider: lit(PROVIDERS, { required: true }), model: str({ maxLen: 200 }), base_url: str({ maxLen: 500 }) };
const ConfirmIn: Model = { action_id: int({ required: true }), approve: bool({ required: true }) };
const UndoIn: Model = { action_id: int({ required: true }) };
const SavedAttachment: Model = { ...Attachment, kind: str({ maxLen: 20 }), chars: int({ default: 0, ge: 0 }) };
const ChatSave: Model = {
  title: str({ maxLen: 120 }),
  kind: lit(['study', 'code'], { default: 'study' }),
  mode: str({ default: 'explain', maxLen: 20 }),
  format: str({ default: 'auto', maxLen: 20 }),
  task_id: optInt(),
  folder_id: optInt(),
  tokens: int({ default: 0, ge: 0 }),
  messages: {
    kind: 'list', required: true, minItems: 1, maxItems: MAX_MESSAGES,
    item: { kind: 'model', model: {
      role: lit(['user', 'assistant'], { required: true }),
      content: str({ maxLen: 200_000 }),
      meta: { kind: 'dict', default: {}, check: (v: object) => {
        if (JSON.stringify(v).length > MAX_META) throw new ValueError('too much detail in one message');
        return v;
      } },
    } },
  },
  attachment: { kind: 'model', nullable: true, default: null, model: SavedAttachment },
  summary: str({ maxLen: MAX_SUMMARY }),
};

type Settings = { assistant_enabled: boolean; code_enabled: boolean; provider: string; model: string; base_url: string;
  terms_version: string; terms_agreed_at: string; run_notice: boolean; keep_chats_days: number; think: boolean };

const keyName = (provider: string) => `ai-key-${provider}`;
const nowIso = () => {
  const d = new Date(), p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};

/** Old records that only matter for a while: task-change records after 90 days, and chats past the student's limit. */
export async function cleanUpRecords(ctx: Ctx, keepChatsDays?: number) {
  const { db } = ctx;
  return db.tx(async () => {
    const days = keepChatsDays ?? (await getSetting<Settings>(db, SETTING_KEY, AISettings)).keep_chats_days;
    const age = `-${KEEP_DAYS} days`;
    const removed: Record<string, number> = {};
    removed.changes = (await db.run("DELETE FROM file_changes WHERE status NOT IN ('applying', 'undoing') AND created_at < " +
      "datetime('now', 'localtime', ?) AND id NOT IN (SELECT id FROM file_changes ORDER BY id DESC LIMIT ?)", age, KEEP_CHANGES)).changes;
    removed.actions = (await db.run("DELETE FROM ai_actions WHERE status NOT IN ('pending', 'applying', 'undoing') AND created_at < " +
      "datetime('now', 'localtime', ?) AND id NOT IN (SELECT id FROM ai_actions ORDER BY id DESC LIMIT ?)", age, KEEP_ACTIONS)).changes;
    removed.chats = 0;
    if (days) {
      const old = (await db.all("SELECT id FROM conversations WHERE updated_at < datetime('now', 'localtime', ?)", `-${days} days`)).map(r => r.id);
      for (let i = 0; i < old.length; i += 500) {
        const part = old.slice(i, i + 500), marks = part.map(() => '?').join(',');
        await db.run(`DELETE FROM messages WHERE conversation_id IN (${marks})`, ...part);
        await db.run(`DELETE FROM conversations WHERE id IN (${marks})`, ...part);
      }
      removed.chats = old.length;
    }
    removed.backups = 0;
    return removed;
  });
}

export function registerAi(r: { addStream(method: string, path: string, h: Handler): void }, ctx: Ctx) {
  const { db, platform } = ctx;
  const route = (method: string, path: string, h: Handler) => r.addStream(method, path, h);

  const load = () => db.tx(() => getSetting<Settings>(db, SETTING_KEY, AISettings));
  const save = (s: Settings) => db.tx(() => putSetting(db, SETTING_KEY, dumpJson(AISettings, s)));
  const agreed = (s: Settings) => s.terms_version === TERMS_VERSION;
  const requireAgreement = async () => {
    const s = await load();
    if (!agreed(s)) throw new HttpError(403, 'Read and agree to the terms of use first.');
    return s;
  };
  const key = (provider: string) => platform.secrets.get(keyName(provider)).catch(() => null);
  const hint = async (provider: string) => {
    const k = await key(provider);
    return k && k.length >= 8 ? `…${k.slice(-4)}` : k ? 'saved' : null;
  };
  const provider = async (s: Settings) => getProvider(s.provider, {
    key: await key(s.provider), baseUrl: s.provider === 'custom' ? s.base_url || null : null, fetch: platform.fetch,
  });

  const canThink = async (s: Settings) => {
    if (s.provider !== 'anthropic' || !s.model) return false;
    return (await (await provider(s)).thinkingLevels(s.model)).length > 0;
  };

  const publicState = async (s: Settings) => {
    const ok = agreed(s);
    const p = s.provider in PRESETS ? s.provider : '';
    return {
      preview: true,
      terms: { current_version: TERMS_VERSION, agreed: ok, agreed_version: s.terms_version, agreed_at: s.terms_agreed_at,
        needs_reagreement: !!s.terms_version && !ok },
      assistant_enabled: ok && s.assistant_enabled,
      code_enabled: false,                                  // the code workspace works with folders on a computer
      run_notice: s.run_notice,
      keep_chats_days: s.keep_chats_days,
      think: s.think, can_think: ok && (await canThink(s)),
      provider: p, model: s.model, base_url: s.base_url,
      key: p ? await hint(p) : null,
      providers: Object.fromEntries(Object.entries(PRESETS).map(([k, v]) =>
        [k, { name: v.name, needs_key: v.needs_key, key_url: v.key_url, limit_url: v.limit_url, about: v.about, base_url: v.base_url }])),
    };
  };

  route('GET', '/api/ai/state', async () => publicState(await load()));
  route('GET', '/api/ai/terms', () => termsDict());

  route('POST', '/api/ai/terms/agree', async req => {
    const { data: a } = parse<Row>(Agreement, body(req));
    if (a.version !== TERMS_VERSION) throw new HttpError(409, 'These terms have been updated. Read the new version and agree again.');
    if (Object.keys(TICKS).some(k => a.ticks[k] !== true)) throw new HttpError(400, 'Tick all three boxes to agree.');
    const s = await load();
    s.terms_version = TERMS_VERSION;
    s.terms_agreed_at = nowIso();
    s.assistant_enabled = true;                           // agreeing is choosing to turn it on
    await save(s);
    return publicState(s);
  });

  route('POST', '/api/ai/run-notice', async () => {
    const s = await requireAgreement();
    s.run_notice = true;
    await save(s);
    return { run_notice: true };
  });

  route('POST', '/api/ai/terms/withdraw', async () => {
    const s = await load();
    s.terms_version = s.terms_agreed_at = '';
    s.assistant_enabled = s.code_enabled = false;
    await save(s);
    return publicState(s);
  });

  route('PUT', '/api/ai/settings', async req => {
    const { data } = parse<Row>(AISettingsUpdate, body(req));
    const s = await requireAgreement();
    if (data.code_enabled === true) throw new HttpError(400, 'The code workspace is in the desktop app: it works with project folders on your computer.');
    const keepBefore = s.keep_chats_days;
    for (const [k, v] of Object.entries(data)) if (v !== null) (s as any)[k] = typeof v === 'string' ? v.trim() : v;
    if (s.base_url && !/^https?:\/\//.test(s.base_url)) throw new HttpError(400, 'The base URL should start with http:// or https://');
    await save(s);
    const state: Row = await publicState(s);
    if (s.keep_chats_days !== keepBefore && s.keep_chats_days) {
      try {
        state.removed_chats = (await cleanUpRecords(ctx, s.keep_chats_days)).chats;
      } catch (e) {
        console.error('Clearing old chats failed', e);
        state.clean_up_failed = true;
      }
    }
    return state;
  });

  route('PUT', '/api/ai/key', async req => {
    const { data: k } = parse<Row>(KeyIn, body(req));
    await requireAgreement();
    await platform.secrets.set(keyName(k.provider), k.key.trim());
    return publicState(await load());
  });

  route('DELETE', '/api/ai/key/:provider', async req => {
    const p = req.params.provider;
    if (!(PROVIDERS as readonly string[]).includes(p)) {
      throw new HttpError(422, [{ type: 'literal_error', loc: ['path', 'provider'], msg: "Input should be 'anthropic', 'openai', 'deepseek' or 'custom'", input: p }]);
    }
    await requireAgreement();
    try {
      await platform.secrets.remove(keyName(p));
    } catch {
      throw new HttpError(500, "Couldn't remove the key from this phone's secure storage. Try again.");
    }
    return publicState(await load());
  });

  route('POST', '/api/ai/test', async req => {
    const { data: t } = parse<Row>(TestIn, body(req));
    const s = await requireAgreement();
    // Only the custom provider has a chosen address, so a saved key can never be sent somewhere else
    const p = getProvider(t.provider, { key: await key(t.provider), baseUrl: t.provider === 'custom' ? (t.base_url || s.base_url || null) : null, fetch: platform.fetch });
    let res = await p.testConnection(t.model);
    const suggested = res.ok ? suggestModel(t.provider, res.models) : '';
    if (res.ok && !t.model && suggested) res = await p.testConnection(suggested);
    return { ok: res.ok, message: res.message, models: res.models, tools: res.tools, cloud_models: res.cloud_models, suggested };
  });

  route('POST', '/api/ai/attach', async req => {
    const name = queryStr(req, 'name');
    if (name === null || name.length < 1 || name.length > 260) {
      throw new HttpError(422, [{ type: name === null ? 'missing' : 'string_too_short', loc: ['query', 'name'],
        msg: name === null ? 'Field required' : 'String should have at least 1 character', input: name }]);
    }
    const s = await requireAgreement();
    if (!s.assistant_enabled) throw new HttpError(403, 'Turn on the Study assistant in Settings first.');
    const data = req.bytes ?? new TextEncoder().encode(req.text ?? '');
    if (data.length > files.MAX_UPLOAD) throw new HttpError(413, 'That file is over 30 MB. Attach a smaller file, or just the part you need.');
    if (!platform.readPdf && name.toLowerCase().endsWith('.pdf')) throw new HttpError(400, "PDF reading isn't available in this copy of EasyUniTrack.");
    try {
      const doc = await files.extract(name, data, platform.readPdf!);
      return { ...doc, budget: files.budget() };
    } catch (e) {
      if (e instanceof files.FileError) throw new HttpError(400, e.message);
      console.error("Couldn't read an attached file", e);
      throw new HttpError(400, "That file couldn't be read. It may be damaged.");
    }
  });

  const taskContext = (taskId: number) => db.tx(async () => {
    const row = await db.get(`SELECT t.title, t.description, t.notes, t.due_date, t.priority, t.estimated_hours,
                                     s.name AS subject, c.name AS type
                              FROM tasks t LEFT JOIN subjects s ON s.id = t.subject_id
                              LEFT JOIN categories c ON c.id = t.category_id WHERE t.id = ?`, taskId);
    if (!row) return '';
    const label = (k: string) => k.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
    return [`Task: ${row.title}`, ...['subject', 'type', 'due_date', 'priority', 'estimated_hours', 'description', 'notes']
      .filter(k => row[k] !== null && row[k] !== '').map(k => `${label(k)}: ${pyValue(k, row[k])}`)].join('\n');
  });

  route('POST', '/api/ai/chat', async (req: Req) => {
    const { data: c } = parse<Row>(ChatIn, body(req));
    const s = await requireAgreement();
    if (c.mode === 'code') throw new HttpError(403, 'The code workspace is in the desktop app.');
    if (!s.assistant_enabled) throw new HttpError(403, 'Turn on the Study assistant in Settings first.');
    if (!s.provider || !s.model) throw new HttpError(400, 'Choose an AI provider and model in Settings first.');
    if (c.messages[c.messages.length - 1].role !== 'user') throw new HttpError(400, 'The last message must be yours.');
    let attached = '';
    if (c.attachment) {
      const limit = files.budget().chars;
      if (c.attachment.text.length > limit) {
        const who = s.provider === 'custom' ? 'this provider' : PRESETS[s.provider].name;
        throw new HttpError(413, `That's more of the file than ${who} can read with one question (about ${limit.toLocaleString('en-AU')} ` +
          'characters). Choose fewer pages or slides.');
      }
      const words = (t: string) => t.split(/\s+/).filter(Boolean).join(' ');
      attached = prompts.attachmentBlock(words(c.attachment.name), words(c.attachment.included), c.attachment.text);
    }
    const history: Row[] = c.messages.slice(-MAX_HISTORY);
    while (history.length && history[0].role !== 'user') history.shift();
    let system = prompts.systemPrompt(c.mode, c.task_id !== null ? await taskContext(c.task_id) : '', c.format, c.action || '');
    if (c.summary.trim()) system += '\n\n' + prompts.summaryBlock(c.summary);
    const p = await provider(s);
    p.think = c.think === null ? s.think : c.think;
    const canUseTools = (await p.supportsTools(s.model)) !== false;
    const useTools = ['explain', 'practise', 'quiz', 'check'].includes(c.mode) && canUseTools;
    const tools = useTools ? new TaskTools(new TaskStore(db, () => platform.remindersChanged?.()), new ActionLog(db)) : null;
    if (tools) system += '\n\n' + (await tools.addendum());
    if (attached) system += '\n\n' + attached;              // last: every instruction comes before the file's text

    async function* events(signal: AbortSignal) {
      // With a file attached, task changes wait for a yes: the file could contain text aimed at the assistant
      const messages: any[] = [...history];
      const state = { changes: 0, ask_first: !!attached };
      try {
        let said = false;
        let finished = false;
        for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
          let calls: Extract<StreamEvent, { type: 'tool_calls' }> | null = null;
          let fresh = true;
          for await (const ev of p.streamChat(s.model, system, messages, tools ? tools.schema : null, signal)) {
            if (ev.type === 'tool_calls') { calls = ev; continue; }
            let out: StreamEvent = ev;
            if (ev.type === 'text' && ev.text) {
              if (said && fresh) out = { ...ev, text: '\n\n' + ev.text.trimStart() };     // text after a tool call starts its own paragraph
              said = true;
              fresh = false;
            }
            yield out;
          }
          if (signal.aborted) return;
          if (!calls || !tools) { finished = true; break; }
          const [results, appEvents] = await tools.runRound(calls.calls, state);
          for (const ev of appEvents) yield ev;
          messages.push(calls.assistant, ...p.toolResults(results));
        }
        if (!finished) yield { type: 'error', message: 'The assistant took too many steps and was stopped.' };
      } catch (e) {
        if (signal.aborted) return;
        yield { type: 'error', message: e instanceof ProviderError ? e.message : 'Something went wrong while getting the reply. Try again.' };
        if (!(e instanceof ProviderError)) console.error(e);
      }
      yield { type: 'done', model: s.model };
    }
    return sse(events, req.signal);
  });

  route('POST', '/api/ai/summarise', async req => {
    const { data: b } = parse<Row>(SummariseIn, body(req));
    const s = await requireAgreement();
    if (b.kind === 'code' || !s.assistant_enabled) throw new HttpError(403, 'Turn on the Study assistant in Settings first.');
    if (!s.provider || !s.model) throw new HttpError(400, 'Choose an AI provider and model in Settings first.');
    const p = await provider(s);
    let text = '', used = 0;
    try {
      for await (const ev of p.streamChat(s.model, prompts.SUMMARISE, [{ role: 'user', content: prompts.summariseRequest(b.previous, b.messages) }])) {
        if (ev.type === 'text') text += ev.text;
        else if (ev.type === 'usage') used = (ev.input || 0) + (ev.output || 0);
      }
    } catch (e) {
      if (e instanceof ProviderError) throw new HttpError(502, e.message);
      throw e;
    }
    text = text.trim();
    if (!text) throw new HttpError(502, 'The summary came back empty.');
    return { summary: [...text].slice(0, 8000).join(''), tokens: used };
  });

  const taskTools = () => new TaskTools(new TaskStore(db, () => platform.remindersChanged?.()), new ActionLog(db));
  route('POST', '/api/ai/confirm', async req => {
    const { data: cf } = parse<Row>(ConfirmIn, body(req));
    await requireAgreement();
    return taskTools().confirm(cf.action_id, cf.approve);
  });
  route('POST', '/api/ai/undo', async req => {
    const { data: u } = parse<Row>(UndoIn, body(req));
    await requireAgreement();
    return taskTools().undo(u.action_id);
  });

  // "This PC" is for local models, which a phone doesn't run
  route('GET', '/api/ai/system', () => ({ ram_gb: 0, advice: '', ollama: { running: false, version: '' } }));

  route('DELETE', '/api/ai/all', async () => {
    const removed: string[] = [], failed: string[] = [];
    for (const [id, preset] of Object.entries(PRESETS)) {
      if (!(preset.needs_key || id === 'custom')) continue;
      const had = (await key(id)) !== null;
      try {
        await platform.secrets.remove(keyName(id));
        if (had) removed.push(preset.name);
      } catch {
        failed.push(preset.name);
      }
    }
    if (failed.length) {
      const done = removed.length ? ` The key for ${removed.join(', ')} was removed, so save it again if you still need it.` : ' No keys were removed.';
      throw new HttpError(500, `Couldn't remove the saved key for ${failed.join(', ')} from this phone's secure storage.${done} Your AI settings weren't changed. Try again.`);
    }
    await db.tx(async () => {
      for (const table of ['messages', 'conversations', 'file_changes', 'ai_actions', 'code_folders']) await db.run(`DELETE FROM ${table}`);
    });
    const s = parse<Settings>(AISettings, {}).data;
    await save(s);
    return publicState(s);
  });

  // ── Saved chats ──
  const gate = async () => {
    if ((await load()).terms_version !== TERMS_VERSION) throw new HttpError(403, 'Read and agree to the terms of use first.');
  };
  const titleOf = (c: Row) => {
    if (c.title.trim()) return [...c.title.trim()].slice(0, 120).join('');
    const first = c.messages.find((m: Row) => m.role === 'user' && m.content.trim())?.content ?? 'Chat';
    const words = [...first.split(/\s+/).filter(Boolean).join(' ')];
    return words.slice(0, 60).join('') + (words.length > 60 ? '…' : '');
  };
  const exists = async (table: string, id: number | null) => id === null || !!(await db.get(`SELECT 1 FROM ${table} WHERE id=?`, id));
  const write = async (chatId: number, c: Row) => {
    const taskId = (await exists('tasks', c.task_id)) ? c.task_id : null;
    const folderId = (await exists('code_folders', c.folder_id)) ? c.folder_id : null;
    const attachment = c.attachment ? dumpJson(SavedAttachment, c.attachment) : '';
    await db.run("UPDATE conversations SET title=?, kind=?, mode=?, format=?, task_id=?, folder_id=?, tokens=?, attachment=?, summary=?, " +
      "updated_at=datetime('now','localtime') WHERE id=?",
    titleOf(c), c.kind, c.mode, c.format, taskId, folderId, c.tokens, attachment, c.summary, chatId);
    await db.run('DELETE FROM messages WHERE conversation_id=?', chatId);
    for (const [i, m] of (c.messages as Row[]).entries()) {
      await db.run('INSERT INTO messages (conversation_id, position, role, content, meta) VALUES (?, ?, ?, ?, ?)',
        chatId, i, m.role, m.content, JSON.stringify(m.meta));
    }
  };

  route('GET', '/api/ai/chats', async req => {
    const limit = queryInt(req, 'limit') ?? 30;
    await gate();
    return db.tx(() => db.all(
      'SELECT c.id, c.title, c.kind, c.mode, c.task_id, c.folder_id, c.updated_at, f.name AS folder_name, ' +
      "CASE WHEN json_valid(c.attachment) THEN json_extract(c.attachment, '$.name') END AS attachment_name, " +
      '(SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS count ' +
      'FROM conversations c LEFT JOIN code_folders f ON f.id = c.folder_id ' +
      'ORDER BY c.updated_at DESC, c.id DESC LIMIT ?', Math.max(1, Math.min(limit, LIST_LIMIT))));
  });

  route('GET', '/api/ai/chats/:chat_id', async req => {
    const id = intParam(req, 'chat_id');
    await gate();
    return db.tx(async () => {
      const row = await db.get('SELECT * FROM conversations WHERE id=?', id);
      if (!row) throw new HttpError(404, 'That chat has been deleted.');
      const messages = (await db.all('SELECT * FROM messages WHERE conversation_id=? ORDER BY position', id))
        .map(m => ({ role: m.role, content: m.content, meta: JSON.parse(m.meta || '{}') }));
      let attachment = null;
      try {                                                   // a damaged one (from an edited backup) is left off
        attachment = row.attachment ? parse(SavedAttachment, JSON.parse(row.attachment)).data : null;
      } catch { attachment = null; }
      return { ...row, attachment, messages };
    });
  });

  route('POST', '/api/ai/chats', async req => {
    const { data: c } = parse<Row>(ChatSave, body(req));
    await gate();
    return db.tx(async () => {
      const id = (await db.run("INSERT INTO conversations (title) VALUES ('')")).lastId;
      await write(id, c);
      return { id, title: titleOf(c) };
    });
  });

  route('PUT', '/api/ai/chats/:chat_id', async req => {
    const id = intParam(req, 'chat_id');
    const { data: c } = parse<Row>(ChatSave, body(req));
    await gate();
    return db.tx(async () => {
      if (!(await db.get('SELECT 1 FROM conversations WHERE id=?', id))) throw new HttpError(404, 'That chat has been deleted.');
      await write(id, c);
      return { id, title: titleOf(c) };
    });
  });

  route('DELETE', '/api/ai/chats/:chat_id', async req => {
    const id = intParam(req, 'chat_id');
    await gate();
    await db.tx(async () => {
      await db.run('DELETE FROM messages WHERE conversation_id=?', id);
      await db.run('DELETE FROM conversations WHERE id=?', id);
    });
    return { ok: true };
  });

  // The code workspace links folders on a computer; the phone has none to list
  route('GET', '/api/code/folders', () => []);
}

/** A value as the desktop's f-string shows it: estimated hours are stored as a decimal, so 4 hours reads "4.0". */
function pyValue(k: string, v: unknown) {
  return k === 'estimated_hours' && typeof v === 'number' && Number.isInteger(v) ? v.toFixed(1) : String(v);
}

/** Server-sent events from an async generator, ending when it does or when the screen stops listening. */
function sse(gen: (signal: AbortSignal) => AsyncGenerator<unknown>, outer?: AbortSignal): Response {
  const ctrl = new AbortController();
  const enc = new TextEncoder();
  let stream: ReadableStreamDefaultController<Uint8Array>;
  const abort = () => {
    ctrl.abort();
    try { stream.error(new DOMException('The user aborted a request.', 'AbortError')); } catch { /* already closed */ }
  };
  outer?.addEventListener('abort', abort);
  const body = new ReadableStream<Uint8Array>({
    async start(c) {
      stream = c;
      try {
        for await (const ev of gen(ctrl.signal)) {
          if (ctrl.signal.aborted) break;
          c.enqueue(enc.encode(`data: ${JSON.stringify(ev)}\n\n`));
        }
        if (!ctrl.signal.aborted) c.close();
      } catch (e) {
        if (!ctrl.signal.aborted) c.error(e);
      } finally {
        outer?.removeEventListener('abort', abort);
      }
    },
    cancel() { ctrl.abort(); },
  });
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' } });
}
