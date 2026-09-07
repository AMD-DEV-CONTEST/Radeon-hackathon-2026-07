"""Publish a validated dataset and/or checkpoint to Hugging Face Hub.

Authentication is read only from the Hugging Face cache or ``HF_TOKEN``. The
token is never accepted as a command-line argument and is never written to the
release receipt.
"""

from __future__ import annotations

import argparse
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from radeonvla.artifact_io import atomic_write_json, sha256_path
from radeonvla.paths import PROJECT_ROOT


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-repo", default=None, help="Hub dataset repo, for example user/name.")
    parser.add_argument("--dataset-root", type=Path, default=None)
    parser.add_argument("--dataset-card", type=Path, default=PROJECT_ROOT / "docs" / "DATASET_CARD.md")
    parser.add_argument("--dataset-validation", type=Path, default=None)
    parser.add_argument("--expected-episodes", type=int, default=1000)
    parser.add_argument("--episodes-per-task", type=int, default=50)
    parser.add_argument("--model-repo", default=None, help="Hub model repo, for example user/name.")
    parser.add_argument("--policy-path", type=Path, default=None)
    parser.add_argument("--model-card", type=Path, default=PROJECT_ROOT / "docs" / "MODEL_CARD.md")
    parser.add_argument(
        "--model-evidence",
        type=Path,
        action="append",
        default=[],
        help="Validated evidence file to publish below evaluation/ in the model repository; repeatable.",
    )
    visibility = parser.add_mutually_exclusive_group()
    visibility.add_argument("--private", dest="private", action="store_true", default=True)
    visibility.add_argument("--public", dest="private", action="store_false")
    parser.add_argument(
        "--confirm-public-release",
        action="store_true",
        help="Required with --public so an unfinished artifact cannot be exposed accidentally.",
    )
    parser.add_argument(
        "--skip-reload-check",
        action="store_true",
        help="Skip immutable-revision download/reload checks (not allowed for the final release receipt).",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "huggingface_release.json",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _resolve(path: Path | None) -> Path | None:
    if path is None or path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def _validate_pairs(args: argparse.Namespace) -> None:
    dataset_pair = bool(args.dataset_repo) == bool(args.dataset_root)
    model_pair = bool(args.model_repo) == bool(args.policy_path)
    if not dataset_pair:
        raise ValueError("--dataset-repo and --dataset-root must be provided together")
    if not model_pair:
        raise ValueError("--model-repo and --policy-path must be provided together")
    if not args.dataset_repo and not args.model_repo:
        raise ValueError("Provide a dataset pair, a model pair, or both")
    if not args.private and not args.confirm_public_release:
        raise ValueError("--public requires --confirm-public-release")


def _read_release_card(path: Path, *, allow_draft: bool) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Release card not found: {path}")
    text = path.read_text(encoding="utf-8")
    draft_markers = ("Release status: pre-release", "TBD", "[PENDING]")
    found_markers = [marker for marker in draft_markers if marker in text]
    if found_markers and not allow_draft:
        raise ValueError(f"Release card still contains pre-release markers {found_markers}: {path}")
    return text


def _card_body(markdown: str) -> str:
    """Remove YAML front matter so Hub-generated dataset metadata is preserved."""
    if not markdown.startswith("---\n"):
        return markdown
    end = markdown.find("\n---\n", 4)
    return markdown[end + 5 :] if end >= 0 else markdown


def _assert_repo_namespaces(identity: dict, repo_ids: list[str]) -> None:
    allowed = {str(identity.get("name", ""))}
    allowed.update(str(org.get("name", "")) for org in identity.get("orgs", []))
    for repo_id in repo_ids:
        namespace, separator, _ = repo_id.partition("/")
        if not separator or namespace not in allowed:
            raise PermissionError(
                f"Hub repo namespace {namespace!r} is not the authenticated user or one of its organizations: "
                f"{sorted(name for name in allowed if name)}"
            )


def _model_evidence_uploads(paths: list[Path]) -> list[tuple[Path, str]]:
    uploads: list[tuple[Path, str]] = []
    destinations: set[str] = set()
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Model evidence file not found: {path}")
        destination = f"evaluation/{path.name}"
        if destination in destinations:
            raise ValueError(f"Duplicate model evidence filename: {path.name}")
        destinations.add(destination)
        uploads.append((path, destination))
    return uploads


def _validate_local_dataset(
    repo_id: str,
    root: Path,
    *,
    expected_episodes: int,
    episodes_per_task: int,
    report_path: Path | None,
) -> None:
    from radeonvla.validate_dataset import main as validate_dataset

    command = [
        "--repo-id",
        repo_id,
        "--dataset-root",
        str(root),
        "--expected-episodes",
        str(expected_episodes),
        "--episodes-per-task",
        str(episodes_per_task),
        "--require-strict-physics",
        "--max-frames",
        "64",
    ]
    if report_path is not None:
        command.extend(["--json", str(report_path)])
    result = validate_dataset(command)
    if result != 0:
        raise RuntimeError(f"Dataset publication validation failed with exit code {result}")


def _publish_dataset(args: argparse.Namespace, api, *, private: bool) -> dict:
    from huggingface_hub import hf_hub_download
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    root = _resolve(args.dataset_root)
    card = _resolve(args.dataset_card)
    validation = _resolve(args.dataset_validation)
    assert root is not None and card is not None and args.dataset_repo
    if not root.is_dir():
        raise FileNotFoundError(f"Dataset root not found: {root}")
    detailed_card = _read_release_card(card, allow_draft=False)
    _validate_local_dataset(
        args.dataset_repo,
        root,
        expected_episodes=args.expected_episodes,
        episodes_per_task=args.episodes_per_task,
        report_path=validation,
    )
    local_hash = sha256_path(root)
    dataset = LeRobotDataset(args.dataset_repo, root=root, video_backend="pyav")
    if int(dataset.num_episodes) != args.expected_episodes:
        raise RuntimeError(f"Dataset reopened with {dataset.num_episodes} episodes")
    dataset.push_to_hub(
        private=private,
        license="cc-by-4.0",
        tags=["robotics", "lerobot", "smolvla", "amd-rocm", "genesis"],
    )
    api.update_repo_settings(args.dataset_repo, repo_type="dataset", private=private)
    generated_readme = Path(
        hf_hub_download(args.dataset_repo, "README.md", repo_type="dataset", force_download=True)
    ).read_text(encoding="utf-8")
    generated_front_matter = generated_readme
    if generated_readme.startswith("---\n"):
        front_matter_end = generated_readme.find("\n---\n", 4)
        if front_matter_end >= 0:
            generated_front_matter = generated_readme[: front_matter_end + 5]
    merged_card = generated_front_matter.rstrip() + "\n\n" + _card_body(detailed_card).lstrip()
    api.upload_file(
        repo_id=args.dataset_repo,
        repo_type="dataset",
        path_or_fileobj=merged_card.encode("utf-8"),
        path_in_repo="README.md",
        commit_message="Publish validated dataset card",
    )
    if validation is not None and validation.is_file():
        api.upload_file(
            repo_id=args.dataset_repo,
            repo_type="dataset",
            path_or_fileobj=str(validation),
            path_in_repo="validation/dataset_validation.json",
            commit_message="Add strict dataset validation receipt",
        )
    revision = api.dataset_info(args.dataset_repo).sha
    if not args.skip_reload_check:
        with tempfile.TemporaryDirectory(prefix="radeonvla-hf-dataset-") as temporary:
            reloaded_root = Path(temporary) / "dataset"
            reloaded = LeRobotDataset(
                args.dataset_repo,
                root=reloaded_root,
                revision=revision,
                video_backend="pyav",
            )
            if int(reloaded.num_episodes) != args.expected_episodes or len(reloaded) <= 0:
                raise RuntimeError("Immutable Hub dataset reload verification failed")
            _validate_local_dataset(
                args.dataset_repo,
                reloaded_root,
                expected_episodes=args.expected_episodes,
                episodes_per_task=args.episodes_per_task,
                report_path=None,
            )
    return {
        "repo_id": args.dataset_repo,
        "revision": revision,
        "local_sha256": local_hash,
        "num_episodes": args.expected_episodes,
        "episodes_per_task": args.episodes_per_task,
        "reload_verified": not args.skip_reload_check,
    }


def _publish_model(args: argparse.Namespace, api, *, private: bool) -> dict:
    from huggingface_hub import snapshot_download

    policy_path = _resolve(args.policy_path)
    card = _resolve(args.model_card)
    assert policy_path is not None and card is not None and args.model_repo
    evidence_uploads = _model_evidence_uploads(args.model_evidence)
    if not policy_path.is_dir():
        raise FileNotFoundError(f"Policy path not found: {policy_path}")
    _read_release_card(card, allow_draft=False)
    required = (
        "config.json",
        "model.safetensors",
        "policy_preprocessor.json",
        "policy_postprocessor.json",
        "vlm_assets/radeonvla_vlm_assets.json",
    )
    missing = [name for name in required if not (policy_path / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Checkpoint is not self-contained; missing: {missing}")
    local_hash = sha256_path(policy_path)
    api.create_repo(args.model_repo, repo_type="model", private=private, exist_ok=True)
    api.update_repo_settings(args.model_repo, repo_type="model", private=private)
    api.upload_folder(
        repo_id=args.model_repo,
        repo_type="model",
        folder_path=str(policy_path),
        commit_message="Upload validated RadeonVLA-Reflex checkpoint",
    )
    api.upload_file(
        repo_id=args.model_repo,
        repo_type="model",
        path_or_fileobj=str(card),
        path_in_repo="README.md",
        commit_message="Publish validated model card",
    )
    evidence_names: list[str] = []
    for evidence, destination in evidence_uploads:
        api.upload_file(
            repo_id=args.model_repo,
            repo_type="model",
            path_or_fileobj=str(evidence),
            path_in_repo=destination,
            commit_message=f"Add validated model evidence: {evidence.name}",
        )
        evidence_names.append(destination)
    revision = api.model_info(args.model_repo).sha
    if not args.skip_reload_check:
        with tempfile.TemporaryDirectory(prefix="radeonvla-hf-model-") as temporary:
            snapshot = Path(
                snapshot_download(
                    repo_id=args.model_repo,
                    revision=revision,
                    local_dir=Path(temporary) / "model",
                )
            )
            from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

            policy = SmolVLAPolicy.from_pretrained(snapshot)
            del policy
    return {
        "repo_id": args.model_repo,
        "revision": revision,
        "local_sha256": local_hash,
        "reload_verified": not args.skip_reload_check,
        "evidence": evidence_names,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _validate_pairs(args)
    args.dataset_root = _resolve(args.dataset_root)
    args.policy_path = _resolve(args.policy_path)
    args.dataset_card = _resolve(args.dataset_card)
    args.model_card = _resolve(args.model_card)
    args.model_evidence = [_resolve(path) for path in args.model_evidence]
    assert all(path is not None for path in args.model_evidence)
    args.dataset_validation = _resolve(args.dataset_validation)
    args.receipt = _resolve(args.receipt)

    for path in (args.dataset_root, args.policy_path):
        if path is not None and not path.is_dir():
            raise FileNotFoundError(path)
    print(
        "[publish-hf] plan: "
        f"dataset={args.dataset_repo or '<skip>'} model={args.model_repo or '<skip>'} "
        f"visibility={'private' if args.private else 'public'}"
    )
    if args.dry_run:
        if args.dataset_card is not None and args.dataset_repo:
            _read_release_card(args.dataset_card, allow_draft=True)
        if args.model_card is not None and args.model_repo:
            _read_release_card(args.model_card, allow_draft=True)
        print("[publish-hf] dry-run only; no authentication or Hub mutation performed")
        return 0

    from huggingface_hub import HfApi

    api = HfApi()
    identity = api.whoami()
    repo_ids = [repo_id for repo_id in (args.dataset_repo, args.model_repo) if repo_id]
    _assert_repo_namespaces(identity, repo_ids)
    receipt = {
        "published_at": datetime.now(UTC).isoformat(),
        "account": identity.get("name"),
        "private": args.private,
        "dataset": _publish_dataset(args, api, private=args.private) if args.dataset_repo else None,
        "model": _publish_model(args, api, private=args.private) if args.model_repo else None,
    }
    if args.skip_reload_check:
        print("[publish-hf] upload completed, but final receipt withheld because reload checks were skipped")
        return 2
    assert args.receipt is not None
    atomic_write_json(args.receipt, receipt)
    print(f"[publish-hf] immutable release receipt -> {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
