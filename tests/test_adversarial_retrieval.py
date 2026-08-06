from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core import LocalRetriever, assess_file_matches, infer_intent


class AdversarialRetrievalTests(unittest.TestCase):
    """Immutable confusion set for fuzzy file-finding boundaries."""

    def setUp(self):
        self.directory = TemporaryDirectory()
        root = Path(self.directory.name)
        documents = {
            "os-thread-2024.md": "实验报告 课程名称 操作系统 实验项目名称 线程同步 实验学生姓名 李明 学号 1001",
            "os-page-2024.md": "实验报告 课程名称 操作系统 实验项目名称 页面置换 实验学生姓名 李明 学号 1001",
            "os-file-2024.md": "实验报告 课程名称 操作系统 实验项目名称 文件管理 实验学生姓名 李明 学号 1001",
            "database-lab-2025.md": "实验报告 课程名称 数据库原理 实验项目名称 SQL 查询 实验学生姓名 李明 学号 1001",
            "database-course-design-2025.md": "课程设计报告 课程名称 数据库原理 大作业 数据库系统设计 实验学生姓名 李明 学号 1001",
            "os-course-design-2025.md": "课程设计报告 课程名称 操作系统 大作业 文件系统设计 实验学生姓名 李明 学号 1001",
            "database-template.md": "数据库实验报告模板 仅供填写",
            "network-exam-2025.md": "计算机网络实验试卷答案",
        }
        files = []
        for name, content in documents.items():
            path = root / name
            path.write_text(content, encoding="utf-8")
            files.append(path)
        self.retriever = LocalRetriever()
        self.retriever.index_paths(files)

    def tearDown(self):
        self.directory.cleanup()

    def _sources(self, query: str) -> list[str]:
        plan = infer_intent(query)
        return [match.source for match in self.retriever.locate_files(query, limit=20, intent_plan=plan)]

    def test_inventory_paraphrases_keep_course_scope(self):
        for query in (
            "操作系统的实验报告有哪些",
            "列一下我做过的操作系统实验",
            "把操作系统实验都找出来",
            "我都做过啥操作系统实验",
        ):
            with self.subTest(query=query):
                sources = self._sources(query)
                self.assertEqual(3, len(sources))
                self.assertTrue(all(source.startswith("os-") and "course-design" not in source for source in sources))

    def test_absent_intersection_never_degrades_to_similarity(self):
        for query in (
            "有没有数据库课设的实验报告",
            "有木有数据库课程设计实验报告",
            "找一下数据库课设实验报告",
            "数据库课程设计实验报告存在吗",
        ):
            with self.subTest(query=query):
                plan = infer_intent(query)
                matches = self.retriever.locate_files(query, limit=8, intent_plan=plan)
                self.assertEqual([], matches)
                self.assertEqual("no_match", assess_file_matches(query, plan, matches).status)

    def test_negative_topic_and_role_are_hard_exclusions(self):
        for query in (
            "找实验报告，但不要数据库的",
            "找实验报告，排除数据库",
            "找非数据库的实验报告",
        ):
            with self.subTest(query=query):
                sources = self._sources(query)
                self.assertTrue(sources)
                self.assertTrue(all("database" not in source for source in sources))
        self.assertNotIn("database-template.md", self._sources("找数据库实验报告，不要模板"))

    def test_alternatives_do_not_become_an_impossible_conjunction(self):
        sources = set(self._sources("找数据库或者操作系统的实验报告"))
        self.assertIn("database-lab-2025.md", sources)
        self.assertTrue(any(source.startswith("os-") and "course-design" not in source for source in sources))
        self.assertNotIn("database-course-design-2025.md", sources)

    def test_wrong_year_and_ordinal_abstain_with_close_files_present(self):
        for query in (
            "找 2025 年的操作系统实验报告",
            "找数据库第三次实验报告",
            "找 2099 年的数据库实验报告",
        ):
            with self.subTest(query=query):
                plan = infer_intent(query)
                matches = self.retriever.locate_files(query, limit=8, intent_plan=plan)
                self.assertEqual([], matches)
                self.assertEqual("no_match", assess_file_matches(query, plan, matches).status)

    def test_short_course_design_report_phrase_requires_an_actual_report(self):
        query = "计算机组成的课设报告"
        plan = infer_intent(query)
        self.assertIn("computer_organization", plan.topics)
        self.assertIn("course_design_report", plan.required_roles)
        self.assertFalse(plan.clarification_needed)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            documents = {
                "课程设计报告模板.md": "计算机组成与结构课程设计说明书 学生姓名 ______",
                "课程设计必备知识.md": "计算机组成与结构课程设计必备知识 单周期 CPU MIPS",
                "操作系统课设报告.md": "课程设计说明书 课程名称 操作系统 CPU 调度与文件系统 学生姓名 王芳",
                "正式课设报告.md": "课程设计说明书 课程名称 计算机组成与结构 学生姓名 李明 设计题目 单周期 CPU",
            }
            paths = []
            for name, content in documents.items():
                path = root / name
                path.write_text(content, encoding="utf-8")
                paths.append(path)
            retriever = LocalRetriever()
            retriever.index_paths(paths)
            self.assertEqual(["正式课设报告.md"], [match.source for match in retriever.locate_files(query, limit=8)])

            without_filled = LocalRetriever()
            without_filled.index_paths(paths[:3])
            absent_matches = without_filled.locate_files(query, limit=8)
            self.assertEqual([], absent_matches)
            decision = assess_file_matches(query, plan, absent_matches)
            self.assertEqual("no_match", decision.status)
            self.assertIn("templates", decision.reason)


if __name__ == "__main__":
    unittest.main()
