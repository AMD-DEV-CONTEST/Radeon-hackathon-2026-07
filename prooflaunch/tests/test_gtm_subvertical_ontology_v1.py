from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_case_evidence_funnel_v2 import build_case_evidence_funnel_standard
from prooflaunch_remix.gtm_subvertical_ontology_v1 import (
    GTMSubverticalOntologyError,
    build_ontology,
    compile_change_proposal,
    verify_ontology,
)


class GTMSubverticalOntologyV1Tests(unittest.TestCase):
    def test_all_81_have_definitions_inclusions_and_exclusions(self) -> None:
        standard = build_case_evidence_funnel_standard()
        ontology = build_ontology(standard["subverticals"])
        verify_ontology(ontology)
        self.assertEqual(ontology["subvertical_count"], 81)
        self.assertTrue(all(len(row["definition"]) >= 80 for row in ontology["subverticals"]))
        self.assertTrue(all(len(row["inclusion_scope"]) == 3 and len(row["exclusion_scope"]) == 3 for row in ontology["subverticals"]))

    def test_new_subvertical_proposal_inherits_200_40_10_5_and_never_auto_applies(self) -> None:
        ontology = build_ontology(build_case_evidence_funnel_standard()["subverticals"])
        proposal = compile_change_proposal(ontology, [{
            "subvertical_id": "b2b.example.new_category",
            "business_model": "b2b",
            "vertical": "example",
            "subvertical": "new_category",
            "definition": "A deliberately long and precise new category definition that exceeds eighty characters and preserves one primary monetized offer.",
            "inclusion_scope": ["one", "two", "three"],
            "exclusion_scope": ["one", "two", "three"],
        }], proposed_version="2.0.0", proposer_name="Named Owner")
        self.assertEqual(proposal["new_subverticals"][0]["required_structured_candidates"], 200)
        self.assertEqual(proposal["new_subverticals"][0]["required_mechanism_deep_audits"], 40)
        self.assertFalse(proposal["automatic_application_allowed"])
        self.assertEqual(proposal["status"], "pending_named_approval")

    def test_tampered_definition_fails_seal(self) -> None:
        ontology = build_ontology(build_case_evidence_funnel_standard()["subverticals"])
        broken = copy.deepcopy(ontology)
        broken["subverticals"][0]["definition"] = "thin"
        with self.assertRaisesRegex(GTMSubverticalOntologyError, "seal"):
            verify_ontology(broken)


if __name__ == "__main__":
    unittest.main()
