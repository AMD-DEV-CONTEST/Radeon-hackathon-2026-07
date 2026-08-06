import { DatabaseSync } from "node:sqlite";
import { MIGRATION_SQL } from "./migrations.js";
import {
  MIGRATION_003_ID,
  MIGRATION_003_NAME,
  MIGRATION_003_SQL
} from "./migration-003.js";
import {
  MIGRATION_004_ID,
  MIGRATION_004_NAME,
  MIGRATION_004_SQL
} from "./migration-004.js";
import {
  MIGRATION_005_ID,
  MIGRATION_005_NAME,
  MIGRATION_005_SQL
} from "./migration-005.js";

export type Db = DatabaseSync;

function appliedMigrationIds(db: Db): Set<number> {
  const rows = db
    .prepare(`SELECT id FROM schema_migrations`)
    .all() as Array<{ id: number }>;
  return new Set(rows.map((row) => row.id));
}

function recordMigration(db: Db, id: number, name: string): void {
  db.prepare(
    `INSERT OR IGNORE INTO schema_migrations (id, name, applied_at)
     VALUES (?, ?, ?)`
  ).run(id, name, new Date().toISOString());
}

/**
 * Open SQLite and apply incremental migrations.
 * Base schema (1+2) is idempotent CREATE IF NOT EXISTS; 003+ are recorded.
 */
export function openDatabase(path: string = ":memory:"): Db {
  const db = new DatabaseSync(path);
  db.exec("PRAGMA foreign_keys = ON;");
  db.exec(MIGRATION_SQL);
  recordMigration(db, 1, "c2_initial");
  recordMigration(db, 2, "agent_checkpoints");

  const applied = appliedMigrationIds(db);
  if (!applied.has(MIGRATION_003_ID)) {
    db.exec("BEGIN IMMEDIATE");
    try {
      db.exec(MIGRATION_003_SQL);
      recordMigration(db, MIGRATION_003_ID, MIGRATION_003_NAME);
      db.exec("COMMIT");
    } catch (error) {
      db.exec("ROLLBACK");
      throw error;
    }
  }
  if (!applied.has(MIGRATION_004_ID)) {
    // re-read after 003 may have been applied in this open
    const again = appliedMigrationIds(db);
    if (!again.has(MIGRATION_004_ID)) {
      db.exec("BEGIN IMMEDIATE");
      try {
        db.exec(MIGRATION_004_SQL);
        recordMigration(db, MIGRATION_004_ID, MIGRATION_004_NAME);
        db.exec("COMMIT");
      } catch (error) {
        db.exec("ROLLBACK");
        throw error;
      }
    }
  }

  const afterRag = appliedMigrationIds(db);
  if (!afterRag.has(MIGRATION_005_ID)) {
    db.exec("BEGIN IMMEDIATE");
    try {
      db.exec(MIGRATION_005_SQL);
      recordMigration(db, MIGRATION_005_ID, MIGRATION_005_NAME);
      db.exec("COMMIT");
    } catch (error) {
      db.exec("ROLLBACK");
      throw error;
    }
  }

  return db;
}

/** List applied migration ids (for tests). */
export function listAppliedMigrations(db: Db): number[] {
  return [...appliedMigrationIds(db)].sort((a, b) => a - b);
}
