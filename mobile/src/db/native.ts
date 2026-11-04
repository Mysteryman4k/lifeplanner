/* Native SQLite on the phone (@capacitor-community/sqlite). The file lives in the app's private storage,
   which Android and iOS keep across updates and remove only when the app is uninstalled. */
import { CapacitorSQLite, SQLiteConnection, type SQLiteDBConnection } from '@capacitor-community/sqlite';
import type { Driver, Param, Row } from './db';

export const DB_NAME = 'planner';

export class NativeDriver implements Driver {
  private constructor(private conn: SQLiteDBConnection, private sqlite: SQLiteConnection) {}

  static async open(): Promise<NativeDriver> {
    const sqlite = new SQLiteConnection(CapacitorSQLite);
    await sqlite.checkConnectionsConsistency().catch(() => undefined);
    const existing = (await sqlite.isConnection(DB_NAME, false)).result;
    const conn = existing
      ? await sqlite.retrieveConnection(DB_NAME, false)
      : await sqlite.createConnection(DB_NAME, false, 'no-encryption', 1, false);
    await conn.open();
    await conn.execute('PRAGMA foreign_keys=ON', false);
    return new NativeDriver(conn, sqlite);
  }

  async all(sql: string, params: Param[]): Promise<Row[]> {
    const res = await this.conn.query(sql, params as any[]);
    return res.values ?? [];
  }

  async run(sql: string, params: Param[]) {
    // transaction=false: this app opens and closes its own transactions (Database.tx)
    const res = await this.conn.run(sql, params as any[], false);
    return { changes: res.changes?.changes ?? 0, lastId: res.changes?.lastId ?? 0 };
  }

  async exec(sql: string) { await this.conn.execute(sql, false); }
  async begin() { await this.conn.beginTransaction(); }
  async commit() { await this.conn.commitTransaction(); }
  async rollback() {
    if ((await this.conn.isTransactionActive()).result) await this.conn.rollbackTransaction();
  }

  async close() {
    await this.conn.close();
    await this.sqlite.closeConnection(DB_NAME, false);
  }
}
