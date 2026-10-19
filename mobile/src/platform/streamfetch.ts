/* fetch() for the AI providers on Android, through the app's StreamFetch plugin (StreamFetchPlugin.java):
   the reply arrives piece by piece, as a reply being written should, and no provider has to allow requests
   from web pages. Same shape as fetch(): a Response whose body is a stream, and AbortSignal stops it. */
import { registerPlugin, type PluginListenerHandle } from '@capacitor/core';

interface StreamFetchPlugin {
  start(o: { id: string; url: string; method: string; headers: Record<string, string>; body?: string; readTimeout?: number }):
    Promise<{ status: number; headers: Record<string, string> }>;
  cancel(o: { id: string }): Promise<void>;
  addListener(event: 'chunk', fn: (e: { id: string; data: string }) => void): Promise<PluginListenerHandle>;
  addListener(event: 'end', fn: (e: { id: string; error?: string }) => void): Promise<PluginListenerHandle>;
}

type Sink = { chunk(bytes: Uint8Array): void; end(error?: string): void };

export function nativeStreamFetch(plugin: StreamFetchPlugin = registerPlugin<StreamFetchPlugin>('StreamFetch')): typeof fetch & { buffered(): number } {
  const sinks = new Map<string, Sink>();
  const starting = new Set<string>();                    // start() sent, its stream not made yet
  const early = new Map<string, { chunks: Uint8Array[]; end?: { error?: string } }>();    // their events so far
  let listening: Promise<unknown> | null = null;
  const listen = () => (listening ??= Promise.all([
    plugin.addListener('chunk', e => {
      const sink = sinks.get(e.id);
      if (!sink && !starting.has(e.id)) return;           // stopped or finished: the rest is dropped
      const bytes = Uint8Array.from(atob(e.data), ch => ch.charCodeAt(0));
      if (sink) sink.chunk(bytes);
      else (early.get(e.id) ?? early.set(e.id, { chunks: [] }).get(e.id)!).chunks.push(bytes);
    }),
    plugin.addListener('end', e => {
      const sink = sinks.get(e.id);
      if (sink) sink.end(e.error);
      else if (starting.has(e.id)) (early.get(e.id) ?? early.set(e.id, { chunks: [] }).get(e.id)!).end = { error: e.error };
    }),
  ]));
  let n = 0;

  const doFetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    await listen();
    const id = `r${Date.now()}-${n++}`;
    const signal = init.signal;
    if (signal?.aborted) throw new DOMException('The user aborted a request.', 'AbortError');
    const headers = Object.fromEntries(new Headers(init.headers).entries());
    let head: { status: number; headers: Record<string, string> };
    const onAbort = () => { void plugin.cancel({ id }); };
    signal?.addEventListener('abort', onAbort);
    starting.add(id);
    try {
      head = await plugin.start({ id, url: String(input), method: init.method ?? 'GET', headers,
        body: typeof init.body === 'string' ? init.body : undefined });
    } catch (e) {
      starting.delete(id);
      early.delete(id);
      signal?.removeEventListener('abort', onAbort);
      if (signal?.aborted) throw new DOMException('The user aborted a request.', 'AbortError');
      throw new TypeError(`Network request failed (${(e as Error)?.message ?? 'network'})`);
    }
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        starting.delete(id);
        const finish = (error?: string) => {
          sinks.delete(id);
          signal?.removeEventListener('abort', onAbort);
          if (error) c.error(new TypeError(error === 'timeout' ? 'timeout' : 'network error'));
          else c.close();
        };
        sinks.set(id, { chunk: bytes => c.enqueue(bytes), end: finish });
        const before = early.get(id);
        early.delete(id);
        before?.chunks.forEach(b => c.enqueue(b));
        if (before?.end) finish(before.end.error);
        signal?.addEventListener('abort', () => {
          sinks.delete(id);
          try { c.error(new DOMException('The user aborted a request.', 'AbortError')); } catch { /* closed */ }
        });
      },
      cancel() { sinks.delete(id); void plugin.cancel({ id }); },
    });
    return new Response(body, { status: head.status, headers: head.headers });
  }) as typeof fetch;
  // How many requests have events waiting for their stream (tests check stopped ones leave none behind)
  return Object.assign(doFetch, { buffered: () => early.size + starting.size });
}
