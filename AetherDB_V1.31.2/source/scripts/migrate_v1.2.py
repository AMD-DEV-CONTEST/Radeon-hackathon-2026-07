import sqlite3, os, sys

DB = "novel_world_zh.db"

def migrate():
    print("V1.2.0 Migration: book_id + entity_translations + FTS5")
    print("=" * 50)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 1. book_id to all 6 tables
    tables = ["entities", "relations", "tag_index", "entity_versions", "references_map", "timeline_events"]
    for t in tables:
        cols = [r["name"] for r in c.execute("PRAGMA table_info(" + t + ")").fetchall()]
        if "book_id" not in cols:
            c.execute("ALTER TABLE " + t + " ADD COLUMN book_id TEXT DEFAULT 'default'")
            c.execute("CREATE INDEX IF NOT EXISTS idx_" + t + "_book ON " + t + "(book_id)")
            print(f"  [ADD] book_id -> {t}")
        else:
            print(f"  [OK]  book_id already in {t}")

    # 2. entity_translations table
    c.execute("CREATE TABLE IF NOT EXISTS entity_translations ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT NOT NULL, "
        "language TEXT NOT NULL, title TEXT NOT NULL, "
        "content TEXT, full_content TEXT, ai_summary TEXT, book_id TEXT, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE(entity_id, language))")
    c.execute("CREATE INDEX IF NOT EXISTS idx_et_entity ON entity_translations(entity_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_et_lang ON entity_translations(language)")
    print("  [ADD] entity_translations table")

    # 3. Migrate entities -> entity_translations (zh)
    existing = c.execute("SELECT COUNT(*) as cnt FROM entity_translations").fetchone()["cnt"]
    if existing == 0:
        rows = c.execute("SELECT * FROM entities WHERE is_active = 1").fetchall()
        migrated = 0
        for r in rows:
            c.execute("INSERT OR IGNORE INTO entity_translations "
                "(entity_id, language, title, content, full_content, ai_summary) "
                "VALUES (?, 'zh', ?, ?, ?, ?)",
                (r["entity_id"], r["title"] or "", r["content"] or "",
                 r["full_content"] or r["content"] or "", r["ai_summary"] or ""))
            migrated += 1
        print(f"  [MIGRATE] {migrated} entities to entity_translations (zh)")
    else:
        print(f"  [OK]  entity_translations already has {existing} entries")

    # 4. FTS5 virtual table
    c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5("
        "entity_id UNINDEXED, title, content, full_content, "
        "tokenize='unicode61 remove_diacritics 2')")
    ft = c.execute("SELECT COUNT(*) as cnt FROM entities_fts").fetchone()["cnt"]
    if ft == 0:
        c.execute("INSERT INTO entities_fts(rowid, entity_id, title, content, full_content) "
            "SELECT rowid, entity_id, title, content, full_content FROM entities WHERE is_active = 1")
        ft2 = c.execute("SELECT COUNT(*) as cnt FROM entities_fts").fetchone()["cnt"]
        print(f"  [ADD]  FTS5 indexed: {ft2} entities")
    else:
        print(f"  [OK]  FTS5 already has {ft} entities")

    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
