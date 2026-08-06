from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_entity_registry_v2 import (
    GTMEntityRegistryError,
    compile_entity_registry,
    resolve_entity,
    stable_entity_id,
    verify_entity_registry,
)


class GTMEntityRegistryV2Tests(unittest.TestCase):
    def _registry(self) -> dict:
        old_id = stable_entity_id("company", "Oldco")
        new_id = stable_entity_id("company", "Newco")
        brand_id = stable_entity_id("brand", "Field Brand")
        regional_id = stable_entity_id("regional_account", "Field Brand UK")
        entities = [
            {"entity_id": old_id, "entity_kind": "company", "canonical_name": "Oldco", "aliases": [{"value": "Old Company", "valid_from": "2019-01-01", "valid_to": "2024-01-01"}]},
            {"entity_id": new_id, "entity_kind": "company", "canonical_name": "Newco", "aliases": [{"value": "New Company"}]},
            {"entity_id": brand_id, "entity_kind": "brand", "canonical_name": "Field Brand", "aliases": []},
            {"entity_id": regional_id, "entity_kind": "regional_account", "canonical_name": "Field Brand UK", "aliases": [{"value": "@fieldbrand_uk"}], "market_scope": ["uk_ireland"]},
        ]
        relationships = [
            {"source_entity_id": old_id, "target_entity_id": new_id, "relationship_type": "renamed_to", "valid_from": "2024-01-01", "valid_to": "open"},
            {"source_entity_id": brand_id, "target_entity_id": new_id, "relationship_type": "sub_brand_of", "valid_from": "2024-01-01", "valid_to": "open"},
            {"source_entity_id": regional_id, "target_entity_id": brand_id, "relationship_type": "regional_account_of", "valid_from": "2024-01-01", "valid_to": "open", "market_scope": ["uk_ireland"]},
        ]
        return compile_entity_registry(entities, relationships)

    def test_rename_subbrand_and_regional_account_are_temporal_relationships(self) -> None:
        payload = self._registry()
        verify_entity_registry(payload)
        self.assertEqual({row["relationship_type"] for row in payload["relationships"]}, {"renamed_to", "sub_brand_of", "regional_account_of"})
        self.assertEqual(resolve_entity(payload, "Old Company", entity_kind="company")["status"], "resolved")
        self.assertEqual(resolve_entity(payload, "@fieldbrand_uk", entity_kind="regional_account")["status"], "resolved")

    def test_ambiguous_alias_never_auto_resolves(self) -> None:
        entities = [
            {"entity_kind": "company", "canonical_name": "Alpha One", "aliases": [{"value": "Alpha"}]},
            {"entity_kind": "company", "canonical_name": "Alpha Two", "aliases": [{"value": "Alpha"}]},
        ]
        payload = compile_entity_registry(entities, [])
        result = resolve_entity(payload, "Alpha", entity_kind="company")
        self.assertEqual(result["status"], "ambiguous_manual_review")
        self.assertEqual(result["quota_credit"], 0)

    def test_tampered_relationship_fails_seal(self) -> None:
        payload = self._registry()
        broken = copy.deepcopy(payload)
        broken["relationships"][0]["relationship_type"] = "invented"
        with self.assertRaisesRegex(GTMEntityRegistryError, "seal"):
            verify_entity_registry(broken)


if __name__ == "__main__":
    unittest.main()
