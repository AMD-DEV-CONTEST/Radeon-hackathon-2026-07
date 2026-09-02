from __future__ import annotations

import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "audit_restricted_egress.py"
SPEC = importlib.util.spec_from_file_location("audit_restricted_egress", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RestrictedEgressAuditTests(unittest.TestCase):
    def test_blocked_rights_with_body_fails(self) -> None:
        payload = {
            "document_id": "restricted-doc",
            "rights_class": "reference_only_pending_review",
            "text": "prohibited body",
        }
        findings = MODULE.blocked_rights_body_findings(payload)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["body_fields"], ["$.text"])

    def test_blocked_rights_metadata_without_body_passes(self) -> None:
        payload = {
            "document_id": "restricted-doc",
            "rights_class": "reference_only_pending_review",
            "source_uri": "https://example.test/reference",
        }
        self.assertEqual(MODULE.blocked_rights_body_findings(payload), [])

    def test_nested_pending_rights_with_sibling_body_fails(self) -> None:
        payload = {
            "sources": [{"permissionStatus": "pending_review"}],
            "authorial_context": {"business_description": "source-derived body"},
        }
        findings = MODULE.blocked_rights_body_findings(payload)
        self.assertEqual(len(findings), 1)
        self.assertEqual(
            findings[0]["body_fields"],
            ["$.authorial_context", "$.authorial_context.business_description"],
        )

    def test_reference_only_authorial_summary_is_not_a_blocked_state(self) -> None:
        payload = {
            "document_id": "reviewed-reference",
            "rights_class": "reference_only",
            "text": "Bounded original summary.",
        }
        self.assertEqual(MODULE.blocked_rights_body_findings(payload), [])

    def test_reference_manifest_rejects_body_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "fixtures" / "investor-relations" / "document-manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    {
                        "documents": [
                            {
                                "document_id": "reference",
                                "rights_class": "reference_only",
                                "content": "redistributed body",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            findings, count = MODULE.audit_reference_manifest(root)
            self.assertEqual(count, 1)
            self.assertEqual(len(findings), 1)
            self.assertIn("$.documents[0].content", findings[0]["body_fields"])

    def test_final_stage_rejects_broad_copy(self) -> None:
        dockerfile = """
FROM golang:1 AS build
COPY . .
FROM alpine:3
COPY . /app
"""
        findings, _observed = MODULE.audit_final_image_copy_boundary(dockerfile)
        self.assertTrue(any(item.get("error") == "broad or wildcard COPY is forbidden in final image stage" for item in findings))

    def test_builder_broad_copy_and_exact_final_allowlist_pass(self) -> None:
        dockerfile = """
FROM golang:1 AS backend
COPY . .
FROM node:1 AS web
COPY web/ ./
FROM alpine:3
COPY --from=backend /out/signalforge-workspace /usr/local/bin/signalforge-workspace
COPY --from=web /source/web/dist /app/web/dist
COPY --from=backend /out/licenses /app/licenses
COPY --from=web /out/font-licenses /app/licenses/fonts
COPY fixtures/workspace /app/fixtures/workspace
COPY fixtures/golden /app/fixtures/golden
COPY fixtures/retrieval /app/fixtures/retrieval
COPY fixtures/productscope /app/fixtures/productscope
"""
        findings, observed = MODULE.audit_final_image_copy_boundary(dockerfile)
        self.assertEqual(findings, [])
        self.assertEqual(len(observed), 8)

    def test_jsonl_blocked_rights_with_body_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "fixtures" / "workspace" / "leak.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"rights_class": "pending_review", "text": "blocked"}) + "\n",
                encoding="utf-8",
            )
            findings, count = MODULE.audit_public_json(
                root, [Path("fixtures/workspace/leak.jsonl")]
            )
            self.assertEqual(count, 1)
            self.assertEqual(len(findings), 1)

    def test_structured_allowed_path_symlink_is_rejected_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "repo"
            root.mkdir()
            external = parent / "external.json"
            external.write_text(
                json.dumps({"rights_class": "pending_review", "text": "must-not-be-read"}),
                encoding="utf-8",
            )
            alias = root / "fixtures" / "workspace" / "alias.json"
            alias.parent.mkdir(parents=True)
            alias.symlink_to(external)

            findings, count = MODULE.audit_public_json(
                root, [Path("fixtures/workspace/alias.json")]
            )

            self.assertEqual(count, 0)
            self.assertEqual(len(findings), 1)
            self.assertIn("path uses a symlink", findings[0]["error"])

    def test_final_runtime_data_rejects_unsupported_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "fixtures" / "workspace" / "leak.txt"
            path.parent.mkdir(parents=True)
            path.write_text("blocked body", encoding="utf-8")
            findings, count = MODULE.audit_public_json(
                root, [Path("fixtures/workspace/leak.txt")]
            )
            self.assertEqual(count, 0)
            self.assertEqual(
                findings[0]["error"], "unsupported final-image runtime data format"
            )

    def test_final_stage_rejects_run_mount(self) -> None:
        dockerfile = """
FROM golang:1 AS backend
FROM node:1 AS web
FROM alpine:3
RUN --mount=type=bind,source=.,target=/context cp /context/leak /app/leak
COPY --from=backend /out/signalforge-workspace /usr/local/bin/signalforge-workspace
COPY --from=web /source/web/dist /app/web/dist
COPY --from=backend /out/licenses /app/licenses
COPY --from=web /out/font-licenses /app/licenses/fonts
COPY fixtures/workspace /app/fixtures/workspace
COPY fixtures/golden /app/fixtures/golden
COPY fixtures/retrieval /app/fixtures/retrieval
COPY fixtures/productscope /app/fixtures/productscope
"""
        findings, _observed = MODULE.audit_final_image_copy_boundary(dockerfile)
        self.assertTrue(
            any(item.get("error") == "RUN --mount is forbidden in final image stage" for item in findings)
        )

    def test_heredoc_content_cannot_reset_final_stage(self) -> None:
        dockerfile = """
FROM golang:1 AS backend
FROM node:1 AS web
FROM alpine:3
COPY . /app
RUN <<EOF
FROM not-a-real-stage
COPY --from=backend /out/signalforge-workspace /usr/local/bin/signalforge-workspace
COPY --from=web /source/web/dist /app/web/dist
COPY fixtures/workspace /app/fixtures/workspace
COPY fixtures/golden /app/fixtures/golden
COPY fixtures/retrieval /app/fixtures/retrieval
COPY fixtures/productscope /app/fixtures/productscope
EOF
"""
        findings, _observed = MODULE.audit_final_image_copy_boundary(dockerfile)
        self.assertTrue(
            any(item.get("error") == "broad or wildcard COPY is forbidden in final image stage" for item in findings)
        )

    def test_judge_binary_must_be_inside_public_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "repo"
            (root / "evidence").mkdir(parents=True)
            external = parent / "external.pdf"
            external.write_bytes(b"external")
            (root / "evidence" / "judge-package.json").write_text(
                json.dumps(
                    {
                        "artifacts": {
                            "deck": {
                                "path": str(external),
                                "sha256": hashlib.sha256(external.read_bytes()).hexdigest(),
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            findings, artifacts = MODULE.audit_judge_binaries(root, set())
            self.assertEqual(artifacts, [])
            self.assertEqual(
                findings[0]["error"], "artifact path escapes repository candidate"
            )

    def test_judge_package_symlink_is_rejected_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "repo"
            (root / "evidence").mkdir(parents=True)
            external = parent / "external.json"
            external.write_text(
                json.dumps(
                    {
                        "artifacts": {
                            "EXTERNAL_SENTINEL": {
                                "path": "evidence/external.pdf",
                                "sha256": "0" * 64,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            (root / "evidence" / "judge-package.json").symlink_to(external)

            findings, artifacts = MODULE.audit_judge_binaries(root, set())

            self.assertEqual(artifacts, [])
            self.assertEqual(len(findings), 1)
            self.assertEqual(
                findings[0]["error"],
                "judge package path escapes repository candidate or uses a symlink",
            )
            self.assertNotIn("EXTERNAL_SENTINEL", json.dumps(findings))

    def test_prohibited_sealed_path_is_classified_without_reading(self) -> None:
        self.assertEqual(
            MODULE.prohibited_public_path(Path("experiments/sprint32/holdout/cases.json")),
            "sealed evaluation material",
        )


if __name__ == "__main__":
    unittest.main()
