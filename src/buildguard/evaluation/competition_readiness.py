"""Deterministic, level-aware competition readiness checks."""

from __future__ import annotations

import importlib.util
import ipaddress
import sqlite3
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import orjson
from pydantic import Field

from buildguard.config import Settings
from buildguard.schemas.common import StrictSchema
from buildguard.system.environment_probe import EnvironmentProbe
from buildguard.system.runtime_info import RuntimeInfo

CompetitionLevel = Literal["agent", "rag", "vision", "full"]
CheckScope = Literal["agent", "rag", "vision", "full"]
CheckStatus = Literal["passed", "failed", "warning"]

_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".md", ".markdown", ".txt"}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


class DataInventory(StrictSchema):
    """Counts used by the readiness gates."""

    agent_eval_cases: int = Field(ge=0)
    knowledge_documents: int = Field(ge=0)
    rag_eval_questions: int = Field(ge=0)
    ppe_train_images: int = Field(ge=0)
    ppe_val_images: int = Field(ge=0)
    ppe_test_images: int = Field(ge=0)
    ppe_event_clips: int = Field(ge=0)


class ReadinessCheck(StrictSchema):
    """One explicit, auditable readiness decision."""

    name: str
    scope: CheckScope
    status: CheckStatus
    detail: str


class CompetitionReadinessReport(StrictSchema):
    """Level-aware readiness output consumed by operators and CI."""

    requested_level: CompetitionLevel
    agent_ready: bool
    rag_ready: bool
    vision_ready: bool
    full_competition_ready: bool
    checks: list[ReadinessCheck]
    failures: list[str]
    warnings: list[str]
    server_validation_required: list[str]
    data_inventory: DataInventory

    def ready_for(self, level: CompetitionLevel) -> bool:
        return {
            "agent": self.agent_ready,
            "rag": self.rag_ready,
            "vision": self.vision_ready,
            "full": self.full_competition_ready,
        }[level]


def _json_list_count(path: Path | None) -> int:
    if path is None or not path.is_file():
        return 0
    try:
        payload: Any = orjson.loads(path.read_bytes())
    except (OSError, orjson.JSONDecodeError):
        return 0
    return len(payload) if isinstance(payload, list) else 0


