# -*- coding: utf-8 -*-
"""Build the fixed 96 project-original + 64 public-domain Agent source cases.

Together with 48 approved creator training cases (each projected to answer,
planner, and human-approved follow-up), these rows produce the award contract exactly:

* planner 216 (30%)
* answer 288 (40%)
* followup 144 (20%)
* memory/privacy 72 (10%)
* total 720 training rows
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


TRAINING_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = TRAINING_ROOT.parent / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

import agent_runtime  # noqa: E402


SCHEMA = "yijian-agent-source-case-v1"
MANIFEST_SCHEMA = "yijian-agent-support-cases-v1"
PROJECT_CASES = 96
PUBLIC_CASES = 64

TOPICS = (
    "问题目标绑定", "工具计划合法性", "证据忠实", "规则与KataGo分层",
    "模型超时降级", "非法计划拒绝", "记忆默认关闭", "显式保存记忆",
    "逐条删除记忆", "全部清除记忆", "隐私摘要", "来源检索边界",
)
GOALS = (
    "解释实战手的具体代价", "说明AI首选的棋理机制", "比较两手的方向与取舍",
    "回答追问但不新增坐标", "在证据不足时明确边界", "展示可验证的工具结果",
    "保持棋盘基础能力可用", "只保存用户主动确认的学习重点",
)


class BuildError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BuildError(message)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stable_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def metadata(case_id: str, task: str, group: str, source: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA,
        "sourceCaseId": case_id,
        "sourceType": source,
        "split": "train",
        "splitGroup": group,
        "taskType": task,
    }


def project_messages(
    index: int, topic: str, goal: str, variant: str, ordinal: int = 0,
) -> list[dict[str, str]]:
    target = ("actual", "best", "comparison")[index % 3]
    question = f"{goal}。当前重点是{topic}，证据没有提供新的数值或坐标。"
    if variant == "planner":
        plan = agent_runtime.deterministic_plan(question, target)
        agent_runtime.validate_plan(plan)
        return [
            {"role": "system", "content": "你是弈鉴工具规划器，只输出agent-plan-v1 JSON。"},
            {
                "role": "user",
                "content": f"服务端目标：{target}\n规划变体：{ordinal}\n用户问题：{question}",
            },
            {"role": "assistant", "content": canonical_json(plan)},
        ]
    answer = {
        "answer": f"先围绕{topic}处理用户所问目标：{goal}。只引用已经登记的棋盘、规则与KataGo证据；缺少的坐标、胜率和目差不作猜测。",
        "followUps": ["要继续比较两手的机制，还是查看教练核对过的证据？"],
    }
    if variant == "answer_short":
        answer["answer"] = f"围绕{topic}回答当前目标，并把没有证据的坐标和数值留空。"
    if variant == "memory_privacy":
        memory_on = index % 2 == 0
        user = (
            f"当前学习重点是{topic}，目标是{goal}。我明确同意记住：以后提醒我先看弱棋。"
            if memory_on else
            f"当前讨论的是{topic}，目标是{goal}。不要保存这次棋谱、问题或回答，只给出当前建议。"
        )
        response = {
            "answer": (
                "已按你的明确授权只保存学习重点摘要，不保存整盘棋谱。"
                if memory_on else
                "不会写入学习记忆；棋谱与本次对话内容保持不保存。"
            ),
            "followUps": ["你可以随时查看、逐条删除或全部清除学习记忆。"],
        }
        return [
            {"role": "system", "content": "学习记忆默认关闭；仅在用户明确授权时保存最小摘要。"},
            {"role": "user", "content": user},
            {"role": "assistant", "content": canonical_json(response)},
        ]
    base = [
        {"role": "system", "content": "你是弈鉴围棋教练，证据不足时必须明确边界。"},
        {"role": "user", "content": question},
        {"role": "assistant", "content": canonical_json(answer)},
    ]
    if variant == "followup":
        base.extend([
            {"role": "user", "content": "再具体一点，但不要新增证据里没有的事实。"},
            {"role": "assistant", "content": canonical_json({
                "answer": f"具体检查顺序是：先确认{topic}对应的对象，再核对规则事实和KataGo制品，最后说明{goal}的机制与边界。",
                "followUps": [],
            })},
        ])
    return base


def build_project_rows() -> list[dict[str, Any]]:
    rows = []
    for index in range(PROJECT_CASES):
        topic = TOPICS[index % len(TOPICS)]
        goal = GOALS[(index // len(TOPICS)) % len(GOALS)]
        case_id = f"project-agent-{index + 1:03d}"
        group = f"project-original:{case_id}"
        variants = ["answer", "planner", "followup"]
        if index < 72:
            variants.append("memory_privacy")
        if index < 48:
            variants.append("answer_short")
        if index < 8:
            variants.append("planner")
        for ordinal, variant in enumerate(variants):
            task = "answer" if variant in {"answer", "answer_short"} else variant
            rows.append({
                "messages": project_messages(index, topic, goal, variant, ordinal),
                "metadata": {
                    **metadata(case_id, task, group, "project_original"),
                    "variant": f"{variant}-{ordinal}",
                    "topic": topic,
                    "sourceIds": ["yijian-original-pedagogy-v2"],
                    "license": "project-original",
                },
            })
    require(len(rows) == 416, f"项目原创应生成416条，实际{len(rows)}")
    return rows


def _read_public(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BuildError(f"公版语料第{line_number}行JSON错误：{exc}") from exc
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _public_question(row: dict[str, Any]) -> str:
    for message in row.get("messages") or []:
        if message.get("role") == "user":
            return str(message.get("content") or "").rsplit("\n问题：", 1)[-1]
    return "请按证据解释当前目标。"


def public_variant(base: dict[str, Any], index: int, variant: str) -> list[dict[str, str]]:
    messages = [dict(message) for message in base.get("messages") or []]
    require(len(messages) >= 3 and messages[-1].get("role") == "assistant", "公版样本消息结构错误")
    if variant == "answer":
        return messages
    if variant == "planner":
        raw_target = str((base.get("metadata") or {}).get("target") or "")
        target = "best" if "首选" in raw_target else "actual" if "实战" in raw_target else "comparison"
        question = _public_question(base)
        plan = agent_runtime.deterministic_plan(question, target)
        agent_runtime.validate_plan(plan)
        return [
            {"role": "system", "content": "你是弈鉴工具规划器，只输出agent-plan-v1 JSON。"},
            {"role": "user", "content": f"服务端目标：{target}\n用户问题：{question}"},
            {"role": "assistant", "content": canonical_json(plan)},
        ]
    if variant == "answer_short":
        return messages[:-1] + [
            {"role": "assistant", "content": canonical_json({
                "answer": "先回答当前目标，再用公版棋理作为检查角度；具体坐标、数值和变化仍以服务端证据为准。",
                "followUps": ["是否查看这一判断对应的证据边界？"],
            })},
        ]
    return messages + [
        {"role": "user", "content": "这条古典棋理在当前局面里应怎样谨慎使用？"},
        {"role": "assistant", "content": canonical_json({
            "answer": "它只提供检查顺序，不能替代当前棋盘的规则重放或KataGo分析；先核对目标棋块，再谈机制和取舍。",
            "followUps": [],
        })},
    ]


def build_public_rows(path: Path) -> list[dict[str, Any]]:
    source_rows = _read_public(path)
    selected = []
    seen_rows = set()
    for row in source_rows:
        meta = row.get("metadata") or {}
        row_id = str(meta.get("id") or "")
        if not row_id or row_id in seen_rows:
            continue
        seen_rows.add(row_id)
        selected.append(row)
        if len(selected) == PUBLIC_CASES:
            break
    require(len(selected) == PUBLIC_CASES, f"公版语料不足64个独立场景，实际{len(selected)}")
    rows = []
    for index, base in enumerate(selected):
        meta = base.get("metadata") or {}
        seed = str(meta.get("id") or meta.get("scenarioId") or index)
        case_id = stable_id("public-go", seed)
        group = f"public-domain:{case_id}"
        variants = ["answer", "planner"]
        if index < 32:
            variants.append("answer_short")
        for ordinal, variant in enumerate(variants):
            task = "answer" if variant in {"answer", "answer_short"} else variant
            rows.append({
                "messages": public_variant(base, index, variant),
                "metadata": {
                    **metadata(case_id, task, group, "public_domain"),
                    "variant": f"{variant}-{ordinal}",
                    "sourceIds": meta.get("sourceIds") or [],
                    "license": (
                        "project-original+public-domain"
                        if "yijian-original-pedagogy-v2" in (meta.get("sourceIds") or [])
                        else "public-domain"
                    ),
                },
            })
    require(len(rows) == 160, f"公版应生成160条，实际{len(rows)}")
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-input", type=Path, default=TRAINING_ROOT / "data" / "classical_sft_train.jsonl")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        project = build_project_rows()
        public = build_public_rows(args.public_input.resolve())
        output = args.output_dir.resolve()
        project_path = output / "project_original.jsonl"
        public_path = output / "public_domain.jsonl"
        write_jsonl(project_path, project)
        write_jsonl(public_path, public)
        manifest = {
            "schemaVersion": MANIFEST_SCHEMA,
            "passed": True,
            "sourceCaseCounts": {"project_original": 96, "public_domain": 64},
            "rowCounts": {"project_original": len(project), "public_domain": len(public)},
            "creatorProjectionRequired": {"cases": 48, "rows": 144},
            "awardTrainContract": {
                "total": 720,
                "taskCounts": {"planner": 216, "answer": 288, "followup": 144, "memory_privacy": 72},
            },
            "outputs": {
                project_path.name: file_hash(project_path),
                public_path.name: file_hash(public_path),
            },
        }
        write_json(output / "manifest.json", manifest)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    except BuildError as exc:
        parser.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
