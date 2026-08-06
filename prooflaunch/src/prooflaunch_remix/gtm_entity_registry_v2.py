from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
import unicodedata
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMEntityRegistryV2"
ENTITY_KINDS = {"company", "brand", "product", "campaign", "regional_account", "domain"}
RELATIONSHIP_TYPES = {"renamed_to", "acquired_by", "sub_brand_of", "product_of", "campaign_of", "regional_account_of", "domain_of"}


class GTMEntityRegistryError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def normalize_alias(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def stable_entity_id(kind: str, canonical_name: str) -> str:
    if kind not in ENTITY_KINDS:
        raise GTMEntityRegistryError(f"unsupported entity kind: {kind}")
    normalized = normalize_alias(canonical_name)
    if len(normalized) < 2:
        raise GTMEntityRegistryError("canonical entity name is too thin")
    return f"{kind}:{hashlib.sha256(normalized.encode()).hexdigest()[:20]}"


def compile_entity_registry(
    entities: Sequence[Mapping[str, Any]],
    relationships: Sequence[Mapping[str, Any]],
    *,
    registry_version: str = "2.0.0",
) -> dict[str, Any]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", registry_version):
        raise GTMEntityRegistryError("registry_version must be semantic")
    compiled_entities: list[dict[str, Any]] = []
    ids: set[str] = set()
    for raw in entities:
        kind = str(raw.get("entity_kind") or "")
        canonical_name = str(raw.get("canonical_name") or "").strip()
        entity_id = str(raw.get("entity_id") or stable_entity_id(kind, canonical_name))
        if entity_id in ids or kind not in ENTITY_KINDS:
            raise GTMEntityRegistryError(f"duplicate or invalid entity: {entity_id}")
        ids.add(entity_id)
        aliases = []
        for alias in raw.get("aliases", []):
            normalized = normalize_alias(alias.get("value"))
            if not normalized:
                raise GTMEntityRegistryError(f"{entity_id} has an empty alias")
            aliases.append({
                "value": str(alias["value"]).strip(),
                "normalized_value": normalized,
                "locale": str(alias.get("locale") or "und"),
                "valid_from": str(alias.get("valid_from") or "unknown"),
                "valid_to": str(alias.get("valid_to") or "open"),
                "alias_type": str(alias.get("alias_type") or "name"),
                "source_receipt_sha256s": sorted({str(value) for value in alias.get("source_receipt_sha256s", [])}),
            })
        canonical_normalized = normalize_alias(canonical_name)
        if canonical_normalized not in {row["normalized_value"] for row in aliases}:
            aliases.append({
                "value": canonical_name, "normalized_value": canonical_normalized, "locale": "und",
                "valid_from": "unknown", "valid_to": "open", "alias_type": "canonical_name",
                "source_receipt_sha256s": sorted({str(value) for value in raw.get("source_receipt_sha256s", [])}),
            })
        compiled_entities.append({
            "entity_id": entity_id,
            "entity_kind": kind,
            "canonical_name": canonical_name,
            "canonical_normalized_name": canonical_normalized,
            "aliases": sorted(aliases, key=lambda row: (row["normalized_value"], row["valid_from"])),
            "market_scope": sorted({str(value) for value in raw.get("market_scope", [])}),
            "source_receipt_sha256s": sorted({str(value) for value in raw.get("source_receipt_sha256s", [])}),
            "status": str(raw.get("status") or "active"),
        })

    compiled_relationships: list[dict[str, Any]] = []
    relationship_ids: set[str] = set()
    for raw in relationships:
        source_id = str(raw.get("source_entity_id") or "")
        target_id = str(raw.get("target_entity_id") or "")
        relationship_type = str(raw.get("relationship_type") or "")
        if source_id not in ids or target_id not in ids or source_id == target_id or relationship_type not in RELATIONSHIP_TYPES:
            raise GTMEntityRegistryError("relationship references an invalid entity or type")
        valid_from = str(raw.get("valid_from") or "unknown")
        valid_to = str(raw.get("valid_to") or "open")
        relationship_id = f"rel:{hashlib.sha256(f'{source_id}|{relationship_type}|{target_id}|{valid_from}|{valid_to}'.encode()).hexdigest()[:24]}"
        if relationship_id in relationship_ids:
            raise GTMEntityRegistryError("duplicate entity relationship")
        relationship_ids.add(relationship_id)
        compiled_relationships.append({
            "relationship_id": relationship_id,
            "source_entity_id": source_id,
            "target_entity_id": target_id,
            "relationship_type": relationship_type,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "market_scope": sorted({str(value) for value in raw.get("market_scope", [])}),
            "source_receipt_sha256s": sorted({str(value) for value in raw.get("source_receipt_sha256s", [])}),
            "human_review_status": str(raw.get("human_review_status") or "pending"),
        })

    alias_index: dict[str, list[str]] = defaultdict(list)
    for entity in compiled_entities:
        for alias in entity["aliases"]:
            alias_index[alias["normalized_value"]].append(entity["entity_id"])
    ambiguous = {key: sorted(set(value)) for key, value in alias_index.items() if len(set(value)) > 1}
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "registry_version": registry_version,
        "entity_count": len(compiled_entities),
        "relationship_count": len(compiled_relationships),
        "entities": sorted(compiled_entities, key=lambda row: row["entity_id"]),
        "relationships": sorted(compiled_relationships, key=lambda row: row["relationship_id"]),
        "ambiguous_aliases": ambiguous,
        "resolution_policy": {
            "ambiguous_alias_auto_resolution_allowed": False,
            "temporal_relationships_required_for_rename_and_acquisition": True,
            "regional_accounts_must_preserve_market_scope": True,
            "unresolved_entity_quota_credit": 0,
        },
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def resolve_entity(registry: Mapping[str, Any], value: str, *, entity_kind: str | None = None) -> dict[str, Any]:
    verify_entity_registry(registry)
    normalized = normalize_alias(value)
    matches = []
    for entity in registry["entities"]:
        if entity_kind and entity["entity_kind"] != entity_kind:
            continue
        if normalized in {alias["normalized_value"] for alias in entity["aliases"]}:
            matches.append(entity["entity_id"])
    if len(matches) == 1:
        return {"status": "resolved", "entity_id": matches[0], "normalized_input": normalized, "quota_credit": 0}
    if len(matches) > 1:
        return {"status": "ambiguous_manual_review", "candidate_entity_ids": sorted(matches), "normalized_input": normalized, "quota_credit": 0}
    return {"status": "unresolved", "candidate_entity_ids": [], "normalized_input": normalized, "quota_credit": 0}


def verify_entity_registry(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload); supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMEntityRegistryError("entity registry seal is invalid")
    entities = payload.get("entities"); relationships = payload.get("relationships")
    if not isinstance(entities, list) or payload.get("entity_count") != len(entities):
        raise GTMEntityRegistryError("entity aggregate drifted")
    if not isinstance(relationships, list) or payload.get("relationship_count") != len(relationships):
        raise GTMEntityRegistryError("relationship aggregate drifted")
    ids = {row.get("entity_id") for row in entities}
    if len(ids) != len(entities):
        raise GTMEntityRegistryError("entity IDs are duplicated")
    for relationship in relationships:
        if relationship.get("source_entity_id") not in ids or relationship.get("target_entity_id") not in ids:
            raise GTMEntityRegistryError("relationship target drifted")
        if relationship.get("relationship_type") not in RELATIONSHIP_TYPES:
            raise GTMEntityRegistryError("relationship type drifted")
    if payload.get("resolution_policy", {}).get("ambiguous_alias_auto_resolution_allowed") is not False:
        raise GTMEntityRegistryError("ambiguous aliases can auto-resolve")


__all__ = ["GTMEntityRegistryError", "compile_entity_registry", "normalize_alias", "resolve_entity", "stable_entity_id", "verify_entity_registry"]
