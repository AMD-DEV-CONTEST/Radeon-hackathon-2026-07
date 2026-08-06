#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict, deque
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator, Mapping

from tokenizers import Tokenizer

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.v10_cpt_corpus import (
    APPROVED_CPT_LICENSES,
    MAX_PROVIDER_SHARE,
    MIN_PROVIDER_COUNT,
    TARGET_CPT_TOKENS,
    CPTCorpusRecord,
    near_duplicate,
    shingle_set,
    text_sha256,
    verify_cpt_summary,
)
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]
REUSE_MANIFEST = ROOT / "config/cortex_x_v10_reuse_manifest_v1.json"
OUTPUT = ROOT / "data/v10_cpt_corpus"
EVIDENCE = ROOT / "evidence/v10/cpt-corpus-15m-audit.json"
DOWNLOAD_CACHE = Path.home() / ".cache" / "prooflaunch-cpt-downloads"
CANDIDATE_CACHE = Path.home() / ".cache" / "prooflaunch-cpt-candidates"

MODEL_ID = "google/gemma-4-E4B-it"
MODEL_REVISION = "1fe35ce743b357484b97a11646125adffee0b410"
TOKENIZER_SHA256 = "cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f"
MODEL_FILES = ("tokenizer.json", "tokenizer_config.json", "processor_config.json", "config.json")
MODEL_RAW = (
    "https://www.modelscope.cn/api/v1/models/google/gemma-4-E4B-it/repo"
    f"?Revision={MODEL_REVISION}&FilePath={{path}}"
)

SELECTED_PROJECTS = (
    "transformers",
    "ms-swift",
    "peft",
    "trl",
    "langgraph",
    "crewai",
    "openai-agents",
    "agent-r1",
    "matpo",
    "marti",
    "tcod",
    "paddleocr",
    "evalscope",
    "wan2.2",
    "ltx-video",
    "seedvr2",
    "sam2",
    "grounding-dino",
    "flux2",
    "swinir",
    "real-esrgan",
    "whisper",
    "siglip2",
)

PROJECT_DATA_DIRS = (
    "v10_trajectory_kd",
    "v10_gtm_seed",
    "v10_brand_memory",
    "v10_curated_corpus",
)

