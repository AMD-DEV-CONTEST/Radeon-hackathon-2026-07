from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from collections.abc import Iterable
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

from shared_contracts import (
    ArtifactRef,
    CloudDataType,
    CloudExecutionPolicySnapshot,
    FallbackChange,
    FallbackPolicySnapshot,
    FactoryProjectSnapshot,
    GenerationMode,
    ImportPlan,
    KnowledgePack,
    LearningAnalysisRequest,
    LearningSourceKind,
    LearningSourceRequest,
    ReferenceDuty,
    TimelineEvidenceBundle,
    VideoResolution,
)


class EvidenceGateway(Protocol):
    def get_bundle(self, bundle_id: UUID) -> TimelineEvidenceBundle | None: ...

    def get_job(self, job_id: UUID) -> dict | None: ...

    def list_jobs(self, *, limit: int = 50) -> list[dict]: ...

    def research_workspace(self, job_id: UUID) -> dict | None: ...

    def learning_overview(self) -> dict: ...

    def submit_source(
        self,
        source: LearningSourceRequest,
        *,
        idempotency_key: str,
    ) -> dict: ...

    def submit_analysis(
        self,
        request: LearningAnalysisRequest,
        *,
        idempotency_key: str,
    ) -> dict: ...

    def submit_media(
        self,
        *,
        sha256: str,
        size_bytes: int,
        mime_type: str,
        idempotency_key: str,
    ) -> dict: ...


@dataclass(frozen=True, slots=True)
class FactoryImportReceipt:
    project_key: str
    revision_id: UUID
    revision_sha256: str
    root_locator: str
    created: bool


@dataclass(frozen=True, slots=True)
class GenerationCreateCommand:
    mode: GenerationMode
    clip_id: UUID
    model_id: str
    duration_seconds: float
    resolution: VideoResolution
    audio_intent: str
    first_image: ArtifactRef | None = None
    last_image: ArtifactRef | None = None
    reference_duties: tuple[ReferenceDuty, ...] = ()
    reference_exclusions: tuple[str, ...] = ()
    initial_seed_slot: str = "default"
    fallback_allowed_changes: tuple[FallbackChange, ...] = ()
    fallback_model_ids: tuple[str, ...] = ()
    fallback_resolutions: tuple[VideoResolution, ...] = ()
    cloud_provider_allowlist: tuple[str, ...] = ()
    cloud_allowed_data_types: tuple[CloudDataType, ...] = ()
    cloud_provider_retention_notice: str | None = None
    cloud_consent: bool = False


@dataclass(frozen=True, slots=True)
class VisualVerdictCommand:
    verdict: str
    expected_canon_version: int
    expected_state_version: int
    changed_variable: str | None = None
    changed_value: Any = None
    reason: str | None = None


class LegacyFactoryWriteFenced(RuntimeError):
    """A legacy Factory mutation was rejected by unified authority."""


class LegacyFactoryRetired(LegacyFactoryWriteFenced):
    """The legacy Factory write surface has been permanently retired."""


class FactoryGateway(Protocol):
    def snapshot(
        self,
        project_key: str,
        base_revision_id: UUID | None = None,
    ) -> FactoryProjectSnapshot: ...

    def create_import_revision(
        self,
        *,
        project_key: str,
        pack: KnowledgePack,
        plan: ImportPlan,
        base_revision_id: UUID | None = None,
    ) -> FactoryImportReceipt: ...

    def run_from_import(self, receipt: FactoryImportReceipt) -> dict: ...

    def list_generation_projects(self) -> tuple[dict, ...]: ...

    def generation_state(self, project_key: str) -> dict: ...

    def model_registry(self) -> tuple[dict, ...]: ...

    def list_artifacts(
        self,
        project_key: str,
        *,
        mime_prefix: str | None = None,
    ) -> tuple[dict, ...]: ...

    def import_image(
        self,
        project_key: str,
        *,
        content: bytes,
        role: str,
    ) -> dict: ...

    def read_artifact(
        self,
        project_key: str,
        artifact_id: UUID,
    ) -> tuple[bytes, str]: ...

    def create_generation_run(
        self,
        project_key: str,
        *,
        command: GenerationCreateCommand,
        actor_id: str,
        idempotency_key: str,
        expected_state_version: int,
    ) -> dict: ...

    def apply_visual_verdict(
        self,
        project_key: str,
        visual_take_id: UUID,
        *,
        command: VisualVerdictCommand,
        actor_id: str,
        idempotency_key: str,
    ) -> dict: ...

    def acknowledge_generation_outbox(
        self,
        project_key: str,
        sequence: int,
        *,
        expected_state_version: int,
    ) -> dict: ...