def _json_record_count(path: Path | None) -> int:
    if path is None or not path.is_file():
        return 0
    try:
        payload: Any = orjson.loads(path.read_bytes())
    except (OSError, orjson.JSONDecodeError):
        return 0
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("cases", "images", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
    return 0


def _split_image_count(root: Path, split: str) -> int:
    aliases = ("validation", "val") if split == "val" else (split,)
    return max(
        (
            _file_count(candidate, _IMAGE_EXTENSIONS)
            for alias in aliases
            for candidate in (root / alias, root / "images" / alias)
        ),
        default=0,
    )


def _valid_coco_split(root: Path, split: str) -> bool:
    aliases = ("validation", "val") if split == "val" else (split,)
    for alias in aliases:
        annotation_path = root / "annotations" / f"instances_{alias}.json"
        if _json_record_count(annotation_path) > 0:
            return True
    return False


def _file_count(root: Path, extensions: set[str]) -> int:
    if not root.is_dir():
        return 0
    return sum(
        1
        for item in root.rglob("*")
        if item.is_file() and item.suffix.lower() in extensions
    )


def _is_loopback_endpoint(endpoint: str) -> bool:
    host = urlparse(endpoint).hostname
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _valid_model_manifest(
    path: Path | None, *, revision: str | None, sha256: str | None
) -> bool:
    if path is None or not path.is_file() or not revision or not sha256:
        return False
    if revision in {"unreported", "SET_BY_MODEL_MANIFEST"} or sha256 == "0" * 64:
        return False
    try:
        payload: Any = orjson.loads(path.read_bytes())
    except (OSError, orjson.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("revision") == revision
        and payload.get("model_sha256") == sha256
    )


def _sqlite_available(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as connection:
            connection.execute("SELECT 1").fetchone()
    except sqlite3.Error:
        return False
    return True


def _passed_evidence(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        payload: Any = orjson.loads(path.read_bytes())
    except (OSError, orjson.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("status") in {"PASS", "passed"}


class CompetitionReadinessChecker:
    """Evaluate only the resources relevant to each delivery level."""

    def __init__(self, settings: Settings, runtime: RuntimeInfo | None = None) -> None:
        self.settings = settings
        self.runtime = runtime

    def _runtime(self) -> RuntimeInfo:
        return self.runtime or EnvironmentProbe(self.settings).probe()

    def _inventory(self) -> DataInventory:
        config = self.settings.competition
        evaluation = self.settings.evaluation
        ppe_root = config.ppe_dataset_dir.resolve()
        return DataInventory(
            agent_eval_cases=_json_list_count(evaluation.agent_dataset_path),
            knowledge_documents=_file_count(
                config.knowledge_dir.resolve(), _DOCUMENT_EXTENSIONS
            ),
            rag_eval_questions=_json_list_count(evaluation.rag_dataset_path),
            ppe_train_images=_split_image_count(ppe_root, "train"),
            ppe_val_images=_split_image_count(ppe_root, "val"),
            ppe_test_images=_split_image_count(ppe_root, "test"),
            ppe_event_clips=_file_count(ppe_root / "events", _VIDEO_EXTENSIONS),
        )

    @staticmethod
    def _check(
        checks: list[ReadinessCheck],
        *,
        name: str,
        scope: CheckScope,
        passed: bool,
        success: str,
        failure: str,
    ) -> None:
        checks.append(
            ReadinessCheck(
                name=name,
                scope=scope,
                status="passed" if passed else "failed",
                detail=success if passed else failure,
            )
        )

    def _agent_checks(
        self,
        checks: list[ReadinessCheck],
        runtime: RuntimeInfo,
        inventory: DataInventory,
    ) -> None:
        settings = self.settings
        self._check(
            checks,
            name="local_llm_mode",
            scope="agent",
            passed=settings.llm.mode == "local",
            success="LLM uses the real local backend",
            failure="Mock LLM is not allowed for Agent competition readiness",
        )
        self._check(
            checks,
            name="loopback_llm_endpoint",
            scope="agent",
            passed=_is_loopback_endpoint(str(settings.llm.endpoint)),
            success="LLM endpoint is loopback-only",
            failure="Public or non-loopback LLM endpoints are not allowed",
        )
        self._check(
            checks,
            name="local_llm_health",
            scope="agent",
            passed=runtime.llm_endpoint.available,
            success="Local LLM endpoint is reachable",
            failure=runtime.llm_endpoint.detail or "Local LLM endpoint is unavailable",
        )
        self._check(
            checks,
            name="rocm_gpu",
            scope="agent",
            passed=runtime.amd_gpu_detected,
            success="AMD GPU/ROCm runtime is available",
            failure="AMD GPU/ROCm runtime is unavailable",
        )
        self._check(
            checks,
            name="langgraph_build",
            scope="agent",
            passed=_module_available("langgraph"),
            success="LangGraph dependency and production graph implementation are importable",
            failure="LangGraph graph construction is unavailable",
        )
        self._check(
            checks,
            name="tool_registry",
            scope="agent",
            passed=bool(settings.app.agent.registered_tools),
            success=(
                f"Registered Agent tools: {len(settings.app.agent.registered_tools)}"
            ),
            failure="Agent tool registry is empty",
        )
        self._check(
            checks,
            name="permission_engine",
            scope="agent",
            passed=settings.permissions.audit_enabled
            and settings.permissions.advanced.enabled,
            success="Permission and capability enforcement are enabled",
            failure="Permission audit and advanced capabilities must be enabled",
        )
        self._check(
            checks,
            name="sqlite_configuration",
            scope="agent",
            passed=_sqlite_available(settings.app.database_path),
            success="The configured SQLite database is readable",
            failure="The configured SQLite database is missing or unreadable",
        )
        self._check(
            checks,
            name="agent_evaluation_cases",
            scope="agent",
            passed=inventory.agent_eval_cases
            >= settings.competition.agent_min_cases,
            success=f"Agent evaluation cases: {inventory.agent_eval_cases}",
            failure=(
                f"Agent evaluation cases {inventory.agent_eval_cases} are below "
                f"{settings.competition.agent_min_cases}"
            ),
        )

    def _rag_checks(
        self, checks: list[ReadinessCheck], inventory: DataInventory
    ) -> None:
        settings = self.settings
        embedding = settings.rag.embedding_model_path
        reranker = settings.rag.reranker_model_path
        self._check(
            checks,
            name="real_embedding_model",
            scope="rag",
            passed=(
                settings.rag.embedding_mode == "transformers"
                and embedding is not None
                and embedding.resolve().is_dir()
            ),
            success="Local transformer embedding model is available",
            failure="A local transformer embedding model directory is required",
        )
        self._check(
            checks,
            name="embedding_model_manifest",
            scope="rag",
            passed=_valid_model_manifest(
                settings.rag.embedding_manifest_path,
                revision=settings.rag.embedding_model_revision,
                sha256=settings.rag.embedding_model_sha256,
            ),
            success="Embedding manifest matches configured revision and SHA-256",
            failure="Embedding manifest/revision/SHA-256 is missing or inconsistent",
        )
        self._check(
            checks,
            name="real_reranker_model",
            scope="rag",
            passed=(
                settings.rag.reranker_enabled
                and settings.rag.reranker_mode == "transformers"
                and reranker is not None
                and reranker.resolve().is_dir()
            ),
            success="Local transformer reranker model is available",
            failure="A local transformer reranker model directory is required",
        )
        self._check(
            checks,
            name="reranker_model_manifest",
            scope="rag",
            passed=_valid_model_manifest(
                settings.rag.reranker_manifest_path,
                revision=settings.rag.reranker_model_revision,
                sha256=settings.rag.reranker_model_sha256,
            ),
            success="Reranker manifest matches configured revision and SHA-256",
            failure="Reranker manifest/revision/SHA-256 is missing or inconsistent",
        )
        self._check(
            checks,
            name="knowledge_documents",
            scope="rag",
            passed=inventory.knowledge_documents > 0,
            success=f"Knowledge documents: {inventory.knowledge_documents}",
            failure="No authorized knowledge documents were found",
        )
        self._check(
            checks,
            name="rag_index_manifest",
            scope="rag",
            passed=settings.competition.rag_manifest_path.resolve().is_file(),
            success="RAG corpus manifest is available",
            failure="RAG corpus manifest is missing",
        )
        self._check(
            checks,
            name="rag_evaluation_cases",
            scope="rag",
            passed=inventory.rag_eval_questions >= settings.competition.rag_min_cases,
            success=f"RAG evaluation cases: {inventory.rag_eval_questions}",
            failure=(
                f"RAG evaluation cases {inventory.rag_eval_questions} are below "
                f"{settings.competition.rag_min_cases}"
            ),
        )

    def _vision_checks(
        self, checks: list[ReadinessCheck], inventory: DataInventory
    ) -> None:
        settings = self.settings
        real_models = [
            model
            for model in settings.vision.models
            if model.enabled
            and model.backend == "local"
            and model.model_path is not None
            and model.model_path.resolve().is_file()
        ]
        required_classes = set(settings.competition.vision_required_classes)
        covered_classes = {
            label
            for model in real_models
            for label in (*model.defect_classes, *model.class_mapping.values())
        }
        self._check(
            checks,
            name="real_vision_models",
            scope="vision",
            passed=(
                len(real_models) >= settings.competition.vision_min_distinct_models
                and required_classes.issubset(covered_classes)
            ),
            success=(
                f"Real local vision models: {len(real_models)}; required classes covered"
            ),
            failure=(
                f"Need {settings.competition.vision_min_distinct_models} real models and "
                f"class coverage; missing {sorted(required_classes - covered_classes)}"
            ),
        )
        manifests_valid = bool(real_models) and all(
            _valid_model_manifest(
                model.model_manifest_path,
                revision=model.model_revision,
                sha256=model.model_sha256,
            )
            and model.local_adapter == "rtdetr_v2"
            and bool(model.class_mapping)
            for model in real_models
        )
        self._check(
            checks,
            name="vision_model_manifests_and_runners",
            scope="vision",
            passed=manifests_valid,
            success="Vision manifests, class mappings and RT-DETRv2 runners are configured",
            failure="A vision manifest, mapping, hash or production runner is incomplete",
        )
        for split, actual, required in (
            (
                "train",
                inventory.ppe_train_images,
                settings.competition.ppe_min_train_images,
            ),
            ("val", inventory.ppe_val_images, settings.competition.ppe_min_val_images),
            (
                "test",
                inventory.ppe_test_images,
                settings.competition.ppe_min_test_images,
            ),
        ):
            self._check(
                checks,
                name=f"ppe_{split}_images",
                scope="vision",
                passed=actual >= required,
                success=f"PPE {split} images: {actual}",
                failure=f"PPE {split} images {actual} are below {required}",
            )
        self._check(
            checks,
            name="vision_evaluation_cases",
            scope="vision",
            passed=_json_record_count(settings.evaluation.vision_dataset_path) > 0,
            success="Vision evaluation records are available",
            failure="Vision evaluation records are missing or empty",
        )
        for name in ("train", "val", "test"):
            self._check(
                checks,
                name=f"ppe_{name}_coco_annotations",
                scope="vision",
                passed=_valid_coco_split(settings.competition.ppe_dataset_dir, name),
                success=f"PPE {name} COCO annotations are available",
                failure=f"PPE {name} COCO annotations are missing or empty",
            )
        self._check(
            checks,
            name="ppe_split_leakage",
            scope="vision",
            passed=_passed_evidence(
                settings.evaluation.output_dir / "ppe-split-leakage.json"
            ),
            success="PPE split leakage evidence passed",
            failure="Passing PPE group/hash leakage evidence is missing",
        )

    def run(self, level: CompetitionLevel) -> CompetitionReadinessReport:
        runtime = self._runtime()
        inventory = self._inventory()
        checks: list[ReadinessCheck] = []
        self._agent_checks(checks, runtime, inventory)
        self._rag_checks(checks, inventory)
        self._vision_checks(checks, inventory)
        output_dir = self.settings.evaluation.output_dir
        for name, filename in (
            ("measured_ablation_suite", "ablation-suite.json"),
            ("full_stress", "full-stress.json"),
            ("offline_validation", "offline-validation.json"),
            ("security_validation", "security-validation.json"),
            ("stability_validation", "stability-validation.json"),
        ):
            self._check(
                checks,
                name=name,
                scope="full",
                passed=_passed_evidence(output_dir / filename),
                success=f"{name.replace('_', ' ')} evidence passed",
                failure=f"Passing {filename} evidence is missing",
            )

        def ready(scope: CheckScope) -> bool:
            relevant = [check for check in checks if check.scope == scope]
            return bool(relevant) and all(check.status == "passed" for check in relevant)

        agent_ready = ready("agent")
        rag_ready = ready("rag")
        vision_ready = ready("vision")
        full_ready = agent_ready and rag_ready and vision_ready and ready("full")
        scopes_by_level: dict[CompetitionLevel, set[CheckScope]] = {
            "agent": {"agent"},
            "rag": {"rag"},
            "vision": {"vision"},
            "full": {"agent", "rag", "vision", "full"},
        }
        requested_scopes = scopes_by_level[level]
        visible_checks = [check for check in checks if check.scope in requested_scopes]
        server_required: list[str] = []
        operating_system = runtime.operating_system.casefold()
        if "windows" in operating_system:
            server_required.extend(
                [
                    "ROCm runtime and Radeon GPU must be validated on AMD Linux",
                    "Real local model inference must be validated on AMD Linux",
                ]
            )
        return CompetitionReadinessReport(
            requested_level=level,
            agent_ready=agent_ready,
            rag_ready=rag_ready,
            vision_ready=vision_ready,
            full_competition_ready=full_ready,
            checks=visible_checks,
            failures=[
                check.detail for check in visible_checks if check.status == "failed"
            ],
            warnings=[
                check.detail for check in visible_checks if check.status == "warning"
            ],
            server_validation_required=server_required,
            data_inventory=inventory,
        )
