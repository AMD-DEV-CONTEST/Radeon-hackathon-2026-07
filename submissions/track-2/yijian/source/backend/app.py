# -*- coding: utf-8 -*-
"""弈鉴 GoMentor 本地服务。"""

from __future__ import annotations

import base64
import hashlib
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

import coach
import jobs
import library
import media_gateway
import mentor
import reports
import sgf
import teaching_context
from builtin_content import RECENT_EDITORIAL_SLOTS, seed_classics
from engine import KataGoEngine, KataGoError, MockKataGoEngine
from goboard import IllegalMove, gtp_name, replay
from importers import ImportError as GameImportError, import_bytes
from terminology import TERMS

BASE = os.path.dirname(os.path.abspath(__file__))
DEMO_SGF_TEXT = (
    "(;GM[1]FF[4]CA[UTF-8]AP[YIJIAN]SZ[19]KM[7.5]"
    "PB[Demo Black]PW[Demo White]RE[?]"
    ";B[pd];W[dd];B[qp];W[dq];B[pp];W[dp];B[nc];W[cf])"
)
WEB_DIR = os.path.join(BASE, "..", "web")


@asynccontextmanager
async def lifespan(_: FastAPI):
    library.init_db()
    library.recover_interrupted_jobs()
    seed_classics()
    mentor.init_feedback_db()
    if isinstance(engine, KataGoEngine):
        threading.Thread(
            target=engine.warm_up, name="yijian-katago-warmup", daemon=True
        ).start()
    yield


app = FastAPI(
    title="弈鉴 GoMentor",
    version="0.15.0-tactical-semantics",
    lifespan=lifespan,
)
mock_engine = MockKataGoEngine()
try:
    engine = KataGoEngine()
    engine_setup_error = None
except KataGoError as exc:
    engine = mock_engine
    engine_setup_error = str(exc)
analysis_manager = jobs.AnalysisManager(engine)


class SgfBody(BaseModel):
    sgf: str


class VariationBody(SgfBody):
    turn: int
    firstMove: str
    depth: int = 10
    prefix: list[str] = Field(default_factory=list)


class RecommendBody(SgfBody):
    turn: int
    variation: list[str] = Field(default_factory=list)


class ImportBody(BaseModel):
    filename: str = "未命名棋谱.sgf"
    contentBase64: str | None = None
    text: str | None = None


class GamePatch(BaseModel):
    favorite: bool | None = None
    tags: list[str] | None = None
    title: str | None = None


class CoachSettings(BaseModel):
    persona: str = "principles"
    terminologyDensity: str = "medium"
    explanationLength: str = "standard"
    variationDepth: int = 6
    studentRank: str = "amateur_5d"
    studentAge: int | None = None
    playerName: str = ""
    playerAliases: list[str] = Field(default_factory=list)
    lastPerspective: str | None = None
    mentorMode: str = "baseline"


class TeachingLocatorBody(BaseModel):
    """只接受上下文定位符；客户端不得提交棋力或棋理事实。"""

    model_config = ConfigDict(extra="forbid")

    gameId: str = Field(min_length=1, max_length=100)
    reportId: str | None = Field(default=None, min_length=1, max_length=100)
    turn: int = Field(default=0, ge=0)
    variation: list[str] = Field(default_factory=list, max_length=40)


class CoachPreviewBody(TeachingLocatorBody):
    pass


class MentorExplainBody(TeachingLocatorBody):
    mode: str = "baseline"


class MentorFeedbackBody(TeachingLocatorBody):
    reportId: str = Field(min_length=1, max_length=100)
    contextId: str = Field(min_length=64, max_length=64)
    positionHash: str = Field(min_length=64, max_length=64)
    mode: str = "baseline"
    provider: str = "baseline"
    category: str = "comment"
    comment: str = Field(default="", max_length=1200)
    responseText: str = Field(default="", max_length=6000)


class MentorHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(max_length=20)
    content: str = Field(max_length=800)
    contextId: str | None = Field(default=None, max_length=100)
    positionHash: str | None = Field(default=None, max_length=100)


