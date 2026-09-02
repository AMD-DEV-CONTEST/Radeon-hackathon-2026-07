#!/usr/bin/env python3
"""
determinex_corpus_share.py -- opt-in corpus signal sharing to HuggingFace
========================================================================
The flywheel learns from every oracle-verified solve: a symptom -> fix class that the
grounded fixer applies first on the next occurrence. Those classes are the product's real
compounding asset, and they get better the more machines contribute.

They are also derived from THE OPERATOR'S SOURCE CODE, which is the one thing this project
exists to keep local. So sharing is:

  * **OFF by default.** Not "on with a setting to disable" -- absent consent, nothing leaves.
  * **Explicit.** `DETERMINEX_CORPUS_SHARE=1` plus a recorded consent record. A flag alone is
    not consent; a flag can be set by a script the operator never read.
  * **Redacted before it leaves.** A class is a generalized rule, but it is distilled FROM a
    specific repository, and the distillation can carry identifiers, paths and fragments.
    Everything is scrubbed and then RE-SCANNED, because a redactor that is never checked is
    a redactor nobody knows the coverage of.
  * **Previewable.** `--dry-run` prints the exact payload. Nobody should have to trust a
    description of what is about to be uploaded when they can read the bytes.

    python scripts/determinex_corpus_share.py --dry-run     # see exactly what would go
    python scripts/determinex_corpus_share.py --consent     # record consent, once
    python scripts/determinex_corpus_share.py --push        # upload (needs both)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus" / "programbench" / "build_knowledge.json"
CONSENT = ROOT / ".determinex" / "corpus_share_consent.json"
DEFAULT_REPO = "darthceltic85/determinex-corpus"

# What must never leave, whatever else changes. Ordered most-specific first so a broad
# pattern cannot swallow a narrow one before it is seen.
_REDACTIONS: list[tuple[str, re.Pattern]] = [
    ("<key>", re.compile(r"\b(?:sk-ant-api[0-9]{2}-|sk-proj-|sk-)[A-Za-z0-9_\-]{16,}")),
    ("<key>", re.compile(r"\bAIzaSy[A-Za-z0-9_\-]{30,}")),
    ("<key>", re.compile(r"\bghp_[A-Za-z0-9]{30,}|\bhf_[A-Za-z0-9]{30,}")),
    ("<key>", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "<pem>",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    ),
    ("<email>", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")),
    ("<host>", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("<path>", re.compile(r"[A-Za-z]:\\Users\\[^\\\"'\s]+")),
    ("<path>", re.compile(r"/home/[^/\"'\s]+")),
    ("<path>", re.compile(r"/Users/[^/\"'\s]+")),
    ("<drive>", re.compile(r"\b[T-Z]:[/\\][^\"'\s]*")),
]


def redact(text: str) -> str:
    for repl, pat in _REDACTIONS:
        text = pat.sub(repl, text)
    return text


def _residue(text: str) -> list[str]:
    """Re-scan AFTER redaction. A redactor whose output is never checked has unknown
    coverage, and unknown coverage on an upload path is the whole risk."""
    return [repl for repl, pat in _REDACTIONS if pat.search(text)]


def consent_record() -> dict | None:
    try:
        return json.loads(CONSENT.read_text(encoding="utf-8"))
    except Exception:
        return None


def record_consent() -> int:
    CONSENT.parent.mkdir(parents=True, exist_ok=True)
    CONSENT.write_text(
        json.dumps(
            {
                "consented_at": datetime.now(UTC).isoformat(),
                "host": platform.node(),
                "scope": "oracle-verified symptom->fix classes, redacted; no source, no paths, "
                "no credentials, no repository names",
                "revoke": "delete this file; sharing stops immediately",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"consent recorded -> {CONSENT}")
    print("  revoke at any time by deleting that file.")
    return 0


def build_payload() -> dict:
    """The shareable slice: generalized classes only, redacted.

    Deliberately NOT the whole corpus. `per_tool` holds tool-specific build recipes and
    `absorbed_sources` holds ingest provenance -- both are ours, neither generalizes, and
    both raise the chance of leaking something specific to a machine.
    """
    kn = json.loads(CORPUS.read_text(encoding="utf-8"))
    classes = kn.get("class_patterns", {})
    out: dict[str, dict] = {}
    for name, body in classes.items():
        if not isinstance(body, dict):
            continue
        keep = {
            k: redact(str(v))
            for k, v in body.items()
            if k in ("detect", "symptom", "fix", "rule", "measured", "scope", "trap")
        }
        if keep:
            out[name] = keep
    blob = json.dumps(out, sort_keys=True)
    return {
        "schema": "determinex-corpus-share-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "n_classes": len(out),
        "sha256": hashlib.sha256(blob.encode("utf-8")).hexdigest(),
        "classes": out,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--consent", action="store_true", help="record consent (one time)")
    ap.add_argument("--revoke", action="store_true", help="delete the consent record")
    ap.add_argument(
        "--dry-run", action="store_true", help="print the exact payload, upload nothing"
    )
    ap.add_argument("--push", action="store_true", help="upload to HuggingFace")
    ap.add_argument("--repo", default=os.environ.get("DETERMINEX_CORPUS_REPO", DEFAULT_REPO))
    args = ap.parse_args()

    if args.revoke:
        CONSENT.unlink(missing_ok=True)
        print("consent revoked; nothing will be shared.")
        return 0
    if args.consent:
        return record_consent()

    payload = build_payload()
    body = json.dumps(payload, indent=2, ensure_ascii=False)

    left = _residue(body)
    if left:
        print(f"REFUSING: redaction left {left} in the payload. Nothing uploaded.", file=sys.stderr)
        return 1

    if args.dry_run or not args.push:
        print(
            body
            if args.dry_run
            else f"{payload['n_classes']} classes, sha256 {payload['sha256'][:16]}...  "
            f"(--dry-run to see the bytes, --push to upload)"
        )
        return 0

    # --- upload requires BOTH the flag and the recorded consent -------------------------
    if os.environ.get("DETERMINEX_CORPUS_SHARE") != "1":
        print(
            "REFUSING: DETERMINEX_CORPUS_SHARE=1 is not set. Sharing is off by default.",
            file=sys.stderr,
        )
        return 1
    rec = consent_record()
    if not rec:
        print(
            "REFUSING: no consent record. Run --consent first.\n"
            "  A flag alone is not consent: a flag can be set by a script nobody read.",
            file=sys.stderr,
        )
        return 1

    from huggingface_hub import HfApi

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if not token:
        print("REFUSING: no HF_TOKEN in the environment.", file=sys.stderr)
        return 1

    api = HfApi(token=token)
    api.create_repo(repo_id=args.repo, repo_type="dataset", exist_ok=True)
    tmp = ROOT / ".determinex" / "corpus_share_payload.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(body, encoding="utf-8")
    api.upload_file(
        path_or_fileobj=str(tmp),
        path_in_repo="classes.json",
        repo_id=args.repo,
        repo_type="dataset",
    )
    print(
        f"uploaded {payload['n_classes']} classes to {args.repo} "
        f"(sha256 {payload['sha256'][:16]}...)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
