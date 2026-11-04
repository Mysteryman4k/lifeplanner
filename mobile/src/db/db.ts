/* The database the phone app uses, over one of two engines:
   - native SQLite on Android and iPhone (@capacitor-community/sqlite), see native.ts
   - sql.js (SQLite compiled to WebAssembly) for tests and the browser preview, see sqljs.ts
   Everything above this file uses Database only, so both behave the same. */
import { HttpError } from '../http';

export type Row = Record<string, any>;
export type Param = string | number | boolean | null | undefined | Uint8Array;

export interface Driver {
  all(sql: string, params: Param[]): Promise<Row[]>;
  run(sql: string, params: Param[]): Promise<{ changes: number; lastId: number }>;
  /** Several statements with no parameters. */
  exec(sql: string): Promise<void>;
  begin(): Promise<void>;
  commit(): Promise<void>;
  rollback(): Promise<void>;
  /** Called after each committed change (sql.js keeps its file in memory and saves it here). */
  saved?(): Promise<void>;
  close?(): Promise<void>;
}

/** The desktop's _friendly_integrity: what a constraint failure means, in plain words. */
export function friendlyIntegrity(e: unknown): string | null {
  const msg = String((e as Error)?.message ?? e);
  if (!/constraint/i.test(msg)) return null;
  if (msg.includes('UNIQUE')) return 'That name is already used.';
  if (msg.includes('FOREIGN KEY')) return 'A linked item no longer exists.';
  return "That value isn't allowed.";
}

const clean = (params: Param[]) => params.map(p => (p === undefined ? null : typeof p === 'boolean' ? (p ? 1 : 0) : p));

/**
 * One connection, used by one request at a time: tx() queues callers, so a request's statements never
 * interleave with another's (the desktop gets the same from a connection per request plus SQLite's locks).
 */
export class Database {
  private queue: Promise<unknown> = Promise.resolve();

  constructor(public driver: Driver) {}

  all(sql: string, ...params: Param[]) { return this.driver.all(sql, clean(params)); }
  async get(sql: string, ...params: Param[]): Promise<Row | undefined> { return (await this.all(sql, ...params))[0]; }
  /** The first column of the first row. */
  async value(sql: string, ...params: Param[]): Promise<any> {
    const row = await this.get(sql, ...params);
    return row ? Object.values(row)[0] : undefined;
  }
  async run(sql: string, ...params: Param[]) {
    try {
      return await this.driver.run(sql, clean(params));
    } catch (e) {
      const friendly = friendlyIntegrity(e);
      if (friendly) throw new HttpError(400, friendly);
      throw e;
    }
  }
  exec(sql: string) { return this.driver.exec(sql); }

  /**
   * Run fn inside a transaction: committed if it returns, rolled back if it throws (the desktop's `with db()`).
   * Calls are queued so only one runs at a time. Never call tx() from inside fn: it would wait for itself.
   * (Each API request runs in one, see api/index.ts, so route code just uses the database.)
   */
  tx<T>(fn: () => Promise<T>): Promise<T> {
    const run = async () => {
      await this.driver.begin();
      try {
        const out = await fn();
        await this.driver.commit();
        if (this.driver.saved) await this.driver.saved();
        return out;
      } catch (e) {
        try { await this.driver.rollback(); } catch { /* nothing was open */ }
        throw e;
      }
    };
    const next = this.queue.then(run, run);
    this.queue = next.catch(() => undefined);
    return next;
  }

  /**
   * Run fn with the database to itself but without a transaction (for work that manages its own, like a
   * restore that has to switch foreign keys off first, which SQLite ignores inside a transaction).
   */
  exclusive<T>(fn: () => Promise<T>): Promise<T> {
    const run = async () => {
      try { return await fn(); } finally { if (this.driver.saved) await this.driver.saved(); }
    };
    const next = this.queue.then(run, run);
    this.queue = next.catch(() => undefined);
    return next;
  }
}
