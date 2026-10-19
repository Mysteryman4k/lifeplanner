/* AI providers on the phone: the desktop's ai/providers (base, anthropic, openai_compat), over the phone's network.
   Ollama isn't offered: it runs models on a computer, not a phone. Model lists always come from the provider itself. */

export class ProviderError extends Error {}

export const CUT_OFF = 'The reply stopped at its length limit. Ask the assistant to carry on, or to be shorter.';
const CREDENTIAL_HEADERS = new Set(['authorization', 'x-api-key']);
const MAX_SSE_LINE = 1024 * 1024;
const LOOPBACK = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);
const TIMEOUT_MS = 20_000;

export interface Preset {
  name: string; kind: 'anthropic' | 'openai'; base_url: string; needs_key: boolean;
  key_url: string; limit_url: string; about: string; suggest: string[];
}

export const PRESETS: Record<string, Preset> = {
  anthropic: {
    name: 'Anthropic', kind: 'anthropic', base_url: 'https://api.anthropic.com', needs_key: true,
    key_url: 'https://console.anthropic.com/settings/keys', limit_url: 'https://console.anthropic.com/settings/limits',
    about: 'Claude models. Needs an Anthropic account with API credit (18+). Light study use typically costs a few cents a session with a small model.',
    suggest: ['haiku'],
  },
  openai: {
    name: 'OpenAI', kind: 'openai', base_url: 'https://api.openai.com/v1', needs_key: true,
    key_url: 'https://platform.openai.com/api-keys', limit_url: 'https://platform.openai.com/settings/organization/limits',
    about: 'GPT models. Needs an OpenAI platform account with API credit (18+), separate from ChatGPT. Small models cost a few cents a session.',
    suggest: ['mini'],
  },
  deepseek: {
    name: 'DeepSeek', kind: 'openai', base_url: 'https://api.deepseek.com/v1', needs_key: true,
    key_url: 'https://platform.deepseek.com/api_keys', limit_url: 'https://platform.deepseek.com/top_up',
    about: 'DeepSeek models. Prepaid credit, so your balance is your limit. Usually the cheapest option.',
    suggest: ['chat'],
  },
  custom: {
    name: 'Custom', kind: 'openai', base_url: '', needs_key: false, key_url: '', limit_url: '',
    about: 'Any OpenAI-compatible service, such as OpenRouter or Groq. Enter its base URL, and an API key if it needs one.',
    suggest: [],
  },
};

export interface TestResult { ok: boolean; message: string; models: string[]; tools: boolean | null; cloud_models: string[] }
export type StreamEvent =
  | { type: 'text'; text: string }
  | { type: 'usage'; input: number; output: number }
  | { type: 'error'; message: string }
  | { type: 'tool_calls'; calls: ToolCall[]; assistant: any };
export interface ToolCall { id: string; name: string; args: Record<string, any> }
export interface ToolSpec { name: string; description: string; parameters: unknown }

const hostOf = (url: string) => { try { return new URL(url).hostname.replace(/^\[|\]$/g, ''); } catch { return ''; } };
const isLoopback = (url: string) => LOOPBACK.has(hostOf(url)) || LOOPBACK.has(`[${hostOf(url)}]`);

/** Keys may only travel over HTTPS (or plain HTTP to this device). */
export function secureForKeys(url: string) {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' || (u.protocol === 'http:' && isLoopback(url));
  } catch {
    return false;
  }
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

export abstract class Provider {
  readTimeoutMs = 120_000;
  think = false;
  chatModel = '';
  cloudModels: string[] = [];

  constructor(public id: string, public baseUrl: string, public key: string | null, protected fetchFn: typeof fetch) {}

  abstract listModels(): Promise<string[]>;
  abstract streamChat(model: string, system: string, messages: any[], tools?: ToolSpec[] | null, signal?: AbortSignal): AsyncGenerator<StreamEvent>;
  abstract toolResults(results: [ToolCall, string][]): any[];

  async supportsTools(_model: string): Promise<boolean | null> { return true; }
  async thinkingLevels(_model: string): Promise<(string | boolean)[]> { return []; }

  displayName() { return PRESETS[this.id]?.name ?? this.id; }
  /** Redirects aren't followed (a key must only go to the address chosen), so one means the address is wrong. */
  redirected() { return new ProviderError(`${this.displayName()} sent the request somewhere else. Check the base URL.`); }
  unreachableMessage() { return `Couldn't reach ${this.displayName()}. Check your internet connection.`; }

