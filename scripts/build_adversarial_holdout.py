"""Build a deterministic, public-safe fuzzy retrieval holdout.

The generated corpus and queries are synthetic. They exercise semantic contracts
without copying or describing the owner's private files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SUBJECTS = (
    {
        "id": "os",
        "canonical": "操作系统",
        "aliases": ("操作系统", "OS", "Linux 操作系统", "operating system"),
        "english": "operating system",
        "project": "进程、线程、页面置换和文件管理",
    },
    {
        "id": "database",
        "canonical": "数据库原理",
        "aliases": ("数据库", "数据库原理", "database", "database systems"),
        "english": "database",
        "project": "关系模型、SQL 查询和事务管理",
    },
    {
        "id": "computer_org",
        "canonical": "计算机组成与结构",
        "aliases": ("计算机组成", "计算机组成原理", "计组", "computer organization"),
        "english": "computer organization",
        "project": "单周期 CPU、MIPS 数据通路和 Verilog",
    },
    {
        "id": "network",
        "canonical": "计算机网络",
        "aliases": ("计算机网络", "计网", "computer network", "networking"),
        "english": "computer network",
        "project": "TCP、路由和网络抓包",
    },
    {
        "id": "digital_logic",
        "canonical": "数字逻辑",
        "aliases": ("数字逻辑", "数字系统", "Verilog", "digital logic"),
        "english": "digital logic",
        "project": "组合逻辑、时序电路和 Verilog",
    },
)

CN_NUMBERS = {1: "一", 2: "二", 3: "三", 4: "四"}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _row(rows: list[dict[str, object]], category: str, query: str, **expected: object) -> None:
    rows.append({
        "id": f"H{len(rows) + 1:04d}",
        "category": category,
        "query": query,
        **expected,
    })


def build(root: Path) -> dict[str, object]:
    corpus = root / "corpus"
    rows: list[dict[str, object]] = []
    subject_files: dict[str, dict[str, object]] = {}

    for subject in SUBJECTS:
        subject_id = str(subject["id"])
        canonical = str(subject["canonical"])
        project = str(subject["project"])
        labs: list[str] = []
        for number in (1, 2, 3):
            filename = f"{subject_id}-lab-{number}-2024.md"
            labs.append(filename)
            _write(
                corpus / filename,
                f"""实验报告
课程名称：{canonical}
实验项目名称：{project}实验{CN_NUMBERS[number]}
实验学生姓名：李明
学生学号：SYNTHETIC-1001
实验时间：2024-0{number}-15
实验内容：完成{project}的第{CN_NUMBERS[number]}次验证并分析结果。""",
            )
        course_report = f"{subject_id}-course-design-report-2024.md"
        template = f"{subject_id}-course-design-template.md"
        guide = f"{subject_id}-course-design-guide.md"
        notes = f"{subject_id}-study-notes.md"
        exam = f"{subject_id}-exam-answer.md"
        _write(
            corpus / course_report,
            f"""课程设计说明书
