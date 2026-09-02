import sys, sqlite3, json, os

DB_PATH = "novel_world_zh.db"

def migrate():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Ensure table exists
    cursor.execute("CREATE TABLE IF NOT EXISTS entity_translations ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "entity_id TEXT NOT NULL, "
        "language TEXT NOT NULL, "
        "title TEXT NOT NULL, "
        "content TEXT, full_content TEXT, ai_summary TEXT, "
        "book_id TEXT, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE(entity_id, language)"
    ")")
    
    # Count existing
    cursor.execute("SELECT COUNT(*) as cnt FROM entity_translations")
    existing = cursor.fetchone()["cnt"]
    print(f"Existing translations: {existing}")
    
    # Migrate
    cursor.execute("SELECT * FROM entities WHERE is_active = 1")
    entities = [dict(r) for r in cursor.fetchall()]
    print(f"Active entities: {len(entities)}")
    
    migrated = 0
    for ent in entities:
        eid = ent["entity_id"]
        cursor.execute("SELECT id FROM entity_translations WHERE entity_id=? AND language='zh'", (eid,))
        if cursor.fetchone():
            continue
        cursor.execute(
            "INSERT INTO entity_translations "
            "(entity_id, language, title, content, full_content, ai_summary) "
            "VALUES (?, 'zh', ?, ?, ?, ?)",
            (eid, ent.get("title",""), ent.get("content","") or "",
             ent.get("full_content") or ent.get("content","") or "",
             ent.get("ai_summary","") or ""))
        migrated += 1
        if migrated % 10 == 0:
            print(f"  [{migrated}/{len(entities)}] {eid}")
    
    conn.commit()
    conn.close()
    print(f"\nDone. Migrated {migrated} entities.")

if __name__ == "__main__":
    migrate()
