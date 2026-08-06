# -*- coding: utf-8 -*-
"""Build the release-candidate v3 corpus without reading the sealed split.

The v2 question-first builder used ``\b`` to find Go coordinates.  Python
considers Chinese characters word characters, so strings such as ``白J10``
escaped projection and entered the supervision target.  V3 starts again from
the immutable v1 corpus, parses creator evidence structurally, gives the
actual move and KataGo move independent public roles (S/J), and assigns stable
Chinese aliases to every other variation point.

The builder intentionally reads train and dev only.  It carries the sealed
artifact hash forward from the signed parent manifest but never opens or
copies that file.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import build_lora_v2_corpus as legacy


SCHEMA = "yijian-agent-sft-v3"
PROTOCOL = "question-first-runtime-aligned-evidence-bound-v3"

# ASCII boundaries are deliberate.  They find 白J10 / 在K9 while refusing to
# mistake the middle of a SHA-256 or stable identifier for a board point.
COORDINATE = re.compile(
    r"(?<![A-Za-z0-9])([A-HJ-T](?:1[0-9]|[1-9]))(?![A-Za-z0-9])",
    re.IGNORECASE,
)
FULL_COORDINATE = re.compile(r"[A-HJ-T](?:1[0-9]|[1-9])", re.IGNORECASE)
SENTENCE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?|[^。！？!?；;\n]+$")

ANSWER_SYSTEM = (
    "你是弈鉴围棋教练。先判断用户是在问术语、当前局面、实战手S、"
    "KataGo首选J，还是S/J比较。先给明确结论，再说明一个可核对的棋形或规则机制，"
    "最后写取舍或证据边界；不要重复同一句。KataGo只负责候选、胜率、目差和变化，"
    "规则引擎只负责合法性、提子、气和棋块事实，专家材料只作为有来源的教学判断。"
    "不得新增证据中没有的坐标、数值、死活、劫争或强制应手。"
    "面向用户只使用实战手S、AI首选J和证据中的变化点别名。"
    "回答控制在四句左右，只返回JSON对象，字段为answer与followUps。"
)

STEMS = "甲乙丙丁戊己庚辛壬癸"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _parse_evidence(content: str) -> tuple[str, dict[str, Any], str] | None:
    marker = "证据："
    start = content.find(marker)
    if start < 0:
        return None
    raw = content[start + len(marker):]
    stripped = raw.lstrip()
    try:
        value, end = json.JSONDecoder().raw_decode(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    leading = len(raw) - len(stripped)
    prefix = content[: start + len(marker)] + raw[:leading]
    suffix = stripped[end:]
    return prefix, value, suffix


def _move_context(messages: list[dict[str, Any]]) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for message in messages:
        parsed = _parse_evidence(str(message.get("content") or ""))
        if parsed:
            evidence = parsed[1]
            break
    board = evidence.get("board") if isinstance(evidence.get("board"), dict) else {}
    rules = evidence.get("rules") if isinstance(evidence.get("rules"), dict) else {}
    katago = evidence.get("katago") if isinstance(evidence.get("katago"), dict) else {}
    actual = str(board.get("actualMove") or rules.get("actualMove") or "").upper()
    best = str(board.get("bestMove") or katago.get("bestMove") or "").upper()
    actual = actual if FULL_COORDINATE.fullmatch(actual) else ""
    best = best if FULL_COORDINATE.fullmatch(best) else ""
    target_kind = str(
        evidence.get("questionTarget")
        or board.get("targetKind")
        or ""
    ).lower()
    target_move = str(
        evidence.get("questionTargetMove")
        or board.get("questionTargetMove")
        or ""
    ).upper()
    return {
        "actual": actual or None,
        "best": best or None,
        "same": bool(actual and best and actual == best),
        "targetKind": target_kind,
        "targetMove": target_move if FULL_COORDINATE.fullmatch(target_move) else None,
    }


def _variation_label(index: int) -> str:
    # No digits are used, so aliases can never look like a Go coordinate.
    if index < len(STEMS):
        suffix = STEMS[index]
    else:
        suffix = STEMS[index // len(STEMS) - 1] + STEMS[index % len(STEMS)]
    return f"变化点{suffix}"


def _alias_map(messages: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, str]:
    actual = context.get("actual")
    best = context.get("best")
    aliases: dict[str, str] = {}
    for message in messages:
        for match in COORDINATE.finditer(str(message.get("content") or "")):
            point = match.group(1).upper()
            if point in {actual, best} or point in aliases:
                continue
            aliases[point] = _variation_label(len(aliases))
    return aliases


def _public_point(
    point: str,
    context: dict[str, Any],
    aliases: dict[str, str],
    *,
    role: str | None = None,
) -> str:
    point = point.upper()
    actual = context.get("actual")
    best = context.get("best")
    if role == "actual" and point == actual:
        return "S"
    if role == "best" and point == best:
        return "J"
    if role == "target" and point == context.get("targetMove"):
        if context.get("targetKind") == "actual":
            return "S"
        if context.get("targetKind") == "best":
            return "J"
    if context.get("same") and point == actual:
        return "S/J同点"
    if point == actual:
        return "S"
    if point == best:
        return "J"
    return aliases.setdefault(point, _variation_label(len(aliases)))


def _project_text(
    value: str,
    context: dict[str, Any],
    aliases: dict[str, str],
    *,
    target_question: bool = False,
) -> str:
    def replace(match: re.Match[str]) -> str:
        role = "target" if target_question else None
        return _public_point(match.group(1), context, aliases, role=role)

    return COORDINATE.sub(replace, value)


def _project_value(
    value: Any,
    context: dict[str, Any],
    aliases: dict[str, str],
    *,
    key: str | None = None,
) -> Any:
    if isinstance(value, dict):
        return {
            child_key: _project_value(
                child_value, context, aliases, key=str(child_key)
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_project_value(item, context, aliases, key=key) for item in value]
    if not isinstance(value, str):
        return value
    if FULL_COORDINATE.fullmatch(value):
        role = None
        if key == "actualMove":
            role = "actual"
        elif key == "bestMove":
            role = "best"
        elif key == "questionTargetMove":
            role = "target"
        return _public_point(value, context, aliases, role=role)
    return _project_text(value, context, aliases)


def _deduplicate_sentences(value: str) -> str:
    seen: set[str] = set()
    kept: list[str] = []
    for raw in SENTENCE.findall(value):
        sentence = raw.strip()
        if not sentence:
            continue
        normalized = re.sub(r"[\s，,。！？!?；;：:、]", "", sentence)
        if len(normalized) >= 8 and normalized in seen:
            continue
        if len(normalized) >= 8:
            seen.add(normalized)
        kept.append(sentence)
    return "".join(kept).strip()


def _normalize_assistant_json(
    content: str, context: dict[str, Any], aliases: dict[str, str]
) -> str:
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("answer/followup assistant message is not JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("assistant JSON must be an object")
    # The public-domain source projection used purpose/tradeoff/nextFocus.
    # Normalize it to the one production response contract instead of teaching
    # the model two incompatible JSON shapes.
    if not isinstance(value.get("answer"), str):
        purpose = value.get("purpose")
        if not isinstance(purpose, str) or not purpose.strip():
            raise ValueError("assistant JSON must contain answer or purpose")
        tradeoff = value.get("tradeoff")
        answer_parts = [purpose.strip()]
        if isinstance(tradeoff, str) and tradeoff.strip() and tradeoff.strip() not in purpose:
            answer_parts.append(tradeoff.strip())
        value = {
            "answer": "".join(answer_parts),
            "followUps": [value["nextFocus"]]
            if isinstance(value.get("nextFocus"), str) and value["nextFocus"].strip()
            else [],
        }
    followups = value.get("followUps", [])
    if not isinstance(followups, list) or any(not isinstance(item, str) for item in followups):
        raise ValueError("assistant JSON followUps must be a string list")
    answer = _deduplicate_sentences(
        _project_text(value["answer"], context, aliases)
    )
    if not answer:
        raise ValueError("assistant answer became empty")
    projected_followups: list[str] = []
    for item in followups:
        item = _deduplicate_sentences(_project_text(item, context, aliases))
        if item and item not in projected_followups:
            projected_followups.append(item)
    return json.dumps(
        {"answer": answer, "followUps": projected_followups[:2]},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def normalize_row(row: dict[str, Any], *, split: str) -> dict[str, Any]:
    result = copy.deepcopy(row)
    messages = result.get("messages") or []
    if not isinstance(messages, list):
        raise ValueError("row messages must be a list")
    context = _move_context(messages)
    aliases = _alias_map(messages, context)
    task = str((result.get("metadata") or {}).get("taskType") or "")

    for message in messages:
        role = str(message.get("role") or "")
        content = str(message.get("content") or "")
        if role == "system" and task in {"answer", "followup"}:
            message["content"] = ANSWER_SYSTEM
            continue
        parsed = _parse_evidence(content) if role == "user" else None
        if parsed:
            prefix, evidence, suffix = parsed
            projected = _project_value(evidence, context, aliases)
            if isinstance(projected, dict) and (context.get("actual") or context.get("best")):
                projected["moveAliases"] = {
                    "actual": "S" if context.get("actual") else None,
                    "best": "J" if context.get("best") else None,
                    "samePoint": bool(context.get("same")),
                    "variationPoints": list(aliases.values()),
                }
            message["content"] = (
                prefix
                + json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
                + _project_text(suffix, context, aliases, target_question=True)
            )
        elif role == "assistant" and task in {"answer", "followup"}:
            message["content"] = _normalize_assistant_json(content, context, aliases)
        else:
            message["content"] = _project_text(content, context, aliases)

    metadata = result.setdefault("metadata", {})
    metadata.update({
        "schemaVersion": "yijian-agent-source-case-v3",
        "trainingProtocol": PROTOCOL,
        "coordinateProjection": "structured-S-J-stable-variation-aliases-v3",
        "split": split,
    })
    if context.get("same"):
        metadata["actualBestSamePoint"] = True
    return result


def _answer_payload(row: dict[str, Any]) -> tuple[dict[str, Any], int]:
    messages = row.get("messages") or []
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "assistant":
            return json.loads(messages[index]["content"]), index
    raise ValueError("answer row has no assistant message")


def _append_user_requirement(row: dict[str, Any], requirement: str) -> None:
    for message in reversed(row.get("messages") or []):
        if message.get("role") == "user":
            message["content"] = str(message.get("content") or "") + f"\n回答要求：{requirement}"
            return
    raise ValueError("answer row has no user message")


def _concise_answer(value: str) -> str:
    sentences = [item.strip() for item in SENTENCE.findall(value) if item.strip()]
    if len(sentences) <= 3:
        return value
    chosen = sentences[:2] + [sentences[-1]]
    result = "".join(chosen)
    return result if len(result) <= 260 else "".join(sentences[:2])[:260]


def amplify_gold_answers(rows: list[dict[str, Any]]) -> int:
    creators = [
        row for row in rows
        if row.get("metadata", {}).get("sourceType") == "creator_authorized"
        and row.get("metadata", {}).get("taskType") == "answer"
    ]
    projects = [
        index for index, row in enumerate(rows)
        if row.get("metadata", {}).get("sourceType") == "project_original"
        and row.get("metadata", {}).get("taskType") == "answer"
    ]
    if len(creators) != 48 or len(projects) != 144:
        raise ValueError(
            f"v3 gold amplification requires 48 creator and 144 project answers; "
            f"got {len(creators)} and {len(projects)}"
        )
    for offset, row_index in enumerate(projects[:96]):
        source = copy.deepcopy(creators[offset % 48])
        style = "structured" if offset < 48 else "concise"
        _append_user_requirement(
            source,
            (
                "先直接回答原问题，再写具体机制、取舍和证据边界；禁止重复句子。"
                if style == "structured"
                else "用三到四句回答：结论在前，只保留最关键机制和边界，不要重复。"
            ),
        )
        payload, assistant_index = _answer_payload(source)
        if style == "concise":
            payload["answer"] = _concise_answer(payload["answer"])
            payload["followUps"] = list(payload.get("followUps") or [])[:1]
            source["messages"][assistant_index]["content"] = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            )
        source["metadata"].update({
            "augmentationId": f"gold-runtime-{style}-v3",
            "derivedFromSourceCaseId": source["metadata"]["sourceCaseId"],
            "goldAmplification": True,
        })
        rows[row_index] = source
    return 96


def _concept_variants() -> list[tuple[str, str, list[str]]]:
    result: list[tuple[str, str, list[str]]] = []
    for question, answer in legacy.concept_examples():
        result.append((
            question,
            answer,
            ["要把这个概念放到当前棋盘，用规则与变化证据核对吗？"],
        ))
        result.append((
            f"复盘时怎样避免把这个概念用错：{question}",
            answer + "复盘时还要先核对当前局面的行棋方、棋形条件与证据边界，再决定能否套用。",
            ["你想先看成立条件，还是常见误判？"],
        ))
    return result


def _agent_examples() -> list[tuple[str, str, list[str]]]:
    return [
        ("分析当前局面前应怎样分解任务？", "先确定用户目标和行棋方，再由规则引擎核对合法性、提子与气，由KataGo给候选和变化，最后只用已返回的证据组织教学回答。任何一步缺证据，都应保留边界而不是补猜。", ["要查看这轮实际调用了哪些工具吗？"]),
        ("模型提出了白名单外的工具，应该执行吗？", "不执行。Agent只能调用登记白名单中的规则、KataGo、RAG和经授权的记忆工具；非法计划应被服务端拒绝，再改用合法步骤或确定性降级。", ["要查看被拒绝的计划原因吗？"]),
        ("KataGo和规则引擎各自证明什么？", "KataGo证明给定预算下的候选排序、胜率、目差和变化；规则引擎证明落子是否合法、是否提子、棋块有几气和是否出现规则劫点。两类证据不能互相冒充。", ["要按这两个来源分别展开吗？"]),
        ("RAG材料可以当成当前局面的引擎结论吗？", "不可以。RAG提供可追溯的棋理、术语或教学角度；当前局面的首选与数值仍必须来自本次KataGo，规则事实仍必须来自本次棋盘重放。", ["要查看这条材料的来源链吗？"]),
        ("没有检索到来源时能补一个看起来合理的出处吗？", "不能。没有命中的来源就明确写未检索到，并继续使用棋盘、规则与KataGo证据；伪造书名、作者或链接会破坏整条证据链。", ["要改成只看当前局面证据吗？"]),
        ("用户没有同意保存，这轮内容能写入学习记忆吗？", "不能。学习记忆默认关闭，只有用户明确选择保存的摘要才能写入；原始私密正文、棋谱全文和未经授权的推断都不应保存。", ["要保持本轮不保存吗？"]),
        ("用户要求删除已保存的学习重点，Agent该怎么做？", "先调用登记的删除工具，确认删除结果，再向用户报告已删除的条目范围；不能只在聊天里口头承诺，也不能保留隐藏副本。", ["要列出当前仍保留的摘要吗？"]),
        ("含私人信息的原文适合直接写进记忆吗？", "不适合。即使用户同意学习，也只保存完成任务所需的最小摘要，并去除原始隐私正文；授权范围不清楚时保持不写入。", ["要把可保存内容压缩成无隐私摘要吗？"]),
        ("云端模型超时后，棋盘还能继续用吗？", "可以。服务端应取消本次语言生成，保留棋盘、规则重放、KataGo结果和基础复盘，并用确定性说明或稍后重试，不能让模型超时拖垮整个工作台。", ["要查看当前降级状态吗？"]),
        ("断网时怎样保持基本复盘？", "棋盘交互、合法落子、提子与气等本地能力继续工作；需要云端语言模型的润色暂时降级，已有本地证据仍可查看。恢复网络后再重试表达层。", ["要切换到离线基础复盘吗？"]),
        ("计划中出现非法落子时该怎么办？", "规则引擎先拒绝该落子，并返回占点、自杀或劫禁等可核对原因；Agent不得把非法分支交给KataGo当成真实局面，也不得继续编造后续变化。", ["要显示这手的规则拒绝原因吗？"]),
        ("证据只支持局部判断，可以下整盘胜负结论吗？", "不可以。回答应明确限制在当前局部、当前搜索预算和已验证变化；局部优势、厚薄或攻击机会都不能自动外推成整盘胜负。", ["要把结论改写成局部边界版本吗？"]),
        ("连续追问时需要把上一轮整段再说一遍吗？", "不需要。保留上一轮目标和证据引用，只补充用户这次新问的机制或边界；若局面或目标改变，再重新调用相应工具。", ["这轮你想补充哪一个机制？"]),
        ("比较实战手S与首选J时，最少要说明什么？", "先明确哪手更符合当前目标，再分别说明S解决了什么、J多解决了什么，以及这种差别在规则事件或KataGo变化中如何体现。没有证明强制时，不写成必应或必杀。", ["要先看S的代价，还是J的机制？"]),
        ("用户只问实战手S的作用，应怎样回答？", "聚焦S落子后的具体棋形、连接、气或目标变化，并说明它的价值与局限。除非比较有助于回答原问，否则不要把整段内容改写成J的推荐词。", ["要继续比较S与J吗？"]),
        ("用户只问AI首选J，能混入另一手的结论吗？", "不能。先解释J本身的目标和已验证变化；若提到S，只能作为清楚标注的对照，不能把S的规则事实或教学评价算到J身上。", ["要查看J后的主要应对吗？"]),
        ("证据没有胜率和目差，回答能给估算数字吗？", "不能。数值必须来自登记的本次KataGo制品；没有数值时只做有证据的定性说明，并明确未报告胜率或目差。", ["要重新运行KataGo取得数值吗？"]),
        ("胜率属于谁的视角必须说明吗？", "必须。报告胜率前要核对KataGo输出视角、当前行棋方和展示方；视角不明就不报百分比，避免把对手胜率当成己方胜率。", ["要先核对本次分析视角吗？"]),
        ("为什么回答只写S、J和变化点别名？", "S固定表示实战手，J固定表示AI首选，其他变化使用证据内稳定别名。这样既能在棋盘上定位，又能避免模型把旧局面的内部坐标带到新局面。", ["要在棋盘上高亮S与J吗？"]),
        ("如果实战手和AI首选落在同一点，怎样表达？", "仍保留两个角色，并明确写S与J同点：S表示实战身份，J表示引擎身份。不能因为坐标相同就把其中一个角色抹掉。", ["要查看两者同点的证据吗？"]),
        ("直接问题需要写很长吗？", "不需要。先用一句话回答，再给最关键的棋形机制和必要边界；只有复杂比较才展开多分支，避免重复结论和堆叠工具日志。", ["要看精简版还是深入版？"]),
        ("棋盘方向不确定时能继续报坐标吗？", "不能。方向、行棋方或目标着法无法唯一确认时，应停止坐标结论，要求重新校准棋盘或补充证据；不能凭画面印象猜测。", ["要重新校准棋盘方向吗？"]),
        ("工具调用顺序可以由模型随意改吗？", "不能。服务端根据任务类型执行确定性白名单计划，并验证每步输入输出；语言模型可以提出意图，但不能绕过规则校验、来源绑定或授权门禁。", ["要显示本轮合法计划吗？"]),
        ("用户指出行棋方标错后，应继续沿用旧分析吗？", "不应继续。先撤销受影响的结论，按用户更正重新核对棋谱、当前行棋方、规则重放和KataGo输入；新证据通过后再回答，并保留更正说明。", ["要现在重新构建这手证据吗？"]),
    ]


def replace_project_answers(rows: list[dict[str, Any]]) -> tuple[int, int]:
    projects = [
        row for row in rows
        if row.get("metadata", {}).get("sourceType") == "project_original"
        and row.get("metadata", {}).get("taskType") == "answer"
    ]
    # Gold amplification has already replaced 96 of the original project rows.
    if len(projects) != 48:
        raise ValueError(f"expected 48 project answers after gold amplification, got {len(projects)}")
    concepts = _concept_variants()
    agents = _agent_examples()
    if len(concepts) != 24 or len(agents) != 24:
        raise AssertionError("v3 remediation sets must each contain 24 unique examples")
    for index, (row, (question, answer, followups)) in enumerate(
        zip(projects, concepts + agents)
    ):
        row["messages"] = [
            {"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user", "content": f"用户问题：{question}"},
            {
                "role": "assistant",
                "content": json.dumps(
                    {"answer": answer, "followUps": followups},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ]
        row["metadata"].update({
            "augmentationId": f"project-remediation-v3-{index + 1:02d}",
            "projectOriginalAugmentation": (
                "conceptual-routing-remediation-v3"
                if index < 24
                else "agent-runtime-remediation-v3"
            ),
            "questionScope": "conceptual_term" if index < 24 else "agent_runtime",
        })
    return len(concepts), len(agents)


def _message_hash(row: dict[str, Any]) -> str:
    canonical = json.dumps(
        row.get("messages") or [], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sentence_repeats(value: str) -> list[str]:
    seen: set[str] = set()
    repeats: list[str] = []
    for raw in SENTENCE.findall(value):
        normalized = re.sub(r"[\s，,。！？!?；;：:、]", "", raw)
        if len(normalized) < 8:
            continue
        if normalized in seen:
            repeats.append(normalized)
        seen.add(normalized)
    return repeats


def validate_train(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) != 720:
        raise ValueError(f"expected 720 train rows, got {len(rows)}")
    if any(row.get("metadata", {}).get("split") != "train" for row in rows):
        raise ValueError("train corpus contains a non-train row")
    task_counts = Counter(row.get("metadata", {}).get("taskType") for row in rows)
    expected_tasks = {"planner": 216, "answer": 288, "followup": 144, "memory_privacy": 72}
    if task_counts != expected_tasks:
        raise ValueError(f"task counts changed: {task_counts}")
    source_rows = Counter(row.get("metadata", {}).get("sourceType") for row in rows)
    expected_source_rows = {
        "creator_authorized": 240,
        "project_original": 320,
        "public_domain": 160,
    }
    if source_rows != expected_source_rows:
        raise ValueError(f"source projection counts changed: {source_rows}")
    source_cases: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        metadata = row.get("metadata", {})
        source_cases[str(metadata.get("sourceType"))].add(str(metadata.get("sourceCaseId")))
    expected_cases = {"creator_authorized": 48, "project_original": 96, "public_domain": 64}
    actual_cases = {key: len(value) for key, value in source_cases.items()}
    if actual_cases != expected_cases:
        raise ValueError(f"source case counts changed: {actual_cases}")

    duplicates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    coordinate_rows: list[str] = []
    repeated_rows: list[str] = []
    for row in rows:
        metadata = row.get("metadata", {})
        row_id = str(metadata.get("sourceCaseId"))
        task = str(metadata.get("taskType"))
        duplicates[_message_hash(row)].append(row)
        for message in row.get("messages") or []:
            content = str(message.get("content") or "")
            if COORDINATE.search(content):
                coordinate_rows.append(row_id)
            if message.get("role") == "assistant" and task in {"answer", "followup"}:
                try:
                    payload = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"assistant JSON invalid: {row_id}") from exc
                if not isinstance(payload, dict) or not isinstance(payload.get("answer"), str):
                    raise ValueError(f"assistant JSON shape invalid: {row_id}")
                if _sentence_repeats(payload["answer"]):
                    repeated_rows.append(row_id)
    if coordinate_rows:
        raise ValueError(f"v3 still exposes internal coordinates: {coordinate_rows[:3]}")
    if repeated_rows:
        raise ValueError(f"v3 contains repeated answer sentences: {repeated_rows[:3]}")
    illegal_duplicates = [
        group for group in duplicates.values()
        if len(group) > 1
        and any(row.get("metadata", {}).get("taskType") != "planner" for row in group)
    ]
    if illegal_duplicates:
        ids = [row.get("metadata", {}).get("sourceCaseId") for row in illegal_duplicates[0]]
        raise ValueError(f"non-planner duplicate training messages: {ids}")
    return {
        "taskCounts": dict(task_counts),
        "sourceProjectionCounts": dict(source_rows),
        "sourceCaseCounts": actual_cases,
        "coordinateLeakRows": 0,
        "repeatedSentenceRows": 0,
        "allowedPlannerDuplicateGroups": sum(len(group) > 1 for group in duplicates.values()),
    }


def validate_dev(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) != 24:
        raise ValueError(f"expected 24 dev rows, got {len(rows)}")
    if any(row.get("metadata", {}).get("split") != "dev" for row in rows):
        raise ValueError("dev corpus contains a non-dev row")
    leaks = [
        str(row.get("metadata", {}).get("sourceCaseId"))
        for row in rows
        if any(COORDINATE.search(str(message.get("content") or "")) for message in row.get("messages") or [])
    ]
    if leaks:
        raise ValueError(f"dev still exposes internal coordinates: {leaks[:3]}")
    return {"rows": 24, "coordinateLeakRows": 0}


def build(source: Path, output: Path) -> dict[str, Any]:
    manifest_path = source / "manifest.json"
    parent = json.loads(manifest_path.read_text(encoding="utf-8"))
    if parent.get("schemaVersion") != "yijian-agent-sft-v1" or parent.get("passed") is not True:
        raise ValueError("source corpus is not a passed immutable v1 release")
    parent_outputs = parent.get("outputs") or {}
    train_path = source / "agent_sft_train.jsonl"
    dev_path = source / "agent_sft_dev.jsonl"
    for path in (train_path, dev_path):
        if parent_outputs.get(path.name) != sha256(path):
            raise ValueError(f"parent artifact hash mismatch: {path.name}")
    sealed_hash = str(parent_outputs.get("agent_sft_test.jsonl") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", sealed_hash):
        raise ValueError("parent sealed artifact hash is missing")

    # Do not open source/agent_sft_test.jsonl here.
    train = [normalize_row(row, split="train") for row in read_jsonl(train_path)]
    dev = [normalize_row(row, split="dev") for row in read_jsonl(dev_path)]
    gold_rows = amplify_gold_answers(train)
    concept_rows, agent_rows = replace_project_answers(train)
    train_audit = validate_train(train)
    dev_audit = validate_dev(dev)

    output.mkdir(parents=True, exist_ok=True)
    train_output = output / "agent_sft_train.jsonl"
    dev_output = output / "agent_sft_dev.jsonl"
    write_jsonl(train_output, train)
    write_jsonl(dev_output, dev)
    outputs = {
        train_output.name: sha256(train_output),
        dev_output.name: sha256(dev_output),
    }
    result = {
        "schemaVersion": SCHEMA,
        "passed": True,
        "purpose": "qwen3-14b-yijian-lora-v3-runtime-aligned-gold-amplified",
        "sourceCorpus": {
            "artifact": source.name,
            "manifestSha256": sha256(manifest_path),
            "schemaVersion": parent["schemaVersion"],
        },
        "builderSha256": sha256(Path(__file__).resolve()),
        "counts": {"train": 720, "dev": 24, "sealed": 24},
        "taskCounts": train_audit["taskCounts"],
        "sourceProjectionCounts": train_audit["sourceProjectionCounts"],
        "sourceCaseCounts": train_audit["sourceCaseCounts"],
        "gates": {
            "parentTrainDevHashesMatch": True,
            "exactTaskRatio": True,
            "exactSourceCases": True,
            "allMessagesCoordinateFree": True,
            "assistantJsonValid": True,
            "noRepeatedAnswerSentences": True,
            "noNonPlannerExactDuplicates": True,
            "sealedTestAccessed": False,
            "sealedTestEligibleForTraining": False,
        },
        "remediation": {
            "protocol": PROTOCOL,
            "goldRuntimeAnswerVariants": gold_rows,
            "conceptualRoutingRows": concept_rows,
            "agentRuntimeRows": agent_rows,
            "actualBestSamePointPolicy": "independent S/J roles plus samePoint evidence",
            "otherCoordinatePolicy": "stable Chinese variation aliases",
        },
        "audits": {"train": train_audit, "dev": dev_audit},
        "artifacts": {
            "train": {
                "role": "train", "filename": train_output.name,
                "sha256": outputs[train_output.name], "rows": 720,
            },
            "dev": {
                "role": "dev", "filename": dev_output.name,
                "sha256": outputs[dev_output.name], "rows": 24,
            },
            "sealed": {
                "role": "sealed", "sourceFilename": "agent_sft_test.jsonl",
                "sha256": sealed_hash, "rows": 24, "accessed": False,
            },
        },
        "outputs": outputs,
    }
    (output / "manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(
        build(args.source.resolve(), args.output.resolve()),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
