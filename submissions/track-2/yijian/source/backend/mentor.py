# -*- coding: utf-8 -*-
"""可插拔围棋导师：基础讲解、本地离线模型与云端增强共用同一证据协议。"""

from __future__ import annotations

import hashlib
import difflib
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import coach
import classical_go


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FEEDBACK_DB = DATA_DIR / "mentor_feedback.db"
VALID_MODES = {"baseline", "local", "cloud", "compare"}
_STATUS_LOCK = threading.Lock()
_STATUS_CACHE: tuple[float, dict] | None = None
_REGION_ALIASES = {
    "左边上方": ("左边上方", "左上方", "左上区域", "左上角"),
    "中央上方": ("中央上方", "上方中央", "上边", "上侧"),
    "右边上方": ("右边上方", "右上方", "右上区域", "右上角"),
    "左边中腹": ("左边中腹", "左侧中腹", "左边区域"),
    "中央中腹": ("中央中腹", "中央区域", "正中央"),
    "右边中腹": ("右边中腹", "右侧中腹", "右边区域"),
    "左边下方": ("左边下方", "左下方", "左下区域", "左下角"),
    "中央下方": ("中央下方", "下方中央", "下边", "下侧"),
    "右边下方": ("右边下方", "右下方", "右下区域", "右下角"),
}
MENTOR_SYSTEM = (
    "你是弈鉴古典围棋教练。KataGo负责棋力事实，规则引擎负责合法性，"
    "你只依据给定证据组织教学表达。必须先回答用户正在问的目标着法，"
    "再说明棋理、代价和验证方法；不得混淆实战手与AI首选，不得新增坐标、"
    "胜率、目差、死活结论或定式分支。古训只能作为检查角度。只返回JSON："
    "任务为追问时字段是answer与followUps；任务为当前手讲解时字段是"
    "purpose、tradeoff与nextFocus。"
)


class MentorProviderError(RuntimeError):
    """模型服务不可用或输出不符合导师协议。"""


def _provider_config(provider: str) -> dict:
    prefix = "YIJIAN_LOCAL_LLM" if provider == "local" else "YIJIAN_CLOUD_LLM"
    default_url = "http://127.0.0.1:8081/v1" if provider == "local" else ""
    default_model = (
        "Qwen3-4B-Q4_K_M"
        if provider == "local"
        else "Yijian-Qwen3.6-27B-GoCoach"
    )
    url = os.getenv(f"{prefix}_URL", default_url).strip().rstrip("/")
    return {
        "id": provider,
        "name": "本地离线老师" if provider == "local" else "云端增强老师",
        "url": url,
        "model": os.getenv(f"{prefix}_MODEL", default_model).strip() or default_model,
        "apiKey": os.getenv(f"{prefix}_API_KEY", "").strip(),
        "configured": bool(url),
    }


def _request_json(url: str, *, payload: dict | None = None,
                  api_key: str = "", timeout: float = 2.0) -> dict:
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(url, data=data, headers=headers,
                      method="POST" if payload is not None else "GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise MentorProviderError(f"模型服务返回 {exc.code}：{detail}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise MentorProviderError(f"无法连接模型服务：{exc}") from exc


def _probe_provider(config: dict) -> dict:
    value = {key: config[key] for key in ("id", "name", "model", "configured")}
    value.update({"ready": False, "detail": "尚未配置"})
    if not config["configured"]:
        return value
    started = time.perf_counter()
    try:
        response = _request_json(
            f"{config['url']}/models", api_key=config["apiKey"], timeout=.45
        )
        models = response.get("data") if isinstance(response, dict) else None
        detected = models[0].get("id") if isinstance(models, list) and models else config["model"]
        value.update({
            "ready": True,
            "detail": "模型服务已就绪",
            "detectedModel": detected,
            "latencyMs": round((time.perf_counter() - started) * 1000),
        })
    except MentorProviderError as exc:
        value["detail"] = str(exc)
    return value


def provider_status(force: bool = False) -> dict:
    """返回讲解能力状态；短缓存避免界面轮询反复连接模型端口。"""
    global _STATUS_CACHE
    now = time.monotonic()
    with _STATUS_LOCK:
        if not force and _STATUS_CACHE and now - _STATUS_CACHE[0] < 3:
            return _STATUS_CACHE[1]
        local = _probe_provider(_provider_config("local"))
        cloud = _probe_provider(_provider_config("cloud"))
        value = {
            "defaultMode": "baseline",
            "modes": [
                {"id": "baseline", "name": "基础棋理", "ready": True,
                 "detail": "不依赖大模型，始终可用"},
                local,
                cloud,
                {"id": "compare", "name": "双模型对比",
                 "ready": local["ready"] and cloud["ready"],
                 "detail": "同时比较本地与云端输出"},
            ],
            "offlineReady": True,
        }
        _STATUS_CACHE = (now, value)
        return value


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned,
                         flags=re.IGNORECASE | re.DOTALL)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise MentorProviderError("模型没有返回规定的结构化讲解")
    try:
        value = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise MentorProviderError("模型讲解不是有效 JSON") from exc
    required = ("purpose", "tradeoff", "nextFocus")
    if not all(isinstance(value.get(key), str) and value[key].strip() for key in required):
        raise MentorProviderError("模型讲解缺少目的、得失或后续关注点")
    result = {key: value[key].strip()[:700] for key in required}
    copied_placeholders = {
        "这一手的目的与关联棋群", "所得、代价或不确定性", "下一步具体观察动作",
    }
    if any(text in copied_placeholders for text in result.values()):
        raise MentorProviderError("模型只复述了字段说明")
    return result


def _mentor_prompt(settings: dict, position: dict, evidence: dict, purpose: dict) -> str:
    candidates = position.get("moveCandidates") or {}
    actual = candidates.get("actual") or {}
    best = candidates.get("best") or {}
    actual_region = actual.get("region") or {}
    best_region = best.get("region") or {}
    facts = {
        "任务": "当前手讲解",
        "问题目标": "实战手",
        "能力": "厚薄、取舍、先后手与后续验证",
        "证据": {
            "实战手": {
                "区域": actual_region.get("label") or purpose.get("region"),
                "启发式作用": purpose.get("role"),
                "附近己方": purpose.get("ownNearby"),
                "附近对方": purpose.get("enemyNearby"),
                "提子": purpose.get("captured"),
            },
            "AI首选": {
                "区域": best_region.get("label"),
                "来源": evidence.get("source"),
                "演示": evidence.get("demo"),
                "访问量": evidence.get("visits"),
            },
            "KataGo数值只由界面展示": {
                "胜率损失": evidence.get("winrateLoss"),
                "目差损失": evidence.get("scoreLoss"),
            },
            "后续检查": purpose.get("nextFocus"),
        },
        "学员": {
            "棋力": settings.get("studentRank"),
            "人格": settings.get("persona"),
            "篇幅": settings.get("explanationLength"),
        },
        "表达方式": "复盘提问",
        "禁止新增": [
            "服务端未提供的坐标",
            "服务端未提供的胜率或目差",
            "未经验证的死活结论",
            "未经检索的定式分支",
        ],
    }
    return (
        "/no_think\n证据："
        + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
        + "\n问题：请讲清楚实战手的目的、取舍，以及下一步怎样验证。"
    )


def _analysis_label(evidence: dict) -> str:
    if evidence.get("source") == "katago" and evidence.get("demo") is False:
        return "KataGo"
    if evidence.get("demo") or evidence.get("source") == "mock":
        return "演示分析"
    return "服务端分析"


def _analysis_phrase(evidence: dict, noun: str) -> str:
    label = _analysis_label(evidence)
    separator = " " if label == "KataGo" else ""
    return f"{label}{separator}{noun}"


def _remove_numeric_claims(
    structured: dict, purpose: dict, evidence: dict | None = None
) -> dict:
    """模型不能成为第二套数值来源；含数字字段以确定性文案替换。"""
    digit = re.compile(r"[0-9０-９]")
    analysis_evidence = _analysis_phrase(evidence or {}, "证据")
    fallbacks = {
        "purpose": str(purpose.get("role") or "结合关联棋群判断这一手的攻防目的。"),
        "tradeoff": (
            f"具体得失以上方{analysis_evidence}为准；"
            "继续检查所得是否足以补偿形势代价。"
        ),
        "nextFocus": str(purpose.get("nextFocus") or "在推荐变化中比较后续先手与地盘转换。"),
    }
    return {
        key: (fallbacks[key] if digit.search(structured[key]) else structured[key])
        for key in ("purpose", "tradeoff", "nextFocus")
    }


def _remove_unsupported_domain_claims(
    structured: dict,
    position: dict,
    evidence: dict,
    purpose: dict,
) -> dict:
    """专项棋理没有上游证据时，模型不能把训练语料中的领域词串进来。"""
    source = json.dumps(
        {
            "position": position,
            "evidence": evidence,
            "purpose": purpose,
        },
        ensure_ascii=False,
    )
    unsupported = []
    if "劫" not in source:
        unsupported.extend(("劫材", "打劫", "劫争", "应劫", "伪威胁"))
    if "定式" not in source:
        unsupported.append("定式")
    if not any(word in source for word in ("死活", "做活", "杀棋")):
        unsupported.extend(("死活", "做活", "杀棋"))
    fallbacks = {
        "purpose": str(
            purpose.get("role")
            or "结合双方弱棋与关联棋群判断这一手的攻防目的。"
        ),
        "tradeoff": (
            "具体得失以上方权威证据为准；"
            "继续比较先手、厚薄与地盘转换。"
        ),
        "nextFocus": str(
            purpose.get("nextFocus")
            or "在推荐变化中逐手核对双方最强应对。"
        ),
    }
    return {
        key: (
            fallbacks[key]
            if any(word in structured[key] for word in unsupported)
            else structured[key]
        )
        for key in ("purpose", "tradeoff", "nextFocus")
    }