class EmptyEvidenceGateway:
    def get_bundle(self, bundle_id: UUID) -> None:
        return None

    def get_job(self, job_id: UUID) -> None:
        return None

    def list_jobs(self, *, limit: int = 50) -> list[dict]:
        return []

    def research_workspace(self, job_id: UUID) -> None:
        return None

    def learning_overview(self) -> dict:
        return {
            "source_counts": {},
            "progress": {
                "frame_sampling": 0,
                "audio_transcription": 0,
                "timeline_alignment": 0,
            },
            "active_job_id": None,
            "latest_evidence": None,
            "latest_analysis": None,
        }

    def submit_source(
        self,
        source: LearningSourceRequest,
        *,
        idempotency_key: str,
    ) -> dict:
        raise RuntimeError("Analysis service is unavailable")

    def submit_analysis(
        self,
        request: LearningAnalysisRequest,
        *,
        idempotency_key: str,
    ) -> dict:
        raise RuntimeError("Analysis service is unavailable")

    def submit_media(self, **_kwargs) -> dict:
        raise RuntimeError("Analysis service is unavailable")


class HttpEvidenceGateway:
    """Read path-free shared evidence contracts from the Analysis API."""

    def __init__(
        self,
        base_url: str,
        *,
        service_token: str,
        allowed_hosts: Iterable[str] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        parsed = urlsplit(base_url)
        accepted_hosts = frozenset(
            allowed_hosts or {"127.0.0.1", "localhost", "::1"}
        )
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in accepted_hosts
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Analysis evidence gateway host is not allowed")
        if not service_token:
            raise ValueError("Analysis service token is required")
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds

    def get_bundle(self, bundle_id: UUID) -> TimelineEvidenceBundle | None:
        payload = self._read(f"/v1/evidence/{bundle_id}", missing_ok=True)
        if payload is None:
            return None
        return TimelineEvidenceBundle.model_validate(payload)

    def get_job(self, job_id: UUID) -> dict | None:
        payload = self._read(f"/v1/jobs/{job_id}", missing_ok=True)
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise RuntimeError("Analysis learning job response is invalid")
        return payload

    def list_jobs(self, *, limit: int = 50) -> list[dict]:
        """Read a bounded, payload-free history of Analysis research jobs."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("Analysis research job history limit must be between 1 and 50")
        payload = self._read(
            f"/v1/jobs?scope=research&offset=0&limit={limit}",
            missing_ok=False,
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise RuntimeError("Analysis research job history response is invalid")
        return [item for item in payload["items"] if isinstance(item, dict)]

    def research_workspace(self, job_id: UUID) -> dict | None:
        payload = self._read(
            f"/v1/learning/jobs/{job_id}/workspace",
            missing_ok=True,
        )
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise RuntimeError("Analysis research workspace response is invalid")
        if payload.get("evidence") is not None:
            payload = dict(payload)
            payload["evidence"] = TimelineEvidenceBundle.model_validate(
                payload["evidence"]
            ).model_dump(mode="json")
        raw_media_items = payload.get("media_items")
        if raw_media_items is not None:
            if not isinstance(raw_media_items, list) or len(raw_media_items) > 200:
                raise RuntimeError("Analysis research workspace media items are invalid")
            payload = dict(payload)
            media_items: list[dict] = []
            for raw_item in raw_media_items:
                if not isinstance(raw_item, dict):
                    raise RuntimeError(
                        "Analysis research workspace media item is invalid"
                    )
                item = dict(raw_item)
                if item.get("evidence") is not None:
                    item["evidence"] = TimelineEvidenceBundle.model_validate(
                        item["evidence"]
                    ).model_dump(mode="json")
                media_items.append(item)
            payload["media_items"] = media_items
        return payload

    def learning_overview(self) -> dict:
        payload = self._read("/v1/learning/overview", missing_ok=False)
        if not isinstance(payload, dict):
            raise RuntimeError("Analysis learning overview is invalid")
        if payload.get("latest_evidence") is not None:
            payload = dict(payload)
            payload["latest_evidence"] = TimelineEvidenceBundle.model_validate(
                payload["latest_evidence"]
            ).model_dump(mode="json")
        return payload

    def submit_source(
        self,
        source: LearningSourceRequest,
        *,
        idempotency_key: str,
    ) -> dict:
        if source.kind is LearningSourceKind.PROFILE:
            path = "/v1/profile-syncs"
            payload = {
                "sec_user_id": source.sec_user_id,
                "page_size": 20,
                "collect_comments": source.collect_comments,
            }
        elif source.kind is LearningSourceKind.LINK:
            path = "/v1/link-imports"
            payload = {
                "urls": list(source.urls),
                "collect_comments": source.collect_comments,
            }
        else:
            path = "/v1/local-scans"
            payload = {
                "root_id": source.root_id,
                "relative_path": source.relative_path,
            }
        return self._write(path, payload, idempotency_key=idempotency_key)

    def submit_analysis(
        self,
        request: LearningAnalysisRequest,
        *,
        idempotency_key: str,
    ) -> dict:
        return self._write(
            "/v1/analysis-jobs",
            request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
        )

    def submit_media(
        self,
        *,
        sha256: str,
        size_bytes: int,
        mime_type: str,
        idempotency_key: str,
    ) -> dict:
        return self._write(
            "/v1/hub-media-imports",
            {
                "sha256": sha256,
                "size_bytes": size_bytes,
                "mime_type": mime_type,
            },
            idempotency_key=idempotency_key,
        )

    def _read(self, path: str, *, missing_ok: bool):
        request = Request(
            f"{self._base_url}{path}",
            headers={
                "Accept": "application/json",
                "X-Internal-Service-Token": self._service_token,
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.load(response)
        except HTTPError as exc:
            if missing_ok and exc.code == 404:
                return None
            raise RuntimeError(
                "Analysis evidence service rejected the request"
            ) from None
        except (OSError, URLError, ValueError):
            raise RuntimeError(
                "Analysis evidence service is unavailable"
            ) from None
        return payload

    def _write(
        self,
        path: str,
        payload: dict,
        *,
        idempotency_key: str,
    ) -> dict:
        downstream_idempotency_key = "hub-" + hashlib.sha256(
            f"{path}\0{idempotency_key}".encode("utf-8")
        ).hexdigest()
        request = Request(
            f"{self._base_url}{path}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Idempotency-Key": downstream_idempotency_key,
                "X-Internal-Service-Token": self._service_token,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                value = json.load(response)
        except HTTPError as exc:
            if exc.code in {404, 409, 422}:
                raise RuntimeError(
                    f"Analysis request was rejected ({exc.code})"
                ) from None
            raise RuntimeError(
                "Analysis service rejected the request"
            ) from None
        except (OSError, URLError, ValueError):
            raise RuntimeError(
                "Analysis service is unavailable"
            ) from None
        if not isinstance(value, dict) or not isinstance(
            value.get("job_id"), str
        ):
            raise RuntimeError("Analysis service returned an invalid job")
        return value
