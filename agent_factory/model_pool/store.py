from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path
from typing import Any, cast

from agent_factory.model_pool.config import model_pool_store_read_only, resolve_model_pool_store_path
from agent_factory.model_pool.schema import (
    LocalModelArtifact,
    ModelPoolDefaultRole,
    ModelPoolProfile,
    utc_now_text,
)
from agent_factory.sqlite_runtime import connect_sqlite, initialize_sqlite_store


class ModelPoolStoreError(RuntimeError):
    pass


_DEFAULT_PROFILE_ROLES: tuple[ModelPoolDefaultRole, ...] = (
    "main",
    "task",
    "compression",
    "embedding",
    "image_generation",
)
SQLITE_BUSY_TIMEOUT_MS = 10000


class ModelPoolStore:
    def __init__(
        self,
        path: str | Path | None = None,
        *,
        setup: bool = True,
        read_only: bool | None = None,
    ) -> None:
        self.path = resolve_model_pool_store_path(path)
        self.read_only = model_pool_store_read_only() if read_only is None else read_only
        if self.read_only:
            if not self.path.is_file():
                raise ModelPoolStoreError(f"local model registry is not initialized: {self.path}")
        elif setup:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            initialize_sqlite_store(
                self.path,
                self._ensure_schema,
                timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
                wal=True,
            )
        elif not self.path.is_file():
            raise ModelPoolStoreError(f"local model registry is not initialized: {self.path}")

    def upsert_artifact(self, artifact: LocalModelArtifact) -> LocalModelArtifact:
        existing = self.get_artifact(artifact.artifact_id)
        if existing is not None and existing.kind != artifact.kind:
            raise ModelPoolStoreError("artifact kind cannot be changed after registration")
        artifact = artifact.model_copy(
            update={
                "created_at": existing.created_at if existing else artifact.created_at,
                "updated_at": utc_now_text(),
            }
        )
        with self._connect(write=True) as conn:
            conn.execute(
                """
                insert into local_model_artifacts (
                  artifact_id, kind, display_name, local_path, enabled,
                  payload_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(artifact_id) do update set
                  kind=excluded.kind,
                  display_name=excluded.display_name,
                  local_path=excluded.local_path,
                  enabled=excluded.enabled,
                  payload_json=excluded.payload_json,
                  updated_at=excluded.updated_at
                """,
                (
                    artifact.artifact_id,
                    artifact.kind,
                    artifact.display_name,
                    artifact.local_path or "",
                    1 if artifact.enabled else 0,
                    artifact.model_dump_json(),
                    artifact.created_at,
                    artifact.updated_at,
                ),
            )
        return artifact

    def patch_artifact(self, artifact_id: str, payload: dict[str, Any]) -> LocalModelArtifact:
        existing = self.require_artifact(artifact_id)
        candidate = LocalModelArtifact.model_validate({**existing.model_dump(mode="json"), **dict(payload)})
        return self.upsert_artifact(candidate)

    def get_artifact(self, artifact_id: str) -> LocalModelArtifact | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload_json from local_model_artifacts where artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        return LocalModelArtifact.model_validate_json(str(row["payload_json"])) if row else None

    def require_artifact(self, artifact_id: str) -> LocalModelArtifact:
        artifact = self.get_artifact(artifact_id)
        if artifact is None:
            raise ModelPoolStoreError(f"unknown local model artifact: {artifact_id}")
        return artifact

    def list_artifacts(
        self,
        *,
        kind: str | None = None,
        enabled: bool | None = None,
    ) -> list[LocalModelArtifact]:
        clauses: list[str] = []
        args: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        if enabled is not None:
            clauses.append("enabled = ?")
            args.append(1 if enabled else 0)
        query = "select payload_json from local_model_artifacts"
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by updated_at desc, artifact_id asc"
        with self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [LocalModelArtifact.model_validate_json(str(row["payload_json"])) for row in rows]

    def delete_artifact(self, artifact_id: str) -> bool:
        if self.list_profiles(artifact_id=artifact_id):
            raise ModelPoolStoreError(f"artifact is still used by model profiles: {artifact_id}")
        with self._connect(write=True) as conn:
            cursor = conn.execute("delete from local_model_artifacts where artifact_id = ?", (artifact_id,))
        return cursor.rowcount > 0

    def upsert_profile(self, profile: ModelPoolProfile) -> ModelPoolProfile:
        artifact = self.require_artifact(profile.artifact_id)
        if artifact.kind != profile.kind:
            raise ModelPoolStoreError(
                f"profile kind {profile.kind!r} must match artifact kind {artifact.kind!r}"
            )
        existing = self.get_profile(profile.profile_id)
        if existing is not None and existing.kind != profile.kind:
            raise ModelPoolStoreError("profile kind cannot be changed after registration")
        profile = profile.model_copy(
            update={
                "created_at": existing.created_at if existing else profile.created_at,
                "updated_at": utc_now_text(),
            },
            deep=True,
        )
        with self._connect(write=True) as conn:
            conn.execute(
                """
                insert into local_model_profiles (
                  profile_id, artifact_id, kind, engine, served_model_name,
                  display_name, enabled, payload_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(profile_id) do update set
                  artifact_id=excluded.artifact_id,
                  kind=excluded.kind,
                  engine=excluded.engine,
                  served_model_name=excluded.served_model_name,
                  display_name=excluded.display_name,
                  enabled=excluded.enabled,
                  payload_json=excluded.payload_json,
                  updated_at=excluded.updated_at
                """,
                (
                    profile.profile_id,
                    profile.artifact_id,
                    profile.kind,
                    profile.engine,
                    profile.served_model_name,
                    profile.display_name,
                    1 if profile.enabled else 0,
                    profile.model_dump_json(),
                    profile.created_at,
                    profile.updated_at,
                ),
            )
        return profile

    def patch_profile(self, profile_id: str, payload: dict[str, Any]) -> ModelPoolProfile:
        existing = self.require_profile(profile_id)
        candidate = ModelPoolProfile.model_validate({**existing.model_dump(mode="json"), **dict(payload)})
        return self.upsert_profile(candidate)

    def disable_other_profiles(self, kind: str, active_profile_id: str) -> list[str]:
        normalized_kind = self._validate_profile_kind(kind)
        disabled: list[str] = []
        for profile in self.list_profiles(kind=normalized_kind, enabled=True):
            if profile.profile_id == active_profile_id:
                continue
            self.upsert_profile(profile.model_copy(update={"enabled": False}, deep=True))
            disabled.append(profile.profile_id)
        return disabled

    def get_profile(self, profile_id: str) -> ModelPoolProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload_json from local_model_profiles where profile_id = ?",
                (profile_id,),
            ).fetchone()
        return ModelPoolProfile.model_validate_json(str(row["payload_json"])) if row else None

    def require_profile(self, profile_id: str) -> ModelPoolProfile:
        profile = self.get_profile(profile_id)
        if profile is None:
            raise ModelPoolStoreError(f"unknown local model profile: {profile_id}")
        return profile

    def list_profiles(
        self,
        *,
        kind: str | None = None,
        artifact_id: str | None = None,
        enabled: bool | None = None,
    ) -> list[ModelPoolProfile]:
        clauses: list[str] = []
        args: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        if artifact_id:
            clauses.append("artifact_id = ?")
            args.append(artifact_id)
        if enabled is not None:
            clauses.append("enabled = ?")
            args.append(1 if enabled else 0)
        query = "select payload_json from local_model_profiles"
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by updated_at desc, profile_id asc"
        with self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [ModelPoolProfile.model_validate_json(str(row["payload_json"])) for row in rows]

    def delete_profile(self, profile_id: str) -> bool:
        with self._connect(write=True) as conn:
            conn.execute("delete from local_model_default_profiles where profile_id = ?", (profile_id,))
            conn.execute("delete from local_model_active_profiles where profile_id = ?", (profile_id,))
            cursor = conn.execute("delete from local_model_profiles where profile_id = ?", (profile_id,))
        return cursor.rowcount > 0

    def prune_catalog(
        self,
        *,
        kinds: set[str],
        keep_profile_ids: set[str],
        keep_artifact_ids: set[str],
    ) -> dict[str, list[str]]:
        normalized_kinds = {self._validate_profile_kind(kind) for kind in kinds}
        normalized_profile_ids = {str(value).strip() for value in keep_profile_ids if str(value).strip()}
        normalized_artifact_ids = {str(value).strip() for value in keep_artifact_ids if str(value).strip()}
        if not normalized_kinds:
            raise ModelPoolStoreError("catalog pruning requires at least one model kind")

        with self._connect(write=True) as conn:
            kept_profiles = conn.execute(
                "select profile_id, artifact_id, kind from local_model_profiles"
            ).fetchall()
            kept_by_id = {str(row["profile_id"]): row for row in kept_profiles}
            missing_profiles = sorted(normalized_profile_ids - set(kept_by_id))
            if missing_profiles:
                raise ModelPoolStoreError(
                    "catalog pruning cannot keep unknown profiles: " + ", ".join(missing_profiles)
                )
            for profile_id in normalized_profile_ids:
                row = kept_by_id[profile_id]
                if str(row["kind"]) not in normalized_kinds:
                    raise ModelPoolStoreError(
                        f"kept profile kind is outside the pruning scope: {profile_id}"
                    )
                if str(row["artifact_id"]) not in normalized_artifact_ids:
                    raise ModelPoolStoreError(
                        f"kept profile references an artifact outside the retained catalog: {profile_id}"
                    )

            removed_profiles = sorted(
                str(row["profile_id"])
                for row in kept_profiles
                if str(row["kind"]) in normalized_kinds
                and str(row["profile_id"]) not in normalized_profile_ids
            )
            if removed_profiles:
                placeholders = ", ".join("?" for _ in removed_profiles)
                conn.execute(
                    f"delete from local_model_default_profiles where profile_id in ({placeholders})",
                    removed_profiles,
                )
                conn.execute(
                    f"delete from local_model_active_profiles where profile_id in ({placeholders})",
                    removed_profiles,
                )
                conn.execute(
                    f"delete from local_model_profiles where profile_id in ({placeholders})",
                    removed_profiles,
                )

            artifact_rows = conn.execute(
                "select artifact_id, kind from local_model_artifacts"
            ).fetchall()
            removed_artifacts: list[str] = []
            for row in artifact_rows:
                artifact_id = str(row["artifact_id"])
                if str(row["kind"]) not in normalized_kinds or artifact_id in normalized_artifact_ids:
                    continue
                referenced = conn.execute(
                    "select 1 from local_model_profiles where artifact_id = ? limit 1",
                    (artifact_id,),
                ).fetchone()
                if referenced is None:
                    conn.execute(
                        "delete from local_model_artifacts where artifact_id = ?",
                        (artifact_id,),
                    )
                    removed_artifacts.append(artifact_id)

        return {
            "profiles": removed_profiles,
            "artifacts": sorted(removed_artifacts),
        }

    def active_profile_id(self, kind: str) -> str | None:
        normalized_kind = self._validate_profile_kind(kind)
        with self._connect() as conn:
            row = conn.execute(
                "select profile_id from local_model_active_profiles where kind = ?",
                (normalized_kind,),
            ).fetchone()
        return str(row["profile_id"]) if row else None

    def set_active_profile_id(self, kind: str, profile_id: str | None) -> str | None:
        normalized_kind = self._validate_profile_kind(kind)
        normalized_profile_id = str(profile_id or "").strip()
        with self._connect(write=True) as conn:
            if not normalized_profile_id:
                conn.execute("delete from local_model_active_profiles where kind = ?", (normalized_kind,))
                return None
            profile = self.require_profile(normalized_profile_id)
            if profile.kind != normalized_kind or not profile.enabled:
                raise ModelPoolStoreError(
                    f"active {normalized_kind} runtime requires an enabled matching profile"
                )
            conn.execute(
                """
                insert into local_model_active_profiles (kind, profile_id, updated_at)
                values (?, ?, ?)
                on conflict(kind) do update set
                  profile_id=excluded.profile_id,
                  updated_at=excluded.updated_at
                """,
                (normalized_kind, profile.profile_id, utc_now_text()),
            )
        return normalized_profile_id

    @staticmethod
    def _validate_profile_kind(kind: str) -> str:
        normalized = str(kind or "").strip().lower()
        if normalized not in {"chat", "embedding", "image_generation"}:
            raise ModelPoolStoreError(f"unsupported local model profile kind: {kind}")
        return normalized

    def default_profile_ids(self) -> dict[ModelPoolDefaultRole, str | None]:
        return {role: self.resolve_default_profile_id(role) for role in _DEFAULT_PROFILE_ROLES}

    def resolve_default_profile_id(self, role: str) -> str | None:
        normalized_role = self._validate_default_role(role)
        with self._connect() as conn:
            row = conn.execute(
                "select profile_id from local_model_default_profiles where role = ?",
                (normalized_role,),
            ).fetchone()
        if row:
            profile = self.get_profile(str(row["profile_id"]))
            if profile is not None and self._profile_can_be_default(profile, normalized_role):
                return profile.profile_id

        kind = normalized_role if normalized_role in {"embedding", "image_generation"} else "chat"
        candidates = sorted(
            self.list_profiles(kind=kind, enabled=True),
            key=lambda profile: (profile.created_at, profile.profile_id),
        )
        for profile in candidates:
            if self._profile_can_be_default(profile, normalized_role):
                return profile.profile_id
        return None

    def set_default_profile_id(
        self,
        role: str,
        profile_id: str | None,
    ) -> str | None:
        normalized_role = self._validate_default_role(role)
        normalized_profile_id = str(profile_id or "").strip()
        if not normalized_profile_id:
            with self._connect(write=True) as conn:
                conn.execute("delete from local_model_default_profiles where role = ?", (normalized_role,))
            return self.resolve_default_profile_id(normalized_role)

        profile = self.require_profile(normalized_profile_id)
        if not self._profile_can_be_default(profile, normalized_role):
            expected_kind = normalized_role if normalized_role in {"embedding", "image_generation"} else "chat"
            raise ModelPoolStoreError(
                f"default role {normalized_role!r} requires an enabled {expected_kind} profile and artifact"
            )
        with self._connect(write=True) as conn:
            conn.execute(
                """
                insert into local_model_default_profiles (role, profile_id, updated_at)
                values (?, ?, ?)
                on conflict(role) do update set
                  profile_id=excluded.profile_id,
                  updated_at=excluded.updated_at
                """,
                (normalized_role, profile.profile_id, utc_now_text()),
            )
        return profile.profile_id

    @staticmethod
    def _validate_default_role(role: str) -> ModelPoolDefaultRole:
        normalized = str(role or "").strip().lower()
        if normalized not in _DEFAULT_PROFILE_ROLES:
            raise ModelPoolStoreError(f"unsupported default model role: {role}")
        return cast(ModelPoolDefaultRole, normalized)

    def _profile_can_be_default(
        self,
        profile: ModelPoolProfile,
        role: ModelPoolDefaultRole,
    ) -> bool:
        expected_kind = role if role in {"embedding", "image_generation"} else "chat"
        if profile.kind != expected_kind or not profile.enabled:
            return False
        artifact = self.get_artifact(profile.artifact_id)
        return artifact is not None and artifact.enabled

    def public_profiles(self) -> list[dict[str, Any]]:
        artifacts = {artifact.artifact_id: artifact for artifact in self.list_artifacts()}
        return [
            profile.to_public(artifacts.get(profile.artifact_id)).model_dump(mode="json")
            for profile in self.list_profiles()
        ]

    @contextmanager
    def _connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        if write and self.read_only:
            raise ModelPoolStoreError("local model registry is read-only")
        conn = (
            connect_sqlite(
                f"{self.path.as_uri()}?mode=ro",
                timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
                uri=True,
                query_only=True,
            )
            if self.read_only
            else connect_sqlite(
                self.path,
                timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
                query_only=not write,
            )
        )
        try:
            yield conn
            if write:
                conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect(write=True) as conn:
            conn.executescript(
                """
                create table if not exists local_model_artifacts (
                  artifact_id text primary key,
                  kind text not null,
                  display_name text not null,
                  local_path text not null,
                  enabled integer not null,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null
                );
                create index if not exists idx_local_model_artifacts_kind
                  on local_model_artifacts(kind);

                create table if not exists local_model_profiles (
                  profile_id text primary key,
                  artifact_id text not null,
                  kind text not null,
                  engine text not null,
                  served_model_name text not null,
                  display_name text not null,
                  enabled integer not null,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null
                );
                create index if not exists idx_local_model_profiles_artifact
                  on local_model_profiles(artifact_id);
                create index if not exists idx_local_model_profiles_kind
                  on local_model_profiles(kind);
                create index if not exists idx_local_model_profiles_enabled
                  on local_model_profiles(enabled);

                create table if not exists local_model_default_profiles (
                  role text primary key,
                  profile_id text not null,
                  updated_at text not null
                );
                create index if not exists idx_local_model_default_profiles_profile
                  on local_model_default_profiles(profile_id);

                create table if not exists local_model_active_profiles (
                  kind text primary key,
                  profile_id text not null,
                  updated_at text not null
                );
                create index if not exists idx_local_model_active_profiles_profile
                  on local_model_active_profiles(profile_id);
                """
            )
            legacy_rows = conn.execute(
                "select profile_id from local_model_profiles where kind = 'chat' and engine = 'vllm_rocm'"
            ).fetchall()
            legacy_profile_ids = [str(row["profile_id"]) for row in legacy_rows]
            if legacy_profile_ids:
                placeholders = ", ".join("?" for _ in legacy_profile_ids)
                conn.execute(
                    f"delete from local_model_default_profiles where profile_id in ({placeholders})",
                    legacy_profile_ids,
                )
                conn.execute(
                    f"delete from local_model_active_profiles where profile_id in ({placeholders})",
                    legacy_profile_ids,
                )
                conn.execute(
                    f"delete from local_model_profiles where profile_id in ({placeholders})",
                    legacy_profile_ids,
                )
            legacy_artifact_rows = conn.execute(
                "select artifact_id, payload_json from local_model_artifacts where kind = 'chat'"
            ).fetchall()
            for row in legacy_artifact_rows:
                try:
                    payload = json.loads(str(row["payload_json"]))
                except json.JSONDecodeError:
                    continue
                if (
                    str(payload.get("source") or "local_storage") == "external_endpoint"
                    or str(payload.get("model_format") or "").strip().lower() == "llama_cpp"
                ):
                    continue
                artifact_id = str(row["artifact_id"])
                referenced = conn.execute(
                    "select 1 from local_model_profiles where artifact_id = ? limit 1",
                    (artifact_id,),
                ).fetchone()
                if referenced is None:
                    conn.execute(
                        "delete from local_model_artifacts where artifact_id = ?",
                        (artifact_id,),
                    )
            artifact_rows = conn.execute(
                "select artifact_id, payload_json from local_model_artifacts"
            ).fetchall()
            for row in artifact_rows:
                try:
                    payload = json.loads(str(row["payload_json"]))
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict) or "tokenizer_path" not in payload:
                    continue
                payload.pop("tokenizer_path", None)
                conn.execute(
                    "update local_model_artifacts set payload_json = ? where artifact_id = ?",
                    (json.dumps(payload, ensure_ascii=False), str(row["artifact_id"])),
                )
            embedding_rows = conn.execute(
                "select profile_id, engine, payload_json from local_model_profiles where kind = 'embedding'"
            ).fetchall()
            for row in embedding_rows:
                if str(row["engine"]) == "external":
                    continue
                try:
                    payload = json.loads(str(row["payload_json"]))
                except json.JSONDecodeError:
                    continue
                inference = payload.get("inference") if isinstance(payload, dict) else None
                if not isinstance(inference, dict) or set(inference) == {"trust_remote_code"}:
                    continue
                payload["inference"] = {
                    "trust_remote_code": bool(inference.get("trust_remote_code")),
                }
                conn.execute(
                    "update local_model_profiles set payload_json = ? where profile_id = ?",
                    (json.dumps(payload, ensure_ascii=False), str(row["profile_id"])),
                )