  async testConnection(model = ''): Promise<TestResult> {
    let models: string[];
    try {
      models = await this.listModels();
    } catch (e) {
      if (e instanceof ProviderError) return { ok: false, message: e.message, models: [], tools: null, cloud_models: [] };
      throw e;
    }
    if (!models.length) return { ok: true, message: 'Connected, but no models are available yet.', models: [], tools: null, cloud_models: [] };
    const tools = model ? await this.supportsTools(model) : null;
    let msg = 'Connected.';
    if (tools === true) msg += ' Tools supported.';
    else if (tools === false) msg += " This model can't use tools, so task actions will be off.";
    return { ok: true, message: msg, models, tools, cloud_models: [] };
  }

  private guard(headers: Record<string, string>) {
    if (!this.baseUrl) throw new ProviderError("Enter the service's base URL first.");
    if (Object.keys(headers).some(h => CREDENTIAL_HEADERS.has(h.toLowerCase())) && !secureForKeys(this.baseUrl)) {
      throw new ProviderError('Your API key would be sent without encryption. Use an https:// address.');
    }
  }

  /** A plain message for an error status (body: the start of the reply, for services that say why). */
  raiseForStatus(status: number, name: string, body = ''): never | void {
    if (status === 401 || status === 403) {
      throw new ProviderError("That key wasn't accepted. Check it was copied in full, and that it's still active.");
    }
    if (status === 404) {
      const explained = this.serviceMessage(body);
      if (this.chatModel && explained.toLowerCase().includes(this.chatModel.toLowerCase())) {
        throw new ProviderError(`${name} doesn't recognise the model chosen in Settings (${explained}). Choose another one in Settings.`);
      }
      throw new ProviderError(`${name} doesn't recognise that address or model. Check the base URL and model.`);
    }
    if (status === 429) {
      throw new ProviderError(`${name} says you've hit a rate or spending limit. Wait a little, or check your account's credit and limits.`);
    }
    const explained = status === 400 || status === 422 ? this.serviceMessage(body) : '';
    if (explained) throw new ProviderError(`${name} couldn't answer: ${explained}`);
    if (status >= 400) throw new ProviderError(`${name} returned an error (${status}). Try again later.`);
  }

