# -*- coding: utf-8 -*-
"""把严格金标来源案例编译为 Qwen3-14B Agent 多任务 SFT 制品。

创作者数据必须先经过 authorized-video-sft-v3 编译。本工具只做可审计的
任务视图组合，不会把机器候选、原始转写或未签发答案自动晋升为训练数据。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Iterable

TRAINING_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = TRAINING_ROOT.parent / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

import agent_runtime  # noqa: E402


OUTPUT_SCHEMA = "yijian-agent-sft-v1"
SOURCE_CASE_SCHEMA = "yijian-agent-source-case-v1"
TASK_TYPES = {"planner", "answer", "followup", "memory_privacy"}
SPLITS = {"train", "dev", "test"}
SOURCE_TYPES = {"creator_authorized", "project_original", "public_domain"}
PROJECT_SOURCE_IDS = {"yijian-original-pedagogy-v2"}
PUBLIC_SOURCE_IDS = {
    "qijing-compare-strength",
    "qijing-plan-before-shape",
    "qijing-finish-before-moving",
    "qijing-adapt-to-opponent",
    "dunhuang-invade-with-sente",
}
SOURCE_REGISTRY_PATH = TRAINING_ROOT / "sources.json"


class CorpusError(ValueError):
    pass


@lru_cache(maxsize=1)
def _training_source_registry() -> dict[str, dict]:
    try:
        value = json.loads(SOURCE_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"来源许可 registry 无法读取：{SOURCE_REGISTRY_PATH}") from exc
    rows = value.get("allowlist") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        raise CorpusError("来源许可 registry 缺少 allowlist")
    registry = {
        str(row.get("id") or ""): row
        for row in rows if isinstance(row, dict) and row.get("id")
    }
    expected = PROJECT_SOURCE_IDS | PUBLIC_SOURCE_IDS
    missing = expected - set(registry)
    if missing:
        raise CorpusError(f"来源许可 registry 缺少：{sorted(missing)}")
    for source_id in expected:
        row = registry[source_id]
        license_name = str(row.get("license") or "")
        uses = set(row.get("use") or [])
        if "jurisdiction-check-required" in license_name or "agent_sft" not in uses:
            raise CorpusError(f"来源未获本版 Agent SFT 放行：{source_id}")
    return registry


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise CorpusError(f"缺少输入文件：{path}")
    rows = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CorpusError(f"{path}:{index} 不是有效JSON") from exc
        if not isinstance(value, dict):
            raise CorpusError(f"{path}:{index} 必须是JSON对象")
        rows.append(value)
    if not rows:
        raise CorpusError(f"输入文件为空：{path}")
    return rows


def _validate_messages(row: dict, row_id: str) -> list[dict]:
    messages = row.get("messages")
    if not isinstance(messages, list) or len(messages) < 3:
        raise CorpusError(f"{row_id}: messages至少需要system/user/assistant")
    if messages[-1].get("role") != "assistant":
        raise CorpusError(f"{row_id}: 最后一条必须是assistant")
    for message in messages:
        if set(message) != {"role", "content"}:
            raise CorpusError(f"{row_id}: message只允许role/content")
        if message["role"] not in {"system", "user", "assistant"}:
            raise CorpusError(f"{row_id}: message role不合法")
        if not isinstance(message["content"], str) or not message["content"].strip():
            raise CorpusError(f"{row_id}: message content不能为空")
    return messages


def _question_from_creator(row: dict) -> str:
    for message in row.get("messages") or []:
        if message.get("role") != "user":
            continue
        content = str(message.get("content") or "")
        if "\n问题：" in content:
            return content.rsplit("\n问题：", 1)[1].strip()
    raise CorpusError("创作者金标缺少问题正文")


def _evidence_from_creator(row: dict) -> dict:
    for message in row.get("messages") or []:
        content = str(message.get("content") or "")
        if message.get("role") != "user" or not content.startswith("证据："):
            continue
        evidence_text = content[3:].split("\n问题：", 1)[0]
        try:
            evidence = json.loads(evidence_text)
        except json.JSONDecodeError:
            return {}
        return evidence if isinstance(evidence, dict) else {}
    return {}


def _compact_creator_evidence(evidence: dict) -> dict:
    """Keep teaching facts in the prompt while moving bulky provenance to metadata."""
    katago = evidence.get("katagoFacts") or {}
    analysis = katago.get("analysisArtifact") or {}
    rules = (evidence.get("ruleFacts") or {}).get("ruleArtifact") or {}
    return {
        "evidenceRef": ":".join(
            str(evidence.get(name) or "")[:12]
            for name in ("positionHash", "boardFingerprint", "gameIdentity")
        ),
        "questionTarget": evidence.get("questionTarget"),
        "questionTargetMove": evidence.get("questionTargetMove"),
        "board": {
            "turn": evidence.get("turn"),
            "toPlay": evidence.get("toPlay"),
            "subjectColor": evidence.get("subjectColor"),
            "actualMoveNumber": evidence.get("actualMoveNumber"),
            "actualMove": evidence.get("actualMove"),
            "bestMove": evidence.get("bestMove"),
        },
        "katago": {
            "status": katago.get("status"),
            "visits": katago.get("visits"),
            "subjectColor": katago.get("subjectColor"),
            "bestMove": katago.get("bestMove"),
            "candidates": analysis.get("candidates") or [],
        },
        "rules": {
            "legal": rules.get("legal"),
            "boardSize": rules.get("boardSize"),
            "actualMove": rules.get("actualMove"),
            "toPlayAfter": rules.get("toPlayAfter"),
            "capturedStones": rules.get("capturedStones"),
            "koPointAfter": rules.get("koPointAfter"),
        },
        "expertHeuristics": evidence.get("expertHeuristics") or [],
        "pedagogy": evidence.get("pedagogy") or {},
        "claimBoundary": evidence.get("claimBoundary"),
    }


def _compact_creator_messages(row: dict, evidence: dict, question: str) -> list[dict]:
    messages = row["messages"]
    compact = json.dumps(
        _compact_creator_evidence(evidence), ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
    )
    return [
        messages[0],
        {"role": "user", "content": f"证据：{compact}\n问题：{question}"},
        messages[-1],
    ]


def _creator_followup_messages(row: dict, evidence: dict, question: str, row_id: str) -> list[dict]:
    base = _compact_creator_messages(row, evidence, question)
    try:
        approved = json.loads(base[-1]["content"])
    except json.JSONDecodeError as exc:
        raise CorpusError(f"{row_id}: signed creator answer is not JSON") from exc
    followups = approved.get("followUps") if isinstance(approved, dict) else None
    if not isinstance(followups, list) or not followups or not isinstance(followups[0], str):
        raise CorpusError(f"{row_id}: signed creator answer has no approved follow-up")
    pedagogy = evidence.get("pedagogy") or {}
    details = [str(value).strip() for value in (pedagogy.get("mechanism") or []) if str(value).strip()]
    boundary = str(pedagogy.get("boundary") or "").strip()
    if boundary:
        details.append(boundary)
    if not details:
        raise CorpusError(f"{row_id}: signed creator evidence has no follow-up teaching detail")
    return [
        *base,
        {"role": "user", "content": followups[0].strip()},
        {
            "role": "assistant",
            "content": json.dumps(
                {"answer": "；".join(details), "followUps": []},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    ]


def _creator_rows(rows: Iterable[dict], split: str) -> list[dict]:
    compiled = []
    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        row_id = str(metadata.get("id") or "")
        if not row_id:
            raise CorpusError("创作者金标缺少metadata.id")
        _validate_messages(row, row_id)
        if metadata.get("license") != "creator-authorized":
            raise CorpusError(f"{row_id}: 创作者来源未标记授权")
        if metadata.get("commercialDeployment") is not False:
            raise CorpusError(f"{row_id}: 当前创作者数据只能用于非商业比赛版本")
        group = str(metadata.get("splitGroup") or "")
        if not group.startswith("video:"):
            raise CorpusError(f"{row_id}: 创作者金标必须按整条视频分组")
        projected_evidence = _evidence_from_creator(row)
        review_hashes = metadata.get("reviewInputHashes") or {}
        katago_facts = projected_evidence.get("katagoFacts") or {}
        katago_ref = katago_facts.get("trustedArtifactRef") or {}
        base_metadata = {
            "schemaVersion": SOURCE_CASE_SCHEMA,
            "sourceCaseId": row_id,
            "sourceType": "creator_authorized",
            "split": split,
            "splitGroup": group,
            "positionHash": str(projected_evidence.get("positionHash") or ""),
            "boardFingerprint": str(projected_evidence.get("boardFingerprint") or ""),
            "gameIdentity": str(projected_evidence.get("gameIdentity") or ""),
            "videoId": str(metadata.get("videoId") or ""),
            "taskType": "answer",
            "questionTarget": str(metadata.get("target") or "position"),
            "competencies": sorted({str(value) for value in (metadata.get("competency") or [])}),
            "authorizationId": metadata.get("authorizationId"),
            "license": "creator-authorized",
            "projectUseMode": metadata.get("projectUseMode"),
            "commercialDeployment": False,
            "reviewApprovalId": metadata.get("reviewApprovalId"),
            "reviewerId": metadata.get("reviewerId"),
            "sourceChainBindingSha256": metadata.get("sourceChainBindingSha256"),
            "unitContentSha256": review_hashes.get("unitContentSha256"),
            "katagoArtifactSha256": katago_ref.get("artifactSha256"),
            "videoUrl": metadata.get("videoUrl"),
            "timeRangeMs": metadata.get("timeRangeMs"),
            "promptProjection": "creator-evidence-compact-v1",
            "fullEvidenceAvailableByHashes": True,
        }
        for name in (
            "reviewApprovalId", "reviewerId", "authorizationId",
            "sourceChainBindingSha256", "unitContentSha256",
            "katagoArtifactSha256",
        ):
            if not base_metadata.get(name):
                raise CorpusError(f"{row_id}: creator lineage缺少{name}")
        question = _question_from_creator(row)
        compiled.append({
            "messages": _compact_creator_messages(row, projected_evidence, question),
            "metadata": base_metadata,
        })
        target = str(metadata.get("target") or "position")
        planner = agent_runtime.deterministic_plan(question, target)
        compiled.append({
            "messages": [
                {
                    "role": "system",
                    "content": "你是弈鉴工具规划器，只输出agent-plan-v1 JSON。",
                },
                {
                    "role": "user",
                    "content": f"服务端目标：{target}\n用户问题：{question}",
                },
                {
                    "role": "assistant",
                    "content": json.dumps(planner, ensure_ascii=False, separators=(",", ":")),
                },
            ],
            "metadata": {**base_metadata, "taskType": "planner"},
        })
        compiled.append({
            "messages": _creator_followup_messages(row, projected_evidence, question, row_id),
            "metadata": {
                **base_metadata,
                "taskType": "followup",
                "promptProjection": "creator-evidence-followup-v1",
            },
        })
    return compiled


def _project_rows(rows: Iterable[dict], expected_source: str) -> list[dict]:
    source_registry = _training_source_registry()
    compiled = []
    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        row_id = str(metadata.get("sourceCaseId") or metadata.get("id") or "")
        if not row_id:
            raise CorpusError("项目/公版案例缺少sourceCaseId")
        messages = _validate_messages(row, row_id)
        source_type = str(metadata.get("sourceType") or "")
        if source_type != expected_source:
            raise CorpusError(f"{row_id}: sourceType应为{expected_source}")
        split = str(metadata.get("split") or "")
        task_type = str(metadata.get("taskType") or "")
        group = str(metadata.get("splitGroup") or "")
        if split not in SPLITS or task_type not in TASK_TYPES or not group:
            raise CorpusError(f"{row_id}: split/taskType/splitGroup不完整")
        source_ids = metadata.get("sourceIds")
        if not isinstance(source_ids, list) or not source_ids or not all(
            isinstance(value, str) and value for value in source_ids
        ):
            raise CorpusError(f"{row_id}: sourceIds必须是非空字符串数组")
        source_id_set = set(source_ids)
        unregistered = source_id_set - set(source_registry)
        if unregistered:
            raise CorpusError(f"{row_id}: 来源许可 registry 未登记：{sorted(unregistered)}")
        blocked = [
            source_id for source_id in source_id_set
            if "jurisdiction-check-required" in str(
                source_registry[source_id].get("license") or ""
            )
            or "agent_sft" not in set(source_registry[source_id].get("use") or [])
        ]
        if blocked:
            raise CorpusError(f"{row_id}: 来源未获本版训练放行：{sorted(blocked)}")
        license_name = str(metadata.get("license") or "")
        if expected_source == "project_original":
            if source_id_set - PROJECT_SOURCE_IDS or license_name != "project-original":
                raise CorpusError(f"{row_id}: 项目原创来源或许可未登记")
        else:
            unknown = source_id_set - PROJECT_SOURCE_IDS - PUBLIC_SOURCE_IDS
            if unknown or not (source_id_set & PUBLIC_SOURCE_IDS):
                raise CorpusError(f"{row_id}: 公版来源未登记：{sorted(unknown)}")
            expected_license = (
                "project-original+public-domain"
                if source_id_set & PROJECT_SOURCE_IDS else "public-domain"
            )
            if license_name != expected_license:
                raise CorpusError(
                    f"{row_id}: 许可应为{expected_license}，实际为{license_name or '<empty>'}"
                )
        if task_type == "planner":
            try:
                plan = json.loads(messages[-1]["content"])
                agent_runtime.validate_plan(plan)
            except (json.JSONDecodeError, agent_runtime.AgentProtocolError) as exc:
                raise CorpusError(f"{row_id}: Planner金标不合法：{exc}") from exc
        compiled.append({
            "messages": messages,
            "metadata": {
                **metadata,
                "schemaVersion": SOURCE_CASE_SCHEMA,
                "sourceCaseId": row_id,
            },
        })
    return compiled


def _isolation_keys(row: dict) -> set[str]:
    metadata = row["metadata"]
    keys = {f"group:{metadata['splitGroup']}"}
    for name in (
        "videoId", "gameId", "positionHash", "gameIdentity", "boardFingerprint",
    ):
        value = str(metadata.get(name) or "").strip()
        if value:
            keys.add(f"{name}:{value}")
    return keys


def compile_corpus(
    *,
    creator_train: list[dict],
    creator_dev: list[dict],
    creator_test: list[dict],
    project_rows: list[dict],
    public_rows: list[dict],
    minimum_train_rows: int = 700,
    minimum_creator_train_cases: int = 48,
    minimum_creator_holdout_cases: int = 16,
    minimum_project_cases: int = 96,
    minimum_public_cases: int = 64,
    required_train_rows: int | None = None,
    required_task_counts: dict[str, int] | None = None,
    required_train_source_cases: dict[str, int] | None = None,
) -> tuple[dict[str, list[dict]], dict]:
    rows = []
    rows.extend(_creator_rows(creator_train, "train"))
    rows.extend(_creator_rows(creator_dev, "dev"))
    rows.extend(_creator_rows(creator_test, "test"))
    rows.extend(_project_rows(project_rows, "project_original"))
    rows.extend(_project_rows(public_rows, "public_domain"))

    by_split = {name: [] for name in SPLITS}
    keys_by_split: dict[str, set[str]] = {name: set() for name in SPLITS}
    for row in rows:
        split = row["metadata"]["split"]
        by_split[split].append(row)
        keys_by_split[split].update(_isolation_keys(row))
    for left, right in (("train", "dev"), ("train", "test"), ("dev", "test")):
        overlap = keys_by_split[left] & keys_by_split[right]
        if overlap:
            raise CorpusError(f"{left}/{right}存在来源或局面泄漏：{sorted(overlap)[:3]}")

    # Check isolation before exact-message duplication.  A row that leaks the
    # same position into a holdout split is primarily a split violation, even
    # when its messages also happen to be byte-for-byte identical.
    message_groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        message_groups[canonical_hash(row["messages"])].append(row)
    allowed_planner_duplicate_groups = 0
    for digest, duplicate_rows in message_groups.items():
        if len(duplicate_rows) < 2:
            continue
        tasks = {row["metadata"]["taskType"] for row in duplicate_rows}
        cases = [row["metadata"]["sourceCaseId"] for row in duplicate_rows]
        if tasks == {"planner"} and len(cases) == len(set(cases)):
            # Identical deterministic plans are legitimate when distinct
            # evidence cases ask the same target/question. They remain
            # traceable by sourceCaseId and are reported rather than hidden.
            allowed_planner_duplicate_groups += 1
            continue
        raise CorpusError(
            f"存在无意的完全重复训练记录：{digest[:12]}，cases={cases[:3]}"
        )

    source_cases: dict[str, set[str]] = defaultdict(set)
    train_source_cases: dict[str, set[str]] = defaultdict(set)
    creator_holdout = set()
    for row in rows:
        meta = row["metadata"]
        source_cases[meta["sourceType"]].add(meta["sourceCaseId"])
        if meta["split"] == "train":
            train_source_cases[meta["sourceType"]].add(meta["sourceCaseId"])
        if meta["sourceType"] == "creator_authorized" and meta["split"] in {"dev", "test"}:
            creator_holdout.add(meta["sourceCaseId"])
    creator_train_cases = {
        row["metadata"]["sourceCaseId"] for row in by_split["train"]
        if row["metadata"]["sourceType"] == "creator_authorized"
    }
    gates = {
        "trainRows": len(by_split["train"]) >= minimum_train_rows,
        "creatorTrainCases": len(creator_train_cases) >= minimum_creator_train_cases,
        "creatorHoldoutCases": len(creator_holdout) >= minimum_creator_holdout_cases,
        "projectCases": len(source_cases["project_original"]) >= minimum_project_cases,
        "publicCases": len(source_cases["public_domain"]) >= minimum_public_cases,
        "devNonEmpty": bool(by_split["dev"]),
        "testNonEmpty": bool(by_split["test"]),
    }
    task_counts = Counter(
        row["metadata"]["taskType"] for row in by_split["train"]
    )
    train_total = max(1, len(by_split["train"]))
    ratios = {name: task_counts[name] / train_total for name in sorted(TASK_TYPES)}
    ratio_gate = (
        .25 <= ratios["planner"] <= .35
        and .35 <= ratios["answer"] <= .45
        and .15 <= ratios["followup"] <= .25
        and .05 <= ratios["memory_privacy"] <= .15
    )
    gates["taskRatios"] = ratio_gate
    if required_train_rows is not None:
        gates["exactTrainRows"] = len(by_split["train"]) == required_train_rows
    if required_task_counts is not None:
        gates["exactTaskCounts"] = all(
            task_counts[name] == count
            for name, count in required_task_counts.items()
        ) and set(task_counts) <= set(required_task_counts)
    if required_train_source_cases is not None:
        gates["exactTrainSourceCases"] = all(
            len(train_source_cases[name]) == count
            for name, count in required_train_source_cases.items()
        )
    manifest = {
        "schemaVersion": OUTPUT_SCHEMA,
        "passed": all(gates.values()),
        "gates": gates,
        "counts": {name: len(by_split[name]) for name in sorted(SPLITS)},
        "taskCounts": dict(task_counts),
        "taskRatios": ratios,
        "sourceCaseCounts": {
            name: len(values) for name, values in sorted(source_cases.items())
        },
        "trainSourceCaseCounts": {
            name: len(values) for name, values in sorted(train_source_cases.items())
        },
        "split": "video-game-position-isolated-three-way",
        "duplicateAudit": {
            "exactMessageGroups": sum(
                len(group) > 1 for group in message_groups.values()
            ),
            "allowedDeterministicPlannerGroups": allowed_planner_duplicate_groups,
            "unintentionalDuplicateGroups": 0,
        },
    }
    if not manifest["passed"]:
        failed = [name for name, passed in gates.items() if not passed]
        raise CorpusError("多任务训练语料门槛未通过：" + ", ".join(failed))
    return by_split, manifest


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--creator-manifest", type=Path, required=True)
    parser.add_argument("--creator-train", type=Path, required=True)
    parser.add_argument("--creator-dev", type=Path, required=True)
    parser.add_argument("--creator-test", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--minimum-train-rows", type=int, default=700)
    parser.add_argument("--required-train-rows", type=int, default=720)
    args = parser.parse_args()

    manifest = json.loads(args.creator_manifest.read_text(encoding="utf-8"))
    if (
        manifest.get("schemaVersion") != "authorized-video-sft-v3"
        or manifest.get("passed") is not True
        or manifest.get("split") != "video-isolated-three-way"
    ):
        raise SystemExit("创作者v3金标未通过三层隔离编译。")
    try:
        by_split, output_manifest = compile_corpus(
            creator_train=read_jsonl(args.creator_train),
            creator_dev=read_jsonl(args.creator_dev),
            creator_test=read_jsonl(args.creator_test),
            project_rows=read_jsonl(args.project),
            public_rows=read_jsonl(args.public),
            minimum_train_rows=args.minimum_train_rows,
            required_train_rows=args.required_train_rows,
            required_task_counts={
                "planner": 216,
                "answer": 288,
                "followup": 144,
                "memory_privacy": 72,
            },
            required_train_source_cases={
                "creator_authorized": 48,
                "project_original": 96,
                "public_domain": 64,
            },
        )
    except CorpusError as exc:
        raise SystemExit(str(exc)) from exc

    names = {"train": "agent_sft_train.jsonl", "dev": "agent_sft_dev.jsonl", "test": "agent_sft_test.jsonl"}
    for split, filename in names.items():
        write_jsonl(args.output_dir / filename, by_split[split])
    output_manifest["inputs"] = {
        "creatorManifest": file_hash(args.creator_manifest),
        "creatorTrain": file_hash(args.creator_train),
        "creatorDev": file_hash(args.creator_dev),
        "creatorTest": file_hash(args.creator_test),
        "project": file_hash(args.project),
        "public": file_hash(args.public),
    }
    output_manifest["outputs"] = {
        filename: file_hash(args.output_dir / filename)
        for filename in names.values()
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(output_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output_manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
