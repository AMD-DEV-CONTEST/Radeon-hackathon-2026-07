#!/usr/bin/env python3
"""Verify ProgramBench native candidates are not Python-only wrappers.

This guard is for corpus quality, not orchestration code. Python queue/gate
scripts are fine; native ProgramBench tool implementations must ship real
native source when the upstream tool is Go/Rust/C/C++.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / "corpus" / "programbench" / "per_tool_overrides"
AUDIT = ROOT / "logs" / "programbench_factory" / "LANGUAGE_AUDIT.json"


NATIVE_MARKERS = {
    "rust": ["Cargo.toml", "src/main.rs", "src/lib.rs"],
    "go": ["go.mod", "main.go"],
    "c": ["main.c", "Makefile"],
    "cpp": ["main.cpp", "CMakeLists.txt", "Makefile"],
}


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _audit_by_slug() -> dict[str, dict[str, Any]]:
    rows = _load_json(AUDIT, [])
    return {r.get("slug"): r for r in rows if r.get("slug")}


def _source_dir(path: Path) -> Path:
    if (path / "source").is_dir():
        return path / "source"
    return path


def _detect_native_lang(src: Path) -> str | None:
    if (src / "Cargo.toml").is_file() or any(src.glob("src/**/*.rs")):
        return "rust"
    if (src / "go.mod").is_file() or any(src.glob("*.go")) or any(src.glob("cmd/**/*.go")):
        return "go"
    if any(src.glob("*.cpp")) or any(src.glob("**/*.cpp")) or (src / "CMakeLists.txt").is_file():
        return "cpp"
    if any(src.glob("*.c")) or any(src.glob("**/*.c")):
        return "c"
    if (
        any(src.glob("*.cabal"))
        or (src / "stack.yaml").is_file()
        or (src / "cabal.project").is_file()
        or any(src.glob("**/*.hs"))
    ):
        return "haskell"
    if (
        (src / "pom.xml").is_file()
        or (src / "build.gradle").is_file()
        or (src / "project.clj").is_file()
        or any(src.glob("**/*.java"))
        or any(src.glob("**/*.clj"))
    ):
        return "java"
    return None


def _main_py_substantive(src: Path) -> tuple[bool, int, bool]:
    main_py = src / "main.py"
    if not main_py.is_file():
        return False, 0, False
    text = main_py.read_text(encoding="utf-8", errors="replace")
    lines = [
        ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")
    ]
    wrapper_tokens = ("os.execv(", "os.execvp(", "subprocess.run(", "exec(")
    thin = len(lines) <= 8 and any(tok in text for tok in wrapper_tokens)
    return True, len(lines), thin


def _has_bundled_binary(src: Path) -> bool:
    for f in src.iterdir():
        if not f.is_file():
            continue
        if f.name in {"compile.sh", "main.py"}:
            continue
        try:
            head = f.read_bytes()[:4]
        except OSError:
            continue
        if head == b"\x7fELF" or head[:2] == b"MZ":
            return True
    return False


def check_path(
    path: Path,
    *,
    slug: str | None = None,
    strict: bool = True,
    allow_keep_thin: bool = False,
) -> dict[str, Any]:
    src = _source_dir(path)
    if not src.is_dir():
        return {"ok": False, "reason": "source directory missing", "path": str(path)}
    slug = slug or path.name
    audit = _audit_by_slug().get(slug, {})
    audit_lang = audit.get("source_language") or ""
    action = audit.get("action") or ""
    detected = _detect_native_lang(src)
    has_main_py, py_lines, thin_py = _main_py_substantive(src)
    has_binary = _has_bundled_binary(src)

    if audit_lang == "python" or action == "keep-python":
        return {
            "ok": True,
            "reason": "python upstream",
            "slug": slug,
            "audit_language": audit_lang,
            "detected_language": detected,
            "main_py_lines": py_lines,
        }

    if detected:
        if has_main_py and not thin_py:
            return {
                "ok": False,
                "reason": "substantive main.py logic in native candidate",
                "slug": slug,
                "audit_language": audit_lang,
                "audit_action": action,
                "detected_language": detected,
                "main_py_lines": py_lines,
                "thin_main_py": thin_py,
                "bundled_binary": has_binary,
            }
        return {
            "ok": True,
            "reason": "native source present",
            "slug": slug,
            "audit_language": audit_lang,
            "audit_action": action,
            "detected_language": detected,
            "main_py_lines": py_lines,
            "thin_main_py": thin_py,
            "bundled_binary": has_binary,
        }

    if action == "keep-thin" and allow_keep_thin and thin_py and has_binary:
        return {
            "ok": True,
            "reason": "allowed keep-thin binary wrapper",
            "slug": slug,
            "audit_language": audit_lang,
            "audit_action": action,
            "detected_language": detected,
            "main_py_lines": py_lines,
            "thin_main_py": thin_py,
            "bundled_binary": has_binary,
        }

    return {
        "ok": not strict,
        "reason": "wrapper/native-source debt" if has_main_py else "no native source marker",
        "slug": slug,
        "audit_language": audit_lang,
        "audit_action": action,
        "detected_language": detected,
        "main_py_lines": py_lines,
        "thin_main_py": thin_py,
        "bundled_binary": has_binary,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="*", help="override/source/run-root paths")
    ap.add_argument("--slug")
    ap.add_argument("--all-overrides", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-strict", action="store_true")
    ap.add_argument(
        "--allow-keep-thin",
        action="store_true",
        help="permit transparent binary wrappers for audit action keep-thin",
    )
    ap.add_argument("--gap-json", type=Path, help="write failing rows to this JSON file")
    ap.add_argument("--gap-md", type=Path, help="write failing rows to this Markdown file")
    args = ap.parse_args()

    targets: list[tuple[Path, str | None]] = []
    if args.all_overrides:
        targets.extend((p, p.name) for p in sorted(OVERRIDES.iterdir()) if p.is_dir())
    for p in args.paths:
        targets.append((Path(p), args.slug))
    if not targets:
        ap.error("provide paths or --all-overrides")

    results = [
        check_path(
            p,
            slug=s,
            strict=not args.no_strict,
            allow_keep_thin=args.allow_keep_thin,
        )
        for p, s in targets
    ]
    gaps = [r for r in results if not r.get("ok")]
    if args.gap_json:
        args.gap_json.parent.mkdir(parents=True, exist_ok=True)
        args.gap_json.write_text(json.dumps(gaps, indent=2) + "\n", encoding="utf-8")
    if args.gap_md:
        args.gap_md.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# ProgramBench Native Source Gaps",
            "",
            "Non-Python ProgramBench overrides listed here still lack native source or contain Python wrapper logic. Python-upstream tools are excluded.",
            "",
            f"Total gaps: {len(gaps)}",
            "",
            "| slug | reason | audit language | action | detected | main.py lines | bundled binary |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for r in gaps:
            lines.append(
                "| {slug} | {reason} | {audit_language} | {audit_action} | {detected_language} | {main_py_lines} | {bundled_binary} |".format(
                    slug=r.get("slug", ""),
                    reason=r.get("reason", ""),
                    audit_language=r.get("audit_language") or "",
                    audit_action=r.get("audit_action") or "",
                    detected_language=r.get("detected_language") or "",
                    main_py_lines=r.get("main_py_lines", 0),
                    bundled_binary="yes" if r.get("bundled_binary") else "no",
                )
            )
        args.gap_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            status = "OK" if r["ok"] else "FAIL"
            print(
                f"{status} {r.get('slug', '?')}: {r['reason']} "
                f"(audit={r.get('audit_language') or '?'}, detected={r.get('detected_language') or '?'}, "
                f"main_py_lines={r.get('main_py_lines', 0)})"
            )
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
