#!/usr/bin/env python3
"""Extract reproducible Aider Repo Map or RepoGraph context for one repository.

This helper is intentionally inference-free.  The generated text is written
into a task sandbox and consumed by mini-SWE-agent as fixed initial context.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path


OVERRIDE_SYMBOLS = ("hstack", "vstack", "row_join", "col_join")


def source_files(root: Path) -> list[str]:
    excluded = {".git", "__pycache__", ".aider.tags.cache.v3", ".aider.tags.cache.v4"}
    files: list[str] = []
    for path in root.rglob("*"):
        relative_parts = path.relative_to(root).parts
        if (
            not path.is_file()
            or any(part in excluded for part in relative_parts)
            or any(part.startswith(".") for part in relative_parts)
        ):
            continue
        if path.name.startswith(".track2-") or path.name.endswith("_test.py"):
            continue
        files.append(str(path.resolve()))
    return sorted(files)


def issue_mentions(root: Path, files: list[str], issue: str) -> tuple[set[str], set[str]]:
    """Mirror Aider's filename/identifier hint extraction for a standalone map."""
    identifiers = {word for word in re.split(r"\W+", issue) if word}
    relative_files = [str(Path(path).resolve().relative_to(root.resolve())) for path in files]
    words = {
        word.strip("\"'`*_,.!;:?").replace("\\", "/")
        for word in issue.split()
    }
    mentioned_files: set[str] = set()
    by_basename: dict[str, set[str]] = defaultdict(set)
    by_stem: dict[str, set[str]] = defaultdict(set)
    for relative in relative_files:
        normalized = relative.replace("\\", "/")
        path = Path(relative)
        if normalized in words:
            mentioned_files.add(relative)
        if any(mark in path.name for mark in (".", "_", "-")):
            by_basename[path.name].add(relative)
        if len(path.stem) >= 5:
            by_stem[path.stem.lower()].add(relative)
    for basename, matches in by_basename.items():
        if basename in words and len(matches) == 1:
            mentioned_files.update(matches)
    for identifier in identifiers:
        if len(identifier) >= 5:
            mentioned_files.update(by_stem[identifier.lower()])
    return mentioned_files, identifiers


def override_expansion(root: Path, files: list[str], issue: str) -> str:
    """Add deterministic polymorphic-implementation hints to code context.

    Repo maps tend to rank the public entry point (for example ``hstack`` in
    ``common.py``), while the behavior may be implemented by a subclass
    override in another file.  This small, language-aware-enough index keeps
    the context provider inference-free: it only reports definitions of the
    relevant join symbols and their source locations.
    """
    issue_lower = issue.lower()
    symbols = list(OVERRIDE_SYMBOLS) if any(symbol in issue_lower for symbol in OVERRIDE_SYMBOLS) else []
    if not symbols:
        return ""
    patterns = {
        symbol: re.compile(rf"^\s*(?:async\s+)?def\s+{re.escape(symbol)}\s*\(")
        for symbol in symbols
    }
    matches: list[str] = []
    for filename in files:
        path = Path(filename)
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        for line_number, line in enumerate(lines, 1):
            for symbol, pattern in patterns.items():
                if pattern.search(line):
                    matches.append(f"{relative}:{line_number} {line.strip()}")
    if not matches:
        return ""
    return (
        "Polymorphic implementation candidates (inspect every override before editing):\n"
        + "\n".join(f"- {match}" for match in matches[:80])
    )


