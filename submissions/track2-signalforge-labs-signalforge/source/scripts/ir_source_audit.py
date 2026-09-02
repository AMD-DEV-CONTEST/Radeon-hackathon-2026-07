#!/usr/bin/env python3
"""Create a complete source, robots, host, rights, and quarantine audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry_bytes = args.registry.read_bytes()
    registry = json.loads(registry_bytes)
    discovery = json.loads(args.discovery.read_text())
    registry_sha256 = hashlib.sha256(registry_bytes).hexdigest()
    if discovery.get("registry_sha256") != registry_sha256:
        raise SystemExit("discovery report does not match the source registry")
    found = {item["primary_ticker"]: item for item in discovery["sources"]}
    issuers = []
    for source in registry["sources"]:
        item = found[source["primary_ticker"]]
        disposition = item["disposition"]
        issuers.append(
            {
                "ticker": source["primary_ticker"],
                "company_id": source["company_id"],
                "discovery_uri": source["discovery_uri"],
                "allowed_hosts": source["allowed_hosts"],
                "restricted_host_prefixes": source.get("restricted_host_prefixes", {}),
                "root_disposition": disposition,
                "robots_status": item["robots"].get("status_code"),
                "robots_allows_root": item.get("robots_allows_root"),
                "terms_candidates": item.get("terms_link_samples", []),
                "ignored_external_hosts": item.get("external_host_candidates", []),
                "rights_class": source["rights_class"],
                "product_disposition": "quarantined_pending_rights" if source["rights_class"].endswith("pending_review") else "eligible",
                "collection_disposition": (
                    "private_evaluation_only"
                    if disposition in {"root_verified", "head_verified_needs_body"}
                    else "issuer_quarantined"
                ),
            }
        )
    counts: dict[str, int] = {}
    for issuer in issuers:
        counts[issuer["root_disposition"]] = counts.get(issuer["root_disposition"], 0) + 1
    report = {
        "schema_version": "signalforge/ir-source-audit/v1",
        "registry_sha256": registry_sha256,
        "issuer_count": len(issuers),
        "root_disposition_counts": dict(sorted(counts.items())),
        "product_eligible_count": sum(item["product_disposition"] == "eligible" for item in issuers),
        "issuers": issuers,
        "policy": {
            "external_hosts": "Ignored until an issuer-bound host or URI-prefix review is recorded.",
            "rights": "Public availability is not redistribution permission. Raw bytes, extracted text, and vectors remain private and quarantined while review is pending.",
            "blocked_sources": "No authentication, browser circumvention, proxy rotation, or anti-bot bypass is permitted.",
        },
        "claim_boundary": "This is a technical source audit, not legal advice or a grant of content rights.",
    }
    if len(issuers) != 20:
        raise SystemExit("source audit must cover exactly 20 issuers")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"issuer_count": 20, "root_disposition_counts": report["root_disposition_counts"], "product_eligible_count": report["product_eligible_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
