"""main.py — FastAPI backend for the Learning Companion (Todo 8 wiring).

Endpoints (typed):
  POST /api/skills               创建技能
  GET  /api/skills               技能列表（花园视图数据）
  GET  /api/skills/{id}          技能详情（含单元/会话）
  POST /api/materials            上传资料 -> queued 提取作业（worker 异步）
  GET  /api/extraction-runs/{id} 提取作业状态（queued|running|verified|failed）
  POST /api/extraction-runs/{id}/retry  失败作业重试（有界）
  GET  /api/units/{id}           单元详情（含来源跨度与关键点）
  GET  /api/sessions             会话列表（learn/assessment/review）
  POST /api/learning-sessions    学习会话（已验证内容，单活跃会话）
  POST /api/assessment           首次评估（服务端重算权威评分，幂等）
  POST /api/review-sessions      到期复习会话（隐藏答案，来源提示）
  POST /api/sessions/{sid}/submit    复习提交（SM-2 调度）
  POST /api/sessions/{sid}/override  一次用户覆盖（audit 记录）
  POST /api/sessions/{sid}/abandon   放弃会话
  GET  /api/garden/{skill_id}    花园摘要（派生 growth/status）
  GET  /api/stats                统计（区分 preview/verified/pending/failed/due）
  POST /api/admin/drain          包装 app.drain（drained，零在途写者）
  POST /api/admin/undrain        原子重置 accepting 并释放 drain 锁
  GET  /health                   健康检查

Environment:
  LC_DB_PATH       SQLite 路径覆盖（Todo 7 disposable QA）
  LC_GRADER_STUB   none | unavailable（unavailable 使评分客户端失败-关闭）
  LC_EXTRACT_STUB  verify | unset（verify 使提取 worker 确定性通过）

Security: 全链路仅访问本地 127.0.0.1 端点，无任何云端调用。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import contracts, db, drain, extract, llm, processing, review, study, worker

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

app = FastAPI(title="Learning Companion API")
_worker = worker.ExtractionWorker(study.resolve_db())


@app.on_event("startup")
def _startup_recovery() -> None:
    """Startup recovery: requeue interrupted runs; reconcile stale drain state."""
    db_path = study.resolve_db()
    processing.ensure_schema(db_path)
    requeued = processing.requeue_stale_runs(db_path=db_path)
    drain.reconcile_stale()
    _worker.db_path = db_path
    _worker.start()
    print(f"STARTUP_RECOVERY_OK: requeued={requeued} drain={drain._read_state()['state']} worker=started")

# 本地开发允许前端访问；生产应同源部署
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- request models -------------------------------------------------------

class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""


class ExtractRequest(BaseModel):
    skill_id: Optional[int] = None
    skill_name: str = Field(default="", max_length=100)
    text: str = Field(min_length=10, max_length=500_000)
    run_full: bool = False


class ReviewStart(BaseModel):
    skill_id: int


class ReviewMessage(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class LearningStart(BaseModel):
    skill_id: int
    idempotency_key: Optional[str] = None


class AssessmentIn(BaseModel):
    session_id: int
    unit_id: int
    idempotency_key: str = Field(min_length=1, max_length=200)
    recall: str = Field(min_length=1, max_length=8000)


class ReviewSubmit(BaseModel):
    unit_id: int
    idempotency_key: str = Field(min_length=1, max_length=200)
    recall: str = Field(min_length=1, max_length=8000)


class OverrideIn(BaseModel):
    unit_id: int


class ReviewStartNew(BaseModel):
    skill_id: int


class AbandonIn(BaseModel):
    session_id: int


class MaterialIn(BaseModel):
    skill_id: Optional[int] = None
    skill_name: str = Field(default="", max_length=100)
    text: str = Field(min_length=1, max_length=500_000)
    filename: str = Field(default="", max_length=255)


def _validate_markdown_filename(filename: str) -> str:
    """Boundary check: only .md / .markdown uploads are accepted (case-insensitive)."""
    name = filename.strip()
    if not name:
        return ""
    if not name.lower().endswith((".md", ".markdown")):
        raise HTTPException(422, "仅支持 Markdown 文件（.md / .markdown）")
    return name


def _study_error(exc: study.StudyError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detail)


def _read_only_error() -> HTTPException:
    return HTTPException(status_code=503, detail="database is drained; writes rejected")


def _writer_enter() -> Optional[int]:
    """Admit a DB write through the drain protocol (fail-closed when draining)."""
    try:
        return drain.writer_enter()
    except RuntimeError:
        return None


def _writer_exit(fd: Optional[int]) -> None:
    if fd is not None:
        drain.writer_exit(fd)


# ---- skills ---------------------------------------------------------------

@app.post("/api/skills")
def create_skill(req: SkillCreate) -> dict:
    sid = db.create_skill(req.name, req.description)
    return {"id": sid, **db.get_skill(sid)}


@app.get("/api/skills", response_model=contracts.SkillListOut)
def list_skills() -> contracts.SkillListOut:
    skills = db.list_skills()
    for s in skills:
        s["card_count"] = len(db.list_cards(s["id"]))
    return contracts.SkillListOut(skills=skills)


@app.get("/api/skills/{skill_id}", response_model=contracts.SkillDetailOut)
def get_skill(skill_id: int) -> contracts.SkillDetailOut:
    s = db.get_skill(skill_id)
    if s is None:
        raise HTTPException(404, "skill not found")
    s["cards"] = db.list_cards(skill_id)
    s["sessions"] = [db.get_session(session["id"]) for session in db.list_sessions(skill_id)]
    return contracts.SkillDetailOut(**s)


# ---- extract --------------------------------------------------------------

@app.post("/api/extract")
def api_extract(req: ExtractRequest) -> dict:
    if req.skill_id is None:
        if not req.skill_name.strip():
            raise HTTPException(422, "skill_name or skill_id required")
        req.skill_id = db.create_skill(req.skill_name.strip())
    elif db.get_skill(req.skill_id) is None:
        raise HTTPException(404, "skill not found")

    result = extract.extract_two_stage(req.skill_id, req.text, run_full=req.run_full)
    result["skill_id"] = req.skill_id
    return result


# ---- materials / extraction runs (Todo 4 lifecycle + Todo 8 worker) --------

@app.post("/api/materials")
def api_materials(req: MaterialIn) -> dict:
    fd = _writer_enter()
    if fd is None:
        raise _read_only_error()
    try:
        try:
            db_path = study.resolve_db()
            # 先做 Markdown 文件名边界校验，再触碰数据库（422 优先于任何 DB 冲突）
            filename = _validate_markdown_filename(req.filename)
            # create a skill inline in the target schema when only skill_name is given
            skill_id = req.skill_id
            if skill_id is None:
                if not req.skill_name.strip():
                    raise HTTPException(422, "skill_id or skill_name required")
                con = processing.connect(db_path)
                try:
                    cur = con.execute(
                        "INSERT INTO skills(name, description, created_at, updated_at) VALUES(?,?,?,?)",
                        (req.skill_name.strip(), "", processing._now(), processing._now()))
                    con.commit()
                    skill_id = cur.lastrowid
                finally:
                    con.close()
            else:
                con = processing.connect(db_path)
                try:
                    exists = con.execute(
                        "SELECT id FROM skills WHERE id=?", (skill_id,)).fetchone()
                finally:
                    con.close()
                if exists is None:
                    raise HTTPException(404, "skill not found")
            mid, created = processing.ingest_material(
                skill_id, req.text, db_path=db_path, filename=filename)
            rid = processing.create_run(mid, "Qwen2.5-32B-AWQ", db_path=db_path)
        except sqlite3.Error as e:
            raise HTTPException(422, f"material ingestion failed: {e}") from e
    finally:
        _writer_exit(fd)
    # worker picks the queued run asynchronously
    _worker.start()
    return {"material_id": mid, "created": created, "run_id": rid,
            "status": processing.RUN_QUEUED, "skill_id": skill_id}


@app.get("/api/extraction-runs/{run_id}")
def api_extraction_run(run_id: int) -> dict:
    db_path = study.resolve_db()
    con = processing.connect(db_path)
    try:
        row = con.execute(
            "SELECT r.*, m.skill_id AS skill_id FROM extraction_runs r "
            "JOIN materials m ON m.id = r.material_id WHERE r.id=?", (run_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(404, "extraction run not found")
    return dict(row)


@app.post("/api/extraction-runs/{run_id}/retry")
def api_extraction_retry(run_id: int) -> dict:
    fd = _writer_enter()
    if fd is None:
        raise _read_only_error()
    try:
        ok = processing.retry_failed_run(run_id, db_path=study.resolve_db())
    finally:
        _writer_exit(fd)
    if not ok:
        raise HTTPException(409, "run not failed or retry budget exhausted")
    _worker.start()
    return {"ok": True, "run_id": run_id, "status": processing.RUN_QUEUED}


@app.delete("/api/extraction-runs/{run_id}")
def api_extraction_run_delete(run_id: int) -> dict:
    fd = _writer_enter()
    if fd is None:
        raise _read_only_error()
    try:
        ok = processing.delete_extraction_run(run_id, db_path=study.resolve_db())
    finally:
        _writer_exit(fd)
    if not ok:
        raise HTTPException(404, "extraction run not found")
    return {"ok": True, "run_id": run_id}


@app.delete("/api/skills/{skill_id}")
def api_skill_delete(skill_id: int) -> dict:
    fd = _writer_enter()
    if fd is None:
        raise _read_only_error()
    try:
        ok = processing.delete_skill(skill_id, db_path=study.resolve_db())
    finally:
        _writer_exit(fd)
    if not ok:
        raise HTTPException(404, "skill not found")
    return {"ok": True, "skill_id": skill_id}


@app.get("/api/units/{unit_id}")
def api_unit(unit_id: int) -> dict:
    db_path = study.resolve_db()
    con = processing.connect(db_path)
    try:
        row = con.execute("SELECT * FROM learning_units WHERE id=?", (unit_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(404, "unit not found")
    return study._unit_dict(row)


@app.get("/api/skills/{skill_id}/units")
def api_skill_units(skill_id: int) -> dict:
    """Verified/preview units for a skill (target schema, LC_DB_PATH-aware)."""
    db_path = study.resolve_db()
    con = processing.connect(db_path)
    try:
        rows = con.execute(
            "SELECT * FROM learning_units WHERE skill_id=? ORDER BY id", (skill_id,)).fetchall()
    finally:
        con.close()
    return {"units": [study._unit_dict(r) for r in rows]}


@app.get("/api/skills/{skill_id}/runs")
def api_skill_runs(skill_id: int) -> dict:
    """Extraction runs for a skill (material/run provenance for the detail page)."""
    db_path = study.resolve_db()
    con = processing.connect(db_path)
    try:
        rows = con.execute(
            "SELECT r.id, r.material_id, r.status, r.model, r.error_detail, r.retries, r.created_at, "
            "       m.normalized_text AS material_text, m.filename AS material_filename "
            "FROM extraction_runs r JOIN materials m ON m.id = r.material_id "
            "WHERE m.skill_id=? ORDER BY r.id DESC", (skill_id,)).fetchall()
    finally:
        con.close()
    return {"runs": [dict(r) for r in rows]}


@app.get("/api/materials/{material_id}")
def api_material(material_id: int) -> dict:
    """Original uploaded source document (raw Markdown) for the source viewer."""
    db_path = study.resolve_db()
    con = processing.connect(db_path)
    try:
        row = con.execute(
            "SELECT id, skill_id, raw_text, filename, created_at FROM materials WHERE id=?",
            (material_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(404, "material not found")
    return dict(row)


@app.get("/api/sessions")
def api_sessions() -> dict:
    db_path = study.resolve_db()
    con = processing.connect(db_path)
    try:
        rows = con.execute("SELECT * FROM study_sessions ORDER BY id DESC").fetchall()
    finally:
        con.close()
    return {"sessions": [dict(r) for r in rows]}


# ---- review ---------------------------------------------------------------

@app.post("/api/review")
def start_review(req: ReviewStart) -> dict:
    return review.start(req.skill_id)


@app.post("/api/review/{session_id}/message")
def review_message(session_id: int, req: ReviewMessage) -> dict:
    return review.respond(session_id, req.message)


@app.post("/api/review/{session_id}/complete")
def review_complete(session_id: int) -> dict:
    return db.complete_session(session_id)


@app.post("/api/review/{session_id}/override")
def review_override(session_id: int) -> dict:
    return review.override_current(session_id)


@app.post("/api/review/{session_id}/abandon")
def review_abandon(session_id: int) -> dict:
    db.abandon_session(session_id)
    return {"ok": True}


@app.post("/api/decay")
def api_decay() -> dict:
    return db.apply_decay()


# ---- learning / assessment / review (Todo 7, target schema) ----------------

@app.post("/api/learning-sessions")
def api_learning_start(req: LearningStart) -> dict:
    try:
        return study.start_learning_session(req.skill_id, idempotency_key=req.idempotency_key)
    except study.StudyError as e:
        raise _study_error(e) from e


@app.post("/api/assessment")
def api_assessment(req: AssessmentIn) -> dict:
    try:
        return study.submit_assessment(req.session_id, req.unit_id, req.idempotency_key, req.recall)
    except study.StudyError as e:
        raise _study_error(e) from e


@app.post("/api/review-sessions")
def api_review_start(req: ReviewStartNew) -> dict:
    try:
        return study.start_review_session(req.skill_id)
    except study.StudyError as e:
        raise _study_error(e) from e


@app.post("/api/review/{session_id}/submit")
def api_review_submit(session_id: int, req: ReviewSubmit) -> dict:
    try:
        return study.submit_review(session_id, req.unit_id, req.idempotency_key, req.recall)
    except study.StudyError as e:
        raise _study_error(e) from e


@app.post("/api/sessions/{session_id}/override")
def api_review_override(session_id: int, req: OverrideIn) -> dict:
    try:
        return study.override_review(session_id, req.unit_id)
    except study.StudyError as e:
        raise _study_error(e) from e


@app.post("/api/sessions/{session_id}/abandon")
def api_session_abandon(session_id: int) -> dict:
    try:
        return study.abandon_session(session_id)
    except study.StudyError as e:
        raise _study_error(e) from e


@app.get("/api/garden/{skill_id}")
def api_garden(skill_id: int) -> dict:
    try:
        return study.compute_garden(skill_id)
    except study.StudyError as e:
        raise _study_error(e) from e


@app.get("/api/garden")
def api_garden_list() -> dict:
    return {"gardens": study.list_gardens()}


@app.get("/api/stats", response_model=contracts.StatsOut)
def stats() -> contracts.StatsOut:
    skills = db.list_skills()
    cards = db.list_cards()
    sessions = db.list_sessions()
    active = [s for s in sessions if s["status"] == "进行中"]
    # target-schema breakdown (Todo 8): preview/verified/pending/failed/assessment_due/review_due
    db_path = study.resolve_db()
    con = processing.connect(db_path)
    try:
        preview_units = con.execute(
            "SELECT COUNT(*) AS c FROM learning_units WHERE status='preview'").fetchone()["c"]
        verified_units = con.execute(
            "SELECT COUNT(*) AS c FROM learning_units WHERE status='verified'").fetchone()["c"]
        pending_extractions = con.execute(
            "SELECT COUNT(*) AS c FROM extraction_runs WHERE status IN ('queued','running')").fetchone()["c"]
        failed_extractions = con.execute(
            "SELECT COUNT(*) AS c FROM extraction_runs WHERE status='failed'").fetchone()["c"]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        assessment_due = con.execute(
            "SELECT COUNT(*) AS c FROM learning_progress WHERE progress_status IN ('unlearned','learning','assessment_due')"
        ).fetchone()["c"]
        review_due = con.execute(
            "SELECT COUNT(*) AS c FROM learning_progress WHERE progress_status='review_due' "
            "AND next_review_at IS NOT NULL AND next_review_at <= ?", (now,)).fetchone()["c"]
    finally:
        con.close()
    return contracts.StatsOut(
        skills=len(skills),
        cards=len(cards),
        sessions=len(sessions),
        active_sessions=len(active),
        total_growth=round(sum(s["growth_value"] for s in skills), 1),
        avg_growth=round(sum(s["growth_value"] for s in skills) / len(skills), 1) if skills else 0,
        preview_units=preview_units,
        verified_units=verified_units,
        pending_extractions=pending_extractions,
        failed_extractions=failed_extractions,
        assessment_due=assessment_due,
        review_due=review_due,
    )


# ---- admin: drain / undrain (wrap app.drain.py) ----------------------------

@app.post("/api/admin/drain")
def api_admin_drain() -> dict:
    try:
        fd = drain.acquire_drain()
    except TimeoutError:
        raise HTTPException(503, "drain lock acquisition timed out") from None
    try:
        drain.set_drain_state(drain.DRAINING, "api-drain")
        try:
            drain.wait_drained()
        except TimeoutError:
            drain._reset_state()
            raise HTTPException(503, "in-flight writers did not drain; fail-closed") from None
        drain.set_drain_state(drain.DRAINED, "api-drain")
        return {"state": drain.DRAINED, "in_flight": 0}
    finally:
        drain.release_drain(fd)


@app.post("/api/admin/undrain")
def api_admin_undrain() -> dict:
    # atomically reset accepting + release drain lock (drain lock is held per request;
    # the state reset is the admission gate; release happens via release_drain below)
    state = drain._read_state()
    if state["state"] == drain.ACCEPTING:
        raise HTTPException(409, "not draining")
    drain._reset_state()
    print("UNDRAIN_OK: accepting")
    return {"state": drain.ACCEPTING, "in_flight": 0}


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "drain_state": drain._read_state()["state"],
        "db_path": str(study.resolve_db()),
    }


# ---- SPA fallback (non-/api routes serve index.html; /api + assets preserved) ---
# Mount the hashed asset directory FIRST so JS/CSS get correct MIME types;
# the catch-all below only serves index.html for non-api, non-asset app routes.

if (WEB_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")


@app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
def spa_fallback(full_path: str) -> str:
    if full_path.startswith("api/") or full_path.startswith("assets/"):
        raise HTTPException(404, "route not found")
    index = WEB_DIST / "index.html"
    if index.exists():
        return index.read_text(encoding="utf-8")
    return "<h3>Learning Companion API</h3><p>前端构建中。API 见 /docs</p>"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    index = WEB_DIST / "index.html"
    if index.exists():
        return index.read_text(encoding="utf-8")
    return "<h3>Learning Companion API</h3><p>前端构建中。API 见 /docs</p>"