课程名称：{canonical}
学生姓名：李明
学生学号：SYNTHETIC-1001
设计题目：{project}综合设计
完成时间：2024-06-20
设计内容：实现{project}，给出架构、代码、验证结果和总结。""",
        )
        _write(corpus / template, f"{canonical}课程设计报告模板\n学生姓名：______\n设计内容：请填写。")
        _write(corpus / guide, f"{canonical}课程设计指导书与必备知识\n参考主题：{project}\n报告提交要求。")
        _write(corpus / notes, f"{canonical}复习重点与学习笔记\n{project}\n仅用于复习，不是实验报告或试卷。")
        _write(corpus / exam, f"{canonical}期末试卷答案\n涉及{project}\n仅供考后复习。")
        subject_files[subject_id] = {
            "labs": labs,
            "course_report": course_report,
            "template": template,
            "guide": guide,
            "notes": notes,
            "exam": exam,
        }

    single_patterns = (
        "帮我找{alias}第{cn}次实验报告",
        "{alias}实验{cn}的正式文档在哪里",
        "以前做的{alias}实验报告第{cn}份",
        "只要{alias}实验{cn}，不要模板",
        "locate {english} lab report {number}",
    )
    for subject in SUBJECTS:
        files = subject_files[str(subject["id"])]
        for number in (1, 2, 3):
            for pattern_index, pattern in enumerate(single_patterns):
                alias = subject["aliases"][pattern_index % len(subject["aliases"])]
                _row(
                    rows,
                    "single_lab",
                    pattern.format(alias=alias, english=subject["english"], number=number, cn=CN_NUMBERS[number]),
                    expected_files=[files["labs"][number - 1]],
                    expected_mode="single",
                    expected_topic=str(subject["id"]),
                    expected_role="experiment",
                )

    inventory_patterns = (
        "{alias}的实验报告有哪些",
        "列一下我做过的{alias}实验",
        "把{alias}实验都找出来",
        "我都做过啥{alias}实验",
        "全部列出{alias}实验报告",
        "show me every {english} lab report",
        "{alias}有哪几份实验报告",
        "按顺序列出{alias}的所有实验",
    )
    for subject in SUBJECTS:
        files = subject_files[str(subject["id"])]
        for index, pattern in enumerate(inventory_patterns):
            alias = subject["aliases"][index % len(subject["aliases"])]
            _row(
                rows,
                "inventory",
                pattern.format(alias=alias, english=subject["english"]),
                expected_files=files["labs"],
                expected_mode="inventory",
                expected_topic=str(subject["id"]),
                expected_role="experiment",
                expect_multiple=True,
            )

    course_patterns = (
        "{alias}的课设报告",
        "找{alias}课程设计报告正式版",
        "我写的{alias}课程设计说明书",
        "{alias}大作业报告在哪里",
        "locate the completed {english} course design report",
        "不要模板，找{alias}课设报告",
        "那份{alias}课程设计完成版",
        "帮我打开{alias}的正式课设报告",
    )
    for subject in SUBJECTS:
        files = subject_files[str(subject["id"])]
        for index, pattern in enumerate(course_patterns):
            alias = subject["aliases"][index % len(subject["aliases"])]
            _row(
                rows,
                "course_design_report",
                pattern.format(alias=alias, english=subject["english"]),
                expected_files=[files["course_report"]],
                expected_mode="single",
                expected_topic=str(subject["id"]),
                expected_role="course_design_report",
            )

    for subject in SUBJECTS:
        alias = subject["aliases"][0]
        for query in (
            f"找 2099 年的{alias}实验报告",
            f"有没有 2099 年的{alias}课程设计报告",
            f"{alias}第九次实验报告在哪里",
            f"找{alias}实验九的正式文档",
        ):
            _row(
                rows,
                "absent_year_or_ordinal",
                query,
                expect_no_match=True,
                expected_topic=str(subject["id"]),
            )
        for query in (
            f"有没有{alias}课设实验报告",
            f"找{alias}课程设计的实验报告",
            f"{alias}大作业实验报告存在吗",
            f"locate the {subject['english']} course-project lab report",
        ):
            _row(
                rows,
                "absent_role_intersection",
                query,
                expect_no_match=True,
                expected_topic=str(subject["id"]),
            )

    negative_patterns = (
        "找{alias}课程设计报告，不要模板",
        "不是指导书，我要{alias}课设报告",
        "排除必备知识，只找{alias}课程设计完成版",
        "{alias}课设报告，别给我空白模版",
        "find the completed {english} course report without templates",
        "我要{alias}本人填写的课设报告，不是参考资料",
    )
    for subject in SUBJECTS:
        files = subject_files[str(subject["id"])]
        for index, pattern in enumerate(negative_patterns):
            alias = subject["aliases"][index % len(subject["aliases"])]
            _row(
                rows,
                "negative_role",
                pattern.format(alias=alias, english=subject["english"]),
                expected_files=[files["course_report"]],
                expected_topic=str(subject["id"]),
                expected_role="course_design_report",
            )

    pairs = [(SUBJECTS[left], SUBJECTS[right]) for left in range(len(SUBJECTS)) for right in range(left + 1, len(SUBJECTS))]
    for left, right in pairs:
        expected = [*subject_files[str(left["id"])]["labs"], *subject_files[str(right["id"])]["labs"]]
        for pattern in (
            "{left}或者{right}的实验报告有哪些",
            "列出{left}或{right}全部实验",
            "show all {left_en} or {right_en} lab reports",
        ):
            _row(
                rows,
                "alternatives_inventory",
                pattern.format(left=left["aliases"][0], right=right["aliases"][0], left_en=left["english"], right_en=right["english"]),
                expected_files=expected,
                expected_mode="inventory",
                expect_multiple=True,
            )

    notes_patterns = (
        "找我整理的{alias}重点，不要试卷",
        "{alias}复习笔记在哪里",
        "不是答案，找{alias}学习笔记",
        "locate my {english} study notes",
        "{alias}有哪些复习重点文档",
    )
    for subject in SUBJECTS:
        files = subject_files[str(subject["id"])]
        for index, pattern in enumerate(notes_patterns):
            alias = subject["aliases"][index % len(subject["aliases"])]
            _row(
                rows,
                "study_notes",
                pattern.format(alias=alias, english=subject["english"]),
                expected_files=[files["notes"]],
                expected_topic=str(subject["id"]),
            )

    existence_patterns = (
        "有没有{alias}第三次实验报告",
        "{alias}课程设计报告存在吗",
        "能找到{alias}实验二吗",
        "do I have a {english} course design report",
        "is there a completed {english} lab report 1",
    )
    for subject in SUBJECTS:
        files = subject_files[str(subject["id"])]
        expected_by_pattern = (files["labs"][2], files["course_report"], files["labs"][1], files["course_report"], files["labs"][0])
        for index, pattern in enumerate(existence_patterns):
            alias = subject["aliases"][index % len(subject["aliases"])]
            _row(
                rows,
                "positive_existence",
                pattern.format(alias=alias, english=subject["english"]),
                expected_files=[expected_by_pattern[index]],
                expected_mode="existence",
                expected_topic=str(subject["id"]),
            )

    clarification_queries = (
        "帮我找以前写过的那个报告",
        "找一下那个实验",
        "我记得有份文档但忘了主题",
        "那个课设放哪了",
        "find my old report",
        "where is that document",
        "我之前做的东西",
        "找一份以前的材料",
        "就是上次说的那个文件",
        "帮我找报告，不记得什么课",
        "some presentation I made before",
        "找那个大作业",
        "以前写过的实验在哪里",
        "我忘了文件名和内容",
        "retrieve the thing I wrote",
    )
    for query in clarification_queries:
        _row(rows, "clarification", query, should_clarify=True)

    queries = root / "queries.jsonl"
    _write(queries, "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows))
    manifest_hash = hashlib.sha256(queries.read_bytes()).hexdigest()
    metadata = {
        "schema": 1,
        "cases": len(rows),
        "corpus_files": len(list(corpus.glob("*.md"))),
        "query_manifest_sha256": manifest_hash,
        "categories": sorted({str(row["category"]) for row in rows}),
        "synthetic_only": True,
    }
    _write(root / "manifest.json", json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True))
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(__file__).parent.parent / "evaluation" / "fuzzy_holdout_v1")
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