def aider_repo_map(
    root: Path,
    aider_root: Path,
    model: str,
    map_tokens: int,
    issue: str = "",
    focus_files: list[str] | None = None,
    focus_identifiers: list[str] | None = None,
) -> str:
    """Run Aider's open-source RepoMap without invoking a second model.

    Aider's ``RepoMap`` only needs a token-counting model object and a small
    IO adapter for this static extraction path.  Avoid importing Aider's full
    interactive ``Model``/``InputOutput`` stack: that would install a second
    provider client and could accidentally make a context ablation call an
    external API.
    """
    sys.path.insert(0, str(aider_root.resolve()))
    from aider.repomap import RepoMap

    class _MapIO:
        def tool_output(self, *_args, **_kwargs):
            return None

        def tool_error(self, *_args, **_kwargs):
            return None

    class _MapModel:
        def token_count(self, text: str) -> int:
            # The map only uses this to rank/truncate tags.  A deterministic
            # character estimate keeps C1 inference-free and provider-neutral.
            return max(1, len(text) // 4)

    io = _MapIO()
    main_model = _MapModel()
    mapper = RepoMap(
        map_tokens=map_tokens,
        root=str(root),
        main_model=main_model,
        io=io,
        max_context_window=32768,
        # RepoMap's interactive default expands the budget 8x when no files
        # have been added to chat.  This standalone harness has no chat files,
        # so disable that expansion to keep C1 within its declared budget.
        map_mul_no_files=1,
        refresh="files",
    )
    files = source_files(root)
    mentioned_files, mentioned_identifiers = issue_mentions(root, files, issue)
    relative_files = {
        str(Path(path).as_posix()).lstrip("./")
        for path in (focus_files or [])
    }
    valid_relative_files = {
        relative
        for relative in relative_files
        if (root / relative).is_file()
    }
    mentioned_files.update(valid_relative_files)
    mentioned_identifiers.update(
        identifier for identifier in (focus_identifiers or []) if identifier
    )
    rendered = mapper.get_repo_map(
        [],
        files,
        mentioned_fnames=mentioned_files,
        mentioned_idents=mentioned_identifiers,
        force_refresh=True,
    )
    expansion = override_expansion(root, files, issue)
    output = "\n\n".join(part for part in (rendered or "", expansion) if part)
    # RepoMap's internal token counter is provider/model dependent.  Enforce
    # the declared experiment budget at the extraction boundary so a static
    # map can never expand into hundreds of thousands of prompt characters.
    budget_chars = max(1, int(map_tokens) * 4)
    if len(output) > budget_chars:
        output = output[:budget_chars].rsplit("\n", 1)[0]
    return output


def repo_graph(root: Path, repograph_root: Path, map_tokens: int, max_files: int = 80) -> str:
    module_root = repograph_root.resolve() / "repograph"
    sys.path.insert(0, str(module_root))
    import construct_graph
    from construct_graph import CodeGraph

    construct_graph.tqdm = lambda iterable: iterable

    graph_builder = CodeGraph(root=str(root))
    # ``create_structure`` returns a mapping whose top-level keys are the
    # repository's relative path components.  Keep that mapping intact:
    # ``get_tags_raw`` walks it using paths such as ``django/apps/config.py``.
    # Unwrapping the repository basename would drop the first directory level
    # and cause valid files to raise ``KeyError``.
    python_files = [path for path in source_files(root) if path.endswith(".py")][:max_files]
    # Upstream currently returns Tag namedtuples from extraction while its
    # graph constructor indexes dictionaries.  Normalize only that interface
    # mismatch and retain the project's extraction and edge construction.
    # The upstream ranker assumes every source file has a perfectly formed
    # structure entry.  Real benchmark repositories intentionally contain a
    # few malformed/generated files, so extract each file independently and
    # retain the valid static tags instead of turning the whole provider into
    # an unavailable context.  No file-list fallback is used here.
    raw_tags = []
    skipped = 0
    for filename in python_files:
        relative = str(Path(filename).resolve().relative_to(root.resolve())).replace("\\", "/")
        try:
            raw_tags.extend(graph_builder.get_tags(filename, relative))
        except Exception:
            skipped += 1
    if not raw_tags:
        raise RuntimeError("RepoGraph extracted no tags")
    tags = [tag._asdict() if hasattr(tag, "_asdict") else dict(tag) for tag in raw_tags]
    graph = graph_builder.tag_to_graph(tags)

    lines = ["RepoGraph definitions and references:"]
    if skipped:
        lines.append(f"RepoGraph skipped malformed files: {skipped}")
    for tag in tags:
        info = str(tag.get("info") or "").replace("\n", " ")[:500]
        raw_line = tag.get("line")
        if isinstance(raw_line, list) and raw_line:
            line_label = "-".join(str(value) for value in raw_line[:2])
        elif isinstance(raw_line, int) and raw_line >= 0:
            line_label = str(raw_line + 1)
        else:
            line_label = "?"
        lines.append(
            f"{tag['rel_fname']}:{line_label} [{tag['kind']}/{tag['category']}] "
            f"{tag['name']}" + (f" | {info}" if info else "")
        )
    lines.append("RepoGraph edges:")
    for source, target in list(graph.edges())[:1000]:
        lines.append(f"{source} -> {target}")
    expansion = override_expansion(root, source_files(root), " ".join(OVERRIDE_SYMBOLS))
    if expansion:
        lines.extend(["", expansion])
    # Keep the provider's declared budget deterministic (roughly four
    # characters per token, matching the inference-free Aider adapter).
    return "\n".join(lines)[: max(1, map_tokens * 4)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=("aider", "repograph"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--aider-root", type=Path)
    parser.add_argument("--repograph-root", type=Path)
    parser.add_argument("--model", default="openai/Qwen3.6-35B-A3B")
    parser.add_argument("--map-tokens", type=int, default=2048)
    parser.add_argument("--max-files", type=int, default=80)
    parser.add_argument("--issue", default="")
    parser.add_argument("--focus-file", action="append", default=[])
    parser.add_argument("--focus-identifier", action="append", default=[])
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"repository not found: {root}")
    if args.provider == "aider":
        if not args.aider_root:
            raise SystemExit("--aider-root is required for provider=aider")
        output = aider_repo_map(
            root,
            args.aider_root,
            args.model,
            args.map_tokens,
            args.issue,
            args.focus_file,
            args.focus_identifier,
        )
    else:
        if not args.repograph_root:
            raise SystemExit("--repograph-root is required for provider=repograph")
        output = repo_graph(root, args.repograph_root, args.map_tokens, args.max_files)
    print(output)


if __name__ == "__main__":
    main()
