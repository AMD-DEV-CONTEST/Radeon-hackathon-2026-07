"""S5-3 迁移管理测试（stdlib-only）。

注意：migrations.py 是纯标准库、零内部依赖的模块。为避免触发 core/__init__.py
的整包 eager 导入（约 30 个无关模块），这里直接按文件路径加载，既快又隔离。

⚠️ core/migrations.py 尚未创建（待 S5 模块化时实现），测试标记为 skip。
"""

import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MIGRATIONS_PATH = os.path.join(_HERE, "..", "core", "migrations.py")

_MIGRATIONS_EXISTS = os.path.exists(_MIGRATIONS_PATH)

if _MIGRATIONS_EXISTS:
    import importlib.util
    import sqlite3
    import tempfile
    _spec = importlib.util.spec_from_file_location(
        "xai_core_migrations", _MIGRATIONS_PATH)
    _migrations = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_migrations)
    Migrator = _migrations.Migrator


@unittest.skipIf(not _MIGRATIONS_EXISTS, "core/migrations.py 尚未创建（待 S5 模块化时实现）")
class TestMigrator(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.conn = sqlite3.connect(os.path.join(self._tmp, "test.db"))
        self.conn.row_factory = sqlite3.Row
        self.m = Migrator(self.conn)

    def test_applies_pending(self):
        migrations = [
            (1, "create memory table", "CREATE TABLE memory (id INTEGER PRIMARY KEY)"),
            (2, "add notes column", "ALTER TABLE memory ADD COLUMN note TEXT"),
            (3, "create tags table", "CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT)"),
        ]
        applied = self.m.migrate(migrations)
        self.assertEqual(applied, [1, 2, 3])
        # 验证 schema 变更生效
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(memory)")]
        self.assertIn("note", cols)
        tables = [r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertIn("tags", tables)
        self.assertIn("schema_migrations", tables)

    def test_idempotent(self):
        migrations = [(1, "create memory", "CREATE TABLE memory (id INTEGER PRIMARY KEY)")]
        first = self.m.migrate(migrations)
        second = self.m.migrate(migrations)
        self.assertEqual(first, [1])
        self.assertEqual(second, [], "重复迁移应无操作")

    def test_partial_apply_from_existing(self):
        # 先应用 v1
        self.m.migrate([(1, "v1", "CREATE TABLE t1 (id INTEGER)")])
        # 再加入 v2、v3，应只应用 v2、v3
        applied = self.m.migrate([
            (1, "v1", "CREATE TABLE t1 (id INTEGER)"),
            (2, "v2", "CREATE TABLE t2 (id INTEGER)"),
            (3, "v3", "CREATE TABLE t3 (id INTEGER)"),
        ])
        self.assertEqual(applied, [2, 3])

    def test_records_versions(self):
        self.m.migrate([
            (1, "v1", "CREATE TABLE t1 (id INTEGER)"),
            (2, "v2", "CREATE TABLE t2 (id INTEGER)"),
        ])
        self.assertEqual(self.m.applied_versions(), {1, 2})


if __name__ == "__main__":
    unittest.main(verbosity=2)