  /** The service's own explanation, short, without its request id and with anything like a key taken out. */
  serviceMessage(body: string): string {
    let data: any;
    try { data = JSON.parse(body); } catch { return ''; }
    const err = data && typeof data === 'object' && !Array.isArray(data) ? data.error : null;
    let msg = err && typeof err === 'object' ? err.message : err;
    if (typeof msg !== 'string') return '';
    msg = msg.split(/\s+/).filter(Boolean).join(' ');
    if (this.key) msg = msg.replace(new RegExp([...this.key].map(escapeRe).join('\\s*'), 'g'), '[key]');
    msg = msg.replace(/\s*\(request[_ ]id:[^)]*\)/gi, '');
    msg = msg.replace(/\b(?:sk|pk|key|api[_-]?key)[-_][A-Za-z0-9_-]{6,}|\bAIza[0-9A-Za-z_-]{20,}|\bBearer\s+\S+/gi, '[key]');
    msg = msg.replace(/\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{32,}/g, '[key]');
    return [...msg].length <= 240 ? msg : [...msg].slice(0, 239).join('') + '…';
  }

  async request(method: string, path: string, headers: Record<string, string> = {}, json?: unknown, timeoutMs = TIMEOUT_MS): Promise<any> {
    const name = this.displayName();
    this.guard(headers);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    let res: Response;
    let text: string;
    try {
      res = await this.fetchFn(this.baseUrl + path, {
        method, signal: ctrl.signal, redirect: 'manual',
        headers: json === undefined ? headers : { ...headers, 'Content-Type': 'application/json' },
        body: json === undefined ? undefined : JSON.stringify(json),
      });
      text = await res.text();
    } catch (e) {
      if (ctrl.signal.aborted) throw new ProviderError(`${name} took too long to answer. Try again in a moment.`);
      throw new ProviderError(this.unreachableMessage());
    } finally {
      clearTimeout(timer);
    }
    if (res.status >= 400) this.raiseForStatus(res.status, name, text.slice(0, 2000));
    if (res.status < 200 || res.status >= 300) throw this.redirected();
    try {
      return JSON.parse(text);
    } catch {
      throw new ProviderError(`${name} sent a reply EasyUniTrack couldn't read. Check the base URL.`);
    }
  }

  /** POST and yield each server-sent-event data line, with the same checks and plain errors as request(). */
  async *streamLines(path: string, headers: Record<string, string>, json: unknown, signal?: AbortSignal): AsyncGenerator<string> {
    const name = this.displayName();
    this.guard(headers);
    const ctrl = new AbortController();
    const stopped = () => ctrl.abort();
    signal?.addEventListener('abort', stopped);
    let timedOut = false;
    let timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, this.readTimeoutMs);
    const waitMore = () => {
      clearTimeout(timer);
      timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, this.readTimeoutMs);
    };
    try {
      let res: Response;
      try {
        res = await this.fetchFn(this.baseUrl + path, {
          method: 'POST', signal: ctrl.signal, redirect: 'manual',
          headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(json),
        });
      } catch {
        if (signal?.aborted) return;
        if (timedOut) throw new ProviderError(`${name} took too long to answer. Try again in a moment.`);
        throw new ProviderError(this.unreachableMessage());
      }
      if (res.status >= 400) this.raiseForStatus(res.status, name, (await res.text()).slice(0, 2000));
      if (res.status < 200 || res.status >= 300) throw this.redirected();
      if (!res.body) throw new ProviderError(`${name} sent a reply EasyUniTrack couldn't read. Check the base URL.`);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      const tooLong = () => new ProviderError(`${name} sent a reply EasyUniTrack couldn't read (a line was too long). Check the base URL, or try again.`);
      for (;;) {
        let chunk: ReadableStreamReadResult<Uint8Array>;
        try {
          chunk = await reader.read();
        } catch {
          if (signal?.aborted) return;
          if (timedOut) throw new ProviderError(`${name} took too long to answer. Try again in a moment.`);
          throw new ProviderError(`The connection to ${name} dropped. Try again.`);
        }
        waitMore();
        buf += chunk.done ? dec.decode() : dec.decode(chunk.value, { stream: true });
        let cut: number;
        while ((cut = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, cut).replace(/\r$/, '');
          buf = buf.slice(cut + 1);
          if (line.length > MAX_SSE_LINE) throw tooLong();
          if (line.startsWith('data:')) {
            const data = line.slice(5).trim();
            if (data && data !== '[DONE]') yield data;
          }
        }
        if (buf.length > MAX_SSE_LINE) throw tooLong();
        if (chunk.done) break;
      }
      const last = buf.replace(/\r$/, '');
      if (last.startsWith('data:')) {
        const data = last.slice(5).trim();
        if (data && data !== '[DONE]') yield data;
      }
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', stopped);
    }
  }
}

// ── Anthropic ──
const API_VERSION = '2023-06-01';
const MAX_TOKENS = 8192;
const THINK_BUDGET = 4096;
const MODEL_TTL = 600_000, MODEL_FAILED_TTL = 30_000;
const MODELS = new Map<string, [number, any]>();

export class AnthropicProvider extends Provider {
  headers(): Record<string, string> {
    if (!this.key) throw new ProviderError('Add your Anthropic API key first.');
    // The phone calls Anthropic directly, as a browser would (the key never leaves the phone otherwise)
    return { 'x-api-key': this.key, 'anthropic-version': API_VERSION, 'anthropic-dangerous-direct-browser-access': 'true' };
  }

  async listModels() {
    const data = await this.request('GET', '/v1/models?limit=100', this.headers());
    return (data?.data ?? []).map((m: any) => m?.id).filter(Boolean);
  }

  async modelInfo(model: string) {
    const headers = this.headers();
    const cacheKey = `${this.baseUrl}|${model}|${await shortHash(this.key!)}`;
    const hit = MODELS.get(cacheKey);
    if (hit && Date.now() < hit[0]) {
      if (hit[1] instanceof ProviderError) throw hit[1];
      return hit[1];
    }
    try {
      const data = await this.request('GET', `/v1/models/${model}`, headers, undefined, 6000);
      MODELS.set(cacheKey, [Date.now() + MODEL_TTL, data]);
      return data;
    } catch (e) {
      if (e instanceof ProviderError) MODELS.set(cacheKey, [Date.now() + MODEL_FAILED_TTL, e]);
      throw e;
    }
  }

