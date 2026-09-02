"""Run swebench eval harness on Windows (stubs Unix-only 'resource' module)."""

import argparse
import builtins
import io
import locale
import pathlib
import sys
import types

# ── Windows UTF-8 fix ──────────────────────────────────────────────────────
# swebench uses open() and Path.write_text() without encoding= throughout.
# On Windows the default is cp1252, which crashes on the eval scripts.
# Fix: make ALL text-mode file I/O default to UTF-8.

# 1. Patch locale so open() picks up UTF-8 as preferred encoding.
locale.getpreferredencoding = lambda do_setlocale=True: "utf-8"

# 2. Patch pathlib.Path.write_text (called at swebench line 199).
_orig_write_text = pathlib.Path.write_text


def _utf8_write_text(self, data, encoding=None, errors=None, newline=None):
    return _orig_write_text(
        self, data, encoding=encoding or "utf-8", errors=errors, newline=newline
    )


pathlib.Path.write_text = _utf8_write_text  # type: ignore[method-assign]

# 3. Patch pathlib.Path.read_text too (symmetric, avoids decode errors).
_orig_read_text = pathlib.Path.read_text


def _utf8_read_text(self, encoding=None, errors=None):
    return _orig_read_text(self, encoding=encoding or "utf-8", errors=errors)


pathlib.Path.read_text = _utf8_read_text  # type: ignore[method-assign]

# 4. Patch builtins.open so f.write(test_output) at swebench line 212 works.
_orig_open = builtins.open


def _utf8_open(
    file,
    mode="r",
    buffering=-1,
    encoding=None,
    errors=None,
    newline=None,
    closefd=True,
    opener=None,
):
    if encoding is None and "b" not in mode:
        encoding = "utf-8"
    return _orig_open(file, mode, buffering, encoding, errors, newline, closefd, opener)


builtins.open = _utf8_open  # type: ignore[assignment]
io.open = _utf8_open  # type: ignore[assignment]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_r = types.ModuleType("resource")
_r.getrlimit = lambda x: (1024, 4096)
_r.setrlimit = lambda x, y: None
_r.RLIMIT_NOFILE = 7
sys.modules["resource"] = _r

from swebench.harness.run_evaluation import main  # type: ignore[import]

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("-p", "--predictions_path", required=True)
    p.add_argument("-id", "--run_id", required=True)
    p.add_argument("--max_workers", type=int, default=2)
    p.add_argument("--dataset_name", default="princeton-nlp/SWE-bench_Lite")
    p.add_argument("--split", default="test")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--cache_level", default="env")
    p.add_argument("--report_dir", default="logs/swebench/eval_results")
    p.add_argument("--force_rebuild", type=bool, default=False)
    p.add_argument("--clean", type=bool, default=False)
    p.add_argument("--open_file_limit", type=int, default=4096)
    p.add_argument("--namespace", default=None)
    p.add_argument("--rewrite_reports", type=bool, default=False)
    p.add_argument("--modal", type=bool, default=False)
    p.add_argument("--instance_ids", nargs="*", default=[])
    args = p.parse_args()

    main(
        dataset_name=args.dataset_name,
        split=args.split,
        instance_ids=args.instance_ids,
        predictions_path=args.predictions_path,
        max_workers=args.max_workers,
        force_rebuild=args.force_rebuild,
        cache_level=args.cache_level,
        clean=args.clean,
        open_file_limit=args.open_file_limit,
        run_id=args.run_id,
        timeout=args.timeout,
        namespace=args.namespace,
        rewrite_reports=args.rewrite_reports,
        modal=args.modal,
        report_dir=args.report_dir,
    )