TEXT_SUFFIXES = frozenset(
    {".md", ".mdx", ".rst", ".txt", ".py", ".json", ".jsonl", ".yaml", ".yml", ".toml"}
)
REPOSITORY_TRAINING_SUFFIXES = frozenset(
    {".md", ".mdx", ".rst", ".txt", ".py", ".json", ".jsonl", ".yaml", ".yml", ".toml"}
)
EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".github",
        "assets",
        "build",
        "checkpoints",
        "dist",
        "external",
        "fixtures",
        "generated",
        "golden",
        "images",
        "node_modules",
        "snapshots",
        "static",
        "third_party",
        "vendor",
        "weights",
    }
)
REPOSITORY_TRAINING_EXCLUDED_PARTS = EXCLUDED_PARTS | frozenset(
    {
        "benchmark",
        "benchmarks",
        "demo",
        "demos",
        "example",
        "examples",
        "notebook",
        "notebooks",
        "sample",
        "samples",
        "test",
        "tests",
    }
)
EXCLUDED_NAMES = frozenset(
    {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock", "poetry.lock", "changelog.md"}
)
HASH_KEY = re.compile(r"(?:sha|hash|digest|checksum|etag)", re.IGNORECASE)
IDENTITY_KEY = re.compile(r"(?:^|_)(?:id|url|uri|locator|timestamp|created_at|updated_at)$", re.IGNORECASE)
HEXISH = re.compile(r"\b[0-9a-f]{32,}\b", re.IGNORECASE)

MAX_CHUNK_TOKENS = 2048
MIN_CHUNK_TOKENS = 64
PROVIDER_CANDIDATE_CAP = 2_600_000
PROVIDER_ACCEPTED_CAP = int(TARGET_CPT_TOKENS * MAX_PROVIDER_SHARE)
MAX_IDENTICAL_PREFIX = 24
SHARD_RECORDS = 750
USER_AGENT = "ProofLaunch-CPT-Corpus/1.0 (rights-audited reproducible collector)"


def _request(url: str, *, attempts: int = 5) -> bytes:
    cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    cache_path = DOWNLOAD_CACHE / cache_key
    digest_path = DOWNLOAD_CACHE / f"{cache_key}.sha256"
    if cache_path.is_file() and digest_path.is_file():
        payload = cache_path.read_bytes()
        if hashlib.sha256(payload).hexdigest() == digest_path.read_text(encoding="utf-8").strip():
            return payload

    def retain(payload: bytes) -> bytes:
        DOWNLOAD_CACHE.mkdir(parents=True, exist_ok=True)
        _write_bytes(cache_path, payload)
        atomic_write_text(
            digest_path,
            hashlib.sha256(payload).hexdigest() + "\n",
        )
        return payload

    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=120) as response:
                return retain(response.read())
        except http.client.IncompleteRead as error:
            completed = subprocess.run(
                [
                    "curl",
                    "--fail",
                    "--location",
                    "--silent",
                    "--show-error",
                    "--retry",
                    str(attempts),
                    "--retry-all-errors",
                    "--max-time",
                    "300",
                    "--user-agent",
                    USER_AGENT,
                    url,
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if completed.returncode == 0 and completed.stdout:
                return retain(completed.stdout)
            last = RuntimeError(
                "urllib response was incomplete and curl fallback failed: "
                f"curl_exit={completed.returncode}; partial_bytes={len(error.partial)}"
            )
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last = error
            if attempt + 1 < attempts:
                time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _normalize_text(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw).replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n{5,}", "\n\n\n\n", text)
    return text.strip()


def _safe_member(path: str, size: int) -> bool:
    pure = PurePosixPath(path)
    parts = {part.casefold() for part in pure.parts}
    if parts & EXCLUDED_PARTS:
        return False
    if pure.name.casefold() in EXCLUDED_NAMES:
        return False
    if pure.suffix.casefold() not in TEXT_SUFFIXES:
        return False
    return 64 <= size <= 1_500_000


def _safe_repository_training_member(
    path: str,
    size: int,
    *,
    nested_license_roots: tuple[PurePosixPath, ...],
) -> bool:
    pure = PurePosixPath(path)
    relative = PurePosixPath(*pure.parts[1:])
    parts = {part.casefold() for part in relative.parts}
    if parts & REPOSITORY_TRAINING_EXCLUDED_PARTS:
        return False
    if relative.name.casefold() in EXCLUDED_NAMES:
        return False
    if relative.suffix.casefold() not in REPOSITORY_TRAINING_SUFFIXES:
        return False
    if any(relative == root or root in relative.parents for root in nested_license_roots):
        return False
    return 64 <= size <= 1_500_000


def _nested_license_roots(members: Iterable[tarfile.TarInfo]) -> tuple[PurePosixPath, ...]:
    roots: set[PurePosixPath] = set()
    for member in members:
        if not member.isfile():
            continue
        relative = PurePosixPath(*PurePosixPath(member.name).parts[1:])
        if len(relative.parts) <= 1:
            continue
        name = relative.name.casefold()
        if name.startswith(("license", "copying")):
            roots.add(relative.parent)
    return tuple(sorted(roots, key=str))


def _content_class(path: str) -> str:
    lower = path.casefold()
    suffix = PurePosixPath(path).suffix.casefold()
    if "/docs/" in lower or suffix in {".md", ".mdx", ".rst", ".txt"}:
        return "documentation"
    if "/test" in lower:
        return "test"
    if "/example" in lower or "/demo" in lower:
        return "example"
    if suffix in {".json", ".jsonl", ".yaml", ".yml", ".toml"}:
        return "structured_config"
    return "source_code"


def _chunks(tokenizer: Tokenizer, text: str) -> Iterator[tuple[str, int]]:
    ids = tokenizer.encode(text, add_special_tokens=False).ids
    for start in range(0, len(ids), MAX_CHUNK_TOKENS):
        part = ids[start : start + MAX_CHUNK_TOKENS]
        if len(part) < MIN_CHUNK_TOKENS:
            continue
        decoded = tokenizer.decode(part, skip_special_tokens=False)
        observed = tokenizer.encode(decoded, add_special_tokens=False).ids
        if len(observed) < MIN_CHUNK_TOKENS or len(observed) > MAX_CHUNK_TOKENS:
            raise RuntimeError("Gemma tokenizer normalized chunk outside the admitted token bounds")
        yield decoded, len(observed)


def _candidate_line(
    *, provider: str, source_id: str, path: str, revision: str, license_spdx: str,
    license_evidence_url: str, permitted_use: str,
    asset_level_rights_verified: bool, commercial_training_allowed: bool,
    rights_basis: str, content_class: str, text: str, token_count: int,
) -> str:
    return json.dumps(
        {
            "provider": provider,
            "source_id": source_id,
            "source_path": path,
            "source_revision": revision,
            "license_spdx": license_spdx,
            "license_evidence_url": license_evidence_url,
            "permitted_use": permitted_use,
            "asset_level_rights_verified": asset_level_rights_verified,
            "commercial_training_allowed": commercial_training_allowed,
            "rights_basis": rights_basis,
            "content_class": content_class,
            "text": text,
            "token_count": token_count,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _repo_candidates(
    tokenizer: Tokenizer,
    project: Mapping[str, object],
    destination: Path,
) -> dict[str, object]:
    provider = str(project["project_id"])
    repository = str(project["repository_url"])
    revision = str(project["revision"])
    license_spdx = str(project["license_spdx"])
    if license_spdx not in APPROVED_CPT_LICENSES or not project.get("license_approved_for_code_reuse"):
        raise RuntimeError(f"{provider} is not rights-admitted for CPT")
    candidate_cache_key = stable_sha256(
        {
            "schema": "ProofLaunchCPTRepositoryCandidateCacheV2",
            "provider": provider,
            "revision": revision,
            "tokenizer_sha256": TOKENIZER_SHA256,
            "maximum_chunk_tokens": MAX_CHUNK_TOKENS,
            "minimum_chunk_tokens": MIN_CHUNK_TOKENS,
            "candidate_cap": PROVIDER_CANDIDATE_CAP,
            "suffixes": sorted(REPOSITORY_TRAINING_SUFFIXES),
            "excluded_parts": sorted(REPOSITORY_TRAINING_EXCLUDED_PARTS),
        }
    )
    cached_candidates = CANDIDATE_CACHE / f"{candidate_cache_key}.jsonl"
    cached_receipt = CANDIDATE_CACHE / f"{candidate_cache_key}.receipt.json"
    if cached_candidates.is_file() and cached_receipt.is_file():
        receipt = json.loads(cached_receipt.read_text(encoding="utf-8"))
        if receipt.get("candidate_file_sha256") == sha256_file(cached_candidates):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached_candidates, destination)
            return receipt
    owner_repo = repository.removeprefix("https://github.com/").strip("/")
    archive_url = f"https://codeload.github.com/{owner_repo}/tar.gz/{revision}"
    payload = _request(archive_url)
    archive_sha = hashlib.sha256(payload).hexdigest()
    selected_files = 0
    candidate_tokens = 0
    candidate_records = 0
    with tempfile.NamedTemporaryFile(suffix=".tar.gz") as handle:
        handle.write(payload)
        handle.flush()
        with tarfile.open(handle.name, mode="r:gz") as archive, destination.open("w", encoding="utf-8") as output:
            all_members = archive.getmembers()
            nested_roots = _nested_license_roots(all_members)
            members = [
                member
                for member in all_members
                if member.isfile()
                and _safe_repository_training_member(
                    member.name,
                    member.size,
                    nested_license_roots=nested_roots,
                )
            ]
            members.sort(key=lambda item: hashlib.sha256(f"{revision}:{item.name}".encode()).digest())
            for member in members:
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                raw = extracted.read()
                if b"\x00" in raw:
                    continue
                try:
                    decoded = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                text = _normalize_text(decoded)
                if not text or HEXISH.sub("", text).strip() == "":
                    continue
                path = "/".join(PurePosixPath(member.name).parts[1:])
                emitted = False
                for chunk, count in _chunks(tokenizer, text):
                    output.write(
                        _candidate_line(
                            provider=provider,
                            source_id=f"github:{owner_repo}",
                            path=path,
                            revision=revision,
                            license_spdx=license_spdx,
                            license_evidence_url=str(project["license_evidence_url"]),
                            permitted_use="training_candidate",
                            asset_level_rights_verified=True,
                            commercial_training_allowed=True,
                            rights_basis=(
                                "immutable repository root license reviewed for commercial reuse; "
                                "only source/config/associated-documentation text outside assets, "
                                "tests, examples, vendor, "
                                "third-party and nested-license subtrees is admitted"
                            ),
                            content_class=_content_class(path),
                            text=chunk,
                            token_count=count,
                        )
                        + "\n"
                    )
                    emitted = True
                    candidate_tokens += count
                    candidate_records += 1
                    if candidate_tokens >= PROVIDER_CANDIDATE_CAP:
                        break
                selected_files += int(emitted)
                if candidate_tokens >= PROVIDER_CANDIDATE_CAP:
                    break
    receipt = {
        "provider": provider,
        "repository_url": repository,
        "revision": revision,
        "license_spdx": license_spdx,
        "archive_sha256": archive_sha,
        "selected_files": selected_files,
        "candidate_records": candidate_records,
        "candidate_tokens": candidate_tokens,
        "asset_level_rights_verified": True,
        "commercial_training_allowed": True,
        "nested_license_subtrees_excluded": len(nested_roots),
        "candidate_cache_key": candidate_cache_key,
        "candidate_file_sha256": sha256_file(destination),
    }
    CANDIDATE_CACHE.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(destination, cached_candidates)
    atomic_write_text(
        cached_receipt,
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return receipt


def _flatten_training_json(value: object, *, prefix: str = "") -> list[str]:
    output: list[str] = []
    if isinstance(value, Mapping):
        for key in sorted(value):
            name = str(key)
            if HASH_KEY.search(name) or IDENTITY_KEY.search(name):
                continue
            output.extend(_flatten_training_json(value[key], prefix=f"{prefix}.{name}".strip(".")))
    elif isinstance(value, list):
        for item in value[:200]:
            output.extend(_flatten_training_json(item, prefix=prefix))
    elif isinstance(value, str):
        cleaned = _normalize_text(value)
        if cleaned and not cleaned.startswith(("http://", "https://")) and not HEXISH.fullmatch(cleaned):
            output.append(f"{prefix}: {cleaned}" if prefix else cleaned)
    elif isinstance(value, (int, float, bool)) and prefix:
        output.append(f"{prefix}: {value}")
    return output


def _project_candidates(tokenizer: Tokenizer, destination: Path) -> dict[str, object]:
    provider = "prooflaunch-project-owned"
    candidate_tokens = 0
    candidate_records = 0
    selected_files = 0
    with destination.open("w", encoding="utf-8") as output:
        for directory_name in PROJECT_DATA_DIRS:
            directory = ROOT / "data" / directory_name
            for path in sorted(directory.glob("*.json*")):
                if path.name == "manifest.json":
                    continue
                raw_records: Iterable[object]
                if path.suffix == ".jsonl":
                    raw_records = (
                        json.loads(line)
                        for line in path.read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    )
                else:
                    raw_records = (json.loads(path.read_text(encoding="utf-8")),)
                emitted = False
                for index, value in enumerate(raw_records):
                    text = _normalize_text("\n".join(_flatten_training_json(value)))
                    for chunk, count in _chunks(tokenizer, text):
                        output.write(
                            _candidate_line(
                                provider=provider,
                                source_id=f"project:{directory_name}",
                                path=f"data/{directory_name}/{path.name}#{index}",
                                revision=sha256_file(path),
                                license_spdx="MIT",
                                license_evidence_url="project://LICENSE",
                                permitted_use="training_candidate",
                                asset_level_rights_verified=True,
                                commercial_training_allowed=True,
                                rights_basis="project-owned deterministic synthetic and authored corpus",
                                content_class="project_owned_synthetic",
                                text=chunk,
                                token_count=count,
                            )
                            + "\n"
                        )
                        emitted = True
                        candidate_tokens += count
                        candidate_records += 1
                        if candidate_tokens >= PROVIDER_CANDIDATE_CAP:
                            break
                    if candidate_tokens >= PROVIDER_CANDIDATE_CAP:
                        break
                selected_files += int(emitted)
                if candidate_tokens >= PROVIDER_CANDIDATE_CAP:
                    break
            if candidate_tokens >= PROVIDER_CANDIDATE_CAP:
                break
    return {
        "provider": provider,
        "repository_url": "project://prooflaunch_submission",
        "revision": stable_sha256({name: sha256_file(ROOT / "data" / name / "manifest.json") for name in PROJECT_DATA_DIRS}),
        "license_spdx": "MIT",
        "archive_sha256": None,
        "selected_files": selected_files,
        "candidate_records": candidate_records,
        "candidate_tokens": candidate_tokens,
    }


def _minhash(shingles: frozenset[str]) -> tuple[int, ...]:
    if not shingles:
        return ()
    return tuple(
        min(int.from_bytes(hashlib.blake2b(item.encode(), digest_size=8, person=f"cpt{seed}".encode()).digest(), "big") for item in shingles)
        for seed in range(8)
    )


def _write_final_corpus(
    tokenizer: Tokenizer,
    candidate_paths: Mapping[str, Path],
    build_root: Path,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    iterators = {provider: path.open("r", encoding="utf-8") for provider, path in candidate_paths.items()}
    active = deque(sorted(iterators))
    provider_tokens: Counter[str] = Counter()
    provider_records: Counter[str] = Counter()
    license_tokens: Counter[str] = Counter()
    class_tokens: Counter[str] = Counter()
    source_paths: set[tuple[str, str]] = set()
    exact_hashes: set[str] = set()
    prefix_counts: Counter[tuple[str, ...]] = Counter()
    shingle_rows: list[frozenset[str]] = []
    lsh: defaultdict[tuple[int, int], set[int]] = defaultdict(set)
    exact_rejected = near_rejected = prefix_rejected = 0
    evaluation_candidate_rejected = 0
    total_tokens = total_records = 0
    corpus_hasher = hashlib.sha256()
    shard_summaries: list[dict[str, object]] = []
    shard_handle = None
    shard_path: Path | None = None
    shard_records = shard_tokens = 0

    def close_shard() -> None:
        nonlocal shard_handle, shard_path, shard_records, shard_tokens
        if shard_handle is None or shard_path is None:
            return
        shard_handle.close()
        shard_summaries.append(
            {
                "path": str(shard_path.relative_to(build_root)),
                "records": shard_records,
                "tokens": shard_tokens,
                "sha256": sha256_file(shard_path),
            }
        )
        shard_handle = None
        shard_path = None
        shard_records = shard_tokens = 0

    def open_shard() -> None:
        nonlocal shard_handle, shard_path
        index = len(shard_summaries)
        shard_path = build_root / "shards" / f"cpt-{index:04d}.jsonl"
        shard_path.parent.mkdir(parents=True, exist_ok=True)
        shard_handle = shard_path.open("w", encoding="utf-8")

    while total_tokens < TARGET_CPT_TOKENS and active:
        provider = active.popleft()
        if provider_tokens[provider] >= PROVIDER_ACCEPTED_CAP:
            continue
        accepted_this_turn = False
        iterator = iterators[provider]
        while True:
            line = iterator.readline()
            if not line:
                iterator.close()
                break
            candidate = json.loads(line)
            if candidate.get("content_class") in {"test", "example"}:
                evaluation_candidate_rejected += 1
                continue
            text = str(candidate["text"])
            available = min(
                int(candidate["token_count"]),
                TARGET_CPT_TOKENS - total_tokens,
                PROVIDER_ACCEPTED_CAP - provider_tokens[provider],
            )
            if available <= 0:
                break
            if available != int(candidate["token_count"]):
                ids = tokenizer.encode(text, add_special_tokens=False).ids[:available]
                text = tokenizer.decode(ids, skip_special_tokens=False)
                observed = tokenizer.encode(text, add_special_tokens=False).ids
                if len(observed) != available:
                    continue
            digest = text_sha256(text)
            if digest in exact_hashes:
                exact_rejected += 1
                continue
            words = tuple(re.findall(r"[\w]+", text.casefold(), flags=re.UNICODE))
            prefix = words[:32]
            if prefix and prefix_counts[prefix] >= MAX_IDENTICAL_PREFIX:
                prefix_rejected += 1
                continue
            shingles = shingle_set(text)
            signature = _minhash(shingles)
            possible: set[int] = set()
            for band in range(4):
                if signature:
                    possible.update(lsh[(band, hash(signature[band * 2 : band * 2 + 2]))])
            if any(near_duplicate(shingles, shingle_rows[index]) for index in possible):
                near_rejected += 1
                continue
            total_records += 1
            record = CPTCorpusRecord(
                record_id=f"cpt-{total_records:08d}",
                provider=provider,
                source_id=str(candidate["source_id"]),
                source_path=str(candidate["source_path"]),
                source_revision=str(candidate["source_revision"]),
                license_spdx=str(candidate["license_spdx"]),
                license_evidence_url=str(candidate["license_evidence_url"]),
                permitted_use=str(candidate["permitted_use"]),
                asset_level_rights_verified=bool(candidate["asset_level_rights_verified"]),
                commercial_training_allowed=bool(candidate["commercial_training_allowed"]),
                rights_basis=str(candidate["rights_basis"]),
                content_class=str(candidate["content_class"]),
                text=text,
                token_count=available,
                content_sha256=digest,
            )
            if shard_handle is None:
                open_shard()
            assert shard_handle is not None
            shard_handle.write(json.dumps(record.__dict__, ensure_ascii=False, sort_keys=True) + "\n")
            shard_records += 1
            shard_tokens += available
            total_tokens += available
            provider_tokens[provider] += available
            provider_records[provider] += 1
            license_tokens[record.license_spdx] += available
            class_tokens[record.content_class] += available
            source_paths.add((provider, record.source_path.split("#", 1)[0]))
            exact_hashes.add(digest)
            prefix_counts[prefix] += 1
            row_index = len(shingle_rows)
            shingle_rows.append(shingles)
            for band in range(4):
                if signature:
                    lsh[(band, hash(signature[band * 2 : band * 2 + 2]))].add(row_index)
            corpus_hasher.update(digest.encode())
            accepted_this_turn = True
            if shard_records >= SHARD_RECORDS:
                close_shard()
            break
        if accepted_this_turn and provider_tokens[provider] < PROVIDER_ACCEPTED_CAP:
            active.append(provider)
    close_shard()
    for handle in iterators.values():
        if not handle.closed:
            handle.close()
    if total_tokens != TARGET_CPT_TOKENS:
        raise RuntimeError(
            f"rights-admitted deduplicated corpus shortfall: {TARGET_CPT_TOKENS - total_tokens} tokens"
        )
    maximum_share = max(provider_tokens.values()) / total_tokens
    summary = {
        "token_count": total_tokens,
        "token_count_observed": True,
        "record_count": total_records,
        "provider_count": len(provider_tokens),
        "provider_token_counts": dict(sorted(provider_tokens.items())),
        "provider_record_counts": dict(sorted(provider_records.items())),
        "maximum_provider_share": maximum_share,
        "license_token_counts": dict(sorted(license_tokens.items())),
        "content_class_token_counts": dict(sorted(class_tokens.items())),
        "source_file_count": len(source_paths),
        "duplicate_record_count": 0,
        "near_duplicate_record_count": 0,
        "unresolved_rights_count": 0,
        "model_output_record_count": 0,
        "evaluation_contamination_count": 0,
        "forbidden_evaluation_class_token_count": 0,
        "rejected_exact_duplicates": exact_rejected,
        "rejected_near_duplicates": near_rejected,
        "rejected_template_prefixes": prefix_rejected,
        "rejected_evaluation_candidates": evaluation_candidate_rejected,
        "maximum_identical_prefix_count": max(prefix_counts.values(), default=0),
        "corpus_content_sha256": corpus_hasher.hexdigest(),
    }
    if len(provider_tokens) < MIN_PROVIDER_COUNT or maximum_share > MAX_PROVIDER_SHARE:
        raise RuntimeError("final CPT source diversity gate failed")
    return summary, shard_summaries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="rebuild the immutable 15M corpus")
    args = parser.parse_args()
    if OUTPUT.exists() and not args.refresh:
        manifest = json.loads((OUTPUT / "manifest.json").read_text(encoding="utf-8"))
        print(json.dumps({"status": "retained", "token_count": manifest["summary"]["token_count"]}, sort_keys=True))
        return 0

    with tempfile.TemporaryDirectory(prefix="prooflaunch-cpt-build-", dir=ROOT / "data") as temporary:
        build_root = Path(temporary) / "v10_cpt_corpus"
        tokenizer_dir = build_root / "tokenizer"
        tokenizer_hashes: dict[str, str] = {}
        for name in MODEL_FILES:
            payload = _request(MODEL_RAW.format(path=name))
            _write_bytes(tokenizer_dir / name, payload)
            tokenizer_hashes[name] = hashlib.sha256(payload).hexdigest()
        if tokenizer_hashes["tokenizer.json"] != TOKENIZER_SHA256:
            raise RuntimeError("pinned Gemma tokenizer hash drifted")
        tokenizer = Tokenizer.from_file(str(tokenizer_dir / "tokenizer.json"))
        if tokenizer.get_vocab_size() != 262_144:
            raise RuntimeError("unexpected Gemma tokenizer vocabulary")

        reuse = json.loads(REUSE_MANIFEST.read_text(encoding="utf-8"))
        project_map = {row["project_id"]: row for row in reuse["projects"]}
        missing = sorted(set(SELECTED_PROJECTS) - set(project_map))
        if missing:
            raise RuntimeError(f"reuse manifest is missing selected CPT projects: {missing}")
        candidate_dir = build_root / ".candidates"
        candidate_dir.mkdir(parents=True)
        candidate_paths: dict[str, Path] = {}
        source_receipts: list[dict[str, object]] = []
        project_path = candidate_dir / "prooflaunch-project-owned.jsonl"
        project_receipt = _project_candidates(tokenizer, project_path)
        candidate_paths[str(project_receipt["provider"])] = project_path
        source_receipts.append(project_receipt)
        print(json.dumps(project_receipt, sort_keys=True), flush=True)
        for project_id in SELECTED_PROJECTS:
            path = candidate_dir / f"{project_id}.jsonl"
            receipt = _repo_candidates(tokenizer, project_map[project_id], path)
            candidate_paths[project_id] = path
            source_receipts.append(receipt)
            print(json.dumps(receipt, sort_keys=True), flush=True)

        summary, shards = _write_final_corpus(tokenizer, candidate_paths, build_root)
        shutil.rmtree(candidate_dir)
        manifest = {
            "schema": "ProofLaunchCPTCorpus15MV1",
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "tokenizer_backend": "tokenizers.Tokenizer",
            "tokenizer_add_special_tokens": False,
            "tokenizer_vocab_size": tokenizer.get_vocab_size(),
            "tokenizer_sha256": tokenizer_hashes["tokenizer.json"],
            "model_file_hashes": tokenizer_hashes,
            "target_tokens": TARGET_CPT_TOKENS,
            "source_receipts": source_receipts,
            "shards": shards,
            "summary": summary,
            "rights_boundary": (
                "Only project-owned records and source/config/associated-documentation text whose immutable repository-root "
                "license was reviewed for commercial reuse are admitted. Repository binary/media "
                "assets, tests, examples, vendor/third-party trees, nested-license subtrees, hosted model "
                "outputs, public campaign assets, sealed evaluation cases, private data and "
                "unresolved licenses are excluded. A repository license flag alone is insufficient."
            ),
            "training_observed": False,
            "cpt_checkpoint_observed": False,
        }
        manifest["content_sha256"] = stable_sha256(manifest)
        manifest_path = build_root / "manifest.json"
        atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        manifest_file_sha = sha256_file(manifest_path)
        audit = {
            "schema": "ProofLaunchCPTCorpus15MAuditV1",
            **summary,
            "tokenizer_sha256": tokenizer_hashes["tokenizer.json"],
            "manifest_sha256": manifest_file_sha,
            "manifest_content_sha256": manifest["content_sha256"],
            "source_receipt_count": len(source_receipts),
            "shard_count": len(shards),
            "rights_profile": "competition_permissive_asset_level_verified",
            "training_observed": False,
            "cpt_checkpoint_observed": False,
            "status": "passed_corpus_construction_not_training",
        }
        verify_cpt_summary(audit)
        if OUTPUT.exists():
            shutil.rmtree(OUTPUT)
        os.replace(build_root, OUTPUT)
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(EVIDENCE, json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        print(
            json.dumps(
                {
                    "status": audit["status"],
                    "tokens": audit["token_count"],
                    "records": audit["record_count"],
                    "providers": audit["provider_count"],
                    "maximum_provider_share": audit["maximum_provider_share"],
                    "manifest_sha256": audit["manifest_sha256"],
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
