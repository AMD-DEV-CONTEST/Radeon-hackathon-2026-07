from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


_STARTUP_TIMING_T0 = time.perf_counter()


def _startup_timing_enabled() -> bool:
    return os.environ.get("XENIX_STARTUP_TIMING", "").strip().lower() in {"1", "true", "yes", "on"}


def _emit_startup_timing(event: str, start: float | None = None) -> None:
    if not _startup_timing_enabled():
        return
    fields = [
        "XENIX_STARTUP_TIMING",
        event,
        f"since_run_dev_start_ms={(time.perf_counter() - _STARTUP_TIMING_T0) * 1000:.3f}",
    ]
    if start is not None:
        fields.append(f"elapsed_ms={(time.perf_counter() - start) * 1000:.3f}")
    print("\t".join(fields), file=sys.stderr, flush=True)


def _configure_development_ocr_bundle_source(project_root: Path) -> None:
    """Expose the generated local OCR archive as one explicit dev source."""

    if any(
        os.environ.get(name, "").strip()
        for name in (
            "XENIX_KNOWLEDGE_OCR_CATALOG",
            "XENIX_KNOWLEDGE_OCR_ARTIFACT",
        )
    ):
        return
    catalog_path = project_root / "dist" / "knowledge-ocr" / "runtime_catalog.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        artifact_name = catalog.get("artifact_name") if isinstance(catalog, dict) else None
    except (OSError, ValueError):
        return
    if (
        not isinstance(artifact_name, str)
        or not artifact_name
        or Path(artifact_name).name != artifact_name
    ):
        return
    os.environ["XENIX_KNOWLEDGE_OCR_CATALOG"] = str(catalog_path)
    os.environ["XENIX_KNOWLEDGE_OCR_ARTIFACT"] = str(catalog_path.parent / artifact_name)


def main() -> int:
    _emit_startup_timing("run_dev.main.start")
    project_root = Path(__file__).resolve().parents[1]
    src_path = project_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    _emit_startup_timing("run_dev.path.ready")
    _configure_development_ocr_bundle_source(project_root)
    _emit_startup_timing("run_dev.ocr_bundle_source.ready")

    if len(sys.argv) >= 2 and sys.argv[1] == "--analysis-lambda-worker":
        import_start = time.perf_counter()
        from xenix.services.analysis_lambda_worker import main as worker_main
        _emit_startup_timing("run_dev.import_analysis_lambda_worker", import_start)

        if len(sys.argv) != 4:
            raise SystemExit("Usage: xenix --analysis-lambda-worker <input-json> <output-json>")
        worker_main(sys.argv[2], sys.argv[3])
        return 0

    import_start = time.perf_counter()
    from xenix.main import main as application_main
    _emit_startup_timing("run_dev.import_xenix_main", import_start)

    call_start = time.perf_counter()
    exit_code = application_main(sys.argv[1:])
    _emit_startup_timing("run_dev.application_main", call_start)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
