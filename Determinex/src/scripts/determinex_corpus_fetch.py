"""Materialise a corpus tool's upstream source at its pinned commit.

WHY THE SOURCE IS NOT IN THE PUBLIC REPO. `corpus/` carries complete upstream checkouts of ~200 CLI
tools, because the Native Reimplementation Loop feeds real source and a real test oracle to a model.
That is the product, and it has to stay available. Re-hosting it in the git repo does not work in
either direction:

  SIZE   the pack is 9.73 GiB. GitHub soft-limits at 1 GB and rejects any single file over 100 MB.
  LAW    publishing those trees is REDISTRIBUTION of other people's software, and MIT/BSD/ISC/
         Apache-2.0 all require the copyright notice and license text to travel with the code.

So the public repo ships what is genuinely Determinex's: the oracles, the build recipes
(`compile.sh`), the eval reports, the learned build knowledge, and `canonical_tasks.json`, which
pins `repository` + `commit` for all 200 tasks. This command reconstructs any tool's tree from
upstream at exactly that commit and overlays our recipe on top. Same inputs to the model, no
re-hosting, and every project is fetched from — and attributed to — its own maintainers.

    determinex corpus list
    determinex corpus fetch cmatrix
    determinex corpus fetch --all --into T:/determinex-corpus-src

The complete pre-materialised corpus is also published as a dataset for anyone who wants it in one
download rather than 200 clones; see corpus/THIRD_PARTY_NOTICES.md for what it contains and under
which licenses.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_TASKS = _ROOT / "corpus" / "programbench" / "canonical_tasks.json"
OVERRIDES = _ROOT / "corpus" / "programbench" / "per_tool_overrides"
DEFAULT_DEST = _ROOT / ".tmp" / "determinex-corpus-src"


@dataclass(frozen=True)
class Task:
    task_id: str
    repository: str
    commit: str
    language: str

    @property
    def slug(self) -> str:
        """`owner__repo`, the naming convention the override directories already use."""
        parts = self.repository.rstrip("/").removesuffix(".git").split("/")
        return f"{parts[-2]}__{parts[-1]}" if len(parts) >= 2 else self.task_id

    @property
    def clone_url(self) -> str:
        if self.repository.startswith(("http://", "https://", "git@")):
            return self.repository
        return f"https://github.com/{self.repository.strip('/')}"

    @property
    def short_name(self) -> str:
        return self.repository.rstrip("/").removesuffix(".git").split("/")[-1]


def load_tasks() -> list[Task]:
    if not CANONICAL_TASKS.is_file():
        raise SystemExit(f"missing {CANONICAL_TASKS.relative_to(_ROOT)}")
    raw = json.loads(CANONICAL_TASKS.read_text(encoding="utf-8", errors="replace"))
    rows = raw if isinstance(raw, list) else (raw.get("tasks") or list(raw.values()))
    tasks: list[Task] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        repository = str(row.get("repository") or "").strip()
        commit = str(row.get("commit") or "").strip()
        if not repository or not commit:
            continue
        tasks.append(
            Task(
                task_id=str(row.get("id") or row.get("task_id") or repository),
                repository=repository,
                commit=commit,
                language=str(row.get("language") or ""),
            )
        )
    return tasks


def resolve(tasks: list[Task], name: str) -> Task | None:
    """Match a task by id, owner/repo, owner__repo, or bare repo name."""
    needle = name.strip().lower().replace("/", "__")
    for task in tasks:
        if needle in {
            task.task_id.lower(),
            task.slug.lower(),
            task.short_name.lower(),
            task.repository.lower().replace("/", "__"),
        }:
            return task
    return None


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 1800) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, capture_output=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    return proc.returncode == 0, out.strip()[-600:]


def find_overrides(task: Task) -> Path | None:
    """Our build recipe for this tool, if the public repo carries one.

    Matched on the `owner__repo` prefix because the override directories are named
    `owner__repo.commit` and the commit suffix is not always the one canonical_tasks pins.
    """
    if not OVERRIDES.is_dir():
        return None
    prefix = task.slug.lower()
    for candidate in sorted(OVERRIDES.iterdir()):
        if not candidate.is_dir() or candidate.name.startswith((".", "_")):
            continue
        if candidate.name.lower() == prefix or candidate.name.lower().startswith(prefix + "."):
            return candidate
    return None


def fetch(
    task: Task, dest_root: Path, *, force: bool = False, overlay: bool = True
) -> tuple[bool, str]:
    dest = dest_root / task.slug
    if dest.exists() and not force:
        return True, f"already present at {dest} (use --force to refetch)"
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Shallow-fetch the single pinned commit rather than cloning history: these are pins, and a
    # full clone of 200 repos is a great deal of bandwidth for revisions nobody reads.
    ok, detail = _run(["git", "init", "--quiet", str(dest)])
    if not ok:
        return False, f"git init failed: {detail}"
    ok, detail = _run(["git", "remote", "add", "origin", task.clone_url], cwd=dest)
    if not ok:
        return False, f"git remote add failed: {detail}"
    ok, detail = _run(["git", "fetch", "--quiet", "--depth", "1", "origin", task.commit], cwd=dest)
    if not ok:
        # Some hosts refuse fetch-by-sha; fall back to a shallow clone then checkout.
        ok, detail = _run(["git", "fetch", "--quiet", "--depth", "50", "origin"], cwd=dest)
        if not ok:
            return False, f"fetch failed: {detail}"
    ok, detail = _run(["git", "checkout", "--quiet", task.commit], cwd=dest)
    if not ok:
        return False, f"checkout {task.commit[:12]} failed: {detail}"

    copied = 0
    if overlay:
        recipe_dir = find_overrides(task)
        if recipe_dir is not None:
            # Only OUR files. Copying the whole override directory would restore the vendored tree
            # this command exists to avoid re-hosting.
            for name in ("compile.sh", "conftest.py", "eval_report.json", "tests.json"):
                src = recipe_dir / name
                if src.is_file():
                    shutil.copy2(src, dest / name)
                    copied += 1

    return True, f"{dest}  ({task.commit[:12]}, {copied} recipe file(s) overlaid)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="determinex corpus",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list the pinned tools")
    p_list.add_argument("--language", default="", help="filter by language")

    p_fetch = sub.add_parser("fetch", help="materialise a tool's upstream source")
    p_fetch.add_argument("tool", nargs="?", default="")
    p_fetch.add_argument("--all", action="store_true", help="fetch every pinned tool")
    p_fetch.add_argument("--into", type=Path, default=DEFAULT_DEST)
    p_fetch.add_argument("--force", action="store_true", help="refetch even if present")
    p_fetch.add_argument(
        "--no-overlay",
        action="store_true",
        help="skip copying our compile.sh / eval_report.json in",
    )

    args = parser.parse_args(argv)
    tasks = load_tasks()

    if args.command == "list":
        rows = [t for t in tasks if not args.language or t.language == args.language]
        print(f"{len(rows)} pinned tool(s)")
        for task in sorted(rows, key=lambda t: t.short_name):
            print(f"  {task.short_name:32} {task.language:8} {task.repository}@{task.commit[:12]}")
        return 0

    if args.all:
        targets = tasks
    else:
        if not args.tool:
            print("name a tool, or pass --all  (see: determinex corpus list)", file=sys.stderr)
            return 2
        task = resolve(tasks, args.tool)
        if task is None:
            print(
                f"no pinned tool matching {args.tool!r}. Try: determinex corpus list",
                file=sys.stderr,
            )
            return 2
        targets = [task]

    failures = 0
    for task in targets:
        ok, detail = fetch(task, args.into, force=args.force, overlay=not args.no_overlay)
        print(f"  {'OK  ' if ok else 'FAIL'} {task.short_name:28} {detail}")
        if not ok:
            failures += 1
    if failures:
        print(f"\n{failures} of {len(targets)} failed", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
