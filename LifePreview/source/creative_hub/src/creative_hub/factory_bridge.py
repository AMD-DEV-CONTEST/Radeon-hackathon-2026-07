from __future__ import annotations

from pathlib import Path
import json
from datetime import datetime, timezone
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from shared_contracts import (
    CloudExecutionPolicySnapshot,
    FirstLastFrameRequest,
    ImageToVideoRequest,
    TextToVideoRequest,
    FactoryProjectSnapshot,
    FallbackPolicySnapshot,
    GenerationMode,
    ImportPlan,
    KnowledgePack,
    stable_json_sha256,
)

from .gateways import (
    FactoryImportReceipt,
    GenerationCreateCommand,
    LegacyFactoryRetired,
    LegacyFactoryWriteFenced,
    VisualVerdictCommand,
)


_RUN_NAMESPACE = UUID("e0416c60-a5bd-59df-adfd-40362ed92a4e")
_PROMPT_NAMESPACE = UUID("45c46dc7-70d6-59c8-bd04-a436ec5dd1a8")
_CLOUD_NAMESPACE = UUID("fbf76b16-42b3-529a-bf9b-770580797a85")
_FENCED_PHASES = frozenset({"ACTIVATED", "FORWARD_FIX", "RETIRED"})


class LocalFactoryGateway:
    """Composition adapter for the local monorepo factory service boundary.

    The browser never receives a filesystem path.  Deployments may replace this
    adapter with an HTTP transport without changing the Hub API.
    """

    def __init__(
        self,
        projects_root: str | Path,
        *,
        config_dir: str | Path,
        cutover_sessions: sessionmaker[Session] | None = None,
    ):
        self._projects_root = Path(projects_root)
        self._config_dir = Path(config_dir)
        self._cutover_sessions = cutover_sessions

    def bind_cutover_sessions(
        self,
        sessions: sessionmaker[Session],
    ) -> None:
        if (
            self._cutover_sessions is not None
            and self._cutover_sessions is not sessions
        ):
            raise RuntimeError(
                "factory gateway cutover authority is already bound"
            )
        self._cutover_sessions = sessions

    def legacy_authority_phase(self) -> str | None:
        """Return the effective terminal/active cutover phase, if any."""

        if self._cutover_sessions is None:
            return None
        from .cutover_models import CutoverEpochRecord

        with self._cutover_sessions() as session:
            retired = session.scalar(
                select(CutoverEpochRecord.phase)
                .where(CutoverEpochRecord.phase == "RETIRED")
                .limit(1)
            )
            if retired is not None:
                return retired
            return session.scalar(
                select(CutoverEpochRecord.phase)
                .where(CutoverEpochRecord.phase.in_(_FENCED_PHASES))
                .order_by(
                    CutoverEpochRecord.updated_at.desc(),
                    CutoverEpochRecord.id.desc(),
                )
                .limit(1)
            )

    def assert_legacy_write_allowed(self, operation: str) -> None:
        phase = self.legacy_authority_phase()
        if phase == "RETIRED":
            raise LegacyFactoryRetired(
                f"legacy Factory write is retired: {operation}"
            )
        if phase in _FENCED_PHASES:
            raise LegacyFactoryWriteFenced(
                f"legacy Factory write is fenced: {operation}"
            )

    def _state_store(self, project_key: str):
        from drama.v3.state_store import FactoryStateStore

        return FactoryStateStore(
            self._project_root(project_key),
            write_authority_guard=self.assert_legacy_write_allowed,
        )

    def _store(self):
        from drama.imports import FactoryImportStore

        return FactoryImportStore(self._projects_root)

    def _project_root(self, project_key: str) -> Path:
        from drama.runtime import safe_project_root

        return safe_project_root(self._projects_root, project_key)

    def snapshot(
        self,
        project_key: str,
        base_revision_id: UUID | None = None,
    ) -> FactoryProjectSnapshot:
        return self._store().snapshot(project_key, base_revision_id)

    def create_import_revision(
        self,
        *,
        project_key: str,
        pack: KnowledgePack,
        plan: ImportPlan,
        base_revision_id: UUID | None = None,
    ) -> FactoryImportReceipt:
        self.assert_legacy_write_allowed("factory.import-revision.create")
        revision = self._store().create_revision(
            project_key,
            pack,
            plan,
            base_revision_id=base_revision_id,
        )
        return FactoryImportReceipt(
            project_key=revision.project_key,
            revision_id=revision.revision_id,
            revision_sha256=revision.revision_sha256,
            root_locator=str(revision.root),
            created=revision.created,
        )

    def run_from_import(self, receipt: FactoryImportReceipt) -> dict:
        from drama.v3.import_bootstrap import bootstrap_import_revision

        self.assert_legacy_write_allowed("factory.import-revision.bootstrap")
        _revision, state = bootstrap_import_revision(
            receipt.root_locator,
            self._project_root(receipt.project_key),
        )
        return {
            "project_key": receipt.project_key,
            "revision_id": str(receipt.revision_id),
            "project_id": str(state.project_revision.project_id),
            "state_version": state.state_version,
            "state_sha256": state.state_sha256,
            "scene_count": len(state.scenes),
            "clip_count": len(state.clips),
            "runtime": "factory.project-state.v3",
        }

    def list_generation_projects(self) -> tuple[dict, ...]:
        from drama.v3.state_store import FactoryStateStore

        projects: list[dict] = []
        if not self._projects_root.exists():
            return ()
        for child in sorted(self._projects_root.iterdir(), key=lambda item: item.name):
            if not child.is_dir() or not (child / "factory_v3" / "state.json").is_file():
                continue
            state = FactoryStateStore(
                child,
                write_authority_guard=self.assert_legacy_write_allowed,
            ).load()
            projects.append(
                {
                    "project_key": child.name,
                    "project_id": str(state.project_revision.project_id),
                    "revision_id": str(state.project_revision.revision_id),
                    "state_version": state.state_version,
                    "state_sha256": state.state_sha256,
                    "scene_count": len(state.scenes),
                    "clip_count": len(state.clips),
                    "run_count": len(state.runs),
                    "updated_at": state.updated_at.isoformat(),
                }
            )
        return tuple(projects)

    def generation_state(self, project_key: str) -> dict:
        return self._state_store(project_key).load().model_dump(mode="json")

    def model_registry(self) -> tuple[dict, ...]:
        from drama.v3.model_registry import configured_wan_registry

        return tuple(
            {
                "entry": model.entry.model_dump(mode="json"),
                "capabilities": [
                    capability.model_dump(mode="json")
                    for capability in model.capabilities
                ],
            }
            for model in configured_wan_registry().list_models()
        )

    def list_artifacts(
        self,
        project_key: str,
        *,
        mime_prefix: str | None = None,
    ) -> tuple[dict, ...]:
        from drama.v3.artifact_catalog import FactoryArtifactCatalog

        snapshot = FactoryArtifactCatalog(
            self._project_root(project_key)
        ).load()
        return tuple(
            {
                "artifact": item.artifact.model_dump(mode="json"),
                "role": item.role,
                "created_at": item.created_at.isoformat(),
            }
            for item in snapshot.artifacts
            if (
                mime_prefix is None
                or item.artifact.mime.startswith(mime_prefix)
            )
        )

    def import_image(
        self,
        project_key: str,
        *,
        content: bytes,
        role: str,
    ) -> dict:
        from drama.v3.artifact_catalog import FactoryArtifactCatalog

        self.assert_legacy_write_allowed("factory.artifact.import")
        artifact = FactoryArtifactCatalog(
            self._project_root(project_key)
        ).import_image_bytes(
            content,
            role=role,
        )
        return artifact.model_dump(mode="json")

    def read_artifact(
        self,
        project_key: str,
        artifact_id: UUID,
    ) -> tuple[bytes, str]:
        from drama.v3.artifact_catalog import FactoryArtifactCatalog

        catalog = FactoryArtifactCatalog(self._project_root(project_key))
        locator = next(
            (
                item
                for item in catalog.load().artifacts
                if item.artifact.artifact_id == artifact_id
            ),
            None,
        )
        if locator is None:
            raise RuntimeError("factory artifact is unavailable")
        path = catalog.resolve(locator.artifact)
        return path.read_bytes(), locator.artifact.mime

    @staticmethod
    def _hashed_contract(model, payload: dict):
        identity = model.model_construct(
            snapshot_sha256="0" * 64,
            **payload,
        ).model_dump(mode="json", exclude={"snapshot_sha256"})
        return model(
            **identity,
            snapshot_sha256=stable_json_sha256(identity),
        )

    @staticmethod
    def _cloud_policy(
        *,
        project_id: UUID,
        run_id: UUID,
        actor_id: str,
        provider_allowlist: tuple[str, ...],
        allowed_data_types,
        provider_retention_notice: str | None,
        consent: bool,
        created_at: datetime,
    ) -> CloudExecutionPolicySnapshot:
        if allowed_data_types and not consent:
            raise RuntimeError(
                "cloud data authorization requires explicit consent"
            )
        policy_identity = {
            "providers": provider_allowlist,
            "data_types": [
                item.value for item in allowed_data_types
            ],
            "retention": provider_retention_notice,
            "consent": consent,
        }
        policy_digest = stable_json_sha256(policy_identity)
        payload = {
            "snapshot_id": uuid5(
                _CLOUD_NAMESPACE,
                f"{run_id}:{policy_digest}",
            ),
            "project_id": project_id,
            "run_id": run_id,
            "policy_version": 1,
            "provider_allowlist": provider_allowlist,
            "allowed_data_types": allowed_data_types,
            "provider_retention_notice": provider_retention_notice,
            "consented_at": created_at if consent else None,
            "created_by_actor": actor_id,
            "created_at": created_at,
        }
        return LocalFactoryGateway._hashed_contract(
            CloudExecutionPolicySnapshot,
            payload,
        )

    @staticmethod
    def _write_prompt_snapshot(store, compiled) -> None:
        from drama.runtime import atomic_write_json

        store.assert_write_allowed("factory.prompt-snapshot.write")
        prompt_path = store.root / "prompts" / (
            f"{compiled.prompt_snapshot_id}.json"
        )
        payload = compiled.model_dump(mode="json")
        if prompt_path.exists():
            try:
                existing = json.loads(
                    prompt_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                raise RuntimeError("prompt snapshot is unreadable") from None
            if existing != payload:
                raise RuntimeError("prompt snapshot identity conflict")
            return
        atomic_write_json(prompt_path, payload)

    def create_generation_run(
        self,
        project_key: str,
        *,
        command: GenerationCreateCommand,
        actor_id: str,
        idempotency_key: str,
        expected_state_version: int,
    ) -> dict:
        from drama.v3.model_registry import configured_wan_registry
        from drama.v3.prompt_compiler import WanPromptCompiler
        from drama.seeding import derive_initial_seed

        store = self._state_store(project_key)
        store.assert_write_allowed("factory.generation.create")
        state = store.load()
        clip = next(
            (item for item in state.clips if item.clip_id == command.clip_id),
            None,
        )
        if clip is None:
            raise RuntimeError("factory clip is unavailable")
        registry = configured_wan_registry()
        capability = registry.capability(
            model_id=command.model_id,
            mode=command.mode,
        )
        registered = next(
            model
            for model in registry.list_models()
            if model.entry.model_id == command.model_id
        )
        if (
            registered.entry.install_status.value != "installed"
            or registered.entry.verification_status.value != "load_verified"
            or not capability.verified
        ):
            raise RuntimeError(
                "requested local model is not installed and load-verified"
            )
        if command.duration_seconds not in capability.supported_durations_seconds:
            raise RuntimeError("model does not support requested duration")
        if command.resolution not in capability.supported_resolutions:
            raise RuntimeError("model does not support requested resolution")
        if command.mode is GenerationMode.T2V and (
            command.first_image is not None
            or command.last_image is not None
        ):
            raise RuntimeError("T2V does not accept endpoint images")
        if command.mode is GenerationMode.I2V and (
            command.first_image is None
            or command.last_image is not None
        ):
            raise RuntimeError("I2V requires exactly one first image")
        if command.mode is GenerationMode.FIRST_LAST_FRAME and (
            command.first_image is None
            or command.last_image is None
        ):
            raise RuntimeError("first/last-frame generation requires both images")
        run_id = uuid5(
            _RUN_NAMESPACE,
            (
                f"{state.project_revision.project_id}:"
                f"{state.project_revision.revision_id}:"
                f"{idempotency_key}"
            ),
        )
        prompt_snapshot_id = uuid5(
            _PROMPT_NAMESPACE,
            f"{run_id}:1",
        )
        fallback_snapshot_id = uuid5(
            _RUN_NAMESPACE,
            f"{run_id}:fallback-policy",
        )
        created_at = datetime.now(timezone.utc)
        fallback_policy = self._hashed_contract(
            FallbackPolicySnapshot,
            {
                "snapshot_id": fallback_snapshot_id,
                "policy_version": 1,
                "default_block": True,
                "allowed_changes": command.fallback_allowed_changes,
                "fallback_model_ids": command.fallback_model_ids,
                "fallback_resolutions": command.fallback_resolutions,
                "created_by_actor": actor_id,
                "created_at": created_at,
            },
        )
        cloud_policy = self._cloud_policy(
            project_id=state.project_revision.project_id,
            run_id=run_id,
            actor_id=actor_id,
            provider_allowlist=command.cloud_provider_allowlist,
            allowed_data_types=command.cloud_allowed_data_types,
            provider_retention_notice=(
                command.cloud_provider_retention_notice
            ),
            consent=command.cloud_consent,
            created_at=created_at,
        )
        seed = derive_initial_seed(
            project_revision_id=str(
                state.project_revision.revision_id
            ),
            clip_id=str(clip.clip_id),
            generation_mode=command.mode.value,
            model_id=command.model_id,
            initial_seed_slot=command.initial_seed_slot,
        )
        request_values = {
            "project_revision_id": state.project_revision.revision_id,
            "scene_id": clip.scene_id,
            "clip_id": clip.clip_id,
            "run_id": run_id,
            "prompt_snapshot_id": prompt_snapshot_id,
            "prompt_compiler_version": "wan-prompt-compiler.v1",
            "resolved_seed": seed.resolved_seed,
            "seed_derivation_version": seed.seed_derivation_version,
            "seed_input_hash": seed.seed_input_hash,
            "attempt_index": 0,
            "duration_seconds": command.duration_seconds,
            "aspect_ratio": clip.contract.aspect_ratio,
            "resolution": command.resolution,
            "audio_intent": command.audio_intent,
            "reference_duties": command.reference_duties,
            "reference_exclusions": command.reference_exclusions,
            "model_id": command.model_id,
            "capability_snapshot_id": capability.capability_id,
            "fallback_policy_snapshot_id": fallback_snapshot_id,
            "idempotency_key": idempotency_key,
        }
        if command.mode is GenerationMode.T2V:
            request = TextToVideoRequest(**request_values)
        elif command.mode is GenerationMode.I2V:
            request = ImageToVideoRequest(
                **request_values,
                first_image=command.first_image,
            )
        else:
            request = FirstLastFrameRequest(
                **request_values,
                first_image=command.first_image,
                last_image=command.last_image,
            )
        compiled = WanPromptCompiler().compile(
            clip=clip,
            request=request,
            capability=capability,
        )
        self._write_prompt_snapshot(store, compiled)
        state = store.create_run(
            request=request,
            fallback_policy=fallback_policy,
            cloud_policy=cloud_policy,
            expected_state_version=expected_state_version,
        )
        return {
            "state": state.model_dump(mode="json"),
            "compiled_prompt": compiled.model_dump(mode="json"),
        }

    def apply_visual_verdict(
        self,
        project_key: str,
        visual_take_id: UUID,
        *,
        command: VisualVerdictCommand,
        actor_id: str,
        idempotency_key: str,
    ) -> dict:
        from drama.seeding import derive_reroll_seed
        from drama.v3.domain import HumanVerdict
        from drama.v3.model_registry import configured_wan_registry
        from drama.v3.prompt_compiler import WanPromptCompiler

        store = self._state_store(project_key)
        store.assert_write_allowed("factory.visual-verdict.apply")
        state = store.load()
        try:
            verdict = HumanVerdict(command.verdict)
        except ValueError:
            raise RuntimeError("visual verdict is invalid") from None
        derived_request = None
        fallback_policy = None
        cloud_policy = None
        prompt_version = None
        if verdict in {
            HumanVerdict.EDIT,
            HumanVerdict.REROLL,
            HumanVerdict.REWRITE,
        }:
            take = next(
                (
                    item
                    for item in state.visual_takes
                    if item.visual_take_id == visual_take_id
                ),
                None,
            )
            if take is None:
                raise RuntimeError("visual take is unavailable")
            parent = next(
                item for item in state.runs if item.run_id == take.run_id
            )
            child_run_id = uuid5(
                _RUN_NAMESPACE,
                f"{parent.run_id}:{idempotency_key}",
            )
            changes = {
                "run_id": child_run_id,
                "idempotency_key": f"{idempotency_key}:run",
                "parent_run_id": parent.run_id,
                "prompt_snapshot_id": uuid5(
                    _PROMPT_NAMESPACE,
                    (
                        f"{child_run_id}:"
                        f"{parent.prompt_version + (1 if verdict is HumanVerdict.REWRITE else 0)}"
                    ),
                ),
            }
            prompt_version = parent.prompt_version
            if verdict is HumanVerdict.REROLL:
                seed = derive_reroll_seed(
                    parent_resolved_seed=parent.request.resolved_seed,
                    reroll_index=parent.reroll_index + 1,
                )
                changes.update(
                    {
                        "resolved_seed": seed.resolved_seed,
                        "seed_derivation_version": seed.seed_derivation_version,
                        "seed_input_hash": seed.seed_input_hash,
                        "attempt_index": parent.attempt_index + 1,
                    }
                )
            elif verdict is HumanVerdict.REWRITE:
                prompt_version += 1
            else:
                if command.changed_variable is None:
                    raise RuntimeError("edit requires one changed variable")
                if command.changed_variable == "duration_seconds":
                    changes["duration_seconds"] = float(command.changed_value)
                elif command.changed_variable == "audio_intent":
                    changes["audio_intent"] = str(command.changed_value)
                elif command.changed_variable == "reference_exclusions":
                    if not isinstance(command.changed_value, list):
                        raise RuntimeError(
                            "reference exclusions must be a list"
                        )
                    changes["reference_exclusions"] = tuple(
                        str(value) for value in command.changed_value
                    )
                elif command.changed_variable == "resolution":
                    from shared_contracts import VideoResolution

                    changes["resolution"] = VideoResolution.model_validate(
                        command.changed_value
                    )
                elif command.changed_variable == "seed":
                    seed = derive_reroll_seed(
                        parent_resolved_seed=parent.request.resolved_seed,
                        reroll_index=parent.reroll_index + 1,
                    )
                    changes.update(
                        {
                            "resolved_seed": seed.resolved_seed,
                            "seed_derivation_version": seed.seed_derivation_version,
                            "seed_input_hash": seed.seed_input_hash,
                        }
                    )
                else:
                    raise RuntimeError("edit variable is unsupported")
            derived_request = parent.request.model_copy(update=changes)
            fallback_policy = parent.fallback_policy
            cloud_policy = self._cloud_policy(
                project_id=state.project_revision.project_id,
                run_id=child_run_id,
                actor_id=actor_id,
                provider_allowlist=parent.cloud_policy.provider_allowlist,
                allowed_data_types=parent.cloud_policy.allowed_data_types,
                provider_retention_notice=(
                    parent.cloud_policy.provider_retention_notice
                ),
                consent=bool(
                    parent.cloud_policy.allowed_data_types
                ),
                created_at=datetime.now(timezone.utc),
            )
            clip = next(
                item
                for item in state.clips
                if item.clip_id == derived_request.clip_id
            )
            capability = configured_wan_registry().capability(
                model_id=derived_request.model_id,
                mode=derived_request.mode,
            )
            compiled = WanPromptCompiler().compile(
                clip=clip,
                request=derived_request,
                capability=capability,
                rewrite_instruction=(
                    command.reason
                    if verdict is HumanVerdict.REWRITE
                    else None
                ),
            )
            self._write_prompt_snapshot(store, compiled)
        state = store.apply_visual_verdict(
            visual_take_id,
            verdict=verdict,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            expected_canon_version=command.expected_canon_version,
            expected_state_version=command.expected_state_version,
            derived_request=derived_request,
            fallback_policy=fallback_policy,
            cloud_policy=cloud_policy,
            changed_variable=command.changed_variable,
            prompt_version=prompt_version,
            reason=command.reason,
        )
        return {"state": state.model_dump(mode="json")}

    def acknowledge_generation_outbox(
        self,
        project_key: str,
        sequence: int,
        *,
        expected_state_version: int,
    ) -> dict:
        state = self._state_store(project_key).mark_outbox_published(
            sequence,
            expected_state_version=expected_state_version,
        )
        return state.model_dump(mode="json")
