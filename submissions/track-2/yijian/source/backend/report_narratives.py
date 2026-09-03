# -*- coding: utf-8 -*-
"""整盘分析完成后生成可缓存的 LLM 表达层。

本模块只消费已经冻结的 KataGo、规则和启发式证据，不参与引擎计算，
也不允许模型回写任何数值或候选点。
"""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy

import coach
import mentor


SCHEMA_VERSION = "report-narrative-v1"
DEFAULT_NODE_COUNT = 6


def _provider() -> str:
    value = os.getenv("GOMENTOR_BATCH_MENTOR_PROVIDER", "cloud").strip().lower()
    return value if value in ("local", "cloud") else "cloud"


def _settings() -> dict:
    # 延迟导入避免 library -> jobs 的启动依赖形成环。
    import library

    return coach.normalize_settings(
        library.get_setting("coach", coach.DEFAULT_SETTINGS)
    )


def signature_fragment() -> str:
    """报告缓存的一部分；模型、提示词或教学设置改变都会触发重建。"""
    provider = _provider()
    config = mentor._provider_config(provider)
    revision = os.getenv(
        "YIJIAN_MENTOR_MODEL_REVISION", config["model"]
    ).strip()
    payload = {
        "schema": SCHEMA_VERSION,
        "provider": provider,
        "model": config["model"],
        "revision": revision,
        "settings": _settings(),
        "nodes": max(
            0,
            int(
                os.getenv(
                    "GOMENTOR_BATCH_NARRATIVE_NODES",
                    str(DEFAULT_NODE_COUNT),
                )
            ),
        ),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _region(move: str | None, board_size: int = 19) -> str | None:
    if not move or str(move).lower() == "pass":
        return None
    letters = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
    name = str(move).upper()
    if name[0] not in letters:
        return None
    try:
        x = letters.index(name[0])
        row = int(name[1:])
    except (ValueError, IndexError):
        return None
    if not 1 <= row <= board_size:
        return None
    y = board_size - row
    horizontal = (
        "左边" if x < board_size / 3
        else ("右边" if x >= board_size * 2 / 3 else "中央")
    )
    vertical = (
        "上方" if y < board_size / 3
        else ("下方" if y >= board_size * 2 / 3 else "中腹")
    )
    return horizontal + vertical


def _role(purpose: dict) -> str:
    roles = []
    if purpose.get("captures"):
        roles.append("提子")
    if purpose.get("connection"):
        roles.append("联络己方棋块")
    if purpose.get("cut"):
        roles.append("切断对方")
    if purpose.get("defense"):
        roles.append("补强己方弱棋")
    if purpose.get("attack"):
        roles.append("向对方棋块施压")
    return "并兼顾".join(roles[:2]) or "改善局部效率并兼顾全局方向"


def _inputs(raw: dict, node: dict) -> tuple[dict, dict, dict]:
    purpose_evidence = deepcopy(node.get("purposeEvidence") or {})
    engine = raw.get("engine") or {}
    positions = raw.get("positions") or []
    turn = int(node.get("turn") or 0)
    post = positions[turn] if 0 <= turn < len(positions) else {}
    actual = node.get("actualMove")
    best = node.get("recommendedMove")
    size = int((raw.get("game") or {}).get("boardSize") or 19)
    region = _region(actual, size)
    position = {
        "turn": turn,
        "move": actual,
        "player": "黑" if node.get("color") == "B" else "白",
        "boardSize": size,
        "moveCandidates": {
            "decisionTurn": max(0, turn - 1),
            "actual": {
                "kind": "actual",
                "move": actual,
                "region": {
                    "label": region,
                    "source": "coordinate_projection",
                    "confidence": "deterministic",
                },
            } if actual else None,
            "best": {
                "kind": "best",
                "move": best,
                "region": {
                    "label": _region(best, size),
                    "source": "coordinate_projection",
                    "confidence": "deterministic",
                },
                "analysis": {
                    "source": engine.get("source"),
                    "demo": bool(engine.get("demo", True)),
                    "visits": node.get("deepVisits") or engine.get("criticalVisits"),
                    "pv": list(node.get("pv") or [])[:10],
                },
            } if best else None,
            "sameMove": bool(
                actual and best and str(actual).upper() == str(best).upper()
            ),
        },
    }
    evidence = {
        "winrate": (
            float(post["winrateBlack"]) * 100
            if isinstance(post.get("winrateBlack"), (int, float))
            else None
        ),
        "scoreLead": post.get("scoreLeadBlack"),
        "bestMove": best,
        "winrateLoss": node.get("winrateLoss"),
        "scoreLoss": node.get("scoreLoss"),
        "pv": list(node.get("pv") or [])[:10],
        "source": engine.get("source"),
        "demo": bool(engine.get("demo", True)),
        "visits": node.get("deepVisits") or engine.get("criticalVisits"),
    }
    purpose = {
        "title": f"第 {turn} 手 {node.get('color') or ''} {actual or 'pass'} 的作用",
        "region": region or "当前区域",
        "role": _role(purpose_evidence),
        "ownNearby": purpose_evidence.get("connectedGroups"),
        "enemyNearby": purpose_evidence.get("adjacentOpponentGroups"),
        "captured": purpose_evidence.get("captures"),
        "confidence": "heuristic",
        "evidenceSummary": (
            "具体数值以上方 KataGo 权威证据为准；"
            "模型只负责解释实战手与首选的棋理差异。"
        ),
        "nextFocus": "比较双方弱棋、先手权、厚薄与地盘转换。",
        "evidenceSource": list(
            purpose_evidence.get("evidenceSource") or ["board_rules"]
        ),
    }
    return position, evidence, purpose


def enrich(raw: dict) -> dict:
    """在 KataGo 全部任务结束后，为高价值节点批量生成讲解。

    服务不可用时保留完整报告并记录失败，不把 LLM 故障升级为分析故障。
    """
    engine = raw.get("engine") or {}
    provider = _provider()
    config = mentor._provider_config(provider)
    revision = os.getenv(
        "YIJIAN_MENTOR_MODEL_REVISION", config["model"]
    ).strip()
    limit = max(
        0,
        int(
            os.getenv(
                "GOMENTOR_BATCH_NARRATIVE_NODES",
                str(DEFAULT_NODE_COUNT),
            )
        ),
    )
    metadata = {
        "schemaVersion": SCHEMA_VERSION,
        "provider": provider,
        "model": config["model"],
        "modelRevision": revision,
        "requested": 0,
        "generated": 0,
        "failed": 0,
        "skipped": None,
    }
    raw["narrativeBatch"] = metadata
    if (
        limit == 0
        or engine.get("source") != "katago"
        or bool(engine.get("demo", True))
    ):
        metadata["skipped"] = (
            "disabled" if limit == 0 else "requires_true_katago"
        )
        return raw
    if not config["configured"]:
        metadata["skipped"] = "provider_not_configured"
        return raw

    settings = _settings()
    candidates = sorted(
        raw.get("losses") or [],
        key=lambda item: max(
            float(item.get("winrateLoss") or 0) / 10,
            float(item.get("scoreLoss") or 0) / 5,
        ),
        reverse=True,
    )[:limit]
    metadata["requested"] = len(candidates)
    for node in candidates:
        position, evidence, purpose = _inputs(raw, node)
        try:
            result = mentor._call_provider(
                provider, settings, position, evidence, purpose
            )
            node["narrative"] = {
                **result,
                "schemaVersion": SCHEMA_VERSION,
                "modelRevision": revision,
                "settingsFingerprint": signature_fragment(),
            }
            metadata["generated"] += 1
        except mentor.MentorProviderError as exc:
            metadata["failed"] += 1
            metadata.setdefault("errors", []).append(
                {"turn": node.get("turn"), "message": str(exc)[:300]}
            )
    return raw
