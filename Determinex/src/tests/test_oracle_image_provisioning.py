"""Getting the sandbox image is not compiling, and must not be charged to the compile budget.

WHY THIS EXISTS
---------------
Found 2026-07-30 (S9). `_docker_oracle_run` let `docker run` do its own implicit image pull,
inside `timeout + 60` -- where `COMPILE_TIMEOUT` is 60 s and the extra 60 s was commented as
"image pull / container start". `rust:1.82-slim` is 808 MB. So a first-time user's very first
build spent the entire budget downloading and then reported:

    Fix Docker or set DETERMINEX_REQUIRE_DOCKER=0 (reduces isolation).

which is neither the cause nor something they can act on. Measured warm on this box, the same
command finishes in 10 s against a 120 s budget -- the budget was never the problem, the
download inside it was.

Two properties are pinned here, and the second matters more than it looks:

  1. A missing registry image is pulled FIRST, under its own generous timeout, so the compile
     timeout only ever measures compiling.
  2. A provisioning failure RAISES. If it returned a non-zero rc like a normal `docker run`,
     the caller would record it as a compile error -- writing a network or registry problem
     into the WAL as though the generated code were wrong. That is training-data corruption,
     not a bad error message, and this project's whole reward signal depends on the
     distinction.

These are mock-based on purpose: they assert what gets executed and in what order, which is
exactly what a real-Docker test cannot observe (a warm machine never pulls, so the
regression would be invisible).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from hive import compiler as C  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_image_cache():
    """`_IMAGES_PRESENT` is process-level memoisation; leaking it across tests would let one
    test's "already present" hide another's missing-image path."""
    C._IMAGES_PRESENT.clear()
    yield
    C._IMAGES_PRESENT.clear()


class _Recorder:
    """Stands in for subprocess.run, recording argv and replying per-verb."""

    def __init__(self, inspect_rc: int = 0, pull_rc: int = 0, pull_raises: bool = False):
        self.calls: list[list[str]] = []
        self.inspect_rc = inspect_rc
        self.pull_rc = pull_rc
        self.pull_raises = pull_raises

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        verb = argv[1] if len(argv) > 1 else ""
        if verb == "image":  # docker image inspect
            return subprocess.CompletedProcess(argv, self.inspect_rc, b"", b"")
        if verb == "pull":
            if self.pull_raises:
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))
            return subprocess.CompletedProcess(
                argv,
                self.pull_rc,
                "",
                "" if self.pull_rc == 0 else "manifest unknown",
            )
        return subprocess.CompletedProcess(argv, 0, "", "")

    def verbs(self) -> list[str]:
        return [c[1] if len(c) > 1 else "" for c in self.calls]


def test_a_missing_registry_image_is_pulled_before_the_timed_compile(monkeypatch):
    """The pull must happen, and must happen as its own step rather than implicitly."""
    rec = _Recorder(inspect_rc=1)  # not present locally
    monkeypatch.setattr(C.subprocess, "run", rec)

    C._ensure_oracle_image("rust:1.82-slim", "rust")

    assert "pull" in rec.verbs(), (
        f"a missing image was not pulled; the download would land inside the compile "
        f"timeout instead. calls={rec.calls}"
    )
    pull = next(c for c in rec.calls if c[1] == "pull")
    assert pull[2] == "rust:1.82-slim"


def test_the_pull_budget_is_far_larger_than_the_compile_budget(monkeypatch):
    """An 808 MB download cannot fit in a budget sized for container start. If these two ever
    converge again, the original bug is back."""
    captured: dict[str, float] = {}
    rec = _Recorder(inspect_rc=1)

    def spy(argv, **kwargs):
        if len(argv) > 1 and argv[1] == "pull":
            captured["timeout"] = kwargs.get("timeout", 0)
        return rec(argv, **kwargs)

    monkeypatch.setattr(C.subprocess, "run", spy)
    C._ensure_oracle_image("rust:1.82-slim", "rust")

    assert captured.get("timeout", 0) >= C.COMPILE_TIMEOUT * 10, (
        f"pull timeout {captured.get('timeout')}s is not meaningfully larger than the "
        f"{C.COMPILE_TIMEOUT}s compile timeout — a large image will still time out"
    )


def test_a_locally_built_image_reports_its_build_command_and_is_never_pulled(monkeypatch):
    """`determinex-oracle-ts:20` has no registry. `docker pull` on it fails with "pull access
    denied", which reads as an auth problem and sends the operator hunting for credentials
    that do not exist. The actionable fact is the build command."""
    rec = _Recorder(inspect_rc=1)
    monkeypatch.setattr(C.subprocess, "run", rec)

    with pytest.raises(RuntimeError) as exc:
        C._ensure_oracle_image("determinex-oracle-ts:20", "typescript")

    assert "pull" not in rec.verbs(), (
        "attempted to pull a locally-built image; the failure would blame registry auth"
    )
    msg = str(exc.value)
    assert "docker build" in msg, f"no build command in the failure: {msg}"
    assert "typescript.Dockerfile" in msg, f"build command does not name the file: {msg}"


def test_a_failed_pull_raises_rather_than_becoming_a_compile_error(monkeypatch):
    """The load-bearing one. A non-zero rc returned to the caller is indistinguishable from a
    compile failure, so a registry outage would be written to the WAL as a code defect."""
    rec = _Recorder(inspect_rc=1, pull_rc=1)
    monkeypatch.setattr(C.subprocess, "run", rec)

    with pytest.raises(RuntimeError) as exc:
        C._ensure_oracle_image("rust:1.82-slim", "rust")
    assert "rust:1.82-slim" in str(exc.value)
    assert "docker pull" in str(exc.value), "failure does not tell the operator how to fix it"


def test_a_pull_that_times_out_raises_with_the_image_named(monkeypatch):
    rec = _Recorder(inspect_rc=1, pull_raises=True)
    monkeypatch.setattr(C.subprocess, "run", rec)

    with pytest.raises(RuntimeError) as exc:
        C._ensure_oracle_image("go:1.23-alpine", "go")
    assert "go:1.23-alpine" in str(exc.value)


def test_a_present_image_is_neither_pulled_nor_re_inspected(monkeypatch):
    """The oracle runs once per step per attempt; re-inspecting every time adds latency to
    every compile in a session for no information."""
    rec = _Recorder(inspect_rc=0)  # already local
    monkeypatch.setattr(C.subprocess, "run", rec)

    C._ensure_oracle_image("python:3.12-slim", "python")
    assert "pull" not in rec.verbs()
    first = len(rec.calls)

    C._ensure_oracle_image("python:3.12-slim", "python")
    assert len(rec.calls) == first, (
        "a second call re-ran docker image inspect; the result is memoised for the process"
    )


def test_every_configured_image_either_is_pullable_or_ships_a_build_hint():
    """A configured language whose image is neither in a registry nor documented as locally
    built would fail with 'pull access denied' and no path forward."""
    for lang, image in C._ORACLE_IMAGES.items():
        looks_local = "/" not in image and image.startswith("determinex-")
        if looks_local:
            assert lang in C._ORACLE_IMAGE_HINT, (
                f"{lang} uses locally-built image {image} but has no build hint, so a "
                f"missing image cannot report how to obtain it"
            )