def _call_provider(provider: str, settings: dict, position: dict,
                   evidence: dict, purpose: dict) -> dict:
    config = _provider_config(provider)
    if not config["configured"]:
        raise MentorProviderError(f"{config['name']}尚未配置")
    started = time.perf_counter()
    response = _request_json(
        f"{config['url']}/chat/completions",
        api_key=config["apiKey"],
        timeout=float(os.getenv("YIJIAN_LLM_TIMEOUT", "8.5")),
        payload={
            "model": config["model"],
            "messages": [
                {"role": "system", "content": MENTOR_SYSTEM},
                {"role": "user", "content": _mentor_prompt(settings, position, evidence, purpose)},
            ],
            "temperature": .2,
            "max_tokens": 220,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    try:
        text = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise MentorProviderError("模型服务响应缺少讲解正文") from exc
    structured = _remove_numeric_claims(_extract_json(text), purpose, evidence)
    structured = _remove_unsupported_domain_claims(
        structured, position, evidence, purpose
    )
    return {
        "source": provider,
        "sourceLabel": config["name"],
        "model": config["model"],
        "latencyMs": round((time.perf_counter() - started) * 1000),
        "title": purpose.get("title") or "这一手的作用",
        "paragraphs": [structured["purpose"], structured["tradeoff"], structured["nextFocus"]],
    }


def explain(mode: str, settings: dict | None, position: dict | None,
            evidence: dict | None, purpose: dict | None,
            cached_narrative: dict | None = None) -> dict:
    """生成讲解。任何模型失败都返回确定性基础讲解，不阻断复盘。"""
    normalized = coach.normalize_settings(settings)
    position = position or {}
    evidence = evidence or {}
    purpose = purpose or {}
    baseline = coach.preview(normalized, position, evidence, purpose)
    baseline_result = {
        "source": "baseline",
        "sourceLabel": "基础棋理",
        "model": None,
        "latencyMs": 0,
        "title": baseline.get("title") or "这一手的作用",
        "paragraphs": baseline.get("analysisParagraphs") or baseline["paragraphs"][1:],
    }
    selected = mode if mode in VALID_MODES else "baseline"
    if selected == "baseline":
        return {"mode": selected, "primary": baseline_result,
                "results": {"baseline": baseline_result}, "degraded": False,
                "evidence": baseline["evidence"], "evidenceLine": baseline["evidenceLine"]}

    if (
        selected in ("local", "cloud")
        and isinstance(cached_narrative, dict)
        and cached_narrative.get("source") == selected
        and cached_narrative.get("schemaVersion") == "report-narrative-v1"
        and isinstance(cached_narrative.get("paragraphs"), list)
    ):
        cached_result = deepcopy(cached_narrative)
        cached_result["cached"] = True
        return {
            "mode": selected,
            "primary": cached_result,
            "results": {
                "baseline": baseline_result,
                selected: cached_result,
            },
            "errors": {},
            "degraded": False,
            "cached": True,
            "evidence": baseline["evidence"],
            "evidenceLine": baseline["evidenceLine"],
        }

    providers = [selected] if selected in ("local", "cloud") else ["local", "cloud"]
    results: dict[str, dict] = {"baseline": baseline_result}
    errors: dict[str, str] = {}
    if len(providers) == 1:
        provider = providers[0]
        try:
            results[provider] = _call_provider(provider, normalized, position, evidence, purpose)
        except MentorProviderError as exc:
            errors[provider] = str(exc)
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(_call_provider, provider, normalized, position, evidence, purpose): provider
                for provider in providers
            }
            for future in as_completed(futures):
                provider = futures[future]
                try:
                    results[provider] = future.result()
                except MentorProviderError as exc:
                    errors[provider] = str(exc)
    primary = results.get(selected) if selected != "compare" else results.get("local")
    primary = primary or results.get("cloud") or baseline_result
    return {
        "mode": selected,
        "primary": primary,
        "results": results,
        "errors": errors,
        "degraded": primary["source"] == "baseline",
        "evidence": baseline["evidence"],
        "evidenceLine": baseline["evidenceLine"],
    }


def _chat_json(text: str) -> dict:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise MentorProviderError("围棋老师没有返回有效回答")
    if "{" in cleaned or "}" in cleaned:
        value = _extract_json_object(cleaned)
    else:
        # Qwen3.6 在复杂中文教学任务中偶尔遵循正文要求、但忽略 JSON
        # 外壳。正文仍须经过同一套数值、坐标、范围和深度校验。
        value = {"answer": cleaned, "followUps": []}
    answer = value.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise MentorProviderError("围棋老师没有返回有效回答")
    answer = answer.strip()[:1800]
    if (
        re.search(r"(?:胜率|目差)[^。；\n]{0,20}[0-9０-９]", answer)
        or re.search(r"[0-9０-９][^。；\n]{0,8}(?:%|％|个百分点|目差)", answer)
        or re.search(r"[0-9０-９]+(?:\.[0-9０-９]+)?\s*目(?:[^的]|$)", answer)
    ):
        raise MentorProviderError("围棋老师尝试重新生成数值证据")
    followups = value.get("followUps")
    if not isinstance(followups, list):
        followups = []
    followups = [
        str(item).strip()[:80] for item in followups
        if isinstance(item, str) and item.strip()
    ][:3]
    return {"answer": answer, "followUps": followups}


def _validate_supported_numbers(
    answer: str,
    position: dict,
    evidence: dict | None = None,
) -> dict:
    """只允许回答复述服务端已给出的规则计数和两手坐标。"""
    candidates = _move_candidates(position)
    allowed_moves = {
        str(candidate.get("move") or "").upper()
        for candidate in (candidates.get("actual"), candidates.get("best"))
        if isinstance(candidate, dict) and candidate.get("move")
    }
    mentioned_moves = {
        match.upper()
        for match in re.findall(
            r"(?<![A-Z])([A-HJ-T](?:[1-9]|1[0-9]))(?!\d)",
            answer.upper(),
        )
    }
    unexpected_moves = mentioned_moves - allowed_moves
    if unexpected_moves:
        raise MentorProviderError(
            "围棋老师新增了未提供的坐标：" + "、".join(sorted(unexpected_moves))
        )

    allowed_numbers: set[float] = set()

    def collect(value: object) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            allowed_numbers.add(float(value))
        elif isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for candidate in (candidates.get("actual"), candidates.get("best")):
        if not isinstance(candidate, dict):
            continue
        collect(candidate.get("rules"))
        heuristics = (
            candidate.get("heuristics")
            if isinstance(candidate.get("heuristics"), dict)
            else {}
        )
        collect(heuristics.get("localSituation"))
    variation_value = (
        evidence.get("variationEvidence")
        if isinstance(evidence, dict)
        and isinstance(evidence.get("variationEvidence"), dict)
        else {}
    )
    # 允许复述服务端已经关联好的战术语义计数（目标棋块子数、扩气后
    # 气数等），但不把整份 KataGo 数值树无差别放开。
    collect(variation_value.get("tacticalSemantics"))

    without_moves = re.sub(
        r"(?m)^\s*\d+\s*(?:[.．、)]|｜)\s*", "", answer
    )
    for move in allowed_moves:
        without_moves = re.sub(
            re.escape(move), "", without_moves, flags=re.IGNORECASE
        )
    mentioned_numbers = {
        float(value)
        for value in re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", without_moves)
    }
    unsupported = mentioned_numbers - allowed_numbers
    if unsupported:
        rendered = "、".join(
            f"{value:g}" for value in sorted(unsupported)
        )
        raise MentorProviderError("围棋老师新增了未提供的规则计数：" + rendered)
    return {
        "status": "passed",
        "allowedMoves": sorted(allowed_moves),
        "mentionedMoves": sorted(mentioned_moves),
        "mentionedRuleNumbers": sorted(mentioned_numbers),
    }


def _extract_json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned,
                         flags=re.IGNORECASE | re.DOTALL)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise MentorProviderError("围棋老师没有返回规定的结构")
    try:
        value = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise MentorProviderError("围棋老师返回的结构无法读取") from exc
    if not isinstance(value, dict):
        raise MentorProviderError("围棋老师返回的不是对象")
    return value


