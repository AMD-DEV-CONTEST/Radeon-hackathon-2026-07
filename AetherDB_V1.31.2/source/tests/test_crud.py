"""DB CRUD boundary condition tests"""
import unittest, sqlite3, json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            importance INTEGER DEFAULT 5,
            version INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_id) REFERENCES entities(entity_id),
            FOREIGN KEY (target_id) REFERENCES entities(entity_id)
        );
        CREATE TABLE tag_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
        );
        CREATE TABLE entity_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            title TEXT, content TEXT,
            tags TEXT,
            importance INTEGER,
            archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
        );
    """)
    return conn

class TestCreateEntity(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
    def tearDown(self):
        self.conn.close()
    def test_normal_create(self):
        c = self.conn.cursor()
        c.execute("INSERT INTO entities (entity_id, entity_type, title, content, tags) VALUES (?,?,?,?,?)",
                  ("LOC_0001", "location", "Place", "desc", json.dumps([])))
        c.execute("SELECT * FROM entities WHERE entity_id = ?", ("LOC_0001",))
        self.assertIsNotNone(c.fetchone())
    def test_empty_title(self):
        c = self.conn.cursor()
        c.execute("INSERT INTO entities (entity_id,entity_type,title) VALUES (?,?,?)",
                  ("CHR_0001","character",""))
        c.execute("SELECT title FROM entities WHERE entity_id=?", ("CHR_0001",))
        self.assertEqual(c.fetchone()["title"], "")
    def test_default_content(self):
        c = self.conn.cursor()
        c.execute("INSERT INTO entities (entity_id,entity_type,title) VALUES (?,?,?)",
                  ("CON_0001","concept","Test"))
        c.execute("SELECT content FROM entities WHERE entity_id=?", ("CON_0001",))
        self.assertEqual(c.fetchone()["content"], "")

class TestForeignKey(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
    def tearDown(self):
        self.conn.close()
    def test_violation(self):
        c = self.conn.cursor()
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute("INSERT INTO relations (source_id,target_id,relation_type) VALUES (?,?,?)",
                      ("NONEXIST","CHR_0001","related"))
    def test_valid_relation(self):
        c = self.conn.cursor()
        c.execute("INSERT INTO entities (entity_id,entity_type,title) VALUES (?,?,?)",
                  ("CHR_0001","character","A"))
        c.execute("INSERT INTO entities (entity_id,entity_type,title) VALUES (?,?,?)",
                  ("CHR_0002","character","B"))
        c.execute("INSERT INTO relations (source_id,target_id,relation_type) VALUES (?,?,?)",
                  ("CHR_0001","CHR_0002","friend"))
        c.execute("SELECT COUNT(*) FROM relations")
        self.assertEqual(c.fetchone()[0], 1)

class TestSoftDelete(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
        c = self.conn.cursor()
        c.execute("INSERT INTO entities (entity_id,entity_type,title,is_active) VALUES (?,?,?,?)",
                  ("CHR_0001","character","X",1))
        self.conn.commit()
    def tearDown(self):
        self.conn.close()
    def test_soft_delete(self):
        c = self.conn.cursor()
        c.execute("UPDATE entities SET is_active=0 WHERE entity_id=?", ("CHR_0001",))
        c.execute("SELECT is_active FROM entities WHERE entity_id=?", ("CHR_0001",))
        self.assertEqual(c.fetchone()["is_active"], 0)
    def test_query_active_only(self):
        c = self.conn.cursor()
        c.execute("INSERT INTO entities (entity_id,entity_type,title,is_active) VALUES (?,?,?,?)",
                  ("CHR_0002","character","Active",1))
        c.execute("INSERT INTO entities (entity_id,entity_type,title,is_active) VALUES (?,?,?,?)",
                  ("CHR_0003","character","Del",0))
        c.execute("SELECT COUNT(*) as cnt FROM entities WHERE is_active=1")
        self.assertEqual(c.fetchone()["cnt"], 2)

class TestVersionHistory(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
        c = self.conn.cursor()
        c.execute("INSERT INTO entities (entity_id,entity_type,title) VALUES (?,?,?)",
                  ("CHR_0001","character","V"))
        self.conn.commit()
    def tearDown(self):
        self.conn.close()
    def test_version_insert(self):
        c = self.conn.cursor()
        c.execute("INSERT INTO entity_versions (entity_id,version,title,content) VALUES (?,?,?,?)",
                  ("CHR_0001",1,"Old","Old content"))
        c.execute("SELECT COUNT(*) as cnt FROM entity_versions WHERE entity_id=?", ("CHR_0001",))
        self.assertEqual(c.fetchone()["cnt"], 1)
    def test_version_ordering(self):
        c = self.conn.cursor()
        for v in [1,2,3]:
            c.execute("INSERT INTO entity_versions (entity_id,version,title) VALUES (?,?,?)",
                      ("CHR_0001",v,f"V{v}"))
        c.execute("SELECT version FROM entity_versions WHERE entity_id=? ORDER BY version DESC",
                  ("CHR_0001",))
        self.assertEqual([r["version"] for r in c.fetchall()], [3,2,1])

class TestEmptyQuery(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
    def tearDown(self):
        self.conn.close()
    def test_no_match(self):
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) as cnt FROM entities WHERE title LIKE ?", ("%nonexistent%",))
        self.assertEqual(c.fetchone()["cnt"], 0)
    def test_search_deleted(self):
        c = self.conn.cursor()
        c.execute("INSERT INTO entities (entity_id,entity_type,title,is_active) VALUES (?,?,?,?)",
                  ("CHR_0001","character","Deleted",0))
        c.execute("SELECT COUNT(*) as cnt FROM entities WHERE entity_id=? AND is_active=1",
                  ("CHR_0001",))
        self.assertEqual(c.fetchone()["cnt"], 0)

if __name__ == "__main__":
    unittest.main()