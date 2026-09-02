#!/usr/bin/env python3
"""Determinex canonical eval-report reader.

ONE place that understands a ProgramBench eval JSON, so the status vocabulary
(`passed` / `failure` / `error` / `not_run` / `skipped`), bidirectional
test duplication (`eval.tests.*` <-> `tests.*`), and the score formula are never
re-derived in ad-hoc one-liners again. (The `failed`-vs-`failure` counting bug
came from exactly that re-derivation.)

It also parses each failing test's pytest traceback into a structured record --
the invocation argv, stdin, returncode, and the EXPECTED side of the assertion
-- which the I/O extractor and local oracle consume as ground truth.

Official ProgramBench score = passed / total, where total counts
not_run / skipped / error (NOT just runnable). A lock requires
passed == total AND not_run == 0 AND no eval override.

CANONICAL: this is the one eval-JSON reader. New code that needs a score, a
status breakdown, or parsed failures should `from determinex_eval_report import
load` rather than re-deriving `test_results` parsing (which is how the
`failed`-vs-`failure` counting bug kept recurring across ad-hoc one-liners).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

# Canonical status keywords as emitted by the programbench scorer. Never guess
# these -- read them from here.
PASSED = "passed"
FAILURE = "failure"  # NOT "failed"
ERROR = "error"
NOT_RUN = "not_run"
SKIPPED = "skipped"

# Pulls `CompletedProcess(args=['./executable', '-u', '5'], returncode=0, ...)`
RE_COMPLETED = re.compile(r"CompletedProcess\(args=(\[[^\]]*\])(?:,\s*returncode=(-?\d+))?", re.S)
RE_RUNRESULT_RC = re.compile(r"\b(?:rc|code|returncode)\s*=\s*(-?\d+)")
# `assert <left> == <expected>` and `assert <snippet> in <...>`
RE_ASSERT_RC = re.compile(
    r"returncode\s*==\s*(-?\d+)|\.code\s*==\s*(-?\d+)"
    r"|\brc\s*==\s*(-?\d+)"
)
RE_ASSERT_IN = re.compile(r"assert\s+(b?(['\"]).*?\2)\s+in\b")
RE_PARAM_ID = re.compile(r"\[([^\]]+)\]\s*$")


class TestResult(BaseModel):
    """One raw `test_results[]` entry -- the actual WAL/JSON boundary where an
    external eval harness's output enters Determinex. Validated on the way
    in instead of naked dict.get() so a malformed/unexpected shape from an
    eval harness fails loudly at load() rather than silently producing a
    wrong score somewhere downstream."""

    model_config = {"extra": "allow"}  # eval JSON carries more fields than we use

    name: str = ""
    status: str = ""
    # Deliberately Any, not dict | str: the original bare .get() stringified
    # whatever it found here (isinstance(extra, dict) else str(extra or "")).
    # name/status genuinely should always be strings and are worth validating
    # strictly; extra's only consumer is "extract text for traceback parsing"
    # and any type it might legitimately be still needs to flow through to
    # that same fallback, not get rejected as a malformed entry.
    extra: object = ""


class FailRecord(BaseModel):
    name: str
    short: str  # bare test_name (no namespace/param)
    status: str
    argv: list = Field(default_factory=list)  # reconstructed command argv
    returncode_actual: int | None = None
    expect_rc: int | None = None
    expect_in: list = Field(default_factory=list)  # snippets asserted present
    param_id: str | None = None
    text: str = ""  # raw traceback (trimmed)


class EvalReport(BaseModel):
    path: str
    total: int
    passed: int
    counts: dict
    unique_total: int  # de-duplicated across bidir namespaces
    unique_passed: int
    failures: list[FailRecord]
    is_lock: bool
    not_run: int

    @property
    def score(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def summary(self) -> str:
        nr = self.not_run
        lock = " LOCK" if self.is_lock else ""
        return (
            f"{self.passed}/{self.total} ({100 * self.score:.1f}%) "
            f"[unique {self.unique_passed}/{self.unique_total}] "
            f"not_run={nr} {dict(self.counts)}{lock}"
        )


def _bare(name: str) -> str:
    """Strip namespace + parametrize id -> bare test function name."""
    n = name.split("[")[0]
    return n.split(".")[-1]


def _parse_traceback(name: str, text: str) -> FailRecord:
    rec = FailRecord(name=name, short=_bare(name), status=FAILURE, text=text[:4000])
    pm = RE_PARAM_ID.search(name)
    if pm:
        rec.param_id = pm.group(1)
    if not text:
        # parametrize id sometimes carries the expected snippet / rc
        if rec.param_id:
            for mlit in RE_ASSERT_IN.findall(rec.param_id):
                rec.expect_in.append(mlit[0])
        return rec
    m = RE_COMPLETED.search(text)
    if m:
        try:
            rec.argv = json.loads(m.group(1).replace("'", '"'))
        except Exception:
            rec.argv = []
        if m.group(2) is not None:
            rec.returncode_actual = int(m.group(2))
    else:
        rcm = RE_RUNRESULT_RC.search(text)
        if rcm:
            rec.returncode_actual = int(rcm.group(1))
    rcm = RE_ASSERT_RC.search(text)
    if rcm:
        rec.expect_rc = int(next(g for g in rcm.groups() if g is not None))
    for mlit in RE_ASSERT_IN.findall(text):
        rec.expect_in.append(mlit[0])
    return rec


def load(path: str | Path) -> EvalReport:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    results = data.get("test_results", [])
    counts: Counter = Counter()
    failures: list[FailRecord] = []
    uniq_status: dict[str, str] = {}  # bare name -> best status (passed wins)

    for raw in results:
        # Validated WAL/JSON boundary: a genuinely malformed entry (wrong
        # type for name/status/extra) is logged and treated as an empty
        # record rather than either silently corrupting the score (the old
        # bare .get() behavior) or aborting the whole report over one bad
        # entry out of possibly thousands.
        try:
            t = TestResult.model_validate(raw)
        except ValidationError as exc:
            print(f"[determinex_eval_report] malformed test_results entry in {p}: {exc}")
            t = TestResult()
        name = t.name
        status = t.status
        counts[status] += 1
        pid_m = RE_PARAM_ID.search(name)
        bare = _bare(name) + "|" + (pid_m.group(1) if pid_m else "")
        prev = uniq_status.get(bare)
        if prev != PASSED:
            uniq_status[bare] = status if (prev is None or status == PASSED) else prev
        if status not in (PASSED, SKIPPED):
            extra = t.extra
            text = extra.get("text", "") if isinstance(extra, dict) else str(extra or "")
            failures.append(_parse_traceback(name, text))

    total = len(results)
    passed = counts.get(PASSED, 0)
    uniq_total = len(uniq_status)
    uniq_passed = sum(1 for s in uniq_status.values() if s == PASSED)
    not_run = counts.get(NOT_RUN, 0)
    is_lock = (
        passed == total
        and total > 0
        and not_run == 0
        and counts.get(SKIPPED, 0) == 0
        and counts.get(ERROR, 0) == 0
    )
    return EvalReport(
        path=str(p),
        total=total,
        passed=passed,
        counts=dict(counts),
        unique_total=uniq_total,
        unique_passed=uniq_passed,
        failures=failures,
        is_lock=is_lock,
        not_run=not_run,
    )


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="Determinex canonical eval-report reader")
    ap.add_argument("eval_jsons", nargs="+")
    ap.add_argument("--json", action="store_true", help="emit machine JSON")
    ap.add_argument("--failures", action="store_true", help="list parsed failures")
    a = ap.parse_args(argv)
    out = {}
    for ej in a.eval_jsons:
        rep = load(ej)
        short = Path(ej).name.split("__")[-1].split(".")[0]
        if a.json:
            out[short] = {
                **{k: v for k, v in rep.model_dump().items() if k != "failures"},
                "score": rep.score,
            }
        else:
            print(f"{short:18} {rep.summary()}")
            if a.failures:
                for f in rep.failures[:40]:
                    exp = f"rc={f.expect_rc}" if f.expect_rc is not None else ""
                    inn = (" in:" + ",".join(f.expect_in[:2])) if f.expect_in else ""
                    print(f"    {f.short:42} argv={f.argv} act_rc={f.returncode_actual} {exp}{inn}")
    if a.json:
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
