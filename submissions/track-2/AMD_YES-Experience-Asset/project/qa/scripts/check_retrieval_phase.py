#!/usr/bin/env python3
"""Check public invariants for phase-gated current and cross-asset retrieval."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schema" / "retrieval_phase_trace.schema.json"
READY_STATES = {"CONFIRMED", "COMPLETE_WITH_GAPS"}


def load(path: str | pathlib.Path) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def check(trace: dict) -> list[tuple[str, str, str]]:
    findings: list[tuple[str, str, str]] = []
    asset_id = trace.get("asset_id")
    events = trace.get("events")
    if not asset_id:
        findings.append(("HIGH", "AC-30", "asset_id is required"))
    if not isinstance(events, list) or not events:
        return findings + [("HIGH", "AC-30", "events must be a non-empty list")]

    ready = False
    ready_version: str | None = None
    candidate_assets: set[str] = set()
    confirmed_assets: set[str] = set()
    previous_sequence = -1

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            findings.append(("HIGH", "AC-30", f"event[{index}] is not an object"))
            continue
        sequence = event.get("sequence")
        if not isinstance(sequence, int) or sequence <= previous_sequence:
            findings.append(("HIGH", "AC-30", "event sequence must be strictly increasing"))
        elif isinstance(sequence, int):
            previous_sequence = sequence

        event_type = event.get("event_type")
        if event_type == "current_source_retrieval":
            if event.get("scope") != "current_asset":
                findings.append(("CRITICAL", "AC-30", "current-source retrieval escaped current_asset scope"))
            related = event.get("related_asset_id")
            if related and related != asset_id:
                findings.append(("CRITICAL", "AC-30", "current-source retrieval referenced another asset"))

        elif event_type == "current_card_changed":
            ready = False
            ready_version = None
            candidate_assets.clear()
            confirmed_assets.clear()

        elif event_type == "knowledge_card_ready":
            if event.get("milestone_state") not in READY_STATES:
                findings.append(("HIGH", "AC-30", "Knowledge Card readiness requires CONFIRMED or COMPLETE_WITH_GAPS"))
            if event.get("explicit_user_acceptance") is not True:
                findings.append(("HIGH", "AC-30", "Knowledge Card readiness requires explicit user acceptance"))
            version = event.get("knowledge_card_version")
            if not version or not event.get("knowledge_card_hash"):
                findings.append(("HIGH", "AC-30", "Knowledge Card readiness must bind version and hash"))
            else:
                ready = True
                ready_version = version

        elif event_type == "relation_candidate_search":
            if event.get("denied") is True:
                # A refused attempt is not a retrieval. Nothing was read and no
                # model was called, so the pre-readiness rule below would report
                # the opposite of what happened. The reason has to be on the
                # record either way, which is why the attempt is logged at all.
                if not event.get("denial_reason"):
                    findings.append(("HIGH", "AC-30", "a denied search must record its reason"))
                if event.get("related_asset_id"):
                    findings.append((
                        "CRITICAL",
                        "AC-30",
                        "a denied search must not name a cross-asset target",
                    ))
                continue
            if not ready:
                findings.append(("CRITICAL", "AC-30", "cross-asset candidate search ran before Knowledge Card readiness"))
            if event.get("scope") != "cross_asset_summary":
                findings.append(("CRITICAL", "AC-30", "candidate search must use cross_asset_summary scope"))
            if event.get("detail_included") is not False:
                findings.append(("HIGH", "AC-30", "candidate search must not include detailed historical content"))
            related = event.get("related_asset_id")
            if related:
                if related == asset_id:
                    findings.append(("HIGH", "AC-30", "cross-asset candidate cannot be the current asset"))
                candidate_assets.add(related)

        elif event_type == "relation_confirmation":
            related = event.get("related_asset_id")
            if not ready:
                findings.append(("HIGH", "AC-30", "relation was confirmed before Knowledge Card readiness"))
            if not related or related not in candidate_assets:
                findings.append(("HIGH", "AC-30", "relation confirmation does not reference a discovered candidate"))
            elif event.get("confirmed") is True:
                confirmed_assets.add(related)
            else:
                confirmed_assets.discard(related)

        elif event_type == "relation_detail_retrieval":
            related = event.get("related_asset_id")
            if not ready:
                findings.append(("CRITICAL", "AC-30", "detailed historical retrieval ran before Knowledge Card readiness"))
            if event.get("scope") != "cross_asset_detail":
                findings.append(("CRITICAL", "AC-30", "detailed retrieval must use cross_asset_detail scope"))
            if not related or related not in confirmed_assets:
                findings.append(("CRITICAL", "AC-30", "detailed retrieval is not limited to a user-confirmed relation"))
            if not event.get("provenance_refs"):
                findings.append(("HIGH", "AC-30", "detailed retrieval must retain provenance references"))
            if event.get("mutated_current_statements") is not False:
                findings.append(("CRITICAL", "AC-30", "historical retrieval silently mutated current statements"))
            before_hash = event.get("current_statements_hash_before")
            after_hash = event.get("current_statements_hash_after")
            if not before_hash or not after_hash or before_hash != after_hash:
                findings.append(("CRITICAL", "AC-30", "current-statement snapshot changed during historical retrieval"))
            if event.get("knowledge_card_version") != ready_version:
                findings.append(("HIGH", "AC-30", "detailed retrieval is not bound to the ready Knowledge Card version"))

        elif event_type == "relation_no_match":
            if not ready:
                findings.append(("HIGH", "AC-30", "no-match result appeared before Knowledge Card readiness"))

    try:
        import jsonschema
    except ImportError:
        pass
    else:
        try:
            jsonschema.validate(trace, load(SCHEMA))
        except jsonschema.ValidationError as exc:
            path = "/".join(str(part) for part in exc.absolute_path)
            findings.append(("HIGH", "AC-30", f"JSON Schema: {exc.message} @ /{path}"))

    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace")
    args = parser.parse_args()
    try:
        trace = load(args.trace)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"CRITICAL AC-30 invalid input: {exc}")
        return 1

    findings = check(trace)
    for severity, ac_id, message in findings:
        print(f"{severity:9} {ac_id} {message}")
    if any(item[0] in {"CRITICAL", "HIGH"} for item in findings):
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