class MentorChatBody(TeachingLocatorBody):
    question: str = Field(min_length=1, max_length=1200)
    provider: str = "local"
    targetKind: str | None = Field(
        default=None, pattern="^(actual|best|comparison|position)$"
    )
    history: list[MentorHistoryItem] = Field(default_factory=list, max_length=8)


class AnalysisJobBody(BaseModel):
    gameId: str
    perspective: str = "B"
    force: bool = False
    mode: str = "fast"


class NodeAnalysisBody(BaseModel):
    gameId: str
    perspective: str = "B"
    turn: int = Field(ge=1)
    visits: int = Field(default=256, ge=128, le=512)


class MediaGenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern="^(image|video)$")
    model: str = Field(min_length=2, max_length=100)
    prompt: str = Field(min_length=3, max_length=6000)
    negativePrompt: str | None = Field(default=None, max_length=2000)
    size: str = Field(default="16:9", max_length=30)
    resolution: str = Field(default="2k", max_length=30)
    n: int = Field(default=1, ge=1, le=4)
    duration: int = Field(default=5, ge=2, le=20)
    seed: int | None = Field(default=None, ge=0, le=2147483647)
    audio: bool = False
    imageUrls: list[str] = Field(default_factory=list, max_length=16)
    lastFrameUrl: str | None = Field(default=None, max_length=14_000_000)


def _game_payload(game: sgf.Game) -> dict:
    board, _ = replay(game)
    stones = board.stones()
    return {
        "info": game.info,
        "size": game.size,
        "moveCount": len(game.moves),
        "moves": [
            {
                "number": move.number,
                "color": move.color,
                "coord": move.coord,
                "gtp": gtp_name(move.coord, game.size) if not move.is_pass else "pass",
            }
            for move in game.moves
        ],
        "captured": {"black": board.captured[1], "white": board.captured[2]},
        "finalStones": {"black": stones[1], "white": stones[2]},
    }


def _parse_or_400(text: str) -> sgf.Game:
    try:
        game = sgf.parse(text)
    except sgf.SGFError as exc:
        raise HTTPException(400, f"SGF 解析失败：{exc}") from exc
    if not game.moves:
        raise HTTPException(400, "棋谱中没有着手")
    return game


