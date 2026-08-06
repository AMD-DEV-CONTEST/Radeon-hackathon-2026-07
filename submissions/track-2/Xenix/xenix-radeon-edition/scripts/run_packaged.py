from __future__ import annotations

# This must remain the first application operation. Velopack may exit from run()
# while handling install/update hooks.
import velopack

velopack.App().set_auto_apply_on_startup(False).run()

import os
import sys
import time


_STARTUP_TIMING_T0 = time.perf_counter()


def _startup_timing_enabled() -> bool:
    return os.environ.get("XENIX_STARTUP_TIMING", "").strip().lower() in {"1", "true", "yes", "on"}


def _emit_startup_timing(event: str, start: float | None = None) -> None:
    if not _startup_timing_enabled():
        return
    fields = [
        "XENIX_STARTUP_TIMING",
        event,
        f"since_run_packaged_start_ms={(time.perf_counter() - _STARTUP_TIMING_T0) * 1000:.3f}",
    ]
    if start is not None:
        fields.append(f"elapsed_ms={(time.perf_counter() - start) * 1000:.3f}")
    print("\t".join(fields), file=sys.stderr, flush=True)


def main() -> int:
    _emit_startup_timing("run_packaged.main.start")

    if len(sys.argv) >= 2 and sys.argv[1] == "--analysis-lambda-worker":
        import_start = time.perf_counter()
        from xenix.services.analysis_lambda_worker import main as worker_main

        _emit_startup_timing("run_packaged.import_analysis_lambda_worker", import_start)
        if len(sys.argv) != 4:
            raise SystemExit("Usage: xenix --analysis-lambda-worker <input-json> <output-json>")
        worker_main(sys.argv[2], sys.argv[3])
        return 0

    import_start = time.perf_counter()
    from xenix.main import main as application_main

    _emit_startup_timing("run_packaged.import_xenix_main", import_start)
    call_start = time.perf_counter()
    exit_code = application_main(sys.argv[1:])
    _emit_startup_timing("run_packaged.application_main", call_start)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
