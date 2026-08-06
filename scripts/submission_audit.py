"""Audit the public ClaimCourt competition package without reading private workspaces."""

from __future__ import annotations

import json
import re
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parent.parent
SUBMISSION = ROOT / "submission"

REQUIRED_FILES = {
    "README.md": 5000,
    "requirements.txt": 100,
    "requirements-radeon.txt": 100,
    "submission/ClaimCourt_Project_Description.pdf": 100_000,
    "submission/ClaimCourt_Project_Description.docx": 50_000,
    "submission/ClaimCourt_Presentation.pptx": 100_000,
    "submission/DEMO_SCRIPT.md": 2000,
    "submission/PR_BODY.md": 1000,
    "docs/evidence/radeon-championship-live-20260805.json": 1000,
    "docs/evidence/radeon-fuzzy-holdout-live-20260805.json": 100_000,
}

ENGLISH_MATERIALS = (
    ROOT / "README.md",
    SUBMISSION / "PROJECT_DESCRIPTION.md",
    SUBMISSION / "DEMO_SCRIPT.md",
    SUBMISSION / "PR_BODY.md",
    SUBMISSION / "SUBMISSION_CHECKLIST.md",
    SUBMISSION / "PUBLIC_RELEASE_MANIFEST.md",
)

PUBLIC_SCAN_ROOTS = (
    ROOT / "README.md",
    ROOT / "requirements.txt",
    ROOT / "requirements-radeon.txt",
    ROOT / "api.py",
    ROOT / "app.py",
    ROOT / "core.py",
    ROOT / "frontend" / "src",
    ROOT / "scripts",
    ROOT / "training",
    ROOT / "tests",
    ROOT / "demo_corpus",
    ROOT / "championship_corpus",
    ROOT / "evaluation" / "fuzzy_holdout_v1",
    ROOT / "submission",
)

SECRET_PATTERNS = {
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key_body": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]{40,}?-----END [A-Z ]*PRIVATE KEY-----"),
}


def iter_text_files(path: Path):
    if path.is_file():
        yield path
        return
    for candidate in path.rglob("*"):
        if not candidate.is_file():
            continue
        if any(part in {"node_modules", "dist", "__pycache__"} for part in candidate.parts):
            continue
        if candidate.suffix.lower() in {".md", ".txt", ".py", ".json", ".jsonl", ".ts", ".tsx", ".js", ".cjs", ".html", ".eml"}:
            yield candidate