  override async thinkingLevels(model: string) {
    let caps: any;
    try {
      caps = (await this.modelInfo(model))?.capabilities || {};
    } catch (e) {
      if (e instanceof ProviderError) return [];
      throw e;
    }
    const thinking = caps.thinking || {};
    if (!thinking.supported) return [];
    const types = thinking.types || {};
    const levels: string[] = ['disabled', 'between_tools', 'adaptive', 'enabled'].filter(t => types[t]?.supported);
    if (caps.effort?.low?.supported) levels.push('effort');
    return levels;
  }

  /** Quick replies unless the student turned on Think (see the desktop's AnthropicProvider.request_options). */
  async requestOptions(model: string): Promise<Record<string, unknown>> {
    const levels = await this.thinkingLevels(model);
    if (!this.think) {
      if (levels.includes('disabled')) return { thinking: { type: 'disabled' } };
      if (levels.includes('between_tools')) return { thinking: { type: 'between_tools' } };
      return levels.includes('effort') ? { output_config: { effort: 'low' } } : {};
    }
    if (levels.includes('adaptive')) return { thinking: { type: 'adaptive', display: 'omitted' } };
    if (levels.includes('enabled')) return { thinking: { type: 'enabled', budget_tokens: THINK_BUDGET } };
    return {};
  }

  async *streamChat(model: string, system: string, messages: any[], tools?: ToolSpec[] | null, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
    this.chatModel = model;
    const body: Record<string, unknown> = { model, max_tokens: MAX_TOKENS, system, messages, stream: true, ...(await this.requestOptions(model)) };
    if (tools?.length) body.tools = tools.map(t => ({ name: t.name, description: t.description, input_schema: t.parameters }));
    const usage = { type: 'usage' as const, input: 0, output: 0 };
    let stop = '';
    const blocks = new Map<number, any>();
    for await (const data of this.streamLines('/v1/messages', this.headers(), body, signal)) {
      const ev = JSON.parse(data);
      const kind = ev.type;
      if (kind === 'content_block_start') {
        const b = ev.content_block || {};
        let block: any;
        if (b.type === 'tool_use') block = { type: 'tool_use', id: b.id, name: b.name, json: '' };
        else if (b.type === 'thinking') block = { type: 'thinking', thinking: b.thinking ?? '', signature: b.signature ?? '' };
        else if (b.type === 'redacted_thinking') block = { type: 'redacted_thinking', data: b.data ?? '' };
        else block = { type: 'text', text: '' };
        blocks.set(ev.index ?? 0, block);
      } else if (kind === 'content_block_delta') {
        const d = ev.delta || {};
        const i = ev.index ?? 0;
        if (!blocks.has(i)) blocks.set(i, { type: 'text', text: '' });
        const block = blocks.get(i);
        if (d.type === 'text_delta') {
          block.text = (block.text ?? '') + d.text;
          yield { type: 'text', text: d.text };
        } else if (d.type === 'input_json_delta') block.json = (block.json ?? '') + (d.partial_json ?? '');
        else if (d.type === 'thinking_delta') block.thinking = (block.thinking ?? '') + (d.thinking ?? '');
        else if (d.type === 'signature_delta') block.signature = (block.signature ?? '') + (d.signature ?? '');
      } else if (kind === 'message_start') {
        usage.input = ev.message?.usage?.input_tokens ?? 0;
      } else if (kind === 'message_delta') {
        usage.output = ev.usage?.output_tokens ?? usage.output;
        stop = ev.delta?.stop_reason || stop;
      } else if (kind === 'error') {
        throw new ProviderError(`Anthropic stopped with an error: ${ev.error?.message ?? 'unknown'}`);
      }
    }
    yield usage;
    if (stop === 'max_tokens') {
      yield { type: 'error', message: CUT_OFF };
      return;                                          // a tool call cut off part way is never run
    }
    const calls: ToolCall[] = [], content: any[] = [];
    for (const [, b] of [...blocks.entries()].sort((x, y) => x[0] - y[0])) {
      if (b.type === 'tool_use') {
        let args = {};
        try { args = JSON.parse(b.json || '{}'); } catch { args = {}; }
        calls.push({ id: b.id, name: b.name, args });
        content.push({ type: 'tool_use', id: b.id, name: b.name, input: args });
      } else if (b.type === 'thinking') content.push({ type: 'thinking', thinking: b.thinking, signature: b.signature });
      else if (b.type === 'redacted_thinking') content.push({ type: 'redacted_thinking', data: b.data });
      else if (b.text) content.push({ type: 'text', text: b.text });
    }
    if (calls.length) yield { type: 'tool_calls', calls, assistant: { role: 'assistant', content } };
  }

