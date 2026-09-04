from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from policyseal.api.dependencies import AppServices
from policyseal.application.matrix import default_xlsx_contexts
from policyseal.domain.models import DisclosureContext


def _context_json(context: DisclosureContext) -> str:
    return json.dumps(asdict(context))


async def _create_task(
    client: httpx.AsyncClient,
    source: Path,
    context: DisclosureContext,
    requester_id: str,
) -> dict[str, object]:
    response = await client.post(
        "/api/tasks",
        files={"file": (source.name, source.read_bytes(), "application/octet-stream")},
        data={"context_json": _context_json(context), "requester_id": requester_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_safe_workflow_supports_events_simulation_exports_and_deletion(
    api_app: FastAPI,
    hero_xlsx: Path,
) -> None:
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await _create_task(
            client,
            hero_xlsx,
            default_xlsx_contexts()[0],
            "requester-api-1",
        )
        task_id = str(created["id"])
        revision_id = str(created["revisions"][0]["id"])
        assert created["revisions"][0]["status"] == "draft"

        analyzed_response = await client.post(f"/api/revisions/{revision_id}/analyze")
        assert analyzed_response.status_code == 200
        analyzed = analyzed_response.json()
        assert analyzed["status"] == "exportable"
        assert analyzed["decisions"]
        assert analyzed["action_counts"]

        review = (await client.get(f"/api/revisions/{revision_id}/review")).json()
        assert review["file_kind"] == "xlsx"
        assert review["regions"]
        assert review["regions"][0]["source_text"]
        assert review["regions"][0]["rule_reasons"]
        assert review["evidence"]
        assert review["preview_urls"] == []

        thread_response = await client.post(
            "/api/copilot/threads",
            json={
                "task_id": task_id,
                "revision_id": revision_id,
                "display_reference": "api-workflow",
            },
        )
        assert thread_response.status_code == 201
        thread_id = thread_response.json()["thread_id"]
        reply_response = await client.post(
            f"/api/copilot/threads/{thread_id}/messages",
            json={
                "task_id": task_id,
                "message": "Why was the supplier bank account removed?",
            },
        )
        assert reply_response.status_code == 200
        reply = reply_response.json()
        assert reply["intent"] == "explain"
        assert reply["citations"][0]["category"] == "bank_payment"
        assert reply["model_dependent"] is False

        events_response = await client.get(f"/api/revisions/{revision_id}/events")
        assert events_response.status_code == 200
        event_ids = [
            int(line.removeprefix("id: "))
            for line in events_response.text.splitlines()
            if line.startswith("id: ")
        ]
        assert event_ids == sorted(event_ids)
        assert len(event_ids) >= 8

        resumed_response = await client.get(
            f"/api/revisions/{revision_id}/events",
            headers={"Last-Event-ID": str(event_ids[-2])},
        )
        resumed_ids = [
            int(line.removeprefix("id: "))
            for line in resumed_response.text.splitlines()
            if line.startswith("id: ")
        ]
        assert resumed_ids == [event_ids[-1]]

        business = await client.get(f"/api/revisions/{revision_id}/download")
        evidence = await client.get(f"/api/revisions/{revision_id}/evidence")
        assert business.status_code == 200
        assert business.content.startswith(b"PK")
        assert evidence.status_code == 200
        assert evidence.headers["content-type"] == "application/zip"

        simulation_response = await client.post(
            f"/api/tasks/{task_id}/simulations",
            json={"context": json.loads(_context_json(default_xlsx_contexts()[1]))},
        )
        assert simulation_response.status_code == 200
        simulation = simulation_response.json()
        assert simulation["downloadable"] is False
        assert len(simulation["decisions"]) == len(analyzed["decisions"])
        task_before_formal = (await client.get(f"/api/tasks/{task_id}")).json()
        assert len(task_before_formal["revisions"]) == 1

        formal_response = await client.post(
            f"/api/tasks/{task_id}/formal-context",
            json={
                "simulation_id": simulation["id"],
                "actor": "requester-api-1",
            },
        )
        assert formal_response.status_code == 200
        assert formal_response.json()["revision_number"] == 2

        listed = await client.get("/api/tasks")
        assert listed.status_code == 200
        assert [task["id"] for task in listed.json()] == [task_id]

        deleted = await client.delete(
            f"/api/tasks/{task_id}",
            params={"actor": "requester-api-1"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["revision_count"] == 2
        assert (await client.get(f"/api/tasks/{task_id}")).status_code == 404
        removed_thread = await client.post(
            f"/api/copilot/threads/{thread_id}/messages",
            json={"task_id": task_id, "message": "Why?"},
        )
        assert removed_thread.status_code == 404


@pytest.mark.asyncio
async def test_approval_is_bound_and_required_for_pdf_download(
    api_app: FastAPI,
    hero_pdf: Path,
) -> None:
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await _create_task(
            client,
            hero_pdf,
            DisclosureContext.candidate_supplier_corporate_email(),
            "requester-api-2",
        )
        revision_id = str(created["revisions"][0]["id"])
        analyzed = (await client.post(f"/api/revisions/{revision_id}/analyze")).json()
        assert analyzed["status"] == "awaiting_approval"

        review = (await client.get(f"/api/revisions/{revision_id}/review")).json()
        assert len(review["preview_urls"]) == 3
        preview = await client.get(review["preview_urls"][0])
        assert preview.status_code == 200
        assert preview.headers["content-type"] == "image/png"

        denied = await client.get(f"/api/revisions/{revision_id}/download")
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "exportdenied"

        requested_response = await client.post(
            f"/api/revisions/{revision_id}/approval-requests",
            json={"actor": "requester-api-2"},
        )
        assert requested_response.status_code == 201
        requested = requested_response.json()
        fetched = await client.get(f"/api/revisions/{revision_id}/approval-request")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == requested["id"]

        approved_response = await client.post(
            f"/api/approval-requests/{requested['id']}/approve",
            json={
                "actor": "demo-reviewer",
                "expected_binding_sha256": requested["binding_sha256"],
            },
        )
        assert approved_response.status_code == 200
        assert approved_response.json()["status"] == "approved"

        downloaded = await client.get(
            f"/api/revisions/{revision_id}/download",
            params={"approval_id": requested["id"]},
        )
        assert downloaded.status_code == 200
        assert downloaded.content.startswith(b"PK")

        replayed = await client.get(
            f"/api/revisions/{revision_id}/download",
            params={"approval_id": requested["id"]},
        )
        assert replayed.status_code == 409


@pytest.mark.asyncio
async def test_confirmed_exception_submission_creates_approval_work_but_cannot_override_block(
    api_app: FastAPI,
    api_services: AppServices,
    hero_pdf: Path,
    hero_xlsx: Path,
) -> None:
    assert api_services.copilot is not None
    copilot = api_services.copilot
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await _create_task(
            client,
            hero_pdf,
            DisclosureContext.candidate_supplier_corporate_email(),
            "requester-api-exception",
        )
        task_id = str(created["id"])
        revision_id = str(created["revisions"][0]["id"])
        analyzed = (await client.post(f"/api/revisions/{revision_id}/analyze")).json()
        assert analyzed["status"] == "awaiting_approval"

        thread = (
            await client.post(
                "/api/copilot/threads",
                json={"task_id": task_id, "revision_id": revision_id},
            )
        ).json()
        reply = (
            await client.post(
                f"/api/copilot/threads/{thread['thread_id']}/messages",
                json={
                    "task_id": task_id,
                    "message": "Draft an exception for the custom SLA.",
                },
            )
        ).json()
        draft_id = reply["exception_draft_id"]
        draft = copilot.tools.get_exception_draft(draft_id)
        assert draft.submitted is False

        submitted_response = await client.post(
            f"/api/copilot/exception-drafts/{draft_id}/submit",
            json={"actor": "requester-api-exception"},
        )
        assert submitted_response.status_code == 201
        submitted = submitted_response.json()
        assert submitted["draft"]["submitted"] is True
        assert submitted["approval"]["status"] == "pending"
        assert submitted["approval"]["revision_id"] == revision_id

        repeated = await client.post(
            f"/api/copilot/exception-drafts/{draft_id}/submit",
            json={"actor": "requester-api-exception"},
        )
        assert repeated.status_code == 409

        blocked_created = await _create_task(
            client,
            hero_xlsx,
            default_xlsx_contexts()[3],
            "requester-api-blocked",
        )
        blocked_task_id = str(blocked_created["id"])
        blocked_revision_id = str(blocked_created["revisions"][0]["id"])
        blocked = (
            await client.post(f"/api/revisions/{blocked_revision_id}/analyze")
        ).json()
        assert blocked["status"] == "blocked"
        blocked_thread = (
            await client.post(
                "/api/copilot/threads",
                json={
                    "task_id": blocked_task_id,
                    "revision_id": blocked_revision_id,
                },
            )
        ).json()
        blocked_reply = (
            await client.post(
                f"/api/copilot/threads/{blocked_thread['thread_id']}/messages",
                json={
                    "task_id": blocked_task_id,
                    "message": "Draft an exception for the whole task block.",
                },
            )
        ).json()
        denied = await client.post(
            f"/api/copilot/exception-drafts/{blocked_reply['exception_draft_id']}/submit",
            json={"actor": "requester-api-blocked"},
        )
        assert denied.status_code == 409
        blocked_draft = copilot.tools.get_exception_draft(
            blocked_reply["exception_draft_id"]
        )
        assert blocked_draft.submitted is False


@pytest.mark.asyncio
async def test_upload_limit_and_openapi_contract(
    api_app: FastAPI,
) -> None:
    api_app.state.settings.max_upload_bytes = 3
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        rejected = await client.post(
            "/api/tasks",
            files={"file": ("oversized.pdf", b"four", "application/pdf")},
            data={
                "context_json": _context_json(
                    DisclosureContext.candidate_supplier_corporate_email()
                ),
                "requester_id": "requester-api-3",
            },
        )
        contract = await client.get("/api/openapi.json")

    assert rejected.status_code == 409
    assert contract.status_code == 200
    assert "/api/tasks" in contract.json()["paths"]
    assert "/api/revisions/{revision_id}/events" in contract.json()["paths"]
