"""Optional FastAPI surface for raw, single-file local uploads."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

try:
    from fastapi import Request
except ImportError:  # keep the evidence core importable without the API extra
    Request = Any  # type: ignore[misc,assignment]

from app.agents.intake import assess_intake
from app.demo.business_cases import (
    list_experience_scenarios,
    seed_experience_case,
)
from app.evidence.pipeline import EvidenceReconstructionPipeline
from app.evidence.workspace import CaseWorkspace, DEFAULT_MAX_BYTES
from app.graph.workflow import CaseOrchestrator
from app.rag.service import build_retriever
from app.schemas.evidence import SourceRole
from app.ui.experience import experience_page


def create_app(
    case_root: Path | str = Path("data/cases"),
    *,
    checkpoint_path: Path | str | None = None,
    legal_corpus_path: Path | str | None = None,
    qdrant_path: Path | str | None = None,
):
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.concurrency import run_in_threadpool
        from fastapi.responses import HTMLResponse
    except ImportError as exc:
        raise RuntimeError(
            "FastAPI is optional. Install the project 'api' extra."
        ) from exc

    app = FastAPI(title="Accident Rights Evidence API", version="0.1.0")
    workspace = CaseWorkspace(case_root)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "model_policy": "loopback-only"}

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/experience", response_class=HTMLResponse, include_in_schema=False)
    async def experience():
        return experience_page()

    @app.get("/experience/scenarios", include_in_schema=False)
    async def experience_scenarios():
        return list_experience_scenarios()

    @app.post("/cases")
    async def create_case(request: Request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        try:
            case_id = workspace.create_case(payload.get("case_id"))
            return {"case_id": case_id}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/cases/{case_id}/sources")
    async def upload_source(
        case_id: str,
        request: Request,
        filename: str,
        role: SourceRole = SourceRole.OTHER,
    ):
        workspace.store(case_id)
        temporary_path: Path | None = None
        received = 0
        try:
            with tempfile.NamedTemporaryFile(
                prefix="evidence-upload-",
                suffix=Path(filename).suffix,
                dir=workspace.case_dir(case_id),
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > DEFAULT_MAX_BYTES:
                        raise HTTPException(
                            status_code=413, detail="Evidence upload exceeds size limit."
                        )
                    temporary.write(chunk)
            record = await run_in_threadpool(
                workspace.ingest_file,
                case_id,
                temporary_path,
                role=role,
                original_name=filename,
            )
            return record.to_dict()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)

    @app.get("/cases/{case_id}")
    async def get_case(case_id: str):
        try:
            store = workspace.store(case_id)
            result = store.export_case(case_id)
            result["intake"] = assess_intake(
                store.list_sources(case_id)
            ).to_dict()
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/cases/{case_id}/sources/{source_id}/role")
    async def update_source_role(
        case_id: str,
        source_id: str,
        role: SourceRole,
    ):
        try:
            store = workspace.store(case_id)
            source = store.get_source(source_id)
            if source.case_id != case_id:
                raise KeyError(source_id)
            return store.update_source_role(source_id, role).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/cases/{case_id}/reconstruct")
    async def reconstruct(case_id: str):
        try:
            return (
                await run_in_threadpool(
                    EvidenceReconstructionPipeline(workspace).reconstruct, case_id
                )
            ).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def with_orchestrator():
        retriever = build_retriever(
            corpus_path=legal_corpus_path, qdrant_path=qdrant_path
        )
        orchestrator = CaseOrchestrator(
            workspace=workspace,
            retriever=retriever,
            checkpoint_path=checkpoint_path
            or os.getenv(
                "ORCHESTRATOR_CHECKPOINT_DB",
                "data/checkpoints/orchestrator.sqlite3",
            ),
        )
        return retriever, orchestrator

    @app.post("/experience/run/{scenario_id}", include_in_schema=False)
    async def run_experience(scenario_id: str):
        retriever = orchestrator = None
        try:
            case_id, scenario = await run_in_threadpool(
                seed_experience_case, workspace, scenario_id
            )
            thread_id = (
                f"THREAD-EXP-{scenario.short_label}-"
                f"{uuid.uuid4().hex[:8].upper()}"
            )
            retriever, orchestrator = with_orchestrator()
            result = await run_in_threadpool(
                orchestrator.run,
                case_id,
                thread_id=thread_id,
            )
            result["experience"] = {
                **scenario.public_summary(),
                "synthetic": True,
                "thread_id": thread_id,
            }
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            if orchestrator:
                orchestrator.close()
            if retriever:
                retriever.close()

    @app.post("/cases/{case_id}/workflow")
    async def run_workflow(
        case_id: str,
        thread_id: str | None = None,
        interrupt_after: str | None = None,
    ):
        retriever = orchestrator = None
        try:
            workspace.store(case_id)
            retriever, orchestrator = with_orchestrator()
            return await run_in_threadpool(
                orchestrator.run,
                case_id,
                thread_id=thread_id,
                interrupt_after=interrupt_after,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            if orchestrator:
                orchestrator.close()
            if retriever:
                retriever.close()

    @app.post("/workflows/{thread_id}/resume")
    async def resume_workflow(thread_id: str):
        retriever = orchestrator = None
        try:
            retriever, orchestrator = with_orchestrator()
            return await run_in_threadpool(orchestrator.resume, thread_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            if orchestrator:
                orchestrator.close()
            if retriever:
                retriever.close()

    @app.get("/workflows/{thread_id}")
    async def workflow_status(thread_id: str):
        retriever = orchestrator = None
        try:
            retriever, orchestrator = with_orchestrator()
            return await run_in_threadpool(orchestrator.status, thread_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            if orchestrator:
                orchestrator.close()
            if retriever:
                retriever.close()

    @app.post("/workflows/{thread_id}/approval")
    async def decide_workflow_approval(thread_id: str, request: Request):
        retriever = orchestrator = None
        try:
            payload = await request.json()
            if not payload.get("approver"):
                raise HTTPException(status_code=400, detail="approver is required")
            retriever, orchestrator = with_orchestrator()
            return await run_in_threadpool(
                orchestrator.decide_approval,
                thread_id,
                decision=str(payload.get("decision", "")),
                approver=str(payload["approver"]),
                comments=str(payload.get("comments", "")),
            )
        except HTTPException:
            raise
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            if orchestrator:
                orchestrator.close()
            if retriever:
                retriever.close()

    return app
