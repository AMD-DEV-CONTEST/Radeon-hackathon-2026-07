#!/usr/bin/env python3
"""Corpus-first ProgramBench router.

This is the machine-checkable stoplight between "the corpus knows what to do"
and any expensive or provenance-sensitive action. It is intentionally pure by
default: consult corpus elsewhere, pass the answer here, and get a route record
that says whether official eval/autofix is allowed or whether the tool must go
through spec extraction, native reimpl, and local oracle first.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PB = ROOT / "corpus" / "programbench"


@dataclass(frozen=True)
class CorpusRoute:
    slug: str
    engine: str
    verdict: str
    official_eval_allowed: bool
    autofix_allowed: bool
    local_oracle_required: bool
    reason: str
    stages: list[dict[str, Any]] = field(default_factory=list)
    oracle_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _engine(answer: dict[str, Any]) -> str:
    return str(answer.get("engine") or answer.get("recommended_engine") or "")


def _source_class(answer: dict[str, Any]) -> str:
    shape = answer.get("source_shape") or {}
    return str(shape.get("class") or "")


def _path_from(blob: dict[str, Any] | None) -> str:
    return str((blob or {}).get("path") or "")


def _stage(name: str, command: list[str], reason: str) -> dict[str, Any]:
    return {"name": name, "command": command, "reason": reason}


def _oracle_green(oracle_result: dict[str, Any] | None) -> bool:
    if not oracle_result:
        return False
    try:
        passed = int(oracle_result.get("passed", -1))
        total = int(oracle_result.get("total", -2))
    except (TypeError, ValueError):
        return False
    return total > 0 and passed == total


def _oracle_seen(oracle_result: dict[str, Any] | None) -> bool:
    if not oracle_result:
        return False
    return "passed" in oracle_result and "total" in oracle_result


def _spec_stages(slug: str, spec_path: str) -> list[dict[str, Any]]:
    stages = []
    if spec_path:
        stages.append(
            _stage(
                "local-oracle",
                [
                    "python3",
                    "scripts/determinex_local_oracle.py",
                    "<candidate>",
                    "--spec",
                    spec_path,
                ],
                "validate the candidate against the harvested corpus spec before official eval",
            )
        )
    else:
        stages.append(
            _stage(
                "extract-spec",
                ["python3", "scripts/pb_bulk_spec.py", "--only", slug],
                "harvest the exact ProgramBench I/O contract before writing or evaluating",
            )
        )
    return stages


def route_from_corpus(
    answer: dict[str, Any],
    *,
    current_verdict: str = "",
    oracle_result: dict[str, Any] | None = None,
) -> CorpusRoute:
    """Return the allowed next action for one corpus consultation.

    The key invariant: official eval is allowed only for candidates that are not
    upstream-source trees and have already passed the local oracle when the
    corpus has a spec/skill for them.
    """
    slug = str(answer.get("slug") or "")
    engine = _engine(answer)
    source_class = _source_class(answer)
    spec = answer.get("spec") if isinstance(answer.get("spec"), dict) else None
    skill = answer.get("reimpl_skill") if isinstance(answer.get("reimpl_skill"), dict) else None
    spec_path = _path_from(spec)

    if source_class == "upstream-source-prohibited" or engine == "native-reimpl-loop":
        if _oracle_green(oracle_result):
            return CorpusRoute(
                slug=slug,
                engine=engine or "native-reimpl-loop",
                verdict="oracle-green-ready-for-official",
                official_eval_allowed=True,
                autofix_allowed=False,
                local_oracle_required=False,
                reason="native reimplementation passed local oracle; official eval may now measure the candidate",
                stages=[
                    _stage(
                        "official-eval",
                        ["python3", "scripts/pb_eval_unified.py", slug],
                        "candidate passed local oracle",
                    )
                ],
                oracle_result=oracle_result,
            )
        if _oracle_seen(oracle_result):
            return CorpusRoute(
                slug=slug,
                engine=engine or "native-reimpl-loop",
                verdict="oracle-red-needs-tail",
                official_eval_allowed=False,
                autofix_allowed=False,
                local_oracle_required=True,
                reason="native reimplementation still fails local oracle; patch the candidate before official eval",
                stages=_spec_stages(slug, spec_path),
                oracle_result=oracle_result,
            )

    if source_class == "upstream-source-prohibited" or engine == "native-reimpl-loop":
        lang = str((spec or {}).get("language") or "<native-lang>")
        return CorpusRoute(
            slug=slug,
            engine=engine or "native-reimpl-loop",
            verdict="needs-native-reimpl",
            official_eval_allowed=False,
            autofix_allowed=False,
            local_oracle_required=True,
            reason="current override is an upstream-source tree; Addendum H allows only native reimpl",
            stages=[
                _stage(
                    "extract-spec",
                    ["python3", "scripts/pb_bulk_spec.py", "--only", slug],
                    "turn the official tests into an exact I/O contract",
                ),
                _stage(
                    "write-native-reimpl",
                    [
                        "python3",
                        "scripts/determinex_reimpl_drive.py",
                        slug,
                        "--lang",
                        lang,
                        "--no-official",
                    ],
                    "write a few-file native reimplementation, not an upstream build",
                ),
                _stage(
                    "local-oracle",
                    [
                        "python3",
                        "scripts/determinex_local_oracle.py",
                        "<candidate>",
                        "--spec",
                        spec_path or "<spec>",
                    ],
                    "iterate locally until the candidate is green",
                ),
                _stage(
                    "official-eval-after-local-green",
                    ["python3", "scripts/pb_eval_unified.py", slug],
                    "spend official eval only after local oracle passes",
                ),
            ],
            oracle_result=oracle_result,
        )

    if engine == "extract-spec-first" or not spec_path:
        return CorpusRoute(
            slug=slug,
            engine=engine or "extract-spec-first",
            verdict="needs-spec-extraction",
            official_eval_allowed=False,
            autofix_allowed=False,
            local_oracle_required=True,
            reason="no harvested spec is available; extract corpus examples before fixing or evaluating",
            stages=_spec_stages(slug, ""),
            oracle_result=oracle_result,
        )

    if engine in {"reimpl-skill-oracle", "spec-local-oracle"} or spec or skill:
        stages = _spec_stages(slug, spec_path)
        if _oracle_green(oracle_result):
            return CorpusRoute(
                slug=slug,
                engine=engine or "spec-local-oracle",
                verdict="oracle-green-ready-for-official",
                official_eval_allowed=True,
                autofix_allowed=False,
                local_oracle_required=False,
                reason="local oracle is green; official eval may now measure the candidate",
                stages=[
                    _stage(
                        "official-eval",
                        ["python3", "scripts/pb_eval_unified.py", slug],
                        "candidate passed local oracle",
                    )
                ],
                oracle_result=oracle_result,
            )
        if _oracle_seen(oracle_result):
            return CorpusRoute(
                slug=slug,
                engine=engine or "spec-local-oracle",
                verdict="oracle-red-needs-tail",
                official_eval_allowed=False,
                autofix_allowed=False,
                local_oracle_required=True,
                reason="local oracle still fails; patch the candidate against all oracle failures first",
                stages=stages,
                oracle_result=oracle_result,
            )
        return CorpusRoute(
            slug=slug,
            engine=engine or "spec-local-oracle",
            verdict="needs-local-oracle-tail"
            if current_verdict == "near-lock"
            else "needs-local-oracle",
            official_eval_allowed=False,
            autofix_allowed=False,
            local_oracle_required=True,
            reason="corpus has a spec/skill; local oracle must pass before another official eval",
            stages=stages,
            oracle_result=oracle_result,
        )

    return CorpusRoute(
        slug=slug,
        engine=engine,
        verdict="corpus-route-unknown",
        official_eval_allowed=False,
        autofix_allowed=False,
        local_oracle_required=True,
        reason="corpus did not produce a safe eval route",
        stages=_spec_stages(slug, spec_path),
        oracle_result=oracle_result,
    )


def plan_tool(slug: str, oracle_result: dict[str, Any] | None = None) -> CorpusRoute:
    sys.path.insert(0, str(ROOT / "scripts"))
    import determinex_pb_ask_corpus as ask

    answer = ask.ask_corpus(slug)
    return route_from_corpus(answer, oracle_result=oracle_result)


def _load_oracle_result(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug")
    ap.add_argument("--oracle-result", help="JSON with passed/total from determinex_local_oracle")
    ap.add_argument("--json", action="store_true", help="emit only JSON")
    args = ap.parse_args(argv)

    route = plan_tool(args.slug, _load_oracle_result(args.oracle_result))
    data = route.to_dict()
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    print(f"{route.slug}: {route.verdict}")
    print(
        f"official_eval_allowed={route.official_eval_allowed} "
        f"autofix_allowed={route.autofix_allowed} "
        f"local_oracle_required={route.local_oracle_required}"
    )
    print(f"reason: {route.reason}")
    for stage in route.stages:
        print(f"- {stage['name']}: {' '.join(stage['command'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