  toolResults(results: [ToolCall, string][]) {
    return [{ role: 'user', content: results.map(([call, text]) => ({ type: 'tool_result', tool_use_id: call.id, content: text })) }];
  }
}

async function shortHash(s: string) {
  const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)));
  return [...bytes.slice(0, 8)].map(b => b.toString(16).padStart(2, '0')).join('');
}

// ── OpenAI-compatible (OpenAI, DeepSeek, custom services) ──
export class OpenAICompatProvider extends Provider {
  headers(): Record<string, string> {
    if (this.key) return { Authorization: `Bearer ${this.key}` };
    if (PRESETS[this.id]?.needs_key) throw new ProviderError(`Add your ${this.displayName()} API key first.`);
    return {};
  }

  async listModels() {
    const data = await this.request('GET', '/models', this.headers());
    const items = data && typeof data === 'object' && Array.isArray(data.data) ? data.data : [];
    return items.filter((m: any) => m && typeof m === 'object' && m.id).map((m: any) => String(m.id)).sort();
  }

  async *streamChat(model: string, system: string, messages: any[], tools?: ToolSpec[] | null, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
    this.chatModel = model;
    const body: Record<string, unknown> = { model, stream: true, stream_options: { include_usage: true },
      messages: [{ role: 'system', content: system }, ...messages] };
    if (tools?.length) {
      body.tools = tools.map(t => ({ type: 'function', function: { name: t.name, description: t.description, parameters: t.parameters } }));
    }
    const usage = { type: 'usage' as const, input: 0, output: 0 };
    let text = '', stop = '';
    const calls = new Map<number, { id: string; name: string; arguments: string }>();
    for await (const data of this.streamLines('/chat/completions', this.headers(), body, signal)) {
      const ev = JSON.parse(data);
      for (const choice of ev.choices || []) {
        stop = choice.finish_reason || stop;
        const delta = choice.delta || {};
        if (delta.content) {
          text += delta.content;
          yield { type: 'text', text: delta.content };
        }
        for (const tc of delta.tool_calls || []) {
          const i = tc.index ?? calls.size;
          if (!calls.has(i)) calls.set(i, { id: '', name: '', arguments: '' });
          const c = calls.get(i)!;
          c.id = tc.id || c.id;
          const fn = tc.function || {};
          c.name = fn.name || c.name;
          const args = fn.arguments;
          c.arguments += args && typeof args === 'object' ? JSON.stringify(args) : (args || '');
        }
      }
      if (ev.usage) {
        usage.input = ev.usage.prompt_tokens ?? 0;
        usage.output = ev.usage.completion_tokens ?? 0;
      }
    }
    yield usage;
    if (stop === 'length') {
      yield { type: 'error', message: CUT_OFF };
      return;
    }
    if (calls.size) {
      const out: ToolCall[] = [], native: any[] = [];
      for (const [n, c] of [...calls.entries()].sort((x, y) => x[0] - y[0])) {
        const cid = c.id || `call_${n}`;
        let args = {};
        try { args = JSON.parse(c.arguments || '{}'); } catch { args = {}; }
        out.push({ id: cid, name: c.name, args });
        native.push({ id: cid, type: 'function', function: { name: c.name, arguments: c.arguments || '{}' } });
      }
      yield { type: 'tool_calls', calls: out, assistant: { role: 'assistant', content: text || null, tool_calls: native } };
    }
  }

  toolResults(results: [ToolCall, string][]) {
    return results.map(([call, text]) => ({ role: 'tool', tool_call_id: call.id, content: text }));
  }
}

export function getProvider(id: string, opts: { key?: string | null; baseUrl?: string | null; fetch: typeof fetch }): Provider {
  const preset = PRESETS[id];
  const url = (opts.baseUrl || preset.base_url).replace(/\/+$/, '');
  const Cls = preset.kind === 'anthropic' ? AnthropicProvider : OpenAICompatProvider;
  return new Cls(id, url, opts.key ?? null, opts.fetch);
}

/** A sensible default from the provider's own list: cheap and good enough for study help. */
export function suggestModel(id: string, models: string[]): string {
  for (const word of PRESETS[id]?.suggest ?? []) {
    const m = models.find(x => x.toLowerCase().includes(word));
    if (m) return m;
  }
  return models[0] ?? '';
}
