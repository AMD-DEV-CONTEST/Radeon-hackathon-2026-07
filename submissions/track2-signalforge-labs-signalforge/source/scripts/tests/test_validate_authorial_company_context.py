import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).parents[1] / "validate_authorial_company_context.py"
SPEC = importlib.util.spec_from_file_location("validate_authorial_company_context", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AuthorialCompanyContextValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(
            (Path(__file__).parents[2] / "contracts" / "authorial-company-context.schema.json").read_text()
        )
        text = "Original company context without financial figures."
        self.artifact = {
            "schema_version": "signalforge/authorial-company-context/v1",
            "context_id": "example-v1",
            "issuer": {
                "company_id": "sec-cik:0000000001",
                "name": "Example Inc.",
                "ticker": "EX",
                "market": "US",
            },
            "created_at": "2026-07-23T00:00:00Z",
            "status": "private_evaluation_review_required",
            "method": {
                "description": "Original synthesis.",
                "expression_policy": "Do not copy source expression.",
                "numeric_policy": "Use deterministic sources for numbers.",
            },
            "sources": [{
                "source_id": "official-profile",
                "title": "Official profile",
                "uri": "https://example.com/about",
                "source_class": "corporate_profile",
                "authority_tier": "E",
                "retrieved_at": "2026-07-23T00:00:00Z",
                "capture_sha256": "a" * 64,
                "http_status": 200,
                "retrieval_status": "retrieved_directly",
                "evidence_method": "Direct bounded retrieval.",
                "rights_class": "reference_only_authorial_derivation_pending_review",
            }],
            "authorial_context": {
                "one_sentence": "Example description.",
                "business_description": "Example business description.",
                "product_families": [{
                    "id": "example-product",
                    "title": "Example product",
                    "summary": "Example product summary.",
                    "source_ids": ["official-profile"],
                }],
                "solution_domains": [{
                    "id": "example-solution",
                    "title": "Example solution",
                    "summary": "Example solution summary.",
                    "source_ids": ["official-profile"],
                }],
                "customer_and_workload_profile": "Example customer context.",
                "analytical_interpretations": [],
            },
            "semantic_projection": {
                "text": text,
                "projection_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "numeric_content": "none",
                "embedding_policy": "private_evaluation_until_review",
            },
            "claim_boundary": {
                "supported_uses": ["Qualitative company orientation."],
                "prohibited_uses": ["Financial facts."],
                "issuer_claims": [],
            },
            "review": {
                "authorial": True,
                "source_traceable": True,
                "human_review": "pending",
                "product_eligible": False,
            },
        }

    def test_valid_artifact(self) -> None:
        self.assertEqual(MODULE.validate(self.artifact, self.schema), [])

    def test_rejects_unresolved_source_reference(self) -> None:
        self.artifact["authorial_context"]["product_families"][0]["source_ids"] = ["missing"]
        errors = MODULE.validate(self.artifact, self.schema)
        self.assertIn("sources:unresolved references:missing", errors)

    def test_rejects_projection_hash_mismatch(self) -> None:
        self.artifact["semantic_projection"]["projection_sha256"] = "0" * 64
        errors = MODULE.validate(self.artifact, self.schema)
        self.assertIn("semantic_projection:projection hash mismatch", errors)

    def test_rejects_numeric_projection(self) -> None:
        text = "Original context with 1 unsupported numeric claim."
        self.artifact["semantic_projection"]["text"] = text
        self.artifact["semantic_projection"]["projection_sha256"] = hashlib.sha256(text.encode()).hexdigest()
        errors = MODULE.validate(self.artifact, self.schema)
        self.assertIn("semantic_projection:numeric literal survived", errors)

    def test_accepts_declared_blocked_index_extract(self) -> None:
        source = self.artifact["sources"][0]
        source.pop("capture_sha256")
        source["http_status"] = 403
        source["http_response_sha256"] = "b" * 64
        source["retrieval_status"] = "direct_access_blocked_official_index_extract_used"
        source["evidence_method"] = "Official index extract; direct access blocked."
        self.assertEqual(MODULE.validate(self.artifact, self.schema), [])


if __name__ == "__main__":
    unittest.main()