def _analysis_key(game: sgf.Game) -> str:
    value = (
        f"{game.size}|{game.info.get('KM', '')}|{game.info.get('RU', '')}|" +
        "|".join(f"{move.color}:{move.coord}" for move in game.moves)
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@app.get("/api/health")
def health():
    detail = engine.health() if isinstance(engine, KataGoEngine) else {
        "engine": "mock",
        "demo": True,
        "configured": False,
        "setupError": engine_setup_error,
    }
    return {"status": "ok", "version": app.version, "terminologyCount": len(TERMS), **detail}


@app.get("/api/media/status")
def media_status():
    return media_gateway.status()


@app.get("/api/media/models")
def media_models():
    return {"items": media_gateway.MODEL_CATALOG}


@app.post("/api/media/generate")
def media_generate(body: MediaGenerateBody):
    try:
        return media_gateway.submit(body.model_dump())
    except media_gateway.MediaGatewayError as exc:
        raise HTTPException(
            exc.status_code,
            {"message": str(exc), "upstream": exc.detail},
        ) from exc


@app.get("/api/media/tasks/{task_id}")
def media_task(task_id: str):
    try:
        return media_gateway.task(task_id)
    except media_gateway.MediaGatewayError as exc:
        raise HTTPException(
            exc.status_code,
            {"message": str(exc), "upstream": exc.detail},
        ) from exc


@app.get("/api/demo")
def demo_game(analyze: bool = False):
    game = _parse_or_400(DEMO_SGF_TEXT)
    selected = engine if analyze else mock_engine
    return {"game": _game_payload(game), "analysis": selected.analyze_game(game)}


@app.post("/api/game")
def parse_game(body: SgfBody):
    try:
        return {"game": _game_payload(_parse_or_400(body.sgf))}
    except IllegalMove as exc:
        raise HTTPException(400, f"棋谱重放失败（非法着手）：{exc}") from exc


@app.post("/api/analyze")
def analyze(body: SgfBody):
    game = _parse_or_400(body.sgf)
    try:
        payload = _game_payload(game)
        engine_signature = (
            f"{engine.version}:{engine.model_name}:{engine.max_visits}"
            if isinstance(engine, KataGoEngine) else "mock"
        )
        cache_key = _analysis_key(game)
        analysis = library.get_analysis_cache(cache_key, engine_signature)
        if analysis is None:
            analysis = engine.analyze_game(game)
            if isinstance(engine, KataGoEngine):
                library.put_analysis_cache(cache_key, engine_signature, analysis)
        else:
            analysis = {**analysis, "cached": True}
    except IllegalMove as exc:
        raise HTTPException(400, f"棋谱重放失败（非法着手）：{exc}") from exc
    except KataGoError as exc:
        raise HTTPException(503, f"真实 KataGo 暂时无法分析：{exc}") from exc
    return {"game": payload, "analysis": analysis}


@app.post("/api/variation")
def analyze_variation(body: VariationBody):
    if not isinstance(engine, KataGoEngine):
        raise HTTPException(503, "真实 KataGo 未配置，无法推演变化")
    try:
        return engine.analyze_variation(
            _parse_or_400(body.sgf), body.turn, body.firstMove, body.depth, body.prefix
        )
    except KataGoError as exc:
        raise HTTPException(503, f"KataGo 变化推演失败：{exc}") from exc


@app.post("/api/recommend")
def recommend_position(body: RecommendBody):
    if not isinstance(engine, KataGoEngine):
        raise HTTPException(503, "真实 KataGo 未配置，无法申请推荐手")
    try:
        return engine.analyze_position(_parse_or_400(body.sgf), body.turn, body.variation)
    except KataGoError as exc:
        raise HTTPException(503, f"KataGo 推荐手分析失败：{exc}") from exc


@app.get("/api/library/games")
def library_games(
    category: str = "",
    q: str = "",
    sort: str = "recent",
    page: int = Query(1, ge=1),
    pageSize: int = Query(30, ge=1, le=100),
):
    return library.list_games(category, q, sort, page, pageSize)


@app.get("/api/library/status")
def library_status():
    """返回可展示内容数量与近期职业授权审核位，不把占位计入棋谱。"""
    return {
        "classics": library.list_games("classics", page_size=100)["total"],
        "recent": library.list_games("recent", page_size=100)["total"],
        "recentEditorialSlots": RECENT_EDITORIAL_SLOTS,
    }


@app.post("/api/library/import")
def library_import(body: ImportBody):
    if body.contentBase64:
        try:
            raw = base64.b64decode(body.contentBase64, validate=True)
        except ValueError as exc:
            raise HTTPException(400, "文件内容不是有效的 Base64") from exc
    elif body.text is not None:
        raw = body.text.encode("utf-8")
    else:
        raise HTTPException(400, "缺少棋谱文件内容")
    try:
        imported = import_bytes(raw, body.filename)
        game, created = library.add_import(imported)
    except GameImportError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        payload = _game_payload(imported.game)
    except IllegalMove as exc:
        raise HTTPException(400, f"棋谱主线无法合法重放：{exc}") from exc
    return {
        "created": created,
        "duplicate": not created,
        "message": "导入成功" if created else "导入成功，已有相同棋谱，未重复保存",
        "game": game,
        "parsed": payload,
        "encoding": imported.encoding,
    }


@app.get("/api/library/games/{game_id}")
def library_game(game_id: str):
    game = library.get_game(game_id)
    if not game:
        raise HTTPException(404, "棋谱不存在")
    return game


@app.post("/api/analysis/jobs")
def analysis_job_create(body: AnalysisJobBody):
    if body.mode not in ("fast", "deep"):
        raise HTTPException(400, "分析模式必须是 fast 或 deep")
    if body.perspective not in ("B", "W"):
        raise HTTPException(400, "执棋方必须是 B 或 W")
    try:
        return analysis_manager.create(
            body.gameId, body.perspective, body.force, body.mode
        )
    except KeyError as exc:
        raise HTTPException(404, "棋谱不存在") from exc


@app.get("/api/analysis/jobs/{job_id}")
def analysis_job_get(job_id: str):
    job = analysis_manager.get(job_id)
    if not job:
        raise HTTPException(404, "分析任务不存在")
    return job


@app.post("/api/analysis/jobs/{job_id}/cancel")
def analysis_job_cancel(job_id: str):
    job = analysis_manager.cancel(job_id)
    if not job:
        raise HTTPException(404, "分析任务不存在")
    return job


@app.post("/api/analysis/node")
def analysis_node(body: NodeAnalysisBody):
    if body.perspective not in ("B", "W"):
        raise HTTPException(400, "执棋方必须是 B 或 W")
    try:
        return analysis_manager.deepen_node(
            body.gameId, body.perspective, body.turn, body.visits
        )
    except KeyError as exc:
        raise HTTPException(404, "棋谱或整盘报告不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except KataGoError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/library/games/{game_id}/report")
def library_game_report(game_id: str, perspective: str = "", rank: str = ""):
    game = library.get_game(game_id)
    if not game:
        raise HTTPException(404, "棋谱不存在")
    selected_side = perspective if perspective in ("B", "W") else None
    cached = library.latest_report(game_id, selected_side)
    if not cached:
        raise HTTPException(409, "该棋谱尚未完成整盘预分析")
    settings = coach.normalize_settings(library.get_setting("coach", coach.DEFAULT_SETTINGS))
    selected_rank = reports.normalize_rank(rank or settings["studentRank"])
    rendered = reports.render_report(cached["raw"], selected_rank)
    return {
        "game": game,
        "reportId": cached["id"],
        "reportSignature": cached.get("signature"),
        "reportRevision": cached.get("revision"),
        "perspective": cached["perspective"],
        "report": rendered,
    }


@app.patch("/api/library/games/{game_id}")
def library_patch(game_id: str, body: GamePatch):
    game = library.update_game(game_id, body.model_dump(exclude_none=True))
    if not game:
        raise HTTPException(404, "棋谱不存在")
    return game


@app.delete("/api/library/games/{game_id}")
def library_delete(game_id: str):
    game = library.get_game(game_id)
    if not game:
        raise HTTPException(404, "棋谱不存在")
    if not game["isUserContent"]:
        raise HTTPException(403, "内置棋谱不可删除，可以取消收藏或添加标签")
    library.delete_game(game_id)
    return {"deleted": True}


@app.post("/api/library/sync")
def library_sync():
    # 本地包已随版本审核；远程更新仅在用户主动点击时响应，当前不访问任意商业棋库。
    return {
        "status": "review-required",
        "classics": library.list_games("classics", page_size=100)["total"],
        "recent": library.list_games("recent", page_size=100)["total"],
        "recentEditorialSlots": RECENT_EDITORIAL_SLOTS,
        "message": "经典内容包已是最新；近期职业20盘尚待逐盘确认原始链接与再分发许可。",
    }


@app.get("/api/coach/settings")
def coach_settings():
    return {
        "settings": coach.normalize_settings(library.get_setting("coach", coach.DEFAULT_SETTINGS)),
        "personas": [{"id": key, **value} for key, value in coach.PERSONAS.items()],
    }


@app.put("/api/coach/settings")
def coach_settings_put(body: CoachSettings):
    settings = coach.normalize_settings(body.model_dump())
    library.put_setting("coach", settings)
    return {"settings": settings}


def _authoritative_teaching_context(
    body: TeachingLocatorBody,
    *,
    include_variation_evidence: bool = False,
) -> dict:
    try:
        context = teaching_context.build_authoritative_context(
            body.gameId,
            body.turn,
            body.variation,
            engine,
            body.reportId,
        )
        if include_variation_evidence:
            context = teaching_context.enrich_with_variation_evidence(
                context, engine
            )
        return context
    except teaching_context.TeachingContextError as exc:
        raise HTTPException(
            exc.status_code,
            {"code": exc.code, "message": str(exc)},
        ) from exc


@app.post("/api/coach/preview")
def coach_preview(body: CoachPreviewBody):
    settings = library.get_setting("coach", coach.DEFAULT_SETTINGS)
    context = _authoritative_teaching_context(body)
    position, evidence, purpose = teaching_context.mentor_inputs(context)
    result = coach.preview(settings, position, evidence, purpose)
    return {**result, "teachingContext": context}


@app.get("/api/mentor/status")
def mentor_status(force: bool = False):
    return mentor.provider_status(force)


@app.post("/api/mentor/explain")
def mentor_explain(body: MentorExplainBody):
    settings = library.get_setting("coach", coach.DEFAULT_SETTINGS)
    context = _authoritative_teaching_context(body)
    position, evidence, purpose = teaching_context.mentor_inputs(context)
    result = mentor.explain(
        body.mode,
        settings,
        position,
        evidence,
        purpose,
        context.get("expression", {}).get("cachedNarrative"),
    )
    return {**result, "teachingContext": context}


@app.post("/api/mentor/feedback")
def mentor_feedback(body: MentorFeedbackBody):
    context = _authoritative_teaching_context(body)
    if (
        body.contextId != context["contextId"]
        or body.positionHash != context["positionHash"]
    ):
        raise HTTPException(409, "反馈上下文已过期，请基于当前讲解重新评价")
    payload = body.model_dump()
    payload["turn"] = context["subject"]["effectiveTurn"]
    return mentor.save_feedback(payload)


@app.get("/api/mentor/feedback/summary")
def mentor_feedback_summary():
    return mentor.feedback_summary()


@app.post("/api/mentor/chat")
def mentor_chat(body: MentorChatBody):
    request_started = time.perf_counter()
    settings = library.get_setting("coach", coach.DEFAULT_SETTINGS)
    evidence_started = time.perf_counter()
    context = _authoritative_teaching_context(
        body, include_variation_evidence=True
    )
    evidence_ms = round((time.perf_counter() - evidence_started) * 1000)
    position, evidence, purpose = teaching_context.mentor_inputs(context)
    history = [
        item.model_dump()
        for item in body.history
        if (
            item.contextId == context["contextId"]
            and (
                not item.positionHash
                or item.positionHash == context["positionHash"]
            )
        )
    ]
    answer_started = time.perf_counter()
    result = mentor.chat(
        body.provider, body.question, history, settings,
        position, evidence, purpose, body.targetKind,
    )
    answer_ms = round((time.perf_counter() - answer_started) * 1000)
    model_ms = int(result.get("latencyMs") or 0)
    total_ms = round((time.perf_counter() - request_started) * 1000)
    result["modelLatencyMs"] = model_ms
    result["latencyMs"] = total_ms
    result["timing"] = {
        "totalMs": total_ms,
        "evidenceMs": evidence_ms,
        "answerMs": answer_ms,
        "modelReportedMs": model_ms,
        "answerAttempts": int(
            ((result.get("context") or {}).get("answerValidation") or {})
            .get("repair", {}).get("attempts", 1)
        ),
    }
    adjudication = context.get("adjudication") or {}
    result["context"] = {
        **(result.get("context") or {}),
        "gameId": context["gameId"],
        "contextId": context["contextId"],
        "positionHash": context["positionHash"],
        "baseTurn": context["subject"]["baseTurn"],
        "variation": context["subject"]["variation"],
        "adjudicationId": adjudication.get("adjudicationId"),
        "variationEvidenceHash": adjudication.get("variationEvidenceHash"),
        "variationEvidenceStatus": (
            (adjudication.get("variationEvidence") or {}).get("status")
        ),
    }
    return {**result, "teachingContext": context}


@app.get("/api/terminology")
def terminology(category: str = "", q: str = "", limit: int = Query(30, ge=1, le=300)):
    values = TERMS
    if category:
        values = [entry for entry in values if entry["category"] == category]
    if q:
        values = [entry for entry in values if q in entry["term"] or any(q in alias for alias in entry["aliases"])]
    return {"items": values[:limit], "total": len(values), "allCount": len(TERMS)}


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
