/* sql.js engine: SQLite compiled to WebAssembly. Used by the tests and the browser preview
   (npm run preview), where there's no native SQLite. The preview keeps its file in IndexedDB. */
import type { Database as SqlJsDb, SqlJsStatic } from 'sql.js';
import type { Driver, Param, Row } from './db';

export class SqlJsDriver implements Driver {
  constructor(private db: SqlJsDb, private onSave?: (bytes: Uint8Array) => Promise<void>) {
    db.exec('PRAGMA foreign_keys=ON');
  }

  static async open(SQL: SqlJsStatic, bytes?: Uint8Array | null, onSave?: (bytes: Uint8Array) => Promise<void>) {
    return new SqlJsDriver(bytes ? new SQL.Database(bytes) : new SQL.Database(), onSave);
  }

  async all(sql: string, params: Param[]): Promise<Row[]> {
    const stmt = this.db.prepare(sql);
    try {
      stmt.bind(params as any);
      const rows: Row[] = [];
      while (stmt.step()) rows.push(stmt.getAsObject());
      return rows;
    } finally {
      stmt.free();
    }
  }

  async run(sql: string, params: Param[]) {
    this.db.run(sql, params as any);
    const changes = this.db.getRowsModified();
    const lastId = Number(this.db.exec('SELECT last_insert_rowid()')[0].values[0][0]);
    return { changes, lastId };
  }

  async exec(sql: string) { this.db.exec(sql); }
  async begin() { this.db.exec('BEGIN'); }
  async commit() { this.db.exec('COMMIT'); }
  async rollback() { this.db.exec('ROLLBACK'); }

  async saved() {
    if (this.onSave) await this.onSave(this.bytes());
  }

  /** The whole file. sql.js reopens its connection to export, which resets the foreign keys setting. */
  bytes() {
    const out = this.db.export();
    this.db.exec('PRAGMA foreign_keys=ON');
    return out;
  }
}