def main() -> int:
    checks: dict[str, object] = {}
    failures: list[str] = []
    warnings: list[str] = []

    file_checks = {}
    for relative, minimum in REQUIRED_FILES.items():
        path = ROOT / relative
        size = path.stat().st_size if path.exists() else 0
        passed = size >= minimum
        file_checks[relative] = {"exists": path.exists(), "bytes": size, "passed": passed}
        if not passed:
            failures.append(f"missing_or_small:{relative}")
    checks["required_files"] = file_checks

    english_checks = {}
    for path in ENGLISH_MATERIALS:
        text = path.read_text(encoding="utf-8")
        chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
        english_checks[str(path.relative_to(ROOT))] = {"chinese_characters": chinese, "passed": chinese == 0}
        if chinese:
            failures.append(f"non_english_material:{path.relative_to(ROOT)}")
    checks["english_materials"] = english_checks

    secret_hits = []
    seen: set[Path] = set()
    for scan_root in PUBLIC_SCAN_ROOTS:
        for path in iter_text_files(scan_root):
            if path in seen:
                continue
            seen.add(path)
            text = path.read_text(encoding="utf-8", errors="replace")
            for kind, pattern in SECRET_PATTERNS.items():
                for match in pattern.finditer(text):
                    value = match.group(0)
                    if "NOT_A_REAL_SECRET" in value or "[redacted]" in value.casefold():
                        continue
                    secret_hits.append({"file": str(path.relative_to(ROOT)), "kind": kind})
    checks["secret_scan"] = {"hits": secret_hits, "passed": not secret_hits}
    if secret_hits:
        failures.append("secret_shaped_content_detected")

    local_path_hits = []
    for path in ENGLISH_MATERIALS:
        text = path.read_text(encoding="utf-8")
        if re.search(r"[A-Za-z]:\\Users\\|/Users/[^/]+/|/home/[^/]+/", text):
            local_path_hits.append(str(path.relative_to(ROOT)))
    checks["personal_path_scan"] = {"hits": local_path_hits, "passed": not local_path_hits}
    if local_path_hits:
        failures.append("personal_path_in_submission_material")

    with ZipFile(SUBMISSION / "ClaimCourt_Project_Description.docx") as archive:
        docx_bad = archive.testzip()
        docx_has_document = "word/document.xml" in archive.namelist()
    checks["docx"] = {"valid_zip": docx_bad is None, "has_document_xml": docx_has_document, "passed": docx_bad is None and docx_has_document}
    if docx_bad is not None or not docx_has_document:
        failures.append("invalid_docx")

    with ZipFile(SUBMISSION / "ClaimCourt_Presentation.pptx") as archive:
        pptx_bad = archive.testzip()
        slide_count = len([name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)])
    checks["pptx"] = {"valid_zip": pptx_bad is None, "slides": slide_count, "passed": pptx_bad is None and slide_count == 10}
    if pptx_bad is not None or slide_count != 10:
        failures.append("invalid_pptx")

    try:
        import fitz

        document = fitz.open(SUBMISSION / "ClaimCourt_Project_Description.pdf")
        pdf_pages = len(document)
        pdf_text = "".join(page.get_text() for page in document)
        pdf_passed = pdf_pages == 6 and "ClaimCourt" in pdf_text and "Agent Architecture" in pdf_text
        checks["pdf"] = {"pages": pdf_pages, "text_characters": len(pdf_text), "passed": pdf_passed}
        if not pdf_passed:
            failures.append("invalid_project_pdf")
    except Exception as exc:
        checks["pdf"] = {"error": f"{type(exc).__name__}: {exc}", "passed": False}
        failures.append("invalid_project_pdf")

    championship = json.loads((ROOT / "docs/evidence/radeon-championship-live-20260805.json").read_text(encoding="utf-8"))
    holdout = json.loads((ROOT / "docs/evidence/radeon-fuzzy-holdout-live-20260805.json").read_text(encoding="utf-8"))
    live_passed = all((
        championship.get("embedding_active") is True,
        championship.get("memory_finder", {}).get("source") == "Customer_Delivery_Risk_Q4_Final.pptx",
        championship.get("court", {}).get("mode") == "local vLLM",
        holdout.get("runtime", {}).get("live_stack_passed") is True,
        holdout.get("metrics", {}).get("overall_pass_rate") == 1.0,
        holdout.get("metrics", {}).get("unsafe_wrong_auto_selections") == 0,
    ))
    checks["radeon_live_evidence"] = {"passed": live_passed}
    if not live_passed:
        failures.append("radeon_live_evidence_failed")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    pr_body = (SUBMISSION / "PR_BODY.md").read_text(encoding="utf-8")
    identity_passed = "Track 2, Zi Fei Yu, ClaimCourt" in readme and "Zi Fei Yu" in pr_body
    checks["submission_identity"] = {"passed": identity_passed}
    if not identity_passed:
        failures.append("submission_identity_mismatch")

    video_missing = "TBD" in pr_body
    checks["demo_video"] = {"public_url_present": not video_missing, "passed": not video_missing}
    if video_missing:
        warnings.append("demo_video_url_missing")

    result = {
        "schema": 1,
        "ready_except_video": not failures and video_missing,
        "ready_for_pr": not failures and not video_missing,
        "failures": failures,
        "warnings": warnings,
        "checks": checks,
    }
    output = SUBMISSION / "submission_audit.json"
    output.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