def _trend(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "未知"
    if number > .05:
        return "改善"
    if number < -.05:
        return "受损"
    return "基本稳定"


def _move_candidates(position: dict) -> dict:
    value = position.get("moveCandidates")
    return value if isinstance(value, dict) else {}


def _question_target(
    question: str,
    position: dict,
    evidence: dict,
    requested_kind: str | None = None,
) -> dict:
    """识别问题目标；显式文字优先，随后采用经服务端解析的客户端意图。"""
    candidates = _move_candidates(position)
    actual = candidates.get("actual") if isinstance(candidates.get("actual"), dict) else {}
    best = candidates.get("best") if isinstance(candidates.get("best"), dict) else {}
    actual_move = str(actual.get("move") or position.get("move") or "").upper()
    best_move = str(best.get("move") or evidence.get("bestMove") or "").upper()
    question_text = str(question or "")
    normalized = question_text.upper()
    asks_actual = bool(actual_move and actual_move in normalized) or any(
        word in question_text for word in ("实战", "本手", "这手", "为什么不好", "错误")
    )
    asks_best = bool(best_move and best_move in normalized) or any(
        word in normalized for word in ("AI", "首选", "推荐", "候选")
    )
    comparison = (
        (asks_actual and asks_best)
        or any(
            word in question_text
            for word in ("相比", "比较", "区别", "差异", "不同")
        )
        and (asks_actual or asks_best)
    )
    if comparison:
        kind, label, move, confidence, source = (
            "comparison",
            "实战与 AI 首选比较",
            None,
            "high",
            "explicit_question_text",
        )
    elif asks_best:
        kind, label, move, confidence, source = (
            "best",
            "AI 首选",
            best_move or None,
            "high",
            "explicit_question_text",
        )
    elif asks_actual:
        kind, label, move, confidence, source = (
            "actual",
            "实战手",
            actual_move or None,
            "high",
            "explicit_question_text",
        )
    elif requested_kind == "best" and best:
        kind, label, move, confidence, source = (
            "best",
            "AI 首选",
            best_move or None,
            "high",
            "client_intent_server_resolved",
        )
    elif requested_kind == "comparison" and actual and best:
        kind, label, move, confidence, source = (
            "comparison",
            "实战与 AI 首选比较",
            None,
            "high",
            "client_intent_server_resolved",
        )
    elif requested_kind == "position":
        kind, label, move, confidence, source = (
            "position",
            "当前局面",
            None,
            "high",
            "client_intent_server_resolved",
        )
    elif actual:
        kind, label, move, confidence, source = (
            "actual",
            "实战手",
            actual_move or None,
            "high" if requested_kind == "actual" else "medium",
            (
                "client_intent_server_resolved"
                if requested_kind == "actual"
                else "deterministic_question_router"
            ),
        )
    else:
        kind, label, move, confidence, source = (
            "position",
            "当前局面",
            None,
            "medium",
            "deterministic_question_router",
        )
    return {
        "kind": kind,
        "label": label,
        "move": move,
        "source": source,
        "confidence": confidence,
        "evidencePath": (
            f"facts.moveCandidates.{kind}"
            if kind in ("actual", "best")
            else "facts.moveCandidates"
        ),
    }


_GTP_COLUMNS = "ABCDEFGHJKLMNOPQRST"


def _board_point_pattern(move: object, board_size: int = 19) -> str | None:
    """从坐标确定棋盘点型；这是几何事实，不是棋理评价。"""
    match = re.fullmatch(r"([A-HJ-T])(1[0-9]|[1-9])", str(move or "").upper())
    if not match or board_size < 3:
        return None
    column = _GTP_COLUMNS.find(match.group(1)) + 1
    row = int(match.group(2))
    if column <= 0 or column > board_size or row > board_size:
        return None
    edge_lines = sorted((
        min(column, board_size + 1 - column),
        min(row, board_size + 1 - row),
    ))
    if edge_lines == [3, 3]:
        return "三三"
    if edge_lines == [4, 4]:
        return "星位"
    return None


def _question_focus(question: str, position: dict) -> str:
    """识别追问真正新增的棋理焦点，不替代着法目标路由。"""
    if position.get("phase") != "布局":
        return "general"
    candidates = _move_candidates(position)
    actual = candidates.get("actual") if isinstance(candidates.get("actual"), dict) else {}
    best = candidates.get("best") if isinstance(candidates.get("best"), dict) else {}
    actual_opening = _candidate_opening(actual)
    framework = (
        actual_opening.get("framework")
        if isinstance(actual_opening.get("framework"), dict)
        else {}
    )
    has_three_star = framework.get("formation") == "three_star_style"
    best_is_three_three = _board_point_pattern(best.get("move")) == "三三"
    focus_markers = (
        "点三三", "三三", "三连星", "拆边", "角的优先级", "角为什么",
        "为什么角", "实空", "模样", "外势",
    )
    if has_three_star and best_is_three_three and any(
        marker in str(question or "") for marker in focus_markers
    ):
        return "territory_vs_influence"
    return "general"


def _candidate_region(candidate: dict | None) -> str | None:
    if not isinstance(candidate, dict):
        return None
    region = candidate.get("region")
    if isinstance(region, dict):
        value = region.get("label")
        return str(value) if value else None
    return str(region) if region else None


def _candidate_prompt_projection(
    candidate: dict | None, display_label: str | None = None
) -> dict | None:
    """只给表达模型当前问题所需的最小证据。"""
    if not isinstance(candidate, dict):
        return None
    region = candidate.get("region") if isinstance(candidate.get("region"), dict) else {}
    rules = candidate.get("rules") if isinstance(candidate.get("rules"), dict) else {}
    heuristics = (
        candidate.get("heuristics")
        if isinstance(candidate.get("heuristics"), dict)
        else {}
    )
    geometry = (
        candidate.get("geometry")
        if isinstance(candidate.get("geometry"), dict)
        else {}
    )
    opening = (
        heuristics.get("openingStrategy")
        if isinstance(heuristics.get("openingStrategy"), dict)
        else {}
    )
    local_situation = (
        heuristics.get("localSituation")
        if isinstance(heuristics.get("localSituation"), dict)
        else {}
    )
    liberties = (
        rules.get("libertiesBeforeAfter")
        if isinstance(rules.get("libertiesBeforeAfter"), dict)
        else {}
    )

    def liberty_sentence(side: str) -> str | None:
        values = liberties.get(side)
        if (
            not isinstance(values, list)
            or len(values) < 2
            or not all(isinstance(value, int) for value in values[:2])
        ):
            return None
        before, after = values[:2]
        if before == 0:
            return f"落子后新棋有 {after} 气"
        return f"由 {before} 变为 {after} 气"

    rule_projection = {
        key: value
        for key, value in {
            "合法": rules.get("legal"),
            "提子": rules.get("captures"),
            "联络": rules.get("connection"),
            "连接棋块": rules.get("connectedGroups"),
            "邻接对方棋块": rules.get("adjacentOpponentGroups"),
            "己方相邻棋块气数变化": liberty_sentence("own"),
            "对方相邻棋块气数变化": liberty_sentence("opponent"),
        }.items()
        if value is not None
    }
    heuristic_projection = {
        key: value
        for key, value in {
            "作用": heuristics.get("role"),
            "附近己方": heuristics.get("ownNearby"),
            "附近对方": heuristics.get("enemyNearby"),
            "布局类型": opening.get("strategicType"),
            "发展作用": opening.get("development"),
            "布局优先级": opening.get("priorityPrinciple"),
            "角部现状": (
                opening.get("cornerContext", {}).get("description")
                if isinstance(opening.get("cornerContext"), dict)
                else None
            ),
            "边上框架": (
                opening.get("framework", {}).get("description")
                if isinstance(opening.get("framework"), dict)
                else None
            ),
            "局面性质": local_situation.get("label"),
            "局部判断": local_situation.get("description"),
            "当前重点": local_situation.get("focus"),
            "讲解边界": local_situation.get("scopeGuard"),
            "可信度": heuristics.get("confidence"),
        }.items()
        if value is not None
    }
    return {
        key: value
        for key, value in {
            # 表达模型只需要知道这份证据属于 S 还是 J。真实坐标留在
            # 服务端权威上下文中，避免模型把内部坐标原样抄给用户。
            "显示名": display_label,
            "区域": region.get("label"),
            "坐标几何": {
                key: value
                for key, value in {
                    "层级": geometry.get("zoneLabel"),
                    "方位": geometry.get("sectorLabel"),
                    "可信度": geometry.get("confidence"),
                }.items()
                if value is not None
            } or None,
            "棋盘点型": _board_point_pattern(candidate.get("move")),
            "规则事实": rule_projection or None,
            "启发式判断": heuristic_projection or None,
        }.items()
        if value is not None
    }


def _variation_prompt_projection(value: dict | None, target_kind: str) -> dict | None:
    """压缩多分支裁决，避免把整份规则快照和无关分支塞给表达模型。"""
    if not isinstance(value, dict):
        return None
    if value.get("status") != "ready":
        return {
            "状态": value.get("status") or "unavailable",
            "原因": value.get("reason"),
            "来源": value.get("source"),
        }
    branches = value.get("branches") if isinstance(value.get("branches"), dict) else {}
    comparison = (
        value.get("comparison") if isinstance(value.get("comparison"), dict) else {}
    )
    actual_move = str(comparison.get("actualMove") or "").upper()
    best_move = str(comparison.get("bestMove") or "").upper()

    def public_move(move: object) -> str | None:
        normalized = str(move or "").upper()
        if normalized and normalized == actual_move:
            return "S"
        if normalized and normalized == best_move:
            return "J"
        return None
    selected_kinds = (
        ("best",)
        if target_kind == "best"
        else ("actual", "best")
    )
    projected_branches = {}
    for kind in selected_kinds:
        branch = branches.get(kind)
        if not isinstance(branch, dict):
            continue
        reply_rows = []
        for reply in list(branch.get("replies") or [])[:2]:
            replay = reply.get("ruleReplay") if isinstance(reply.get("ruleReplay"), dict) else {}
            events = []
            for event in list(replay.get("events") or [])[:6]:
                own_group = event.get("newGroup") if isinstance(event.get("newGroup"), dict) else {}
                opponent_groups = (
                    event.get("adjacentOpponentGroups")
                    if isinstance(event.get("adjacentOpponentGroups"), list)
                    else []
                )
                events.append({
                    key: item
                    for key, item in {
                        "手数": event.get("ply"),
                        "行棋方": event.get("player"),
                        # 只在事件恰好落在用户可见的 S/J 时显示着法；其余
                        # 后续坐标由手数和行棋方表达，规则结果仍完整保留。
                        "着法角色": public_move(event.get("move")),
                        "提子": event.get("captures"),
                        "连接合并棋块数": event.get("joinedOwnGroups"),
                        "新棋块": (
                            {
                                "子数": own_group.get("stones"),
                                "气数": own_group.get("liberties"),
                            }
                            if own_group else None
                        ),
                        "相邻对方棋块": [
                            {
                                "子数": group.get("stones"),
                                "气数": group.get("liberties"),
                            }
                            for group in opponent_groups[:3]
                            if isinstance(group, dict)
                        ] or None,
                        "打吃对方棋块数": event.get("opponentGroupsInAtari"),
                        "自身仅一气": event.get("selfAtari"),
                        "规则确认劫点": event.get("koPoint"),
                    }.items()
                    if item is not None
                })
            reply_rows.append({
                "排序": reply.get("rank"),
                "对方应对角色": public_move(reply.get("reply")) or "主要应对",
                "访问量": reply.get("visits"),
                # 只保留开头的棋形变化；长 PV 中远处出现的劫或提子不能
                # 自动解释当前局部急所。
                "开头规则事件": events[:3],
            })
        branch_label = "实战S" if kind == "actual" else "首选J"
        reply_search = (
            branch.get("replySearch")
            if isinstance(branch.get("replySearch"), dict)
            else {}
        )
        projected_branches[branch_label] = {
            "落点角色": "S" if kind == "actual" else "J",
            "落子后KataGo": branch.get("analysisAfterMove"),
            "应对搜索": {
                "数量": reply_search.get("count"),
                "首要应对角色": (
                    public_move(reply_search.get("topReply")) or "主要应对"
                ),
                "首要应对访问占比": reply_search.get("topReplyVisitShare"),
                "解释边界": reply_search.get("interpretationBoundary"),
                "来源": reply_search.get("source"),
            },
            "主要变化": reply_rows,
        }
    return {
        "状态": "已复核",
        "每分支访问量": value.get("visitsPerBranch"),
        "分支": projected_branches,
        "比较": {
            "实战": "S",
            "首选": "J",
            "S后对方首要应对仍是J": bool(
                comparison.get("bestBecameTopReplyAfterActual")
            ),
            "解释边界": comparison.get("interpretationBoundary"),
        },
        "局部棋形语义": value.get("tacticalSemantics"),
        "事实边界": value.get("claimBoundary"),
    }


def _question_for_prompt(question: str, candidates: dict) -> str:
    """模型不需要看到坐标；用服务端角色名替换已解析的两手坐标。"""
    value = str(question or "")
    for kind, label in (("actual", "实战手"), ("best", "AI首选")):
        candidate = candidates.get(kind)
        move = candidate.get("move") if isinstance(candidate, dict) else None
        if move:
            value = re.sub(re.escape(str(move)), label, value, flags=re.IGNORECASE)
    return (
        value.replace("实战 实战手", "实战手")
        .replace("AI AI首选", "AI首选")
        .replace("AI首选 AI首选", "AI首选")
    )


def _mentioned_regions(answer: str) -> set[str]:
    return {
        label
        for label, aliases in _REGION_ALIASES.items()
        if any(alias in answer for alias in aliases)
    }


def _validate_answer_binding(
    answer: str, target: dict, position: dict
) -> dict:
    """拒绝把一手棋的坐标区域描述成另一手；无区域主张时保持通过。"""
    kind = target.get("kind")
    candidates = _move_candidates(position)
    if kind not in ("actual", "best"):
        return {
            "status": "passed",
            "target": kind,
            "checks": ["question_target"],
        }
    candidate = candidates.get(kind)
    expected_region = _candidate_region(candidate)
    if not expected_region:
        return {
            "status": "passed",
            "target": kind,
            "checks": ["question_target"],
            "regionCheck": "not_available",
        }
    mentioned = _mentioned_regions(answer)
    if mentioned and expected_region not in mentioned:
        move = (candidate or {}).get("move") or target.get("move") or "目标着法"
        raise MentorProviderError(
            f"回答区域与{target.get('label') or '问题目标'} {move} 不一致："
            f"权威坐标区域为{expected_region}"
        )
    return {
        "status": "passed",
        "target": kind,
        "checks": ["question_target", "coordinate_region_binding"],
        "expectedRegion": expected_region,
        "mentionedRegions": sorted(mentioned),
    }


def _attach_classical_guidance(
    answer: str,
    question: str,
    target: dict,
    position: dict,
) -> tuple[str, dict]:
    """把可追溯古训作为确定性教学附注；不改写模型的局面主张。"""
    explicitly_requested = any(
        word in question
        for word in ("古典", "古训", "棋理", "口诀", "棋经", "古棋")
    )
    candidates = _move_candidates(position)
    selected = (
        [candidates.get("best")]
        if target.get("kind") == "best"
        else [candidates.get("actual")]
        if target.get("kind") == "actual"
        else [candidates.get("actual"), candidates.get("best")]
    )
    local_fight = any(
        _candidate_local_situation(candidate).get("scope") == "local_fight"
        for candidate in selected
        if isinstance(candidate, dict)
    )
    if local_fight and not explicitly_requested:
        return answer, {"status": "not_requested"}
    principle = classical_go.match_principle(
        question,
        str(target.get("kind") or ""),
        candidates,
    )
    if not principle:
        return answer, {"status": "not_available"}
    if principle["maxim"] in answer:
        return answer, {
            "status": "model_included",
            "principleId": principle["id"],
            "source": principle["work"],
        }
    enriched = (
        f"{answer.rstrip()} 古典棋理可参照“{principle['maxim']}”："
        f"{principle['gloss']}这只是检查角度，具体得失仍以当前变化证据为准。"
    )
    return enriched, {
        "status": "server_appended",
        "principleId": principle["id"],
        "source": principle["work"],
    }


def _chat_prompt(question: str, settings: dict, position: dict,
                 evidence: dict, purpose: dict,
                 question_target: dict | None = None,
                 history: list[dict] | None = None) -> str:
    target = question_target or _question_target(question, position, evidence)
    candidates = _move_candidates(position)
    target_kind = target.get("kind")
    question_focus = _question_focus(question, position)
    focused_comparison = question_focus == "territory_vs_influence"
    move_evidence = {}
    if target_kind in ("actual", "comparison") or focused_comparison:
        move_evidence["实战手"] = _candidate_prompt_projection(
            candidates.get("actual"), "S"
        )
    if target_kind in ("best", "comparison"):
        move_evidence["AI首选"] = _candidate_prompt_projection(
            candidates.get("best"), "J"
        )
    if target_kind == "actual" and candidates.get("best"):
        move_evidence["AI首选（只作对照）"] = _candidate_prompt_projection(
            candidates.get("best"), "J"
        )
    explicitly_asks_for_classical = any(
        word in question
        for word in ("古典", "古训", "棋理", "口诀", "棋经", "古棋")
    )
    selected_candidates = [
        candidate
        for candidate in (
            candidates.get("actual") if target_kind in ("actual", "comparison") else None,
            candidates.get("best") if target_kind in ("best", "comparison") else None,
        )
        if isinstance(candidate, dict)
    ]
    local_fight = any(
        _candidate_local_situation(candidate).get("scope") == "local_fight"
        for candidate in selected_candidates
    )
    may_use_classical = explicitly_asks_for_classical or not local_fight
    classical_principle = (
        classical_go.match_principle(
            question, str(target_kind or ""), candidates
        )
        if may_use_classical
        else {}
    )
    facts = {
        "目标": target.get("label"),
        "本轮焦点": (
            "三三取实空与三连星取模样、外势的兑现速度比较"
            if focused_comparison
            else "按用户原问作答"
        ),
        "阶段": position.get("phase"),
        "来源": evidence.get("source"),
        "演示": bool(evidence.get("demo")),
        "着法": move_evidence,
        "行棋次序关系": {
            "同一急点被让给对手": bool(
                (evidence.get("decisionRelation") or {}).get(
                    "missedBestBecameOpponentBestReply"
                )
            ),
            "可复核事实": (
                (evidence.get("decisionRelation") or {}).get("description")
            ),
            "解释边界": (
                (evidence.get("decisionRelation") or {}).get(
                    "interpretationBoundary"
                )
            ),
            "来源": (evidence.get("decisionRelation") or {}).get("source"),
            "可信度": (
                (evidence.get("decisionRelation") or {}).get("confidence")
            ),
        },
        "多分支变化裁决": _variation_prompt_projection(
            evidence.get("variationEvidence"), str(target_kind or "position")
        ),
        "古训": (
            {
                "原句": classical_principle.get("maxim"),
                "今释": classical_principle.get("gloss"),
                "来源": classical_principle.get("work"),
            }
            if classical_principle
            else None
        ),
    }
    return (
        "/no_think\n只依据证据JSON回答。先阅读多分支变化裁决，再下结论；"
        "面向用户把实战手称为S、AI首选称为J，不要用内部坐标代替S/J；"
        "只讲目标着法，不可串用另一手；"
        "不新增胜率、目差、候选、死活、坐标。启发式须用审慎措辞。"
        "只有证据JSON提供古训时才可引用，并说明仅作检查角度；否则严禁杜撰或引用古训。"
        "回答要先给明确结论，再解释为什么；禁止只说‘需要比较’或‘进入变化验证’。"
        "必须用自然的棋手语言，不得输出JSON数组、方括号或字段名；"
        "气数要写成‘由2气增至3气’这类可读句子，不能声称0气优于2气。"
        "根据问题意图自然组织，不得机械套固定模板：问坐标就直接回答；问一手作用可用两三段；"
        + (
            "这是连续追问，只补充回答用户本轮新问的‘为什么’，不得重复上一轮完整讲解；"
            if history
            else ""
        )
        + (
            "本轮必须聚焦J点三三取得实空与S构成三连星发展模样、外势的取舍；"
            "说明模样兑现较缓、仍可能被侵消，外势没有攻击对象时可能落空。"
            "这些属于棋理启发，须用‘可以理解为、可能’等审慎措辞；不要再泛讲角边中央。"
            if focused_comparison
            else ""
        )
        +
        "只有比较布局两手优先级时，才需要覆盖明确结论、开局价值、全局对抗、"
        "发展潜力以及时机与例外。小标题可按内容自由命名，用‘标题｜正文’和换行增强可读性。"
        "若证据把局面标为‘局部对杀’，回答必须围绕气、连接、切断、先手和局部存亡，"
        "不得转去讨论中腹取势、边上发展潜力、角部大场或宽框架；"
        "坐标区域只说明落点位置，不能替代局面性质。若用户问为什么不好或错误在哪里，"
        "必须明确指出实战与AI首选在局部次序上的差异，不能只复述‘需要确认’。"
        "若‘同一急点被让给对手’为真，必须把它作为核心结论：实战前己方首选该点，"
        "实战脱离后对手首选仍是同一点，因此问题是把双方共同急点的先行权让给对手；"
        "必须明确区分实战S与首选J，再用两手各自的规则变化解释，"
        "不得向用户显示内部坐标，不得把规则信号夸大成必杀。"
        "当多分支变化裁决为已复核时，至少引用一项分支中特有的规则事件或应对次序；"
        "不能再用‘需要进入变化验证’代替现有证据。访问量分布不等于强制应手，"
        "即使某手打吃，也不能写‘迫使、逼迫、必应、只能应’，除非证据明确证明强制；"
        "厚薄、轻重与先手价值若未被直接证明，只能写成‘可能、有利于、可以理解为’等启发式判断；"
        "没有规则确认劫点时不得声称形成劫争，没有提子事件时不得声称已经吃掉棋子。"
        "如果证据含‘局部棋形语义’，必须优先解释具体攻击对象和棋块身份："
        "说明S打吃的对象、黑方先占J时哪块棋被压到一气、以及S后对手抢J如何把同一棋块接长扩气。"
        "这才是共同急点的围棋含义。禁止把‘出现若干次打吃、自紧气或劫点’当成主体讲解，"
        "长PV远处发生的事件不能冒充当前急所的原因；不得只把规则日志改写成中文。"
        "必须说明角、边、中腹的优先级只是布局启发式；若角部已有对方棋子，"
        "要说成角部接近或争夺，不得说成抢占空角。不得臆造对方必然应手。"
        "直接问题控制在三百五十字内，复杂比较最多五百字。只回JSON："
        '{"answer":"...","followUps":[]}'
        f"\n证据：{json.dumps(facts, ensure_ascii=False, separators=(',', ':'))}"
        f"\n用户问题：{_question_for_prompt(question, candidates)}"
    )


def _candidate_geometry(candidate: dict | None) -> dict:
    if not isinstance(candidate, dict):
        return {}
    value = candidate.get("geometry")
    return value if isinstance(value, dict) else {}


def _candidate_opening(candidate: dict | None) -> dict:
    if not isinstance(candidate, dict):
        return {}
    heuristics = candidate.get("heuristics")
    if not isinstance(heuristics, dict):
        return {}
    value = heuristics.get("openingStrategy")
    return value if isinstance(value, dict) else {}


def _candidate_local_situation(candidate: dict | None) -> dict:
    if not isinstance(candidate, dict):
        return {}
    heuristics = candidate.get("heuristics")
    if not isinstance(heuristics, dict):
        return {}
    value = heuristics.get("localSituation")
    return value if isinstance(value, dict) else {}


def _display_move(kind: str, fallback: str = "") -> str:
    if kind == "actual":
        return "S"
    if kind == "best":
        return "J"
    return fallback


def _opening_comparison_fallback(
    position: dict,
    evidence: dict,
    candidates: dict,
) -> str | None:
    actual = candidates.get("actual")
    best = candidates.get("best")
    if not isinstance(actual, dict) or not isinstance(best, dict):
        return None
    actual_geometry = _candidate_geometry(actual)
    best_geometry = _candidate_geometry(best)
    actual_opening = _candidate_opening(actual)
    best_opening = _candidate_opening(best)
    if not actual_geometry or not best_geometry:
        return None
    if position.get("phase") != "布局":
        return None
    if any(
        _candidate_local_situation(candidate).get("scope") == "local_fight"
        for candidate in (actual, best)
    ):
        return None
    if not (actual_opening and best_opening):
        return None
    actual_move = _display_move("actual", "实战手")
    best_move = _display_move("best", "AI 首选")
    actual_sector = actual_geometry.get("sectorLabel") or _candidate_region(actual) or "实战区域"
    best_sector = best_geometry.get("sectorLabel") or _candidate_region(best) or "推荐区域"
    best_development = best_opening.get("development") or "优先处理更紧迫的全局方向"
    actual_development = actual_opening.get("development") or "扩张当前方向"
    priority = best_opening.get("priorityPrinciple") or actual_opening.get("priorityPrinciple")
    corner_context = best_opening.get("cornerContext")
    corner_description = (
        corner_context.get("description")
        if isinstance(corner_context, dict)
        else "角部现状需要结合盘面核对"
    )
    framework = actual_opening.get("framework")
    framework_description = (
        framework.get("description")
        if isinstance(framework, dict)
        else "实战手主要发展当前边上方向"
    )
    player = str(best.get("player") or actual.get("player") or "")
    player_label = "黑方" if player == "B" else ("白方" if player == "W" else "己方")
    return "\n".join((
        (
            f"先说结论｜KataGo 首选 {best_move}。它落在{best_sector}，{best_development}；"
            f"实战 {actual_move} 落在{actual_sector}，{actual_development}。"
            "两手都在发展，但当前角部争夺的优先级更高。"
        ),
        (
            "为什么先碰角｜常用口诀“金角银边草肚皮”只是方向性启发：角依靠两条边线，"
            "通常比单纯边上扩张更容易形成根据和后续。"
            + (f"本局需要注意：{corner_description}。" if corner_description else "")
        ),
        (
            f"全局会怎样｜{best_move}把行动落在对方已有角部附近，主动要求双方处理角上的次序；"
            f"{actual_move}则{framework_description}。"
            "前者先触及对方角部，后者先扩大自己的边上框架，方向不同。"
        ),
        (
            f"两手的潜力｜{best_move}属于主动争夺角部的着法，重点是后续先手和向两边发展的余地；"
            f"{actual_move}让{player_label}的边上子力更连贯，但宽框架仍不是确定地盘，"
            "还要接受对方侵消或分投的检验。"
        ),
        (
            f"什么时候再走边｜这不是说 {actual_move} 是坏棋，而是当前 KataGo 把 {best_move} 排在前面。"
            "先处理更紧迫的角部，再寻找边上扩张时机，通常更不容易把全局主动权让给对手；"
            "具体收益仍应在推荐变化中逐手核对。"
        ),
    ))


def _opening_territory_influence_fallback(
    question: str,
    position: dict,
    candidates: dict,
) -> str | None:
    """回答三三与三连星的专项追问，避免把上一轮五段模板再说一遍。"""
    if _question_focus(question, position) != "territory_vs_influence":
        return None
    actual = candidates.get("actual")
    best = candidates.get("best")
    if not isinstance(actual, dict) or not isinstance(best, dict):
        return None
    asks_why_corner_is_prior = any(
        marker in str(question or "")
        for marker in ("角的优先级", "为什么角", "角为什么")
    )
    if asks_why_corner_is_prior:
        return (
            "角在这里更优先，不是因为‘任何局面都必须先走角’，而是因为收益更快、更确定。"
            "J 是点三三：棋子落下就进入角内，借两条棋盘边线，成空路径较短，"
            "可以更快把价值兑现为实空。\n"
            "S 的价值则要通过三连星的大模样和外势在以后兑现：模样仍可被侵消，"
            "外势还需要配合攻击目标才容易发挥。可以理解为，同样一手棋，J先取得当前可确认的角地，"
            "S只是先搭出未来可能变大的框架。因此KataGo此时先选J；"
            "这不是否定三连星，而是把兑现较慢、可能落空的收益排在后面。"
        )
    return (
        "这里的关键不是抽象地说‘角总比边大’，而是比较实空与模样的兑现速度。"
        "J 是点三三：它直接进入角内，借两条边线更快取得实空；"
        "S 则与下边两翼棋子构成三连星，重点是发展大模样和外势。\n"
        "KataGo 此时把 J 排在前面，可以理解为：三连星的收益偏缓，模样还可能被侵消；"
        "外势如果没有明确的攻击对象，也可能难以兑现甚至落空。"
        "所以 AI 更愿意先拿眼前可兑现的角地，再看下边的发展。"
        "这不等于 S 是坏棋，只是当前次序靠后；具体得失仍以推荐变化为准。"
    )


def _liberty_change(candidate: dict, side: str) -> str | None:
    rules = candidate.get("rules") if isinstance(candidate.get("rules"), dict) else {}
    liberties = rules.get("libertiesBeforeAfter")
    liberties = liberties if isinstance(liberties, dict) else {}
    values = liberties.get(side)
    if (
        isinstance(values, list)
        and len(values) >= 2
        and all(isinstance(value, int) for value in values[:2])
    ):
        before, after = values[:2]
        if before == 0:
            return f"落子后新棋有 {after} 气"
        direction = "增至" if after > before else "减至" if after < before else "仍为"
        return f"由 {before} 气{direction} {after} 气"
    return None


def _variation_fallback_review(evidence: dict) -> str | None:
    value = evidence.get("variationEvidence")
    if not isinstance(value, dict) or value.get("status") != "ready":
        return None
    semantics = (
        value.get("tacticalSemantics")
        if isinstance(value.get("tacticalSemantics"), dict)
        else {}
    )
    semantic_comparison = (
        semantics.get("comparison")
        if isinstance(semantics.get("comparison"), dict)
        else {}
    )
    if semantics.get("status") == "ready" and semantic_comparison.get("mutualVitalPoint"):
        actual_shape = semantics.get("actualSImmediate") or {}
        best_shape = semantics.get("bestJImmediate") or {}
        reply_shape = semantics.get("opponentJAfterS") or {}
        priority = semantics.get("replyPriority") or {}
        actual_target = int(actual_shape.get("atariTargetStones") or 0)
        best_target = int(best_shape.get("atariTargetStones") or 0)
        reply_stones_before = int(reply_shape.get("groupStonesBefore") or best_target)
        reply_liberties_before = int(reply_shape.get("groupLibertiesBefore") or 0)
        reply_stones = int(reply_shape.get("groupStonesAfter") or 0)
        reply_liberties = int(reply_shape.get("groupLibertiesAfter") or 0)
        actual_target_label = "另一颗单子" if actual_target == 1 else f"另一块 {actual_target} 子棋"
        best_target_label = "两子棋" if best_target == 2 else f"{best_target} 子棋"
        boundary = (
            "边界｜J 后所查的主要应对都落在别处，说明对手可以选择脱先；"
            "这不是 J 的强制应手，也不能据此断言这块棋已经死亡。"
            if priority.get("bestBranchTopRepliesAllElsewhere") else ""
        )
        return "\n".join(filter(None, (
            "结论｜S 不是没碰到棋，而是打吃了次要对象，漏掉了双方共同急点 J。"
            "局部对杀中，错过这个次序，就把主要弱棋的攻守主动权交给了对手。",
            f"棋形差别｜S 只把{actual_target_label}压到一气；"
            f"J 则会把对方那块{best_target_label}压到一气。"
            "两手都在打吃，但攻击对象的分量不同。",
            f"为什么 J 更急｜实战先走 S 后，对手的 KataGo 首选不是救那颗单子，"
            f"而是抢 J，把原来的同一块 {reply_stones_before} 子棋接成长为 {reply_stones} 子，"
            f"气从 {reply_liberties_before} 气扩到 {reply_liberties} 气。"
            "因此 J 是攻守转换点：当前一方先占是在攻击，对手先占则是在接长、扩气和安定弱棋。",
            boundary,
        )))
    branches = value.get("branches") if isinstance(value.get("branches"), dict) else {}
    actual = branches.get("actual") if isinstance(branches.get("actual"), dict) else {}
    best = branches.get("best") if isinstance(branches.get("best"), dict) else {}
    comparison = value.get("comparison") if isinstance(value.get("comparison"), dict) else {}

    def summary(branch: dict) -> dict:
        replies = branch.get("replies") if isinstance(branch.get("replies"), list) else []
        first = replies[0] if replies and isinstance(replies[0], dict) else {}
        replay = first.get("ruleReplay") if isinstance(first.get("ruleReplay"), dict) else {}
        rule_summary = replay.get("summary") if isinstance(replay.get("summary"), dict) else {}
        return {
            "reply": first.get("reply"),
            "captures": int(rule_summary.get("capturedStones") or 0),
            "ataris": int(rule_summary.get("atariEvents") or 0),
            "kos": int(rule_summary.get("koEvents") or 0),
        }

    actual_summary = summary(actual)
    best_summary = summary(best)
    parts = []
    if comparison.get("bestBecameTopReplyAfterActual"):
        parts.append("S 后对方的首要应对就是抢 J")
    elif actual_summary["reply"]:
        parts.append("S 后对方有明确的首要应对分支")
    if best_summary["reply"]:
        parts.append("J 后也已复核对方的主要抵抗")
    captures = actual_summary["captures"] + best_summary["captures"]
    ataris = actual_summary["ataris"] + best_summary["ataris"]
    kos = actual_summary["kos"] + best_summary["kos"]
    if captures:
        parts.append(f"两条首要变化的规则重放共出现 {captures} 枚提子")
    if ataris:
        parts.append(f"共出现 {ataris} 次把相邻棋块压到一气的事件")
    if kos:
        parts.append(f"规则引擎确认了 {kos} 次简单劫点")
    if not (captures or ataris or kos):
        parts.append("首要变化没有出现可直接断言的提子、打吃或劫点")
    return "；".join(parts) + "。因此只能依据已重放的次序和规则事件解释，不能夸大成必杀。"


def _tactical_fallback(
    position: dict,
    evidence: dict,
    purpose: dict,
    candidates: dict,
    target: dict,
) -> str | None:
    actual = candidates.get("actual")
    best = candidates.get("best")
    actual = actual if isinstance(actual, dict) else {}
    best = best if isinstance(best, dict) else {}
    selected = (
        [best]
        if target.get("kind") == "best"
        else [actual]
        if target.get("kind") == "actual"
        else [actual, best]
    )
    if not any(
        _candidate_local_situation(item).get("scope") == "local_fight"
        for item in selected
    ):
        return None

    actual_move = _display_move("actual", "实战手")
    best_move = _display_move("best", "AI 首选")
    candidate = best if target.get("kind") == "best" else actual
    local = _candidate_local_situation(candidate)
    own_nearby = local.get("ownNearby")
    enemy_nearby = local.get("enemyNearby")
    own_change = _liberty_change(candidate, "own")
    opponent_change = _liberty_change(candidate, "opponent")
    local_signals = []
    if isinstance(own_nearby, int) and isinstance(enemy_nearby, int):
        local_signals.append(f"落点三格范围内有己方 {own_nearby} 子、对方 {enemy_nearby} 子")
    if own_change:
        local_signals.append(f"相邻己方棋块气数 {own_change}")
    if opponent_change:
        local_signals.append(f"相邻对方棋块气数 {opponent_change}")
    signals = "；".join(local_signals) or "双方棋子在落点附近密集接触"
    evidence_summary = str(
        purpose.get("evidenceSummary")
        or f"具体损失以当前{_analysis_phrase(evidence, '证据')}为准。"
    )
    relation = (
        evidence.get("decisionRelation")
        if isinstance(evidence.get("decisionRelation"), dict)
        else {}
    )
    shared_urgent_point = bool(
        relation.get("missedBestBecameOpponentBestReply")
    )
    actual_own_change = _liberty_change(actual, "own")
    actual_opponent_change = _liberty_change(actual, "opponent")
    best_own_change = _liberty_change(best, "own")
    best_opponent_change = _liberty_change(best, "opponent")

    def labeled_change(change: str | None, label: str) -> str | None:
        if not change:
            return None
        if change.startswith("落子后新棋"):
            return change
        return f"{label}{change}"

    actual_effects = "、".join(
        value
        for value in (
            labeled_change(actual_own_change, "己方相邻棋块"),
            labeled_change(actual_opponent_change, "对方相邻棋块"),
        )
        if value
    )
    best_effects = "、".join(
        value
        for value in (
            labeled_change(best_own_change, "己方相邻棋块"),
            labeled_change(best_opponent_change, "对方相邻棋块"),
        )
        if value
    )
    variation_review = _variation_fallback_review(evidence)

    variation_value = evidence.get("variationEvidence")
    tactical_semantics = (
        variation_value.get("tacticalSemantics")
        if isinstance(variation_value, dict)
        and isinstance(variation_value.get("tacticalSemantics"), dict)
        else {}
    )
    semantic_comparison = (
        tactical_semantics.get("comparison")
        if isinstance(tactical_semantics.get("comparison"), dict)
        else {}
    )
    if (
        variation_review
        and tactical_semantics.get("status") == "ready"
        and semantic_comparison.get("mutualVitalPoint")
    ):
        return variation_review

    if shared_urgent_point and target.get("kind") == "best":
        conclusion = (
            f"先说关键｜{best_move} 是双方共同急点：落子前它是当前一方的 KataGo 首选；"
            f"实战改走 {actual_move} 后，轮到对手时，KataGo 首选仍是 {best_move}。"
            "它的核心价值是抢在对手之前占住局部战斗的先行权。"
        )
        difference = (
            f"为什么比实战急｜{actual_move} 并非完全没作用"
            + (f"——规则重放显示：{actual_effects}" if actual_effects else "")
            + "；但它没有处理双方都想抢的同一要点。"
            + (
                f"{best_move} 的规则重放显示：{best_effects}。"
                if best_effects else ""
            )
        )
    elif shared_urgent_point and target.get("kind") == "comparison":
        conclusion = (
            f"核心差异｜{best_move} 是双方共同急点，{actual_move} 是旁处作战。"
            f"实战前 KataGo 要当前一方先下 {best_move}；改走 {actual_move} 后，"
            f"对手下一手的 KataGo 首选仍是 {best_move}。实战等于把同一急点的先行权让给对手。"
        )
        difference = (
            f"两手各自做了什么｜{actual_move}"
            + (f"使{actual_effects}" if actual_effects else "确实参与了局部接触")
            + "，所以不能简单说它毫无作用；"
            + (
                f"{best_move} 则使{best_effects}，"
                if best_effects else f"{best_move} 则直接占住推荐变化的起点，"
            )
            + "真正的优先级差异在于谁先拿到共同急点。"
        )
    elif shared_urgent_point:
        conclusion = (
            f"先说结论｜{actual_move} 的问题不是没碰到棋，而是漏掉了 {best_move} 这个双方共同急点。"
            f"落子前 KataGo 首选 {best_move}；走完 {actual_move} 轮到对手，"
            f"KataGo 首选仍是 {best_move}。这说明实战把同一个必须先处理的点让给了对手。"
        )
        difference = (
            f"实战的局部作用｜{actual_move}"
            + (f"使{actual_effects}" if actual_effects else "确实在参与局部战斗")
            + "，所以它不是“完全没用”；但局部对杀比较的是次序。"
            + (
                f"{best_move} 的规则重放显示：{best_effects}，"
                if best_effects else ""
            )
            + (
                "多分支规则重放已在下方列出，只陈述其中确认的紧气、提子与劫点事件。"
                if variation_review
                else "应先沿推荐变化确认它具体是在紧气、切断还是封锁。"
            )
        )
    elif target.get("kind") == "best":
        conclusion = (
            f"先看对杀｜{best_move} 的价值在局部战斗次序，不是下边的发展潜力。"
            f"{signals}，所以这里首先要算气、连接和先手。"
        )
        difference = (
            f"推荐点的任务｜KataGo 在 {actual_move} 之前首选 {best_move}；"
            "推荐变化也从这个局部要点开始。它要求先处理贴身战斗，再谈全局。"
        )
    elif target.get("kind") == "comparison":
        conclusion = (
            f"先看对杀｜{actual_move} 与 {best_move} 都处在同一片局部战斗中，"
            "比较标准应是紧气次序、连接与先手，而不是角边中腹的抽象价值。"
        )
        difference = (
            f"关键差异｜KataGo 把 {best_move} 排在 {actual_move} 前面，"
            "说明推荐点对应的局部次序更急；必须沿推荐变化逐手核对哪一方先补气、先断或先脱身。"
        )
    else:
        conclusion = (
            f"先说结论｜{actual_move} 的问题是局部对杀次序，不是中腹发展。"
            f"{signals}，这手确实在参与战斗，但“碰到对方棋”不等于次序正确。"
        )
        difference = (
            f"漏掉的急所｜落子前 KataGo 首选 {best_move}，推荐变化从 {best_move} 开始。"
            f"{evidence_summary}这说明应先核对 {best_move} 所在局部的紧气、封锁和先手价值，"
            f"而不是把 {actual_move} 解释成取势。"
        )
    return "\n".join((
        conclusion,
        difference,
        (
            f"变化复核｜{variation_review}"
            if variation_review
            else (
                "复盘方法｜先播放推荐变化，只盯三件事：双方各剩几气、哪一手是先手、"
                "哪一块棋能先连回或逃出。静态规则证据不足以断言已经杀死或必然逃出，"
                "具体结果必须由变化图确认。"
            )
        ),
    ))


def _validate_answer_scope(
    answer: str,
    question: str,
    target: dict,
    position: dict,
) -> dict:
    candidates = _move_candidates(position)
    selected = (
        [candidates.get("best")]
        if target.get("kind") == "best"
        else [candidates.get("actual")]
        if target.get("kind") == "actual"
        else [candidates.get("actual"), candidates.get("best")]
    )
    tactical = any(
        _candidate_local_situation(candidate).get("scope") == "local_fight"
        for candidate in selected
        if isinstance(candidate, dict)
    )
    if not tactical:
        return {"status": "not_required"}
    off_scope = []
    for phrase in (
            "中腹取势",
            "发展潜力",
            "边上框架",
            "宽框架",
            "全局大场",
            "金角银边",
            "角部争夺",
    ):
        if phrase not in answer:
            continue
        negated = re.search(
            rf"(?:不(?:应|要|该|得)?|无需|无关|而非|不是|避免)"
            rf"[^。；\n]{{0,10}}{re.escape(phrase)}",
            answer,
        )
        if not negated:
            off_scope.append(phrase)
    tactical_terms = sum(
        term in answer
        for term in ("气", "对杀", "攻防", "连接", "切断", "先手", "局部", "紧气")
    )
    asks_for_mistake = any(
        phrase in question for phrase in ("不好", "严重", "错误", "问题", "亏")
    )
    diagnosis_terms = sum(
        term in answer
        for term in ("次序", "急所", "漏", "不如", "首选", "损失", "慢", "错", "问题在")
    )
    concrete_diagnosis = (
        any(term in answer for term in ("次序", "急所", "紧气", "漏"))
        and any(term in answer for term in ("KataGo", "AI首选", "AI 首选", "首选"))
    )
    relation = (
        position.get("decisionRelation")
        if isinstance(position.get("decisionRelation"), dict)
        else {}
    )
    shared_urgent_point = bool(
        relation.get("missedBestBecameOpponentBestReply")
    )
    explains_shared_point = any(
        term in answer
        for term in (
            "共同急点",
            "同一急点",
            "同一点",
            "仍是",
            "仍然是",
            "让给对手",
            "让给了对手",
            "先行权",
        )
    )
    candidate = next(
        (
            item
            for item in selected
            if isinstance(item, dict)
            and _candidate_local_situation(item).get("scope") == "local_fight"
        ),
        {},
    )
    local = _candidate_local_situation(candidate)
    own_nearby = local.get("ownNearby")
    enemy_nearby = local.get("enemyNearby")
    count_conflict = bool(
        isinstance(own_nearby, int)
        and isinstance(enemy_nearby, int)
        and (
            (
                own_nearby >= enemy_nearby
                and any(term in answer for term in ("己方较少", "己方少于", "对方更多"))
            )
            or (
                own_nearby <= enemy_nearby
                and any(term in answer for term in ("对方较少", "对方少于", "己方更多"))
            )
        )
    )
    missing_relation_moves = bool(
        shared_urgent_point
        and (
            not re.search(r"(?<![A-Za-z])S(?![A-Za-z])", answer)
            or not re.search(r"(?<![A-Za-z])J(?![A-Za-z])", answer)
        )
    )
    if (
        off_scope
        or tactical_terms < 3
        or count_conflict
        or (asks_for_mistake and (diagnosis_terms < 1 or not concrete_diagnosis))
        or (shared_urgent_point and not explains_shared_point)
        or missing_relation_moves
    ):
        raise MentorProviderError(
            "回答偏离局部对杀证据"
            + (f"：包含{','.join(off_scope)}" if off_scope else "")
            + ("：附近棋子数量关系说反" if count_conflict else "")
            + ("：未明确区分实战S与首选J" if missing_relation_moves else "")
        )
    return {
        "status": "passed",
        "scope": "local_fight",
        "tacticalTerms": tactical_terms,
        "diagnosisTerms": diagnosis_terms,
        "concreteDiagnosis": concrete_diagnosis,
    }


def _validate_answer_readability(
    answer: str,
    question: str,
    target: dict,
    position: dict | None = None,
) -> dict:
    """拒绝把内部证据结构、伪古训或明显误读直接展示给用户。"""
    if re.search(r"\[\s*\d+\s*,\s*\d+\s*\]", answer):
        raise MentorProviderError("回答直接暴露了内部气数数组")
    if any(phrase in answer for phrase in ("0优于", "0 优于", "更无余味")):
        raise MentorProviderError("回答误读了规则气数信号")
    if isinstance(position, dict):
        candidates = _move_candidates(position)
        internal_moves = [
            str(candidate.get("move") or "")
            for candidate in (candidates.get("actual"), candidates.get("best"))
            if isinstance(candidate, dict) and candidate.get("move")
        ]
        if any(
            re.search(
                rf"(?<![A-Za-z0-9]){re.escape(move)}(?![A-Za-z0-9])",
                answer,
                flags=re.IGNORECASE,
            )
            for move in internal_moves
        ):
            raise MentorProviderError("回答暴露内部坐标，应使用实战S与首选J")
    asks_for_classical = any(
        word in question
        for word in ("古典", "古训", "棋理", "口诀", "棋经", "古棋")
    )
    classical_allowed_by_context = False
    if isinstance(position, dict):
        candidates = _move_candidates(position)
        selected = (
            [candidates.get("best")]
            if target.get("kind") == "best"
            else [candidates.get("actual")]
            if target.get("kind") == "actual"
            else [candidates.get("actual"), candidates.get("best")]
        )
        classical_allowed_by_context = not any(
            _candidate_local_situation(candidate).get("scope") == "local_fight"
            for candidate in selected
            if isinstance(candidate, dict)
        )
    if not (asks_for_classical or classical_allowed_by_context) and any(
        marker in answer for marker in ("古训", "棋经十三篇", "敦煌棋经", "《棋经")
    ):
        raise MentorProviderError("回答擅自加入了与问题无关的古训")
    max_length = 700 if target.get("kind") == "comparison" else 650
    if len(answer) > max_length:
        raise MentorProviderError("回答过长，核心判断不够聚焦")
    return {
        "status": "passed",
        "length": len(answer),
        "maxLength": max_length,
    }


def _validate_variation_grounding(answer: str, evidence: dict) -> dict:
    value = evidence.get("variationEvidence")
    if not isinstance(value, dict) or value.get("status") != "ready":
        return {"status": "not_available"}
    branches = value.get("branches") if isinstance(value.get("branches"), dict) else {}
    summaries = []
    for branch in branches.values():
        if not isinstance(branch, dict):
            continue
        for reply in branch.get("replies") or []:
            replay = reply.get("ruleReplay") if isinstance(reply, dict) else {}
            summary = replay.get("summary") if isinstance(replay, dict) else {}
            if isinstance(summary, dict):
                summaries.append(summary)
    supports_capture = any(int(item.get("capturedStones") or 0) > 0 for item in summaries)
    supports_ko = any(int(item.get("koEvents") or 0) > 0 for item in summaries)
    if re.search(r"(?:形成|进入|出现|是|打)劫(?:争|点)?", answer) and not supports_ko:
        raise MentorProviderError("回答声称出现劫争，但规则重放没有确认劫点")
    if re.search(r"(?:已经|直接|当场)(?:吃掉|提掉|提子)", answer) and not supports_capture:
        raise MentorProviderError("回答声称已经提子，但规则重放没有提子事件")
    if any(
        phrase in answer
        for phrase in ("需要进入变化验证", "具体效果需要变化验证", "仍须沿变化核对")
    ):
        raise MentorProviderError("回答忽略了已经生成的多分支变化裁决")
    claim_boundary = (
        value.get("claimBoundary")
        if isinstance(value.get("claimBoundary"), dict)
        else {}
    )
    not_proven = set(claim_boundary.get("notDirectlyProven") or [])
    def has_positive_claim(pattern: str) -> bool:
        """Reject unsupported assertions without penalising an explicit disclaimer."""
        for sentence in re.split(r"[。！？；\n]", answer):
            if not re.search(pattern, sentence):
                continue
            if re.search(
                r"(?:不能|不可|不得|并非|不是|不等于|不代表|尚未|未能|"
                r"没有(?:证据)?|无法|不能据此|并不能)",
                sentence,
            ):
                continue
            return True
        return False

    forced_reply_pattern = (
        r"(?:迫使|逼迫|强制)(?:对方)?(?:应|回应|应对)|"
        r"(?:对方)?(?:不得不|只能|必应|必须应)"
    )
    if "forced_reply" in not_proven and has_positive_claim(forced_reply_pattern):
        raise MentorProviderError("回答把搜索中的主要应对夸大成了强制应手")
    life_and_death_pattern = (
        r"(?:直接|已经|彻底|必然|决定|确定)[^。；\n]{0,12}"
        r"(?:生死|杀死|做活|活棋|化解危机)|"
        r"(?:生死|杀死|做活|活棋)[^。；\n]{0,12}(?:已定|决定|确定)"
    )
    if "life_and_death" in not_proven and has_positive_claim(life_and_death_pattern):
        raise MentorProviderError("回答把尚未证明的死活结果写成了确定事实")
    if "thickness" in not_proven:
        for sentence in re.split(r"[。！？；\n]", answer):
            if not any(term in sentence for term in ("厚势", "厚薄", "变厚")):
                continue
            if not any(
                hedge in sentence
                for hedge in (
                    "可能", "可以理解为", "倾向", "有机会", "有利于",
                    "可望", "从变化看", "启发式", "尚不能证明",
                )
            ):
                raise MentorProviderError("回答把厚薄启发式写成了已证实的变化结论")
    grounded_terms = [
        term for term in (
            "变化", "应对", "次序", "气", "连接", "切断", "打吃", "提子", "劫点"
        )
        if term in answer
    ]
    if not grounded_terms:
        raise MentorProviderError("回答没有使用多分支变化中的任何规则或次序证据")
    return {
        "status": "passed",
        "supportsCapture": supports_capture,
        "supportsKo": supports_ko,
        "groundedTerms": grounded_terms,
        "adjudicationId": evidence.get("adjudicationId"),
    }


def _validate_tactical_semantic_grounding(
    answer: str, question: str, target: dict, evidence: dict
) -> dict:
    value = evidence.get("variationEvidence")
    semantics = (
        value.get("tacticalSemantics")
        if isinstance(value, dict) and isinstance(value.get("tacticalSemantics"), dict)
        else {}
    )
    comparison = (
        semantics.get("comparison")
        if isinstance(semantics.get("comparison"), dict)
        else {}
    )
    actual_shape = semantics.get("actualSImmediate") or {}
    best_shape = semantics.get("bestJImmediate") or {}
    asks_for_reason = any(
        marker in question
        for marker in ("为什么", "不好", "差", "次序", "急点", "急所", "S", "J")
    )
    if not (
        semantics.get("status") == "ready"
        and comparison.get("mutualVitalPoint")
        and asks_for_reason
        and target.get("kind") in ("actual", "best", "comparison")
    ):
        return {"status": "not_required"}

    j_attack = bool(re.search(
        r"(?:J[^。；\n]{0,55}(?:打吃|紧气|压到一气|攻击)|"
        r"(?:打吃|紧气|压到一气|攻击)[^。；\n]{0,25}J)",
        answer,
    ))
    opponent_j_strengthens = bool(re.search(
        r"(?:(?:对手|对方|白方)[^。；\n]{0,30}J[^。；\n]{0,55}"
        r"(?:接长|连接|扩气|补强|安定|救)|"
        r"J[^。；\n]{0,45}(?:接长|连接|扩气|补强|安定|救)[^。；\n]{0,20}"
        r"(?:同一|原来|这块))",
        answer,
    ))
    group_identity = any(
        marker in answer
        for marker in ("同一块棋", "同一棋块", "攻击对象", "两子棋", "2子棋", "两颗子")
    )
    actual_target_stones = int(actual_shape.get("atariTargetStones") or 0)
    best_target_stones = int(best_shape.get("atariTargetStones") or 0)
    object_contrast = True
    if actual_target_stones == 1 and best_target_stones == 2:
        object_contrast = (
            any(marker in answer for marker in ("单子", "一子", "1子", "一颗"))
            and any(marker in answer for marker in ("两子", "二子", "2子", "两颗"))
        )
    if not (
        j_attack and opponent_j_strengthens and group_identity and object_contrast
    ):
        raise MentorProviderError(
            "回答没有讲清 S/J 攻击对象的差别，以及 J 对同一棋块的攻守角色反转"
        )
    return {
        "status": "passed",
        "mutualVitalPoint": True,
        "checks": ["j_attacks_group", "opponent_j_strengthens_same_group"],
    }


def _validate_chat_answer(
    answer: str,
    question: str,
    question_target: dict,
    position: dict,
    evidence: dict,
    history: list[dict] | None = None,
) -> dict:
    """集中执行回答契约，供首答与一次纠错重试共用。"""
    validation = _validate_answer_binding(answer, question_target, position)
    validation["situationScope"] = _validate_answer_scope(
        answer, question, question_target, position
    )
    validation["readability"] = _validate_answer_readability(
        answer, question, question_target, position
    )
    validation["teachingDepth"] = _validate_answer_depth(
        answer, question, question_target, position
    )
    validation["followUpNovelty"] = _validate_followup_novelty(
        answer, question, position, history or []
    )
    validation["variationGrounding"] = _validate_variation_grounding(
        answer, evidence
    )
    validation["tacticalSemantics"] = _validate_tactical_semantic_grounding(
        answer, question, question_target, evidence
    )
    return validation


def _validate_followup_novelty(
    answer: str,
    question: str,
    position: dict,
    history: list[dict],
) -> dict:
    if not history or _question_focus(question, position) == "general":
        return {"status": "not_required"}
    previous = next((
        str(item.get("content") or "").strip()
        for item in reversed(history)
        if item.get("role") == "assistant" and str(item.get("content") or "").strip()
    ), "")
    if not previous:
        return {"status": "not_required"}
    compact_answer = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", answer)
    compact_previous = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", previous)
    similarity = difflib.SequenceMatcher(
        None, compact_answer, compact_previous
    ).ratio()
    if similarity >= .88:
        raise MentorProviderError("追问回答重复上一轮，没有回应本轮新增问题")
    return {"status": "passed", "similarity": round(similarity, 3)}


def _validate_answer_depth(
    answer: str, question: str, target: dict, position: dict
) -> dict:
    candidates = _move_candidates(position)
    if target.get("kind") not in ("actual", "best", "comparison"):
        return {"status": "not_required"}
    scaffold = _opening_comparison_fallback(position, {}, candidates)
    if not scaffold:
        return {"status": "not_required"}
    if _question_focus(question, position) == "territory_vs_influence":
        checks = {
            "territory": bool(re.search(r"三三|角地|实空", answer)),
            "influence": bool(re.search(r"三连星|模样|外势", answer)),
            "realizationRisk": bool(re.search(r"偏缓|侵消|消解|落空|兑现|攻击对象", answer)),
        }
        if len(answer) < 80 or not all(checks.values()):
            raise MentorProviderError(
                "回答没有讲清三三取实空、三连星取模样外势及其兑现风险"
            )
        return {"status": "passed", "focus": "territory_vs_influence", **checks}
    concepts = sum(
        bool(re.search(pattern, answer))
        for pattern in ("角", "边", "布局|开局", "发展|框架", "先手|主动", "时机|优先")
    )
    sections = len(re.findall(r"(?:^|\n)[^\n｜]{2,10}｜", answer))
    if len(answer) < 150 or concepts < 4 or sections < 2:
        raise MentorProviderError("回答缺少布局优先级、全局对抗与子力发展的完整解释")
    return {
        "status": "passed",
        "concepts": concepts,
        "sections": sections,
    }


def _chat_actions(question: str, evidence: dict) -> list[dict]:
    actions: list[dict] = []
    if evidence.get("bestMove") and any(
        word in question for word in ("变化", "演示", "首选", "推荐", "后续")
    ):
        actions.append({"id": "show_variation", "label": "在棋盘演示推荐变化"})
    if any(word in question for word in ("棋群", "影响", "关联", "弱棋", "哪里")):
        actions.append({"id": "show_highlight", "label": "查看受影响棋群"})
    return actions[:2]


def _chat_fallback(
    question: str,
    evidence: dict,
    purpose: dict,
    position: dict | None = None,
    question_target: dict | None = None,
) -> str:
    position = position or {}
    target = question_target or _question_target(question, position, evidence)
    candidates = _move_candidates(position)
    role = str(purpose.get("role") or "改善当前局部并兼顾全局方向")
    next_focus = str(
        purpose.get("nextFocus")
        or "先检查双方弱棋，再比较实战与推荐图的先后手和地盘转换。"
    )
    evidence_summary = str(
        purpose.get("evidenceSummary")
        or f"具体得失以上方{_analysis_phrase(evidence, '证据')}为准。"
    )
    best = evidence.get("bestMove")
    if target.get("kind") in ("actual", "best", "comparison"):
        tactical_answer = _tactical_fallback(
            position, evidence, purpose, candidates, target
        )
        if tactical_answer:
            return tactical_answer
        focused_opening_answer = _opening_territory_influence_fallback(
            question, position, candidates
        )
        if focused_opening_answer:
            return focused_opening_answer
        opening_answer = _opening_comparison_fallback(
            position, evidence, candidates
        )
        if opening_answer:
            return opening_answer
    if target.get("kind") == "comparison":
        actual_candidate = candidates.get("actual") or {}
        best_candidate = candidates.get("best") or {}
        actual_region = _candidate_region(actual_candidate) or "实战区域"
        best_region = _candidate_region(best_candidate) or "推荐区域"
        actual_move = _display_move("actual", "实战手")
        best_move = _display_move("best", "AI 首选")
        answer = (
            f"实战手 {actual_move} 位于{actual_region}；"
            f"{_analysis_phrase(evidence, '首选')} {best_move} 位于{best_region}。"
            "两手属于不同方向，应在棋盘变化中分别比较先手、地盘转换和双方弱棋。"
        )
        principle = classical_go.match_principle(
            question, "comparison", candidates
        )
        if principle:
            answer += (
                f"古典棋理可参照“{principle['maxim']}”："
                f"{principle['gloss']}"
            )
        return answer
    if target.get("kind") == "best":
        candidate = candidates.get("best") or {}
        region = _candidate_region(candidate)
        candidate_role = str(
            (candidate.get("heuristics") or {}).get("role")
            or "推荐点的局部作用需要进入变化后继续验证"
        )
        prefix = (
            f"{_analysis_phrase(evidence, '首选')}是 J。"
            if best
            else "当前没有可用的推荐点。"
        )
        location = f"它位于{region}。" if region else ""
        answer = (
            f"{prefix}{location}可以理解为：{candidate_role}。"
            "建议在棋盘变化中逐手核对具体效果。"
        )
        principle = classical_go.match_principle(
            question, "best", candidates
        )
        if principle:
            answer += (
                f"古典棋理可参照“{principle['maxim']}”："
                f"{principle['gloss']}"
            )
        return answer
    if any(word in question for word in ("首选", "推荐", "变化", "演示")):
        prefix = (
            f"{_analysis_phrase(evidence, '首选')}是 J。"
            if best
            else "当前没有可用的推荐点。"
        )
        return f"{prefix}建议用棋盘变化逐手比较，而不是只看最终数值。{next_focus}"
    if any(word in question for word in ("记住", "训练", "避免", "以后")):
        return f"这类局面最值得形成固定检查顺序：{next_focus}"
    return f"这手可以理解为：{role}。{evidence_summary}{next_focus}"


def _call_chat_provider(provider: str, question: str, history: list[dict],
                        settings: dict, position: dict, evidence: dict,
                        purpose: dict, question_target: dict | None = None) -> dict:
    config = _provider_config(provider)
    if not config["configured"]:
        raise MentorProviderError(f"{config['name']}尚未配置")
    messages = [{"role": "system", "content": "你是弈鉴围棋老师，严格依据工具证据回答。"}]
    for item in history[-8:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:800]})
    messages.append({
        "role": "user",
        "content": _chat_prompt(
            question, settings, position, evidence, purpose, question_target, history
        ),
    })
    started = time.perf_counter()
    response = _request_json(
        f"{config['url']}/chat/completions",
        api_key=config["apiKey"],
        timeout=float(os.getenv("YIJIAN_CHAT_TIMEOUT", "30")),
        payload={
            "model": config["model"],
            "messages": messages,
            "temperature": .25,
            "max_tokens": 640,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise MentorProviderError("模型服务响应缺少回答正文") from exc
    parsed = _chat_json(content)
    parsed["numericValidation"] = _validate_supported_numbers(
        parsed["answer"], position, evidence
    )
    return {
        **parsed,
        "source": provider,
        "sourceLabel": config["name"],
        "model": config["model"],
        "answerMode": "llm_inference",
        "latencyMs": round((time.perf_counter() - started) * 1000),
    }


def _use_tactical_semantic_fast_path(
    question: str, target: dict, evidence: dict
) -> bool:
    value = evidence.get("variationEvidence")
    semantics = (
        value.get("tacticalSemantics")
        if isinstance(value, dict) and isinstance(value.get("tacticalSemantics"), dict)
        else {}
    )
    comparison = (
        semantics.get("comparison")
        if isinstance(semantics.get("comparison"), dict)
        else {}
    )
    return bool(
        semantics.get("status") == "ready"
        and comparison.get("mutualVitalPoint")
        and target.get("kind") in ("actual", "best", "comparison")
        and any(
            marker in question
            for marker in ("为什么", "不好", "差", "次序", "急点", "急所")
        )
    )


def chat(provider: str, question: str, history: list[dict] | None,
         settings: dict | None, position: dict | None, evidence: dict | None,
         purpose: dict | None, requested_target_kind: str | None = None) -> dict:
    """围绕当前局面的连续追问；模型失败时仍给出受证据约束的基础回答。"""
    chat_started = time.perf_counter()
    normalized = coach.normalize_settings(settings)
    position = position or {}
    evidence = evidence or {}
    purpose = purpose or {}
    selected = provider if provider in ("local", "cloud") else "local"
    baseline = coach.preview(normalized, position, evidence, purpose)
    actions = _chat_actions(question, evidence)
    question_target = _question_target(
        question, position, evidence, requested_target_kind
    )
    if _use_tactical_semantic_fast_path(question, question_target, evidence):
        answer = _chat_fallback(
            question, evidence, purpose, position, question_target
        )
        validation = _validate_chat_answer(
            answer, question, question_target, position, evidence, history or []
        )
        validation["routing"] = {
            "strategy": "deterministic_tactical_semantics",
            "reason": "服务端已确认同一棋块的 S/J 攻守角色反转",
        }
        answer, classical_guidance = _attach_classical_guidance(
            answer, question, question_target, position
        )
        validation["classicalGuidance"] = classical_guidance
        return {
            "answer": answer,
            "followUps": ["如果白方不抢J会怎样？", "J之后双方还能脱先吗？"],
            "source": "evidence",
            "sourceLabel": "服务端战术教练",
            "model": None,
            "answerMode": "deterministic_evidence",
            "latencyMs": round((time.perf_counter() - chat_started) * 1000),
            "degraded": False,
            "error": None,
            "actions": actions,
            "context": {
                "turn": int(position.get("turn") or 0),
                "move": position.get("move"),
                "evidenceLine": baseline["evidenceLine"],
                "questionTarget": question_target,
                "answerValidation": validation,
            },
        }
    try:
        result = _call_chat_provider(
            selected, question, history or [], normalized, position, evidence,
            purpose, question_target,
        )
        try:
            validation = _validate_chat_answer(
                result.get("answer") or "", question, question_target,
                position, evidence, history or [],
            )
        except MentorProviderError as validation_error:
            # 模型服务正常但表达越过证据边界时，只把明确的校验原因反馈给
            # 同一模型重写一次；不重新跑 KataGo，也不放宽事实契约。
            repair_question = (
                f"{question}\n服务端校验未通过：{validation_error}。"
                "请保留原问题，依据同一证据重写，不要辩解或复述校验信息。"
            )
            result = _call_chat_provider(
                selected, repair_question, history or [], normalized,
                position, evidence, purpose, question_target,
            )
            validation = _validate_chat_answer(
                result.get("answer") or "", question, question_target,
                position, evidence, history or [],
            )
            validation["repair"] = {
                "status": "passed",
                "reason": str(validation_error),
                "attempts": 2,
            }
        result["answer"], classical_guidance = _attach_classical_guidance(
            result.get("answer") or "", question, question_target, position
        )
        validation["classicalGuidance"] = classical_guidance
        degraded = False
        error = None
    except MentorProviderError as exc:
        result = {
            "answer": _chat_fallback(
                question, evidence, purpose, position, question_target
            ),
            "followUps": ["AI 首选好在哪里？", "这类错误以后怎么避免？"],
            "source": "baseline",
            "sourceLabel": "基础棋理解答",
            "model": None,
            "answerMode": "deterministic_fallback",
            "latencyMs": round((time.perf_counter() - chat_started) * 1000),
        }
        degraded = True
        error = str(exc)
        validation = {
            "status": "fallback",
            "target": question_target["kind"],
            "checks": ["question_target", "coordinate_region_binding"],
            "reason": str(exc),
            "classicalGuidance": (
                {
                    "status": "deterministic_fallback",
                    "source": "classical_go.match_principle",
                }
                if classical_go.match_principle(
                    question, question_target["kind"], _move_candidates(position)
                )
                else {"status": "not_available"}
            ),
        }
    return {
        **result,
        "degraded": degraded,
        "error": error,
        "actions": actions,
        "context": {
            "turn": int(position.get("turn") or 0),
            "move": position.get("move"),
            "evidenceLine": baseline["evidenceLine"],
            "questionTarget": question_target,
            "answerValidation": validation,
        },
    }


def init_feedback_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(FEEDBACK_DB) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS mentor_feedback (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                game_id TEXT,
                turn INTEGER NOT NULL,
                context_id TEXT NOT NULL DEFAULT '',
                position_hash TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL,
                provider TEXT NOT NULL,
                category TEXT NOT NULL,
                comment TEXT NOT NULL,
                response_hash TEXT NOT NULL,
                response_text TEXT NOT NULL
            )
        """)
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(mentor_feedback)"
            ).fetchall()
        }
        if "context_id" not in columns:
            connection.execute(
                "ALTER TABLE mentor_feedback "
                "ADD COLUMN context_id TEXT NOT NULL DEFAULT ''"
            )
        if "position_hash" not in columns:
            connection.execute(
                "ALTER TABLE mentor_feedback "
                "ADD COLUMN position_hash TEXT NOT NULL DEFAULT ''"
            )


def save_feedback(value: dict) -> dict:
    init_feedback_db()
    response_text = str(value.get("responseText") or "")[:6000]
    item = {
        "id": uuid.uuid4().hex,
        "gameId": str(value.get("gameId") or "")[:100],
        "turn": max(0, int(value.get("turn") or 0)),
        "contextId": str(value.get("contextId") or "")[:100],
        "positionHash": str(value.get("positionHash") or "")[:100],
        "mode": str(value.get("mode") or "baseline")[:20],
        "provider": str(value.get("provider") or "baseline")[:30],
        "category": str(value.get("category") or "comment")[:40],
        "comment": str(value.get("comment") or "").strip()[:1200],
        "responseText": response_text,
        "responseHash": hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
    }
    with sqlite3.connect(FEEDBACK_DB) as connection:
        connection.execute(
            """INSERT INTO mentor_feedback
               (id,game_id,turn,context_id,position_hash,mode,provider,category,
                comment,response_hash,response_text)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
             item["id"], item["gameId"], item["turn"],
             item["contextId"], item["positionHash"], item["mode"],
             item["provider"], item["category"], item["comment"],
             item["responseHash"], item["responseText"]),
        )
    return {"saved": True, "id": item["id"]}


def feedback_summary() -> dict:
    init_feedback_db()
    with sqlite3.connect(FEEDBACK_DB) as connection:
        rows = connection.execute(
            "SELECT provider, category, COUNT(*) FROM mentor_feedback GROUP BY provider, category"
        ).fetchall()
    return {
        "total": sum(row[2] for row in rows),
        "items": [
            {"provider": row[0], "category": row[1], "count": row[2]}
            for row in rows
        ],
    }
