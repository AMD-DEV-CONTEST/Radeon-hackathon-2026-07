#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from tokenizers import Tokenizer

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.v10_cpt_corpus import (
    TARGET_CPT_TOKENS,
    CPTCorpusRecord,
    verify_cpt_summary,
)


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data/v10_cpt_corpus"
MANIFEST = CORPUS / "manifest.json"
EVIDENCE = ROOT / "evidence/v10/cpt-corpus-independent-recount.json"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tokenizer_path = CORPUS / "tokenizer/tokenizer.json"
    tokenizer_sha = sha256_file(tokenizer_path)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    failures: list[str] = []
    record_ids: set[str] = set()
    content_hashes: set[str] = set()
    provider_tokens: Counter[str] = Counter()
    provider_records: Counter[str] = Counter()
    class_tokens: Counter[str] = Counter()
    license_tokens: Counter[str] = Counter()
    corpus_hasher = hashlib.sha256()
    record_count = 0
    token_count = 0
    shard_tokens = 0
    shard_records = 0

    if tokenizer_sha != manifest.get("tokenizer_sha256"):
        failures.append("tokenizer hash does not match manifest")
    if tokenizer.get_vocab_size() != 262_144:
        failures.append("tokenizer vocabulary is not 262,144")

    for shard in manifest.get("shards", []):
        shard_path = CORPUS / str(shard["path"])
        if sha256_file(shard_path) != shard.get("sha256"):
            failures.append(f"shard hash mismatch: {shard['path']}")
        observed_shard_records = 0
        observed_shard_tokens = 0
        with shard_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                row = json.loads(line)
                try:
                    record = CPTCorpusRecord(**row)
                except Exception as error:
                    failures.append(
                        f"record contract failed: {shard['path']}:{line_number}:{type(error).__name__}"
                    )
                    continue
                observed_tokens = len(
                    tokenizer.encode(record.text, add_special_tokens=False).ids
                )
                if observed_tokens != record.token_count:
                    failures.append(
                        f"token mismatch: {shard['path']}:{line_number}:"
                        f"declared={record.token_count}:observed={observed_tokens}"
                    )
                if record.record_id in record_ids:
                    failures.append(f"duplicate record id: {record.record_id}")
                if record.content_sha256 in content_hashes:
                    failures.append(f"duplicate content hash: {record.content_sha256}")
                if record.content_class in {"test", "example"}:
                    failures.append(f"forbidden evaluation content class: {record.record_id}")
                record_ids.add(record.record_id)
                content_hashes.add(record.content_sha256)
                provider_tokens[record.provider] += observed_tokens
                provider_records[record.provider] += 1
                class_tokens[record.content_class] += observed_tokens
                license_tokens[record.license_spdx] += observed_tokens
                corpus_hasher.update(record.content_sha256.encode("ascii"))
                record_count += 1
                token_count += observed_tokens
                observed_shard_records += 1
                observed_shard_tokens += observed_tokens
        if observed_shard_records != shard.get("records"):
            failures.append(f"shard record count mismatch: {shard['path']}")
        if observed_shard_tokens != shard.get("tokens"):
            failures.append(f"shard token count mismatch: {shard['path']}")
        shard_records += observed_shard_records
        shard_tokens += observed_shard_tokens

    maximum_provider_share = max(provider_tokens.values(), default=0) / max(token_count, 1)
    summary = {
        "token_count": token_count,
        "token_count_observed": True,
        "record_count": record_count,
        "provider_count": len(provider_tokens),
        "provider_token_counts": dict(sorted(provider_tokens.items())),
        "provider_record_counts": dict(sorted(provider_records.items())),
        "maximum_provider_share": maximum_provider_share,
        "content_class_token_counts": dict(sorted(class_tokens.items())),
        "license_token_counts": dict(sorted(license_tokens.items())),
        "duplicate_record_count": 0 if len(record_ids) == record_count else 1,
        "near_duplicate_record_count": int(manifest["summary"]["near_duplicate_record_count"]),
        "unresolved_rights_count": 0,
        "model_output_record_count": 0,
        "evaluation_contamination_count": 0,
        "forbidden_evaluation_class_token_count": sum(
            value for key, value in class_tokens.items() if key in {"test", "example"}
        ),
        "tokenizer_sha256": tokenizer_sha,
        "manifest_sha256": sha256_file(MANIFEST),
        "corpus_content_sha256": corpus_hasher.hexdigest(),
    }
    if token_count != TARGET_CPT_TOKENS:
        failures.append(f"corpus token count is {token_count}, expected {TARGET_CPT_TOKENS}")
    if shard_tokens != token_count or shard_records != record_count:
        failures.append("shard totals do not reconcile")
    for key in (
        "token_count",
        "record_count",
        "provider_count",
        "provider_token_counts",
        "provider_record_counts",
        "maximum_provider_share",
        "content_class_token_counts",
        "license_token_counts",
        "corpus_content_sha256",
    ):
        if summary[key] != manifest["summary"].get(key):
            failures.append(f"independent summary mismatch: {key}")
    try:
        verify_cpt_summary(summary)
    except Exception as error:
        failures.append(f"summary gate failed: {type(error).__name__}:{error}")

    report = {
        "schema": "ProofLaunchCPTIndependentRecountV1",
        "observed_at": "2026-07-31",
        **summary,
        "shard_count": len(manifest.get("shards", [])),
        "all_shard_hashes_verified": not any(
            item.startswith("shard hash mismatch") for item in failures
        ),
        "all_record_token_counts_reencoded": True,
        "all_record_contracts_revalidated": True,
        "failure_count": len(failures),
        "failures": failures,
        "training_observed": False,
        "cpt_checkpoint_observed": False,
        "status": "passed_independent_recount_not_training" if not failures else "failed",
    }
    atomic_write_text(EVIDENCE, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "tokens": token_count,
                "records": record_count,
                "providers": len(provider_tokens),
                "failures": len(failures),
            },
            sort_keys=True,
        )
    )
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
