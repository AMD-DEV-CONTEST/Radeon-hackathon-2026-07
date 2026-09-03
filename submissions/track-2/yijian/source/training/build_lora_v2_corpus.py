# -*- coding: utf-8 -*-
"""Build the non-destructive v2 SFT corpus for the second Qwen3-14B LoRA run.

V1 taught the model raw internal coordinates while the production mentor hides
them behind ``S`` (actual move) and ``J`` (KataGo choice).  It also let a stale
move-button intent override ordinary terminology questions.  This builder keeps
the same 720-row source balance and permissions, but aligns the supervised
protocol with the production Agent:

* board-bound answers use S/J rather than internal coordinates;
* term and opening-principle questions are explicitly routed before a board
  verdict is written;
* a small, project-original routing set teaches the failure modes observed in
  the v1 blind review.

It never edits the signed source corpus or its sealed split.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA = "yijian-agent-sft-v2"
COORDINATE = re.compile(r"\b[A-HJ-T](?:[1-9]|1[0-9])\b", re.IGNORECASE)
ACTUAL_RE = re.compile(r'"actualMove"\s*:\s*"([A-HJ-T](?:[1-9]|1[0-9]))"', re.I)
BEST_RE = re.compile(r'"bestMove"\s*:\s*"([A-HJ-T](?:[1-9]|1[0-9]))"', re.I)

ANSWER_SYSTEM = (
    "你是弈鉴围棋教练。先判断用户问的是哪一类："
    "术语/通用棋理、当前棋盘事实、还是两手比较。"
    "术语与通用棋理必须先直接回答定义或取舍，不能假称当前棋盘已有结论；"
    "只有证据明确绑定当前局面时，才解释实战手 S、KataGo 首选 J 或二者的差别。"
    "KataGo负责候选手、胜率、目差和变化；规则引擎负责合法性、提子、气和棋块事实。"
    "不得新增证据中没有的数值、坐标、死活或强制变化。"
    "用户不可见内部坐标：实战手写 S，AI 首选写 J，其余后续坐标概括为“后续变化”。"
    "只返回JSON，字段为answer与followUps。"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def candidate_moves(messages: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    text = "\n".join(str(item.get("content") or "") for item in messages)
    actual = ACTUAL_RE.search(text)
    best = BEST_RE.search(text)
    return (
        actual.group(1).upper() if actual else None,
        best.group(1).upper() if best else None,
    )


def public_text(value: str, actual: str | None, best: str | None) -> str:
    def replace(match: re.Match[str]) -> str:
        point = match.group(0).upper()
        if actual and point == actual:
            return "S"
        if best and point == best:
            return "J"
        return "后续点"

    return COORDINATE.sub(replace, value)


def inferred_scope(question: str) -> str:
    compact = re.sub(r"\s+", "", question)
    if "缓气劫" in compact or (
        any(marker in compact for marker in ("什么是", "什么意思", "定义"))
        and any(term in compact for term in ("征子", "劫", "官子", "定式", "厚势", "三连星", "点三三"))
    ):
        return "conceptual_term"
    if "三连星" in compact and "三三" in compact:
        return "conceptual_opening_tradeoff"
    return "board_evidence"


def normalize_row(row: dict[str, Any], *, split: str) -> dict[str, Any]:
    result = json.loads(json.dumps(row, ensure_ascii=False))
    messages = result.get("messages") or []
    actual, best = candidate_moves(messages)
    task = str((result.get("metadata") or {}).get("taskType") or "")
    if task in {"answer", "followup"} and messages:
        messages[0]["content"] = ANSWER_SYSTEM
    for message in messages:
        message["content"] = public_text(str(message.get("content") or ""), actual, best)
    question = str(messages[1].get("content") or "") if len(messages) > 1 else ""
    metadata = result.setdefault("metadata", {})
    metadata["schemaVersion"] = "yijian-agent-source-case-v2"
    metadata["trainingProtocol"] = "user-question-first-evidence-bound-v2"
    metadata["questionScope"] = inferred_scope(question)
    metadata["coordinateProjection"] = "public-S-J-no-internal-coordinates-v2"
    metadata["split"] = split
    return result


def concept_examples() -> list[tuple[str, str]]:
    return [
        (
            "什么是缓气劫？和普通劫有什么区别？",
            "缓气劫仍然遵守劫争规则：提劫后必须先到别处走一手。它和普通劫的重点差别在于，双方还有填气、补形或转换的余地，因此不能只数劫材；还要比较外围气、劫败后的损失和最强应对。没有逐手变化，不能把当前局面断言为缓气劫。",
        ),
        (
            "什么是征子？为什么先看征子方向？",
            "征子是沿着斜线连续打吃、使对方棋块反复逃跑的计算。它是否成立取决于终点附近有没有己方接应子、对方引征子或断征手；只看起始几手不够，必须把路线走到终点。",
        ),
        (
            "引征和断征分别在做什么？",
            "引征是把对方的征子路线引向己方有接应的位置；断征是用一手切断或改变路线，使原本可行的征子失效。两者都必须按完整路线核对，不能凭局部形状下结论。",
        ),
        (
            "先手官子和后手官子怎么比较？",
            "先手官子走完后对方通常还要在同一区域应对，因此除了局部目数，还保留下一手的主动权。后手官子也有价值，但下完往往把主动权交给对方。比较时应看出入目数、对方是否必须回应，以及更大的官子会不会被抢走。",
        ),
        (
            "什么是逆收？",
            "逆收是对方若不先走就会失去较大收益、而你抢先走能取得较大出入的官子。它的关键不是名字，而是先后手交换造成的目数差；要分别计算双方先走时的结果。",
        ),
        (
            "定式脱先是什么意思？",
            "定式脱先是局部交换尚未完全收束时转到别处下棋。能否脱先取决于己方棋形是否安定、对方有没有强手追击、以及外面的大场是否足够大；不是背完固定手顺就一定可以离开。",
        ),
        (
            "三连星一定比点三三慢吗？",
            "不一定。点三三通常更快兑现角地实空；三连星更强调模样和外势，需要周围配合与攻击对象，也可能被侵消而显得偏缓。具体取舍要看外势能否使用，而不是把任何一种布局当成绝对答案。",
        ),
        (
            "厚势是不是就等于围到很多地？",
            "不是。厚势首先是棋块安定、联络和对外施压的能力，未必立刻变成实地。厚势要借攻击、扩张或转换兑现；若没有作用对象，单纯变厚也可能效率不高。",
        ),
        (
            "什么是腾挪？",
            "腾挪是弱棋在受攻时通过弃、连、断、出头或转换争取安定的手段。目标通常不是硬杀或硬逃，而是减少被攻击的负担、获得先手或把损失转到更有价值的地方。",
        ),
        (
            "为什么不能把 AI 首选当成唯一正确的一手？",
            "AI 首选是在给定规则、搜索预算和当前局面下排在前面的候选。它可以指导复盘，但教学还要说明机制、替代手的代价和证据边界；接近的候选不应被说成绝对唯一。",
        ),
        (
            "为什么回答围棋问题要先分清是在问术语还是在问当前局面？",
            "术语问题需要定义、条件和常见误解；当前局面问题需要棋盘、行棋方、规则事实和变化证据。把两类问题混在一起，会把通用棋理误说成这盘棋的结论，或答非所问。",
        ),
        (
            "什么是劫材？是不是越多越好？",
            "劫材是为了迫使对方应手、再回头提劫而使用的先手威胁。数量重要，大小和兑现方式也重要；无效劫材、损害自己棋形的劫材，不能和真正有效的劫材等量计算。",
        ),
    ]


def replace_routing_rows(rows: list[dict[str, Any]]) -> int:
    replacements = concept_examples() * 2
    candidates = [
        row for row in rows
        if (row.get("metadata") or {}).get("sourceType") == "project_original"
        and (row.get("metadata") or {}).get("taskType") == "answer"
    ]
    if len(candidates) < len(replacements):
        raise ValueError("project-original answer rows are insufficient for v2 routing examples")
    for index, (row, (question, answer)) in enumerate(zip(candidates, replacements)):
        metadata = row["metadata"]
        original_id = str(metadata.get("sourceCaseId") or f"project-{index}")
        row["messages"] = [
            {"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user", "content": f"用户问题：{question}"},
            {"role": "assistant", "content": json.dumps({
                "answer": answer,
                "followUps": ["要把这个概念放到当前棋盘验证吗？"],
            }, ensure_ascii=False, separators=(",", ":"))},
        ]
        metadata.update({
            "sourceCaseId": f"{original_id}-concept-route-v2-{index + 1:02d}",
            "questionScope": "conceptual_term",
            "projectOriginalAugmentation": "conceptual-routing-remediation-v2",
            "coordinateProjection": "not-applicable-general-concept-v2",
        })
    return len(replacements)


def validate(rows: list[dict[str, Any]], expected: int) -> dict[str, Any]:
    if len(rows) != expected:
        raise ValueError(f"expected {expected} rows, got {len(rows)}")
    task_counts = Counter(str((row.get("metadata") or {}).get("taskType")) for row in rows)
    expected_tasks = {"planner": 216, "answer": 288, "followup": 144, "memory_privacy": 72}
    if dict(task_counts) != expected_tasks:
        raise ValueError(f"task ratio changed: {task_counts}")
    source_counts = Counter(str((row.get("metadata") or {}).get("sourceType")) for row in rows)
    if source_counts != {"creator_authorized": 144, "project_original": 416, "public_domain": 160}:
        raise ValueError(f"source balance changed: {source_counts}")
    raw_coordinates = []
    for row in rows:
        if (row.get("metadata") or {}).get("taskType") not in {"answer", "followup"}:
            continue
        for message in row.get("messages") or []:
            if COORDINATE.search(str(message.get("content") or "")):
                raw_coordinates.append(str((row.get("metadata") or {}).get("sourceCaseId")))
                break
    if raw_coordinates:
        raise ValueError(f"assistant-style v2 rows still expose coordinates: {raw_coordinates[:3]}")
    return {
        "taskCounts": dict(sorted(task_counts.items())),
        "sourceCounts": dict(sorted(source_counts.items())),
        "coordinateFreeAnswerAndFollowupRows": True,
        "conceptualRoutingRows": sum(
            (row.get("metadata") or {}).get("projectOriginalAugmentation") == "conceptual-routing-remediation-v2"
            for row in rows
        ),
    }


def build(source: Path, output: Path) -> dict[str, Any]:
    source_manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if source_manifest.get("schemaVersion") != "yijian-agent-sft-v1" or source_manifest.get("passed") is not True:
        raise ValueError("source corpus is not a passed yijian-agent-sft-v1 release")
    output.mkdir(parents=True, exist_ok=True)
    splits = {
        "train": "agent_sft_train.jsonl",
        "dev": "agent_sft_dev.jsonl",
        "test": "agent_sft_test.jsonl",
    }
    transformed: dict[str, list[dict[str, Any]]] = {}
    for split, filename in splits.items():
        transformed[split] = [normalize_row(row, split=split) for row in read_jsonl(source / filename)]
    replaced = replace_routing_rows(transformed["train"])
    train_audit = validate(transformed["train"], 720)
    if len(transformed["dev"]) != 24 or len(transformed["test"]) != 24:
        raise ValueError("dev/test cardinality must remain 24/24")
    for split, filename in splits.items():
        write_jsonl(output / filename, transformed[split])
    manifest = {
        "schemaVersion": SCHEMA,
        "passed": True,
        "purpose": "qwen3-14b-lora-v2-user-question-first-remediation",
        "sourceCorpus": {
            "artifact": source.name,
            "manifestSha256": sha256(source / "manifest.json"),
            "schemaVersion": source_manifest["schemaVersion"],
        },
        "counts": {"train": 720, "dev": 24, "test": 24},
        "taskCounts": train_audit["taskCounts"],
        "sourceCounts": train_audit["sourceCounts"],
        "gates": {
            "sourceReleasePassed": True,
            "exactTaskRatio": True,
            "exactSourceBalance": True,
            "answerAndFollowupCoordinateFree": True,
            "conceptualRoutingAdded": replaced == 24,
            "sealedTestCopiedButNotForTraining": True,
        },
        "remediation": {
            "v1Failure": "stale move target and raw-coordinate template leakage",
            "protocol": "user-question-first-evidence-bound-v2",
            "conceptualRoutingRows": replaced,
            "goldUsage": "all 48 creator train cases retain their answer/planner/followup projections",
        },
        "outputs": {filename: sha256(output / filename) for filename in splits.values()},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source.resolve(), args.output.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
