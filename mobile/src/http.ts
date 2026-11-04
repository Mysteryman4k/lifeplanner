/* The phone's stand-in for FastAPI: routes the screens' fetch('/api/…') calls to handlers in this app,
   with the same status codes and {"detail": …} error bodies as the desktop server, so app.js works unchanged. */

export class HttpError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
}

export interface Req {
  method: string;
  path: string;
  params: Record<string, string>;
  query: URLSearchParams;
  /** The body as text (JSON requests), or null. */
  text: string | null;
  /** The body as bytes (file uploads sent as application/octet-stream), or null. */
  bytes: Uint8Array | null;
  signal?: AbortSignal;
}

/** A handler returns JSON-able data, or a Response for streams. */
export type Handler = (req: Req) => unknown | Promise<unknown>;

interface Route { method: string; parts: string[]; handler: Handler }

export class Router {
  private routes: Route[] = [];

  add(method: string, path: string, handler: Handler) {
    this.routes.push({ method, parts: path.split('/').filter(Boolean), handler });
  }
  get(path: string, h: Handler) { this.add('GET', path, h); }
  post(path: string, h: Handler) { this.add('POST', path, h); }
  put(path: string, h: Handler) { this.add('PUT', path, h); }
  delete(path: string, h: Handler) { this.add('DELETE', path, h); }

  /** Every route, as "METHOD /path/{param}", for the consistency check against the desktop server. */
  list(): string[] {
    return this.routes.map(r => `${r.method} /${r.parts.map(p => (p.startsWith(':') ? `{${p.slice(1)}}` : p)).join('/')}`);
  }

  private match(method: string, path: string) {
    const parts = path.split('/').filter(Boolean);
    let pathMatched = false;
    for (const r of this.routes) {
      if (r.parts.length !== parts.length) continue;
      const params: Record<string, string> = {};
      let ok = true;
      for (let i = 0; i < parts.length; i++) {
        const want = r.parts[i];
        if (want.startsWith(':')) params[want.slice(1)] = decodeURIComponent(parts[i]);
        else if (want !== parts[i]) { ok = false; break; }
      }
      if (!ok) continue;
      pathMatched = true;
      if (r.method === method) return { route: r, params };
    }
    return { route: null, params: {}, pathMatched };
  }

  async handle(method: string, url: string, body: string | Uint8Array | null, signal?: AbortSignal): Promise<Response> {
    const u = new URL(url, 'http://app.local');
    const found = this.match(method, u.pathname);
    if (!found.route) {
      return json(found.pathMatched ? 405 : 404, { detail: found.pathMatched ? 'Method Not Allowed' : 'Not Found' });
    }
    const req: Req = {
      method, path: u.pathname, params: found.params, query: u.searchParams,
      text: typeof body === 'string' ? body : null,
      bytes: body instanceof Uint8Array ? body : null,
      signal,
    };
    try {
      const out = await found.route.handler(req);
      if (out instanceof Response) return out;
      return json(200, out ?? null);
    } catch (e) {
      if (e instanceof HttpError) return json(e.status, { detail: e.detail });
      console.error('Unhandled error in', method, u.pathname, e);
      return new Response('Internal Server Error', { status: 500, headers: { 'Content-Type': 'text/plain' } });
    }
  }
}

export function json(status: number, data: unknown): Response {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
}

// ── Request helpers that behave like FastAPI's parameter parsing ──

function invalid(loc: (string | number)[], msg: string, type: string, input: unknown): never {
  throw new HttpError(422, [{ type, loc, msg, input }]);
}

/** A path parameter declared as int in the desktop server. */
export function intParam(req: Req, name: string): number {
  const v = req.params[name];
  if (!/^[+-]?\d+$/.test(v.trim())) invalid(['path', name], 'Input should be a valid integer, unable to parse string as an integer', 'int_parsing', v);
  return parseInt(v, 10);
}

export function queryStr(req: Req, name: string): string | null {
  return req.query.has(name) ? req.query.get(name) : null;
}

export function queryInt(req: Req, name: string): number | null {
  const v = queryStr(req, name);
  if (v === null) return null;
  if (!/^\s*[+-]?\d+\s*$/.test(v)) invalid(['query', name], 'Input should be a valid integer, unable to parse string as an integer', 'int_parsing', v);
  return parseInt(v, 10);
}

const TRUE = new Set(['1', 'on', 't', 'true', 'y', 'yes']);
const FALSE = new Set(['0', 'off', 'f', 'false', 'n', 'no']);

export function queryBool(req: Req, name: string): boolean | null {
  const v = queryStr(req, name);
  if (v === null) return null;
  const s = v.trim().toLowerCase();
  if (TRUE.has(s)) return true;
  if (FALSE.has(s)) return false;
  invalid(['query', name], 'Input should be a valid boolean, unable to interpret input', 'bool_parsing', v);
}

/** The JSON body (FastAPI answers 422 for a body that isn't JSON). */
export function body(req: Req): unknown {
  if (req.text === null || req.text === '') invalid(['body'], 'Field required', 'missing', null);
  try {
    return JSON.parse(req.text);
  } catch (e) {
    throw new HttpError(422, [{ type: 'json_invalid', loc: ['body', 0], msg: 'JSON decode error', input: {} }]);
  }
}
