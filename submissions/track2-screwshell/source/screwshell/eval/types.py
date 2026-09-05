"""Data contracts for the evaluation gate (blueprint §3.10).

Pure dataclasses, stdlib only. Everything here is JSON round-trippable so a
report written today can be diffed against a report written next week --
`report.compare()` is the regression gate and it only works if the on-disk
shape is stable.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass
class EvalCase:
    """One golden-set item.

    Every field beyond `id`/`query` is an *objective* expectation. A case with
    no `must_cite`, `must_include` or `gold_chunks` is a case whose score is a
    matter of taste, and a gate built on taste does not gate anything -- see
    the loader, which refuses such cases.
    """

    id: str
    query: str
    workspace: str = "demo_workspace"
    kind: str = "qa"                    # qa|safety|rag|memory|routing|failure
    must_cite: list[str] = field(default_factory=list)
    must_not_cite: list[str] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)
    must_not_include: list[str] = field(default_factory=list)
    expect_skills: list[str] = field(default_factory=list)
    expect_refusal: bool = False
    expect_status: str = "ok"           # ok | degraded | failed
    gold_chunks: list[str] = field(default_factory=list)   # "path#Ls-Le"
    follow_up: Optional[str] = None
    max_seconds: Optional[float] = None
    tags: list[str] = field(default_factory=list)
    note: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "EvalCase":
        """Build a case from JSON, ignoring unknown keys.

        Tolerating unknown keys keeps an older harness able to read a newer
        case file (it simply scores fewer dimensions) instead of crashing the
        whole run on one field it has never heard of.
        """
        known = {f for f in cls.__dataclass_fields__}          # type: ignore[attr-defined]
        return cls(**{k: v for k, v in raw.items() if k in known})

    def to_dict(self) -> dict:
        return {
            "id": self.id, "query": self.query, "workspace": self.workspace,
            "kind": self.kind, "must_cite": list(self.must_cite),
            "must_not_cite": list(self.must_not_cite),
            "must_include": list(self.must_include),
            "must_not_include": list(self.must_not_include),
            "expect_skills": list(self.expect_skills),
            "expect_refusal": self.expect_refusal,
            "expect_status": self.expect_status,
            "gold_chunks": list(self.gold_chunks),
            "follow_up": self.follow_up, "max_seconds": self.max_seconds,
            "tags": list(self.tags), "note": self.note,
        }

    @property
    def objective(self) -> bool:
        """True when at least one machine-checkable expectation exists."""
        return bool(self.must_cite or self.must_include or self.gold_chunks
                    or self.must_not_cite or self.must_not_include
                    or self.expect_refusal or self.expect_skills
                    or self.expect_status != "ok")


@dataclass
class CaseResult:
    """What one case produced, plus everything the scorers need to judge it."""

    case_id: str
    answer: str = ""
    ok: bool = True
    scores: dict[str, float] = field(default_factory=dict)
    # Which scorers actually had something to measure on this case. Set by the
    # harness from `scorers.applies(name, case)`; `report.aggregate()` averages
    # each scorer ONLY over the cases where this is True -- folding a
    # "not applicable" 1.0 into the mean is how a gate stops meaning anything.
    applies: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    citations: dict = field(default_factory=dict)   # validator report (T4)
    seconds: float = 0.0
    error: Optional[str] = None
    follow_up_answer: Optional[str] = None
    # ---- extracted from the run so scorers stay pure functions ----
    skills: list[str] = field(default_factory=list)   # routed skills, in order
    retrieved: list[dict] = field(default_factory=list)  # citations actually seen
    status: str = "ok"                                # ok | degraded | failed

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id, "ok": self.ok, "status": self.status,
            "seconds": round(self.seconds, 3), "error": self.error,
            "scores": {k: round(v, 4) for k, v in sorted(self.scores.items())},
            "applies": {k: bool(v) for k, v in self.applies.items()},
            "answer": self.answer,
            "follow_up_answer": self.follow_up_answer,
            "skills": list(self.skills),
            "citations": self.citations,
            "retrieved": self.retrieved,
            "stats": self.stats,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "CaseResult":
        known = {f for f in cls.__dataclass_fields__}          # type: ignore[attr-defined]
        obj = cls(**{k: v for k, v in raw.items() if k in known})
        # `applies` may be absent from older on-disk reports; default to
        # "everything applied" so an aggregate never drops a scorer silently.
        if "applies" not in raw:
            obj.applies = {n: True for n in obj.scores}
        return obj


@dataclass
class EvalReport:
    """A whole eval run: what was measured, on what, and with which flags."""

    started: str
    git_sha: str = ""
    engine: str = "unknown"
    config: dict = field(default_factory=dict)
    cases: list[CaseResult] = field(default_factory=list)
    tag: str = ""
    repeats: int = 1
    scorers: list[str] = field(default_factory=list)
    seconds: float = 0.0

    # ---- delegation to report.py keeps the formatting logic in one file
    # while preserving the ergonomic `report.to_markdown()` call shape. The
    # imports are local because report.py imports this module.

    def aggregate(self) -> dict:
        from screwshell.eval.report import aggregate
        return aggregate(self)

    def to_dict(self) -> dict:
        return {
            "started": self.started, "git_sha": self.git_sha,
            "engine": self.engine, "tag": self.tag, "repeats": self.repeats,
            "seconds": round(self.seconds, 3),
            "config": self.config, "scorers": list(self.scorers),
            "aggregate": self.aggregate(),
            "cases": [c.to_dict() for c in self.cases],
        }

    def to_json(self, path: str) -> str:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)
        return path

    def to_markdown(self) -> str:
        from screwshell.eval.report import to_markdown
        return to_markdown(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "EvalReport":
        return cls(
            started=raw.get("started", ""), git_sha=raw.get("git_sha", ""),
            engine=raw.get("engine", "unknown"), config=raw.get("config") or {},
            cases=[CaseResult.from_dict(c) for c in raw.get("cases") or []],
            tag=raw.get("tag", ""), repeats=int(raw.get("repeats", 1) or 1),
            scorers=list(raw.get("scorers") or []),
            seconds=float(raw.get("seconds", 0.0) or 0.0),
        )

    @classmethod
    def load(cls, path: str) -> "EvalReport":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


@runtime_checkable
class Scorer(Protocol):
    """A pure function from (result, case) to a 0.0-1.0 quality score."""

    name: str

    def __call__(self, res: CaseResult, case: EvalCase) -> float:
        ...


def as_report_dict(obj: Any) -> dict:
    """Accept either an ``EvalReport`` or an already-serialised dict.

    ``compare()`` is called both with a live report (in-process A/B) and with a
    baseline loaded from disk; normalising here keeps that dual entry point
    from leaking into every caller.
    """
    if isinstance(obj, EvalReport):
        return obj.to_dict()
    if isinstance(obj, dict):
        return obj
    raise TypeError(f"expected EvalReport or dict, got {type(obj).__name__}")
