/* The phone's API: every route the screens call, each request in its own transaction
   (the desktop's `with db()`: committed when it succeeds, rolled back when it fails). */
import { Router, type Handler } from '../http';
import type { Ctx } from './context';
import { registerAi } from '../ai/routes';
import { registerSystem } from './system';
import { registerTasks } from './tasks';
import { registerTrack } from './track';

/** A Router whose handlers each run inside one database transaction. */
class TxRouter extends Router {
  constructor(private ctx: Ctx) { super(); }
  override add(method: string, path: string, handler: Handler) {
    super.add(method, path, async req => {
      const out = await this.ctx.db.tx(async () => handler(req));
      if (method !== 'GET') this.ctx.platform.remindersChanged?.();     // what's due may have changed
      return out;
    });
  }
  /** For streamed replies, which open short transactions of their own as they go. */
  addStream(method: string, path: string, handler: Handler) { super.add(method, path, handler); }
}

export function createApi(ctx: Ctx) {
  const router = new TxRouter(ctx);
  registerTasks(router, ctx);
  registerTrack(router, ctx);
  registerSystem(router, ctx);
  registerAi(router, ctx);
  return router;
}

export type Api = ReturnType<typeof createApi>;
