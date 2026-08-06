from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .v10_contracts import V10ContractError, stable_digest


LOCK_SCHEMA = "ProofLaunchFinalLockBundleV1"
LOCK_PATH = Path("config/cortex_x_v10_final_locks.json")
PRIVATE_DATA_PREFIXES = ("data/tokenfactory_teacher_v10/",)


@dataclass(frozen=True)
class LockedFile:
    path: str
    sha256: str
    bytes: int

    def __post_init__(self) -> None:
        if self.path.startswith("/") or ".." in Path(self.path).parts:
            raise V10ContractError("locked paths must be repository relative")
        if len(self.sha256) != 64 or self.bytes < 0:
            raise V10ContractError("locked file metadata is invalid")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entries(root: Path, paths: Iterable[Path]) -> tuple[LockedFile, ...]:
    unique = sorted({path.resolve() for path in paths if path.is_file()})
    entries = []
    for path in unique:
        relative = path.relative_to(root.resolve()).as_posix()
        entries.append(LockedFile(relative, _sha256(path), path.stat().st_size))
    return tuple(entries)


def source_paths(root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for base, patterns in (
        (root / "src", ("*.py",)),
        (root / "scripts", ("*.py", "*.mjs", "*.sh")),
        (root / "demos", ("*.py",)),
        (root / "tests", ("test_*.py",)),
        (root / "docs", ("*.md",)),
        (root / "notebooks", ("*.ipynb",)),
        (root / "web", ("*.html", "*.js", "*.css", "*.json", "*.mjs")),
        (root / "config", ("*.json", "*.yaml", "*.yml")),
        (root / "submission", ("*.md", "*.json")),
    ):
        for pattern in patterns:
            paths.extend(base.rglob(pattern) if base.exists() else ())
    paths.extend(
        path
        for path in (
            root / "LICENSE",
            root / "README.md",
            root / "JUDGE_START_HERE.md",
            root / "SUBMISSION_GATE.json",
        )
        if path.is_file()
    )
    lock_absolute = (root / LOCK_PATH).resolve()
    return tuple(sorted({path for path in paths if path.resolve() != lock_absolute}))


def data_paths(root: Path) -> tuple[Path, ...]:
    data_root = root / "data"
    if not data_root.exists():
        return ()
    return tuple(
        sorted(
            path
            for path in data_root.rglob("*")
            if path.is_file()
            and not any(
                path.relative_to(root).as_posix().startswith(prefix)
                for prefix in PRIVATE_DATA_PREFIXES
            )
        )
    )


def _section(entries: tuple[LockedFile, ...]) -> dict[str, object]:
    payload = [asdict(entry) for entry in entries]
    return {
        "file_count": len(payload),
        "files": payload,
        "content_sha256": stable_digest(payload),
    }


def _model_identities(root: Path) -> list[dict[str, object]]:
    supply = json.loads((root / "config/model_supply_chain.json").read_text(encoding="utf-8"))
    training = json.loads((root / "config/cortex_x_v10_training_plan.json").read_text(encoding="utf-8"))
    identities = [
        {
            "role": role,
            "repo_id": record["repo_id"],
            "revision": record["revision"],
            "license": record["license"],
            "admitted": True,
        }
        for role, record in sorted(supply["models"].items())
    ]
    identities.append(
        {
            "role": "training_base",
            "repo_id": training["base_model"],
            "revision": training["base_revision"],
            "license": "license-review-bound",
            "admitted": True,
        }
    )
    identities.append(
        {
            "role": "distillation_teacher",
            "repo_id": "UNRESOLVED",
            "revision": "UNRESOLVED_PENDING_RIGHTS_AND_METHOD_SELECTION",
            "license": "unresolved",
            "admitted": False,
        }
    )
    return identities


def build_lock_bundle(root: str | Path) -> dict[str, object]:
    project = Path(root).resolve()
    sources = _entries(project, source_paths(project))
    data = _entries(project, data_paths(project))
    model_files = _entries(
        project,
        (
            project / "config/model_supply_chain.json",
            project / "config/radeon_matrix_adapter.json",
            project / "config/cortex_x_v10_training_plan.json",
            project / "config/cortex_x_v10_cpt_contract.json",
            project / "config/cortex_x_v10_on_policy_distillation_contract.json",
        ),
    )
    payload: dict[str, object] = {
        "schema": LOCK_SCHEMA,
        "source_lock": _section(sources),
        "model_lock": {
            **_section(model_files),
            "identities": _model_identities(project),
            "unresolved_models_admitted": False,
        },
        "data_lock": {
            **_section(data),
            "external_datasets": [
                {
                    "dataset_id": "AI-ModelScope/emotion",
                    "revision": "UNRESOLVED_NO_IMMUTABLE_REVISION_RECEIPT",
                    "admitted_for_final_training": False,
                }
            ],
            "excluded_private_prefixes": list(PRIVATE_DATA_PREFIXES),
        },
        "truth_boundary": (
            "The lock proves repository byte identity and fail-closed unresolved dependencies; "
            "it does not prove model weights were downloaded, training ran, or data rights were granted."
        ),
    }
    payload["content_sha256"] = stable_digest(payload)
    return payload


def verify_lock_bundle(root: str | Path, bundle: Mapping[str, Any]) -> tuple[str, ...]:
    project = Path(root).resolve()
    errors: list[str] = []
    if bundle.get("schema") != LOCK_SCHEMA:
        errors.append("schema_mismatch")
    supplied_digest = bundle.get("content_sha256")
    digest_payload = dict(bundle)
    digest_payload.pop("content_sha256", None)
    if supplied_digest != stable_digest(digest_payload):
        errors.append("bundle_digest_mismatch")
    expected = build_lock_bundle(project)
    for name in ("source_lock", "model_lock", "data_lock"):
        if bundle.get(name) != expected.get(name):
            errors.append(f"{name}_drift")
    return tuple(errors)
